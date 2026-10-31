# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "multiprocessing",
    "runpy",
    "traceback",
)

import sys
import os
import multiprocessing
import runpy
import warnings
import traceback
import logging

# Add src/qt to path so resources_rc can be found
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "qt"))

# 1. SILENCE WARNINGS
warnings.filterwarnings("ignore")

# Silence noisy Qt Wayland textinput logs (zwp_text_input_v3_leave spam)
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.wayland.textinput=false")

from PySide6.QtCore import QCoreApplication

from src.gui.logger import setup_logging, get_logger
from src.exceptions.crash_handler import install_crash_handler, CrashHandlerApp

# Install the global crash handler as early as possible so any uncaught
# exception during startup is also captured instead of silently killing the app.
install_crash_handler()
print("[init] CrashHandler installed")


def _current_ios(dm) -> tuple:
    """(version, model) of the currently selected device, or (None, None)."""
    try:
        version = dm.get_current_device_version()
        model = dm.get_current_device_model()
        return (version or None, model or None)
    except Exception:
        return (None, None)


def _show_kill_message(kill) -> None:
    """Present the remote kill reason to the user before shutting down."""
    tr = lambda s: QCoreApplication.translate("Nugget", s)
    reason = str(kill.get("reason")
                 or tr("This version of iOS is currently not supported."))
    print(f"[init] HotLoad: BLOCKED - {reason}", flush=True)
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(tr("GoldenNugget Disabled"))
    box.setText(tr("GoldenNugget has been disabled by its safety rules."))
    box.setInformativeText(reason)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def _hotload_kill_or_none(dm, hotload):
    """Return the active kill rule for the current iOS, or None."""
    version, model = _current_ios(dm)
    try:
        return hotload.kill_rule(version, model)
    except Exception:
        return None


def main() -> int:
    """GUI + fallback CLI dispatcher entry point (importable for the wrapper)."""

    # 2. CLI DISPATCHER
    if len(sys.argv) > 1:
        if '-m' in sys.argv:
            try:
                m_index = sys.argv.index('-m')
                # Args: [module_name, arg1, arg2...]
                sys.argv = sys.argv[m_index+1:]
                module_name = sys.argv[0]

                try:
                    # Attempt 1: Run standard module
                    runpy.run_module(module_name, run_name="__main__", alter_sys=True)
                except ImportError as e:
                    # Attempt 2: Handle "is a package" error by targeting __main__ explicitly
                    if "cannot be directly executed" in str(e) or "No module named" in str(e):
                        runpy.run_module(f"{module_name}.__main__", run_name="__main__", alter_sys=True)
                    else:
                        raise
            except Exception as e:
                # Print error to stderr so the main process can read it
                sys.stderr.write(f"Background Process Crash: {e}\n")
                traceback.print_exc()
            sys.exit()

        first_arg = sys.argv[1]
        if first_arg.endswith('.py') and not first_arg.lower().endswith(('.tendies', '.batter')):
            sys.argv = sys.argv[1:]
            try:
                runpy.run_path(sys.argv[0], run_name="__main__")
            except Exception as e:
                sys.stderr.write(f"Script Crash: {e}\n")
                traceback.print_exc()
            sys.exit()

    # 3. GUI STARTUP
    print("Starting GoldenNugget...")

    if "--test-mode" in sys.argv:
        print("TEST MODE ENABLED: Mock device will be created")

    # Setup logging
    log_file = os.environ.get("GOLDENNUGGET_LOG_FILE")
    verbose = "--debug" in sys.argv or os.environ.get("GOLDENNUGGET_VERBOSE") not in (None, "", "0")
    if verbose:
        setup_logging(log_file, logging.DEBUG, capture_pymobiledevice3=True)
    else:
        setup_logging(log_file)

    logger = get_logger(__name__)
    logger.info("Starting GoldenNugget")

    from src.controllers.nugget_logger import init_logging, log_banner
    init_logging()
    log_banner()

    from src.gui.bootstrap import preload_backend
    backend_preload = preload_backend()

    app = CrashHandlerApp(sys.argv)

    from src.gui.bootstrap import configure_appearance
    configure_appearance(app, os.path.dirname(__file__))

    QCoreApplication.setOrganizationDomain("com.leemin")
    QCoreApplication.setApplicationName("GoldenNugget")
    from src.controllers.settings import Settings
    settings = Settings("settings")

    from src.controllers.hotload import HotLoad
    hotload = HotLoad(settings)
    print("[init] HotLoad: checking safety rules...")

    from src.controllers.translator import Translator
    translator = Translator(app, settings)
    translator.set_default_locale(translator.get_saved_locale_code())
    translator.load_translations()

    from PySide6.QtGui import QIcon
    icon_path = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(__file__)), "nugget.ico")
    app.setWindowIcon(QIcon(icon_path))

    from src.gui.bootstrap import restore_selected_preset
    restore_selected_preset(settings, logger)

    # Import the main window module while the device-manager preload is still
    # running: the GUI import graph no longer pulls in pymobiledevice3, so the
    # two heaviest imports overlap instead of running back-to-back.
    from src.gui.main_window import MainWindow

    # Device manager: the background preload is usually long finished by now
    # (it races with the setup above); waiting here is a no-op in that case.
    # If it failed, the error is re-raised on the main thread exactly as if the
    # import had run here directly.
    backend_preload.wait()
    from src.devicemanagement.device_manager import DeviceManager
    dm = DeviceManager()

    # Test mode: create mock device
    if "--test-mode" in sys.argv:
        from src.devicemanagement.constants import Device
        mock_device = Device(
            udid=0x1234567890ABCDEF,
            usb=True,
            name="Test iPhone 15 Pro",
            version="27.0",
            build="21A5284a",
            model="iPhone15,3",
            hardware="D84AP",
            cpu="t8140",
            locale="en_US"
        )
        mock_device_2 = Device(
            udid=0x1122334455667788,
            usb=True,
            name="Test iPhone 16",
            version="26.6",
            build="26G96",
            model="iPhone17,3",
            hardware="D59AP",
            cpu="t8140",
            locale="en_US"
        )
        dm.data_singleton.current_device = mock_device
        dm.data_singleton.device_available = True
        dm.devices.append(mock_device)
        dm.devices.append(mock_device_2)
        dm.current_device_index = 0
        logger.info("Test mode: Mock devices created")

    # HotLoad: the kill rule is checked BEFORE the GUI is built. If it fires
    # the app refuses to start.
    kill = _hotload_kill_or_none(dm, hotload)
    if kill:
        logger.warning("GoldenNugget disabled by HotLoad rules: %s", kill.get("reason"))
        _show_kill_message(kill)
        return 0
    print("[init] HotLoad ok")

    widget = MainWindow(device_manager=dm, translator=translator)
    translator.fix_ui_for_rtl(widget.ui)
    # Open a little roomier than the 1000x600 minimum when the screen allows.
    avail = widget.screen().availableGeometry()
    widget.resize(max(1000, min(1100, avail.width() - 80)),
                  max(600, min(760, avail.height() - 80)))
    widget.show()
    from src.gui.window_activation import WindowActivationController
    widget._activation_controller = WindowActivationController(app, widget)

    # First-launch dialogs (interface picker + backup reminder) are deferred
    # to the first event-loop iteration so the window is fully mapped and
    # ACTIVE before the modal opens. Running them synchronously right after
    # show() (before app.exec()) can leave the parent unmapped/inactive,
    # which renders the dialog transparent, stuttering or unclickable.
    from PySide6.QtCore import QTimer

    def prepare_control_pages():
        if widget.ios_tweaks.content._inner is None and not getattr(widget.ios_tweaks.content, "_building", False):
            widget.ios_tweaks.content.rebuild()
        widget.ios_daemons.prepare_content()

    QTimer.singleShot(0, prepare_control_pages)

    from src.gui.startup_services import StartupServices
    app._startup_services = StartupServices(
        app, widget, dm, hotload, logger, _hotload_kill_or_none, _show_kill_message)
    app._startup_services.start()
    if app._startup_services._required_update_dialog is None:
        QTimer.singleShot(0, widget.run_first_launch_prompts)

    from src.tweaks.tweaks import tweaks, TweakID
    for arg in sys.argv:
        if arg.endswith('.tendies'):
            tweaks[TweakID.PosterBoard].add_tendie(arg)
        elif arg.endswith('.batter'):
            tweaks[TweakID.Templates].add_template(arg)

    logger.info("GoldenNugget launched.")

    # Qt widgets may only be destroyed on the GUI thread, but Python's cyclic GC
    # runs on whichever thread trips its threshold — and widget wrappers sit in
    # cycles constantly (every ``signal.connect(lambda: self....)`` is one). A
    # device worker (ApplyThread, the device monitor, ...) collecting one of
    # those destroys a QWidget off-thread and segfaults the app inside PySide's
    # ``getWrapperForQObject`` while the GUI thread is dispatching for it.
    #
    # Refcounting still frees objects immediately, so only *cycles* are deferred
    # here: they are collected by a timer on the GUI thread instead. The startup
    # UI graph is frozen first so it is never scanned (or collected) at all.
    import gc
    gc.freeze()
    gc.disable()

    _gc_timer = QTimer(app)
    _gc_timer.setInterval(120_000)
    _gc_timer.timeout.connect(gc.collect)
    _gc_timer.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
