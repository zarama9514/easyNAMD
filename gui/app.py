import json
import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.vmd_viewer import VMDViewerController
from gui.build_panel import BuildPanel
from gui.prepare_panel import PreparePanel
from gui.simulate_panel import SimulatePanel

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

VMD_DEFAULTS = {
    "darwin": "/Applications/VMD2b1.app/Contents/vmd2b1/vmd_MACOSXARM64",
    "linux":  "/usr/local/bin/vmd",
    "win32":  r"C:\Program Files (x86)\University of Illinois\VMD\vmd.exe",
}

NAMD_DEFAULTS = {
    "darwin": [
        "~/software/NAMD_3.0.2_MacOS-universal-multicore/namd3",
        "/usr/local/bin/namd3",
        "/opt/homebrew/bin/namd3",
    ],
    "linux": [
        "/usr/local/bin/namd3",
        "/usr/bin/namd3",
    ],
    "win32": [
        r"C:\Program Files\NAMD\namd3.exe",
        r"C:\Program Files (x86)\NAMD\namd3.exe",
    ],
}


def load_config() -> dict:
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            data = json.load(f)
    else:
        data = {}
    defaults = {
        "vmd_path": "",
        "namd_path": "",
        "namd_threads": 8,
        "default_output_dir": "",
        "namd_system_type": "soluble",
        "namd_rigid_bonds": "all",
        "namd_nonbonded_freq": 1,
        "namd_full_elect_freq": 2,
        "namd_steps_per_cycle": 20,
        "namd_pairlists_per_cycle": 2,
        "namd_margin": 2.0,
        "namd_exclude": "scaled1-4",
        "namd_one_four_scaling": 1.0,
        "namd_switching": True,
        "namd_vdw_force_switching": True,
        "namd_use_settle": True,
        "namd_pme": True,
        "namd_langevin": True,
        "namd_langevin_hydrogen": False,
        "namd_group_pressure": True,
        "namd_flexible_cell": False,
        "namd_constant_area": False,
        "namd_surface_tension": 0.0,
        "namd_wrap_all": True,
        "namd_wrap_water": True,
        "namd_wrap_nearest": True,
        "namd_binary_output": True,
        "namd_binary_restart": True,
        "namd_cuda_soa_integrate": "auto",
        "namd_device_migration": "off",
    }
    defaults.update({key: value for key, value in data.items() if key in defaults})
    return defaults


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("easyNAMD")
        self.geometry("1400x820")
        self.minsize(900, 640)
        self.resizable(True, True)
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.config_data = load_config()
        self.vmd_viewer = VMDViewerController()

        # First-run setup if local VMD or NAMD is missing.
        if not self.config_data.get("vmd_path") or not self.config_data.get("namd_path"):
            self.after(100, self._first_run_setup)

        self._build_ui()

    def _build_ui(self):
        # Tab view
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)

        self.tabs.add("Prepare PDB")
        self.tabs.add("Build")
        self.tabs.add("Simulate")
        self.tabs.add("Settings")

        # Build tab
        self.build_panel = BuildPanel(
            self.tabs.tab("Build"),
            self.config_data,
            vmd_viewer=self.vmd_viewer,
            on_build_success=self._offer_simulate_from_build,
        )
        self.build_panel.pack(fill="both", expand=True)

        self.simulate_panel = SimulatePanel(
            self.tabs.tab("Simulate"),
            self.config_data,
            build_system_provider=self.build_panel.current_namd_system,
        )
        self.simulate_panel.pack(fill="both", expand=True)

        # Prepare PDB tab (hands the cleaned PDB off to Build on save)
        self.prepare_panel = PreparePanel(self.tabs.tab("Prepare PDB"),
                                          self.config_data,
                                          vmd_viewer=self.vmd_viewer,
                                          on_saved=self._use_in_build)
        self.prepare_panel.pack(fill="both", expand=True)

        # Settings tab
        self._build_settings_tab(self.tabs.tab("Settings"))

    def _use_in_build(self, path: str):
        self.build_panel.load_pdb_external(path)
        self.tabs.set("Build")

    def _offer_simulate_from_build(self, data: dict | None):
        if not data:
            return
        self.simulate_panel.load_build_data(data)
        if messagebox.askyesno(
                "NAMD package",
                "Build outputs are ready. Open the Simulate tab to generate a NAMD package?"):
            self.tabs.set("Simulate")

    def _build_settings_tab(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="VMD binary:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.vmd_var = tk.StringVar(value=self.config_data.get("vmd_path", ""))
        ctk.CTkEntry(frame, textvariable=self.vmd_var, width=380).grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkButton(frame, text="Browse", width=80, command=self._browse_vmd).grid(row=0, column=2, padx=5, pady=10)

        ctk.CTkLabel(frame, text="NAMD binary:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        self.namd_var = tk.StringVar(value=self.config_data.get("namd_path", ""))
        ctk.CTkEntry(frame, textvariable=self.namd_var, width=380).grid(row=1, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkButton(frame, text="Browse", width=80, command=self._browse_namd).grid(row=1, column=2, padx=5, pady=10)

        ctk.CTkLabel(frame, text="NAMD threads (+p):").grid(row=2, column=0, sticky="w", padx=10, pady=10)
        self.namd_threads_var = tk.StringVar(value=str(self.config_data.get("namd_threads", 8)))
        ctk.CTkEntry(frame, textvariable=self.namd_threads_var, width=120).grid(row=2, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(frame, text="Default output dir:").grid(row=3, column=0, sticky="w", padx=10, pady=10)
        self.default_outdir_var = tk.StringVar(value=self.config_data.get("default_output_dir", ""))
        ctk.CTkEntry(frame, textvariable=self.default_outdir_var, width=380).grid(row=3, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkButton(frame, text="Browse", width=80, command=self._browse_default_outdir).grid(row=3, column=2, padx=5, pady=10)

        ctk.CTkButton(frame, text="Save settings", command=self._save_settings).grid(
            row=4, column=0, columnspan=3, pady=20)

    def _browse_vmd(self):
        path = filedialog.askopenfilename(title="Select VMD binary")
        if path:
            self.vmd_var.set(path)

    def _browse_namd(self):
        path = filedialog.askopenfilename(title="Select NAMD binary")
        if path:
            self.namd_var.set(path)

    def _browse_default_outdir(self):
        path = filedialog.askdirectory(title="Select default output directory")
        if path:
            self.default_outdir_var.set(path)

    def _save_settings(self):
        self.config_data["vmd_path"] = self.vmd_var.get().strip()
        self.config_data["namd_path"] = self.namd_var.get().strip()
        self.config_data["namd_threads"] = max(1, int(self.namd_threads_var.get() or 1))
        self.config_data["default_output_dir"] = self.default_outdir_var.get().strip()
        self.config_data["namd_system_type"] = self.simulate_panel.system_type_var.get()
        self.config_data["namd_rigid_bonds"] = self.simulate_panel.rigid_bonds_var.get()
        self.config_data["namd_nonbonded_freq"] = int(self.simulate_panel.nonbonded_freq_var.get())
        self.config_data["namd_full_elect_freq"] = int(self.simulate_panel.full_elect_var.get())
        self.config_data["namd_steps_per_cycle"] = int(self.simulate_panel.steps_cycle_var.get())
        self.config_data["namd_pairlists_per_cycle"] = int(self.simulate_panel.pairlists_cycle_var.get())
        self.config_data["namd_margin"] = float(self.simulate_panel.margin_var.get())
        self.config_data["namd_exclude"] = self.simulate_panel.exclude_var.get()
        self.config_data["namd_one_four_scaling"] = float(self.simulate_panel.scaling_var.get())
        self.config_data["namd_switching"] = self.simulate_panel.switching_var.get()
        self.config_data["namd_vdw_force_switching"] = self.simulate_panel.vdw_switch_var.get()
        self.config_data["namd_use_settle"] = self.simulate_panel.use_settle_var.get()
        self.config_data["namd_pme"] = self.simulate_panel.pme_enabled_var.get()
        self.config_data["namd_langevin"] = self.simulate_panel.langevin_enabled_var.get()
        self.config_data["namd_langevin_hydrogen"] = self.simulate_panel.langevin_hydrogen_var.get()
        self.config_data["namd_group_pressure"] = self.simulate_panel.group_pressure_var.get()
        self.config_data["namd_flexible_cell"] = self.simulate_panel.flexible_cell_var.get()
        self.config_data["namd_constant_area"] = self.simulate_panel.constant_area_var.get()
        self.config_data["namd_surface_tension"] = float(self.simulate_panel.surface_tension_var.get())
        self.config_data["namd_wrap_all"] = self.simulate_panel.wrap_all_var.get()
        self.config_data["namd_wrap_water"] = self.simulate_panel.wrap_water_var.get()
        self.config_data["namd_wrap_nearest"] = self.simulate_panel.wrap_nearest_var.get()
        self.config_data["namd_binary_output"] = self.simulate_panel.binary_output_var.get()
        self.config_data["namd_binary_restart"] = self.simulate_panel.binary_restart_var.get()
        self.config_data["namd_cuda_soa_integrate"] = self.simulate_panel.cuda_soa_var.get()
        self.config_data["namd_device_migration"] = self.simulate_panel.device_migration_var.get()
        save_config(self.config_data)
        # Propagate to build panel
        self.build_panel.config = self.config_data
        self.simulate_panel.config = self.config_data
        messagebox.showinfo("Saved", "Settings saved.")

    def _first_run_setup(self):
        import sys
        platform = sys.platform
        default_vmd = VMD_DEFAULTS.get(platform, "")
        default_namd = _detect_namd(platform)

        configured = []
        if not self.config_data.get("vmd_path") and default_vmd and os.path.isfile(default_vmd):
            if messagebox.askyesno("First run", f"Found VMD at:\n{default_vmd}\n\nUse this path?"):
                self.config_data["vmd_path"] = default_vmd
                self.vmd_var.set(default_vmd)
                configured.append("VMD")
        if not self.config_data.get("namd_path") and default_namd:
            if messagebox.askyesno("First run", f"Found NAMD at:\n{default_namd}\n\nUse this path?"):
                self.config_data["namd_path"] = default_namd
                self.namd_var.set(default_namd)
                configured.append("NAMD")
        if configured:
            save_config(self.config_data)
        missing = []
        if not self.config_data.get("vmd_path"):
            missing.append("VMD")
        if not self.config_data.get("namd_path"):
            missing.append("NAMD")
        if missing:
            messagebox.showinfo("First run", f"Please set the {' and '.join(missing)} path in the Settings tab.")
            self.tabs.set("Settings")


def _detect_namd(platform: str) -> str:
    for path in NAMD_DEFAULTS.get(platform, []):
        expanded = os.path.expanduser(path)
        if os.path.isfile(expanded):
            return expanded
    return shutil.which("namd3") or shutil.which("namd2") or ""
