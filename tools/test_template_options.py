"""Regressions for template controls and the files their selections retain."""
import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QVBoxLayout, QWidget
from src.gui.template_option_editors import create_interface
from src.tweaks.posterboard.template_options.picker_option import PickerOption
from src.tweaks.posterboard.template_options.replace_option import ReplaceOption
from src.tweaks.posterboard.template_options.set_option import SetOption
from src.tweaks.posterboard.template_file import TemplateFile

APP = QApplication.instance() or QApplication([])


class TemplateControls(unittest.TestCase):
    def make_picker(self, **extra):
        return PickerOption(dict(type="picker", label="Choose", options=[
            dict(label="First", files=["first.txt"]),
            dict(label="Second", files=["second.txt"])], **extra))

    def build(self, option):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        create_interface(option, widget, layout)
        self.assertIs(widget.layout(), layout)
        row = layout.itemAt(0).widget()
        self.assertIsNotNone(row.layout())
        self.addCleanup(widget.close)
        return widget

    def test_single_picker_applies_the_displayed_default(self):
        option = self.make_picker(default_value=1)
        widget = self.build(option)
        self.assertEqual(widget.findChild(QComboBox).currentIndex(), 1)
        with tempfile.TemporaryDirectory() as folder:
            for name in ("first.txt", "second.txt"):
                Path(folder, name).write_text(name)
            option.apply(folder)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["second.txt"])

    def test_picker_without_default_opens_and_preserves_edited_selection(self):
        option = self.make_picker()
        widget = self.build(option)
        combo = widget.findChild(QComboBox)
        combo.setCurrentIndex(1)
        self.assertEqual(option.selection, 1)
        rebuilt = self.build(option)
        self.assertEqual(rebuilt.findChild(QComboBox).currentIndex(), 1)

    def test_multi_picker_keeps_checked_files(self):
        option = self.make_picker(allow_multiple_selection=True, default_values=[1])
        widget = self.build(option)
        self.assertEqual(option.selection, ["Second"])
        combo = widget.findChild(QComboBox)
        combo.model().item(0).setCheckState(Qt.CheckState.Checked)
        combo.model().item(1).setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(option.selection, ["First"])
        with tempfile.TemporaryDirectory() as folder:
            for name in ("first.txt", "second.txt"):
                Path(folder, name).write_text(name)
            option.apply(folder)
            self.assertTrue(Path(folder, "first.txt").exists())
            self.assertFalse(Path(folder, "second.txt").exists())

    def test_invalid_picker_defaults_rejected_before_any_file_changes(self):
        for kwargs in (dict(default_value=-1), dict(default_value=2),
                       dict(allow_multiple_selection=True, default_values=[2])):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.make_picker(**kwargs)

    def test_replace_layout_is_owned_by_its_row(self):
        option = ReplaceOption(dict(type="replace", label="Image", files=["image.png"],
                                    allowed_files="Images (*.png)"))
        widget = self.build(option)
        row = widget.layout().itemAt(0).widget()
        self.assertIsNotNone(row.layout().itemAt(1).widget().layout())

    def setter(self, **extra):
        return SetOption(dict(type="set", label="Position", files=["scene.caml"],
                              identifier="layer", key="position", setter_type="slider",
                              min_value="0 0", max_value="1 1", step=0.1,
                              value_type="float", default_value="0.2 0.4", **extra))

    def test_float_vector_controls_do_not_mutate_values(self):
        option = self.setter()
        expected = [0.2, 0.4]
        self.assertEqual(option.convert_float(option.value), [200, 400])
        self.assertEqual(option.value, expected)
        self.assertEqual(option.convert_back(option.value), "0.2 0.4")
        self.assertEqual(option.value, expected)
        self.build(option)
        self.build(option)
        self.assertEqual(option.value, expected)
        option.update_value(600, 1)
        self.assertEqual(option.value, [0.2, 0.6])

    def test_numeric_textbox_default_can_be_rendered(self):
        self.build(SetOption(dict(type="set", label="Count", files=["scene.caml"],
                                 identifier="layer", key="count", setter_type="textbox",
                                 default_value=5)))

    def test_templates_do_not_share_preview_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            config = dict(format_version=3, title="Template", author="Test",
                          domain="AppDomain-com.apple.PosterBoard", options=[])
            first_path, second_path = (Path(folder, name) for name in ("first.batter", "second.batter"))
            with zipfile.ZipFile(first_path, "w") as archive:
                archive.writestr("config.json", json.dumps({**config,
                    "resources": ["preview.png"], "previews": ["preview.png"]}))
                archive.writestr("preview.png", b"preview")
            with zipfile.ZipFile(second_path, "w") as archive:
                archive.writestr("config.json", json.dumps(config))
            first = TemplateFile(str(first_path))
            self.addCleanup(first.tmp_dir.cleanup)
            second = TemplateFile(str(second_path))
            self.assertEqual(list(first.previews), ["preview.png"])
            self.assertEqual(second.previews, {})
            self.assertEqual(second.resources, [])


if __name__ == "__main__":
    unittest.main()
