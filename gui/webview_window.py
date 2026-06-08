"""
Persistent pywebview window for the 3Dmol.js viewer.

Run as a separate process (pywebview needs the main thread, which conflicts
with tkinter's mainloop):

    python -m gui.webview_window <html_path> <selection_out> <command_file>

  - <selection_out>: JS calls api.set_selection(json) on every group toggle;
    we write the current selection here so the parent GUI can read it back.
  - <command_file>: the parent writes JSON {"js": "...", "n": <counter>} here;
    a watcher thread runs that JS inside the live page via evaluate_js. This is
    how the parent drives transitions (show groups / focus an altLoc) without
    ever restarting the window.
"""

import json
import os
import sys
import time

import webview

_STOP = False   # set when the window closes so the watcher thread exits cleanly


class Api:
    def __init__(self, selection_out: str | None):
        self._out = selection_out

    def set_selection(self, ids_json: str):
        if self._out:
            with open(self._out, 'w') as f:
                f.write(ids_json)


def _watch_commands(window, command_file: str):
    """Poll the command file; run any new JS payload in the page."""
    last = None
    while not _STOP:
        time.sleep(0.2)
        try:
            if not os.path.isfile(command_file):
                continue
            with open(command_file) as f:
                text = f.read()
            if text == last or not text.strip():
                continue
            last = text
            js = json.loads(text).get('js')
            if js:
                window.evaluate_js(js)
        except Exception:
            # transient read/parse races are harmless; keep watching
            pass


def main():
    global _STOP
    if len(sys.argv) < 2:
        print("usage: webview_window.py <html_path> [selection_out] [command_file]")
        sys.exit(1)

    html_path     = sys.argv[1]
    selection_out = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    command_file  = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None

    api = Api(selection_out)
    window = webview.create_window(
        "easyNAMD — 3D viewer",
        url=html_path,
        js_api=api,
        width=1100,
        height=760,
    )

    # stop the watcher loop as soon as the window is closed
    window.events.closed += lambda: globals().__setitem__('_STOP', True)

    if command_file:
        webview.start(_watch_commands, (window, command_file))
    else:
        webview.start()

    # guarantee the process exits even if a thread is still winding down
    _STOP = True
    os._exit(0)


if __name__ == "__main__":
    main()
