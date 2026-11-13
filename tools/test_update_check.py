"""Update check: a failed fetch is not "up to date", and a 404 still is."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from requests import HTTPError, RequestException

from src.controllers import web_request_handler as wrh
from src.gui.startup_services import StartupServices


def _reset_cache():
    wrh.last_fetched_version = None
    wrh.last_fetched_release = {}
    wrh._update_check_failed = False


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def tearDown(self):
        _reset_cache()

    def _response(self, status=200, payload=None, text="{}"):
        response = Mock()
        response.status_code = status
        response.text = text
        if payload is None:
            response.json.side_effect = ValueError("not json")
        else:
            response.json.return_value = payload
        if status >= 400:
            err = HTTPError(f"{status}")
            err.response = response
            response.raise_for_status.side_effect = err
        else:
            response.raise_for_status.return_value = None
        return response

    def test_newer_tag_is_an_update(self):
        payload = {"tag_name": "v9.9.0", "assets": []}
        with patch("requests.get", return_value=self._response(payload=payload)):
            self.assertIs(wrh.is_update_available("9.7.7", 0), True)

    def test_same_release_is_current(self):
        payload = {"tag_name": "v9.7.7", "assets": []}
        with patch("requests.get", return_value=self._response(payload=payload)):
            self.assertIs(wrh.is_update_available("9.7.7", 0), False)

    def test_404_is_no_update(self):
        with patch("requests.get", return_value=self._response(status=404)):
            self.assertIs(wrh.is_update_available("9.7.7", 0), False)
            self.assertIsNone(wrh.last_fetched_version)

    def test_rate_limit_timeout_and_bad_json_are_unknown(self):
        with patch("requests.get", return_value=self._response(status=403)):
            self.assertIsNone(wrh.is_update_available("9.7.7", 0))
        _reset_cache()
        with patch("requests.get", side_effect=RequestException("timed out")):
            self.assertIsNone(wrh.is_update_available("9.7.7", 0))
        _reset_cache()
        from json import JSONDecodeError
        with patch("requests.get", return_value=self._response(payload={"tag_name": "v1"})) as get:
            get.return_value.json.side_effect = JSONDecodeError("bad", "", 0)
            self.assertIsNone(wrh.is_update_available("9.7.7", 0))

    def test_startup_emits_none_on_failure(self):
        emitted = []
        services = StartupServices.__new__(StartupServices)
        services.closing = type("E", (), {"is_set": lambda self: False})()
        services.log = Mock()
        services.update_ready = Mock()
        services.update_ready.emit.side_effect = emitted.append
        with patch("src.controllers.web_request_handler.is_update_available", return_value=None):
            services._fetch_update()
        self.assertEqual(emitted, [None])

    def test_home_label_distinguishes_failure(self):
        class _Widget:
            def __init__(self):
                self.visible = False
                self._text = ""

            def show(self):
                self.visible = True

            def isVisible(self):
                return self.visible

            def setVisible(self, visible):
                self.visible = visible

            def setText(self, text):
                self._text = text

            def text(self):
                return self._text

        page = type("Page", (), {})()
        page.tr = lambda text: text
        page.update_notice = _Widget()
        page.outdated_lbl = _Widget()
        page.update_info_btn = _Widget()
        page.update_status = lambda: None
        # Load the method without importing the home module (it pulls Qt widgets
        # and the sidebar package). The unbound function is what the UI calls.
        import ast
        tree = ast.parse(Path("src/gui/ios/home.py").read_text())
        method = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "set_update_available")
        ns = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "home.py", "exec"), ns)
        set_update_available = ns["set_update_available"]
        set_update_available(page, None)
        self.assertEqual(page.outdated_lbl.text(), "Could not check for updates")
        self.assertTrue(page.update_notice.isVisible())
        self.assertFalse(page.update_info_btn.isVisible())
        set_update_available(page, False)
        self.assertEqual(page.outdated_lbl.text(), "Up to date!")
        set_update_available(page, True)
        self.assertEqual(page.outdated_lbl.text(), "Outdated version")
        self.assertTrue(page.update_info_btn.isVisible())


if __name__ == "__main__":
    unittest.main()
