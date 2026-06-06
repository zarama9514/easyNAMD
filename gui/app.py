import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from gui.build_panel import BuildPanel

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

VMD_DEFAULTS = {
    "darwin": "/Applications/VMD2b1.app/Contents/vmd2b1/vmd_MACOSXARM64",
    "linux":  "/usr/local/bin/vmd",
    "win32":  r"C:\Program Files (x86)\University of Illinois\VMD\vmd.exe",
}


def load_config() -> dict:
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {"vmd_path": "", "default_output_dir": ""}


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("easyNAMD")
        self.geometry("700x680")
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.config_data = load_config()

        # First-run setup if VMD path is missing
        if not self.config_data.get("vmd_path"):
            self.after(100, self._first_run_setup)

        self._build_ui()

    def _build_ui(self):
        # Tab view
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)

        self.tabs.add("Build")
        self.tabs.add("Settings")

        # Build tab
        self.build_panel = BuildPanel(self.tabs.tab("Build"), self.config_data)
        self.build_panel.pack(fill="both", expand=True)

        # Settings tab
        self._build_settings_tab(self.tabs.tab("Settings"))

    def _build_settings_tab(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="VMD binary:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.vmd_var = tk.StringVar(value=self.config_data.get("vmd_path", ""))
        ctk.CTkEntry(frame, textvariable=self.vmd_var, width=380).grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkButton(frame, text="Browse", width=80, command=self._browse_vmd).grid(row=0, column=2, padx=5, pady=10)

        ctk.CTkLabel(frame, text="Default output dir:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        self.default_outdir_var = tk.StringVar(value=self.config_data.get("default_output_dir", ""))
        ctk.CTkEntry(frame, textvariable=self.default_outdir_var, width=380).grid(row=1, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkButton(frame, text="Browse", width=80, command=self._browse_default_outdir).grid(row=1, column=2, padx=5, pady=10)

        ctk.CTkButton(frame, text="Save settings", command=self._save_settings).grid(
            row=2, column=0, columnspan=3, pady=20)

    def _browse_vmd(self):
        path = filedialog.askopenfilename(title="Select VMD binary")
        if path:
            self.vmd_var.set(path)

    def _browse_default_outdir(self):
        path = filedialog.askdirectory(title="Select default output directory")
        if path:
            self.default_outdir_var.set(path)

    def _save_settings(self):
        self.config_data["vmd_path"] = self.vmd_var.get().strip()
        self.config_data["default_output_dir"] = self.default_outdir_var.get().strip()
        save_config(self.config_data)
        # Propagate to build panel
        self.build_panel.config = self.config_data
        messagebox.showinfo("Saved", "Settings saved.")

    def _first_run_setup(self):
        import sys
        platform = sys.platform
        default_vmd = VMD_DEFAULTS.get(platform, "")

        msg = "VMD path is not configured.\n"
        if default_vmd and os.path.isfile(default_vmd):
            msg += f"Found VMD at:\n{default_vmd}\n\nUse this path?"
            if messagebox.askyesno("First run", msg):
                self.config_data["vmd_path"] = default_vmd
                self.vmd_var.set(default_vmd)
                save_config(self.config_data)
                return
        msg += "Please set it in the Settings tab."
        messagebox.showinfo("First run", msg)
        self.tabs.set("Settings")
