"""
Standalone pywebview window for the 3Dmol.js molecular viewer.

Run as a separate process (pywebview needs the main thread and conflicts with
tkinter's mainloop):

    python -m gui.webview_window <html_path> <selection_out_path>

The JS page calls api.set_selection(json) on every checkbox toggle; we write
the current selection to <selection_out_path> so the parent GUI can read it
back when the window closes.
"""

import sys
import webview


class Api:
    def __init__(self, selection_out_path: str):
        self._out = selection_out_path

    def set_selection(self, ids_json: str):
        with open(self._out, 'w') as f:
            f.write(ids_json)


def main():
    if len(sys.argv) < 2:
        print("usage: webview_window.py <html_path> [selection_out_path]")
        sys.exit(1)

    html_path          = sys.argv[1]
    selection_out_path = sys.argv[2] if len(sys.argv) > 2 else None

    # Only expose the js_api when a selection file is requested (group view)
    api = Api(selection_out_path) if selection_out_path else None
    webview.create_window(
        "easyNAMD — 3D viewer",
        url=html_path,
        js_api=api,
        width=1000,
        height=720,
    )
    webview.start()


if __name__ == "__main__":
    main()
