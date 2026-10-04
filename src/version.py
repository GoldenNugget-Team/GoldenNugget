"""App version constants shared by the backend and the GUI.

Historically these lived in ``src/gui/version.py``; they moved here so the
backend (hotload, crash handling, logging, update checks) never depends on the
GUI package. ``src/gui/version.py`` re-exports them for the GUI side.
"""

App_Version = "9.5.3"
App_Build = 0
