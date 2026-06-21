import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from gui.build_panel import BuildPanel
from gui.prepare_panel import PreparePanel
from gui.simulate_panel import SimulatePanel

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
NAMD_LOCAL_DIR = "/Users/zarama9514/software/NAMD_3.0.2_MacOS-universal-multicore"

VMD_DEFAULTS = {
    "darwin": "/Applications/VMD2b1.app/Contents/vmd2b1/vmd_MACOSXARM64",
    "linux":  "/usr/local/bin/vmd",
    "win32":  r"C:\Program Files (x86)\University of Illinois\VMD\vmd.exe",
}

NAMD_DEFAULTS = {
    "darwin": os.path.join(NAMD_LOCAL_DIR, "namd3"),
    "linux":  "/usr/local/bin/namd3",
    "win32":  "namd3.exe",
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
        "namd_cores": 16,
        "default_output_dir": "",
        "slurm_partition": "",
        "slurm_account": "",
        "slurm_time": "24:00:00",
        "slurm_nodes": 1,
        "slurm_ntasks": 1,
        "slurm_cpus_per_task": 16,
        "slurm_namd_command": "namd3",
        "slurm_modules": "module load namd",
        "slurm_profile": "slurm_cpu",
        "slurm_gpus_per_node": 0,
        "slurm_gpu_devices": "",
        "slurm_set_cpu_affinity": False,
        "slurm_extra_namd_args": "",
    }
    defaults.update(data)
    return defaults


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("easyNAMD")
        self.geometry("1100x720")
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.config_data = load_config()

        # First-run setup if local engines are missing
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

        ctk.CTkLabel(frame, text="Local NAMD cores:").grid(row=2, column=0, sticky="w", padx=10, pady=10)
        self.namd_cores_var = tk.IntVar(value=int(self.config_data.get("namd_cores", 16)))
        ctk.CTkEntry(frame, textvariable=self.namd_cores_var, width=120).grid(row=2, column=1, padx=5, pady=10, sticky="w")

        ctk.CTkLabel(frame, text="Default output dir:").grid(row=3, column=0, sticky="w", padx=10, pady=10)
        self.default_outdir_var = tk.StringVar(value=self.config_data.get("default_output_dir", ""))
        ctk.CTkEntry(frame, textvariable=self.default_outdir_var, width=380).grid(row=3, column=1, padx=5, pady=10, sticky="ew")
        ctk.CTkButton(frame, text="Browse", width=80, command=self._browse_default_outdir).grid(row=3, column=2, padx=5, pady=10)

        ctk.CTkLabel(frame, text="SLURM partition:").grid(row=4, column=0, sticky="w", padx=10, pady=6)
        self.slurm_partition_var = tk.StringVar(value=self.config_data.get("slurm_partition", ""))
        ctk.CTkEntry(frame, textvariable=self.slurm_partition_var, width=160).grid(row=4, column=1, padx=5, pady=6, sticky="w")

        ctk.CTkLabel(frame, text="SLURM account:").grid(row=5, column=0, sticky="w", padx=10, pady=6)
        self.slurm_account_var = tk.StringVar(value=self.config_data.get("slurm_account", ""))
        ctk.CTkEntry(frame, textvariable=self.slurm_account_var, width=160).grid(row=5, column=1, padx=5, pady=6, sticky="w")

        ctk.CTkLabel(frame, text="SLURM time:").grid(row=6, column=0, sticky="w", padx=10, pady=6)
        self.slurm_time_var = tk.StringVar(value=self.config_data.get("slurm_time", "24:00:00"))
        ctk.CTkEntry(frame, textvariable=self.slurm_time_var, width=160).grid(row=6, column=1, padx=5, pady=6, sticky="w")

        ctk.CTkLabel(frame, text="SLURM modules (; separated):").grid(row=7, column=0, sticky="w", padx=10, pady=6)
        self.slurm_modules_var = tk.StringVar(value=self.config_data.get("slurm_modules", "module load namd"))
        ctk.CTkEntry(frame, textvariable=self.slurm_modules_var, width=380).grid(row=7, column=1, padx=5, pady=6, sticky="ew")

        ctk.CTkLabel(frame, text="SLURM profile:").grid(row=8, column=0, sticky="w", padx=10, pady=6)
        self.slurm_profile_var = tk.StringVar(value=self.config_data.get("slurm_profile", "slurm_cpu"))
        ctk.CTkEntry(frame, textvariable=self.slurm_profile_var, width=160).grid(row=8, column=1, padx=5, pady=6, sticky="w")

        ctk.CTkLabel(frame, text="GPUs per node:").grid(row=9, column=0, sticky="w", padx=10, pady=6)
        self.slurm_gpus_var = tk.IntVar(value=int(self.config_data.get("slurm_gpus_per_node", 0)))
        ctk.CTkEntry(frame, textvariable=self.slurm_gpus_var, width=100).grid(row=9, column=1, padx=5, pady=6, sticky="w")

        ctk.CTkLabel(frame, text="GPU devices:").grid(row=10, column=0, sticky="w", padx=10, pady=6)
        self.slurm_devices_var = tk.StringVar(value=self.config_data.get("slurm_gpu_devices", ""))
        ctk.CTkEntry(frame, textvariable=self.slurm_devices_var, width=160).grid(row=10, column=1, padx=5, pady=6, sticky="w")

        ctk.CTkLabel(frame, text="Extra NAMD args:").grid(row=11, column=0, sticky="w", padx=10, pady=6)
        self.slurm_extra_args_var = tk.StringVar(value=self.config_data.get("slurm_extra_namd_args", ""))
        ctk.CTkEntry(frame, textvariable=self.slurm_extra_args_var, width=380).grid(row=11, column=1, padx=5, pady=6, sticky="ew")

        self.slurm_affinity_var = tk.BooleanVar(value=bool(self.config_data.get("slurm_set_cpu_affinity", False)))
        ctk.CTkCheckBox(frame, text="Use +setcpuaffinity",
                        variable=self.slurm_affinity_var).grid(row=12, column=1, sticky="w", padx=5, pady=6)

        ctk.CTkButton(frame, text="Save settings", command=self._save_settings).grid(
            row=13, column=0, columnspan=3, pady=20)

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
        self.config_data["namd_cores"] = int(self.namd_cores_var.get())
        self.config_data["default_output_dir"] = self.default_outdir_var.get().strip()
        self.config_data["slurm_partition"] = self.slurm_partition_var.get().strip()
        self.config_data["slurm_account"] = self.slurm_account_var.get().strip()
        self.config_data["slurm_time"] = self.slurm_time_var.get().strip()
        self.config_data["slurm_modules"] = self.slurm_modules_var.get().strip()
        self.config_data["slurm_profile"] = self.slurm_profile_var.get().strip()
        self.config_data["slurm_gpus_per_node"] = int(self.slurm_gpus_var.get())
        self.config_data["slurm_gpu_devices"] = self.slurm_devices_var.get().strip()
        self.config_data["slurm_set_cpu_affinity"] = self.slurm_affinity_var.get()
        self.config_data["slurm_extra_namd_args"] = self.slurm_extra_args_var.get().strip()
        save_config(self.config_data)
        # Propagate to build panel
        self.build_panel.config = self.config_data
        self.simulate_panel.config = self.config_data
        self.simulate_panel.namd_var.set(self.config_data["namd_path"] or "namd3")
        self.simulate_panel.cpus_var.set(self.config_data["namd_cores"])
        self.simulate_panel.slurm_partition_var.set(self.config_data["slurm_partition"])
        self.simulate_panel.slurm_account_var.set(self.config_data["slurm_account"])
        self.simulate_panel.slurm_time_var.set(self.config_data["slurm_time"])
        self.simulate_panel.slurm_modules_var.set(self.config_data["slurm_modules"])
        self.simulate_panel.slurm_profile_var.set(self.config_data["slurm_profile"])
        self.simulate_panel.slurm_gpu_var.set(self.config_data["slurm_gpus_per_node"])
        self.simulate_panel.slurm_devices_var.set(self.config_data["slurm_gpu_devices"])
        self.simulate_panel.slurm_affinity_var.set(self.config_data["slurm_set_cpu_affinity"])
        self.simulate_panel.slurm_extra_args_var.set(self.config_data["slurm_extra_namd_args"])
        messagebox.showinfo("Saved", "Settings saved.")

    def _first_run_setup(self):
        import sys
        platform = sys.platform
        default_vmd = VMD_DEFAULTS.get(platform, "")
        default_namd = NAMD_DEFAULTS.get(platform, "")

        configured = []
        if not self.config_data.get("vmd_path") and default_vmd and os.path.isfile(default_vmd):
            if messagebox.askyesno("First run", f"Found VMD at:\n{default_vmd}\n\nUse this path?"):
                self.config_data["vmd_path"] = default_vmd
                self.vmd_var.set(default_vmd)
                configured.append("VMD")
        if not self.config_data.get("namd_path") and default_namd and os.path.isfile(default_namd):
            if messagebox.askyesno("First run", f"Found NAMD at:\n{default_namd}\n\nUse this path?"):
                self.config_data["namd_path"] = default_namd
                self.namd_var.set(default_namd)
                self.simulate_panel.namd_var.set(default_namd)
                configured.append("NAMD")
        if configured:
            save_config(self.config_data)
        if not self.config_data.get("vmd_path") or not self.config_data.get("namd_path"):
            messagebox.showinfo("First run", "Please set missing engine paths in the Settings tab.")
            self.tabs.set("Settings")
