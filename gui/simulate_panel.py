import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.namd import (
    Pipeline, SlurmConfig, Stage, SystemConfig, default_pipeline,
    template_library,
)
from core.namd.conf_writer import stage_conf_text
from core.namd.package import generate_package, validate_pipeline_report
from core.namd.run_scripts import render_run_sh, render_slurm

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
PARAMETERS_DIR = os.path.join(ROOT_DIR, "parameters")


def collect_parameter_files() -> list[str]:
    if not os.path.isdir(PARAMETERS_DIR):
        return []
    return sorted(
        os.path.join(PARAMETERS_DIR, f)
        for f in os.listdir(PARAMETERS_DIR)
        if f.endswith((".prm", ".str"))
    )


class StageRow(ctk.CTkFrame):
    def __init__(self, parent, stage: Stage, on_remove, on_duplicate, on_up, on_down):
        super().__init__(parent, fg_color="transparent")
        self.stage = stage
        self.enabled_var = tk.BooleanVar(value=stage.enabled)
        self.name_var = tk.StringVar(value=stage.name)
        self.type_var = tk.StringVar(value=stage.stage_type)
        self.ensemble_var = tk.StringVar(value=stage.ensemble)
        self.duration_var = tk.DoubleVar(value=stage.duration_value if stage.stage_type == "md" else stage.step_count())
        self.unit_var = tk.StringVar(value=stage.duration_unit if stage.stage_type == "md" else "steps")
        self.timestep_var = tk.DoubleVar(value=stage.timestep)
        self.temp_var = tk.DoubleVar(value=stage.temperature)
        self.pressure_var = tk.DoubleVar(value=stage.pressure)
        self.ramp_var = tk.BooleanVar(value=stage.temperature_ramp)
        self.chunks_var = tk.IntVar(value=max(1, int(stage.chunk_count)))
        self.restraint_var = tk.DoubleVar(value=stage.restraints.force_constant)
        self.restart_var = tk.IntVar(value=stage.output.restart_freq)
        self.dcd_var = tk.IntVar(value=stage.output.dcd_freq)
        self.energy_var = tk.IntVar(value=stage.output.output_energies)

        ctk.CTkCheckBox(self, text="", variable=self.enabled_var, width=26).grid(row=0, column=0, padx=2)
        ctk.CTkEntry(self, textvariable=self.name_var, width=130).grid(row=0, column=1, padx=2, sticky="ew")
        ctk.CTkOptionMenu(self, variable=self.type_var, values=["minimize", "md"], width=92).grid(row=0, column=2, padx=2)
        ctk.CTkOptionMenu(self, variable=self.ensemble_var, values=["NVE", "NVT", "NPT"], width=78).grid(row=0, column=3, padx=2)
        ctk.CTkEntry(self, textvariable=self.duration_var, width=70).grid(row=0, column=4, padx=2)
        ctk.CTkOptionMenu(self, variable=self.unit_var, values=["steps", "ps", "ns"], width=70).grid(row=0, column=5, padx=2)
        ctk.CTkEntry(self, textvariable=self.timestep_var, width=58).grid(row=0, column=6, padx=2)
        ctk.CTkEntry(self, textvariable=self.temp_var, width=62).grid(row=0, column=7, padx=2)
        ctk.CTkEntry(self, textvariable=self.pressure_var, width=72).grid(row=0, column=8, padx=2)
        ctk.CTkCheckBox(self, text="", variable=self.ramp_var, width=26).grid(row=0, column=9, padx=2)
        ctk.CTkEntry(self, textvariable=self.chunks_var, width=54).grid(row=0, column=10, padx=2)
        ctk.CTkEntry(self, textvariable=self.restraint_var, width=58).grid(row=0, column=11, padx=2)
        ctk.CTkEntry(self, textvariable=self.restart_var, width=72).grid(row=0, column=12, padx=2)
        ctk.CTkEntry(self, textvariable=self.dcd_var, width=72).grid(row=0, column=13, padx=2)
        ctk.CTkEntry(self, textvariable=self.energy_var, width=72).grid(row=0, column=14, padx=2)

        ctk.CTkButton(self, text="↑", width=28, command=lambda: on_up(self)).grid(row=0, column=15, padx=1)
        ctk.CTkButton(self, text="↓", width=28, command=lambda: on_down(self)).grid(row=0, column=16, padx=1)
        ctk.CTkButton(self, text="+", width=28, command=lambda: on_duplicate(self)).grid(row=0, column=17, padx=1)
        ctk.CTkButton(self, text="✕", width=28, fg_color="transparent",
                      text_color="red", command=lambda: on_remove(self)).grid(row=0, column=18, padx=1)

    def to_stage(self) -> Stage:
        duration = float(self.duration_var.get())
        unit = self.unit_var.get()
        stage = Stage(
            name=self.name_var.get().strip() or "stage",
            stage_type=self.type_var.get(),
            ensemble=self.ensemble_var.get(),
            enabled=self.enabled_var.get(),
            steps=max(1, int(duration)),
            minimize_steps=max(1, int(duration)),
            duration_value=duration,
            duration_unit=unit,
            timestep=float(self.timestep_var.get()),
            temperature=float(self.temp_var.get()),
            pressure=float(self.pressure_var.get()),
            temperature_ramp=self.ramp_var.get(),
            chunk_count=max(1, int(self.chunks_var.get())),
            ramp_start=self.stage.ramp_start,
            ramp_end=float(self.temp_var.get()),
            ramp_increment=self.stage.ramp_increment,
            ramp_freq=self.stage.ramp_freq,
        )
        stage.sync_steps_from_duration()
        stage.restraints.selection = self.stage.restraints.selection
        stage.restraints.reference_pdb = self.stage.restraints.reference_pdb
        stage.restraints.force_constant = float(self.restraint_var.get())
        stage.restraints.enabled = stage.restraints.force_constant > 0.0
        stage.output.restart_freq = max(1, int(self.restart_var.get()))
        stage.output.dcd_freq = max(1, int(self.dcd_var.get()))
        stage.output.xst_freq = max(1, int(self.dcd_var.get()))
        stage.output.output_energies = max(1, int(self.energy_var.get()))
        stage.output.output_timing = max(1, int(self.energy_var.get()))
        return stage


class SimulatePanel(ctk.CTkFrame):
    def __init__(self, parent, config: dict, build_system_provider=None):
        super().__init__(parent)
        self.config = config
        self._build_system_provider = build_system_provider
        self.pipeline = default_pipeline()
        self.stage_rows: list[StageRow] = []
        self.parameter_files: list[str] = collect_parameter_files()
        self._build_ui()
        self._populate_stages()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(self)
        scroll.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        scroll.columnconfigure(1, weight=1)
        row = 0

        ctk.CTkLabel(scroll, text="System", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, columnspan=4, sticky="w", padx=8, pady=(6, 2))
        row += 1

        self.psf_var = tk.StringVar()
        self.pdb_var = tk.StringVar()
        self.cell_var = tk.StringVar()
        self.outdir_var = tk.StringVar()
        self.package_var = tk.StringVar()
        self.start_mode_var = tk.StringVar(value="initial")
        self.restart_prefix_var = tk.StringVar()
        self.first_timestep_var = tk.IntVar(value=0)

        row = self._file_row(scroll, row, "PSF:", self.psf_var, self._browse_psf)
        row = self._file_row(scroll, row, "PDB:", self.pdb_var, self._browse_pdb)
        row = self._file_row(scroll, row, "Cell:", self.cell_var, self._browse_cell)
        row = self._file_row(scroll, row, "Package dir:", self.package_var, self._browse_package_dir)

        restart_row = ctk.CTkFrame(scroll, fg_color="transparent")
        restart_row.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=2)
        ctk.CTkLabel(restart_row, text="Start:", width=90, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(restart_row, variable=self.start_mode_var,
                          values=["initial", "restart"], width=110).pack(side="left", padx=4)
        ctk.CTkLabel(restart_row, text="restart prefix:", text_color="gray").pack(side="left", padx=(10, 2))
        ctk.CTkEntry(restart_row, textvariable=self.restart_prefix_var, width=300).pack(side="left", padx=4)
        ctk.CTkButton(restart_row, text="Browse", width=70,
                      command=self._browse_restart_prefix).pack(side="left", padx=2)
        ctk.CTkLabel(restart_row, text="first timestep:", text_color="gray").pack(side="left", padx=(10, 2))
        ctk.CTkEntry(restart_row, textvariable=self.first_timestep_var, width=90).pack(side="left", padx=4)
        row += 1

        param_row = ctk.CTkFrame(scroll, fg_color="transparent")
        param_row.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=2)
        ctk.CTkLabel(param_row, text="Parameters:", width=90, anchor="w").pack(side="left")
        self.params_label = ctk.CTkLabel(param_row, text=self._params_text(), anchor="w")
        self.params_label.pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkButton(param_row, text="Add", width=70, command=self._add_params).pack(side="left", padx=2)
        ctk.CTkButton(param_row, text="Reset", width=70, command=self._reset_params).pack(side="left", padx=2)
        ctk.CTkButton(param_row, text="From Build", width=90,
                      command=self._load_from_build).pack(side="left", padx=2)
        row += 1

        ctk.CTkLabel(scroll, text="Global MD defaults", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, columnspan=4, sticky="w", padx=8, pady=(12, 2))
        row += 1
        globals_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        globals_frame.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8)
        row += 1

        self.namd_var = tk.StringVar(value=self.config.get("namd_path", "namd3"))
        self.cpus_var = tk.IntVar(value=int(self.config.get("namd_cores", 16)))
        self.temp_var = tk.DoubleVar(value=310.0)
        self.cutoff_var = tk.DoubleVar(value=12.0)
        self.switch_var = tk.DoubleVar(value=10.0)
        self.pairlist_var = tk.DoubleVar(value=14.0)
        self.pme_var = tk.DoubleVar(value=1.0)
        self.damping_var = tk.DoubleVar(value=1.0)
        self.piston_period_var = tk.DoubleVar(value=50.0)
        self.piston_decay_var = tk.DoubleVar(value=25.0)

        self._small_field(globals_frame, "NAMD cmd", self.namd_var, 0, 0, 260)
        self._small_field(globals_frame, "CPUs", self.cpus_var, 0, 2, 70)
        self._small_field(globals_frame, "Temp K", self.temp_var, 0, 4, 80)
        self._small_field(globals_frame, "cutoff", self.cutoff_var, 1, 0, 80)
        self._small_field(globals_frame, "switch", self.switch_var, 1, 2, 80)
        self._small_field(globals_frame, "pairlist", self.pairlist_var, 1, 4, 80)
        self._small_field(globals_frame, "PME Å", self.pme_var, 2, 0, 80)
        self._small_field(globals_frame, "Langevin γ", self.damping_var, 2, 2, 80)
        self._small_field(globals_frame, "Piston period", self.piston_period_var, 2, 4, 80)
        self._small_field(globals_frame, "Piston decay", self.piston_decay_var, 2, 6, 80)

        ctk.CTkLabel(scroll, text="Pipeline", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, columnspan=4, sticky="w", padx=8, pady=(12, 2))
        row += 1
        toolbar = ctk.CTkFrame(scroll, fg_color="transparent")
        toolbar.grid(row=row, column=0, columnspan=4, sticky="w", padx=8, pady=2)
        row += 1
        self.template_var = tk.StringVar(value="Standard protein in water")
        self.template_menu = ctk.CTkOptionMenu(
            toolbar,
            variable=self.template_var,
            values=list(template_library().keys()),
            width=210,
        )
        self.template_menu.pack(side="left", padx=3)
        ctk.CTkButton(toolbar, text="Apply", width=70,
                      command=self._apply_library_template).pack(side="left", padx=3)
        ctk.CTkButton(toolbar, text="+ Stage", width=80, command=self._add_stage).pack(side="left", padx=3)
        ctk.CTkButton(toolbar, text="Save template", width=110,
                      command=self._save_template).pack(side="left", padx=3)
        ctk.CTkButton(toolbar, text="Load template", width=110,
                      command=self._load_template).pack(side="left", padx=3)

        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=(4, 0))
        labels = ["on", "name", "type", "ens", "dur", "unit", "dt", "T", "P", "heat", "chunks", "k", "restart", "dcd", "energy"]
        widths = [28, 130, 92, 78, 70, 70, 58, 62, 72, 34, 54, 58, 72, 72, 72]
        for col, (label, width) in enumerate(zip(labels, widths)):
            ctk.CTkLabel(header, text=label, width=width, text_color="gray").grid(row=0, column=col, padx=2)
        row += 1
        self.stages_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.stages_frame.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8)
        row += 1

        self.timeline_box = ctk.CTkTextbox(scroll, height=120, wrap="none")
        self.timeline_box.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=(6, 2))
        row += 1

        ctk.CTkLabel(scroll, text="SLURM", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, columnspan=4, sticky="w", padx=8, pady=(12, 2))
        row += 1
        slurm = ctk.CTkFrame(scroll, fg_color="transparent")
        slurm.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8)
        row += 1
        self.slurm_partition_var = tk.StringVar(value=self.config.get("slurm_partition", ""))
        self.slurm_account_var = tk.StringVar(value=self.config.get("slurm_account", ""))
        self.slurm_time_var = tk.StringVar(value=self.config.get("slurm_time", "24:00:00"))
        self.slurm_nodes_var = tk.IntVar(value=int(self.config.get("slurm_nodes", 1)))
        self.slurm_ntasks_var = tk.IntVar(value=int(self.config.get("slurm_ntasks", 1)))
        self.slurm_cpus_var = tk.IntVar(value=int(self.config.get("slurm_cpus_per_task", 16)))
        self.slurm_command_var = tk.StringVar(value=self.config.get("slurm_namd_command", "namd3"))
        self.slurm_modules_var = tk.StringVar(value=self.config.get("slurm_modules", "module load namd"))
        self.slurm_profile_var = tk.StringVar(value=self.config.get("slurm_profile", "slurm_cpu"))
        self.slurm_gpu_var = tk.IntVar(value=int(self.config.get("slurm_gpus_per_node", 0)))
        self.slurm_devices_var = tk.StringVar(value=self.config.get("slurm_gpu_devices", ""))
        self.slurm_affinity_var = tk.BooleanVar(value=bool(self.config.get("slurm_set_cpu_affinity", False)))
        self.slurm_extra_args_var = tk.StringVar(value=self.config.get("slurm_extra_namd_args", ""))
        self._small_field(slurm, "profile", self.slurm_profile_var, 0, 6, 120)
        self._small_field(slurm, "partition", self.slurm_partition_var, 0, 0, 120)
        self._small_field(slurm, "account", self.slurm_account_var, 0, 2, 120)
        self._small_field(slurm, "time", self.slurm_time_var, 0, 4, 100)
        self._small_field(slurm, "nodes", self.slurm_nodes_var, 1, 0, 70)
        self._small_field(slurm, "ntasks", self.slurm_ntasks_var, 1, 2, 70)
        self._small_field(slurm, "cpus/task", self.slurm_cpus_var, 1, 4, 80)
        self._small_field(slurm, "command", self.slurm_command_var, 2, 0, 180)
        self._small_field(slurm, "modules", self.slurm_modules_var, 2, 2, 320)
        self._small_field(slurm, "GPUs/node", self.slurm_gpu_var, 3, 0, 70)
        self._small_field(slurm, "devices", self.slurm_devices_var, 3, 2, 100)
        self._small_field(slurm, "extra args", self.slurm_extra_args_var, 3, 4, 220)
        ctk.CTkCheckBox(slurm, text="+setcpuaffinity",
                        variable=self.slurm_affinity_var).grid(row=3, column=6, sticky="w", padx=4)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkButton(actions, text="Validate", width=90, command=self._validate).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Timeline", width=90, command=self._refresh_timeline).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Preview package", width=130,
                      command=self._preview_package).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Generate NAMD package", fg_color="green",
                      command=self._generate).pack(side="left", padx=5)
        self.log_box = ctk.CTkTextbox(actions, height=120, wrap="none")
        self.log_box.pack(side="left", fill="both", expand=True, padx=5)

    def _file_row(self, parent, row, label, var, command):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=3)
        ctk.CTkEntry(parent, textvariable=var).grid(row=row, column=1, columnspan=2, sticky="ew", padx=5)
        ctk.CTkButton(parent, text="Browse", width=80, command=command).grid(row=row, column=3, padx=5)
        return row + 1

    def _small_field(self, parent, label, var, row, col, width):
        ctk.CTkLabel(parent, text=label, text_color="gray").grid(row=row, column=col, sticky="w", padx=4, pady=3)
        ctk.CTkEntry(parent, textvariable=var, width=width).grid(row=row, column=col + 1, sticky="w", padx=4, pady=3)

    def _populate_stages(self):
        for widget in self.stages_frame.winfo_children():
            widget.destroy()
        self.stage_rows.clear()
        for stage in self.pipeline.stages:
            row = StageRow(self.stages_frame, stage, self._remove_stage,
                           self._duplicate_stage, self._move_up, self._move_down)
            row.pack(fill="x", pady=2)
            self.stage_rows.append(row)
        self._refresh_timeline()

    def _set_pipeline(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self._populate_stages()

    def _apply_library_template(self):
        self._set_pipeline(template_library()[self.template_var.get()])

    def _collect_pipeline(self) -> Pipeline:
        return Pipeline(name=self.pipeline.name, stages=[row.to_stage() for row in self.stage_rows])

    def _collect_system(self) -> SystemConfig:
        system = SystemConfig(
            psf=self.psf_var.get().strip(),
            pdb=self.pdb_var.get().strip(),
            cell_file=self.cell_var.get().strip(),
            parameter_files=list(self.parameter_files),
            output_dir=self.package_var.get().strip(),
            namd_command=self.namd_var.get().strip() or "namd3",
            cpu_count=max(1, int(self.cpus_var.get())),
            start_mode=self.start_mode_var.get(),
            restart_prefix=self.restart_prefix_var.get().strip(),
            first_timestep=max(0, int(self.first_timestep_var.get())),
        )
        system.forcefield.cutoff = float(self.cutoff_var.get())
        system.forcefield.switchdist = float(self.switch_var.get())
        system.forcefield.pairlistdist = float(self.pairlist_var.get())
        system.pme.grid_spacing = float(self.pme_var.get())
        system.langevin.damping = float(self.damping_var.get())
        system.barostat.piston_period = float(self.piston_period_var.get())
        system.barostat.piston_decay = float(self.piston_decay_var.get())
        system.infer_stem()
        return system

    def _collect_slurm(self) -> SlurmConfig:
        stem = os.path.splitext(os.path.basename(self.pdb_var.get().strip()))[0] or "easynamd"
        return SlurmConfig(
            profile=self.slurm_profile_var.get().strip() or "slurm_cpu",
            job_name=stem,
            partition=self.slurm_partition_var.get().strip(),
            account=self.slurm_account_var.get().strip(),
            nodes=max(1, int(self.slurm_nodes_var.get())),
            ntasks=max(1, int(self.slurm_ntasks_var.get())),
            cpus_per_task=max(1, int(self.slurm_cpus_var.get())),
            time=self.slurm_time_var.get().strip() or "24:00:00",
            command=self.slurm_command_var.get().strip() or "namd3",
            modules=[line.strip() for line in self.slurm_modules_var.get().split(";") if line.strip()],
            set_cpu_affinity=self.slurm_affinity_var.get(),
            gpu_devices=self.slurm_devices_var.get().strip(),
            gpus_per_node=max(0, int(self.slurm_gpu_var.get())),
            extra_namd_args=self.slurm_extra_args_var.get().strip(),
        )

    def _browse_psf(self):
        self._browse_file(self.psf_var, [("PSF files", "*.psf"), ("All files", "*.*")])

    def _browse_pdb(self):
        self._browse_file(self.pdb_var, [("PDB files", "*.pdb"), ("All files", "*.*")])
        self._update_package_default()

    def _browse_cell(self):
        self._browse_file(self.cell_var, [("Cell files", "*.txt"), ("All files", "*.*")])

    def _browse_restart_prefix(self):
        path = filedialog.askopenfilename(
            title="Select .restart.coor/.vel/.xsc file",
            filetypes=[("NAMD restart", "*.coor *.vel *.xsc"), ("All files", "*.*")],
        )
        if not path:
            return
        for suffix in (".restart.coor", ".restart.vel", ".restart.xsc"):
            if path.endswith(suffix):
                path = path[:-len(suffix)]
                break
        self.restart_prefix_var.set(path)
        self.start_mode_var.set("restart")

    def _browse_file(self, var, filetypes):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            var.set(path)

    def _browse_package_dir(self):
        path = filedialog.askdirectory()
        if path:
            self.package_var.set(path)

    def _add_params(self):
        paths = filedialog.askopenfilenames(
            title="Select NAMD parameter files",
            filetypes=[("CHARMM parameters", "*.prm *.str"), ("All files", "*.*")],
        )
        if paths:
            self.parameter_files.extend(p for p in paths if p not in self.parameter_files)
            self.params_label.configure(text=self._params_text())

    def _reset_params(self):
        self.parameter_files = collect_parameter_files()
        self.params_label.configure(text=self._params_text())

    def _params_text(self) -> str:
        return f"{len(self.parameter_files)} file(s)" if self.parameter_files else "None"

    def _update_package_default(self):
        pdb = self.pdb_var.get().strip()
        if pdb and not self.package_var.get().strip():
            self.package_var.set(os.path.join(os.path.dirname(pdb), "namd"))

    def load_build_data(self, data: dict):
        self.psf_var.set(data.get("psf", ""))
        self.pdb_var.set(data.get("pdb", ""))
        self.cell_var.set(data.get("cell", ""))
        self.package_var.set(os.path.join(data.get("outdir", ""), "namd"))
        self.start_mode_var.set("initial")
        self.restart_prefix_var.set("")
        params = data.get("parameters")
        if params:
            self.parameter_files = list(params)
            self.params_label.configure(text=self._params_text())
        self._refresh_timeline()

    def _load_from_build(self):
        if not self._build_system_provider:
            return
        data = self._build_system_provider()
        if not data:
            messagebox.showinfo("Build system", "Build tab does not have a generated system yet.")
            return
        self.load_build_data(data)

    def _add_stage(self):
        self.pipeline.stages = [row.to_stage() for row in self.stage_rows]
        self.pipeline.stages.append(Stage(name="new_stage", ensemble="NPT"))
        self._populate_stages()

    def _remove_stage(self, row):
        self.pipeline.stages = [r.to_stage() for r in self.stage_rows if r is not row]
        self._populate_stages()

    def _duplicate_stage(self, row):
        stages = [r.to_stage() for r in self.stage_rows]
        idx = self.stage_rows.index(row)
        clone = row.to_stage()
        clone.name = clone.name + "_copy"
        stages.insert(idx + 1, clone)
        self.pipeline.stages = stages
        self._populate_stages()

    def _move_up(self, row):
        self._move(row, -1)

    def _move_down(self, row):
        self._move(row, 1)

    def _move(self, row, delta):
        stages = [r.to_stage() for r in self.stage_rows]
        idx = self.stage_rows.index(row)
        new = idx + delta
        if 0 <= new < len(stages):
            stages[idx], stages[new] = stages[new], stages[idx]
            self.pipeline.stages = stages
            self._populate_stages()

    def _save_template(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("NAMD pipeline", "*.json"), ("All files", "*.*")])
        if path:
            self._collect_pipeline().save(path)

    def _load_template(self):
        path = filedialog.askopenfilename(
            filetypes=[("NAMD pipeline", "*.json"), ("All files", "*.*")])
        if path:
            self.pipeline = Pipeline.load(path)
            self._populate_stages()

    def _validate(self):
        errors, warnings = validate_pipeline_report(self._collect_system(), self._collect_pipeline())
        if errors or warnings:
            parts = []
            if errors:
                parts.append("Errors:\n" + "\n".join(f"- {p}" for p in errors))
            if warnings:
                parts.append("Warnings:\n" + "\n".join(f"- {w}" for w in warnings))
            self._set_log("\n\n".join(parts))
        else:
            self._set_log("Validation OK.")

    def _preview_package(self):
        system = self._collect_system()
        pipeline = self._collect_pipeline()
        stages = pipeline.expanded_stages()
        if not stages:
            self._set_log("No enabled stages.")
            return
        previous = None
        if system.start_mode == "restart" and system.restart_prefix:
            previous = f"../system/{os.path.basename(system.restart_prefix)}"
        chunks = ["# Full NAMD package preview"]
        for i, stage in enumerate(stages, start=1):
            chunks.append(f"\n\n# ===== conf/{stage.output_prefix(i)}.conf =====\n")
            chunks.append(stage_conf_text(system, stage, i, previous))
            previous = stage.output_prefix(i)
        chunks.append("\n\n# ===== run.sh =====\n")
        chunks.append(render_run_sh(system, stages))
        chunks.append("\n\n# ===== submit.slurm =====\n")
        chunks.append(render_slurm(self._collect_slurm(), stages))
        self._set_log("".join(chunks))

    def _refresh_timeline(self):
        if not hasattr(self, "timeline_box"):
            return
        pipeline = self._collect_pipeline()
        stages = pipeline.expanded_stages()
        lines = [
            f"Pipeline: {pipeline.name}",
            f"Expanded stages: {len(stages)}   total MD: {pipeline.total_duration_ns():g} ns   total steps: {pipeline.total_steps()}",
            "",
        ]
        for i, stage in enumerate(stages, start=1):
            lines.append(
                f"{i:02d}. {stage.output_prefix(i)} | {stage.stage_type}/{stage.ensemble} | "
                f"{stage.step_count()} steps | {stage.duration_label()} | "
                f"T={stage.temperature:g} K | P={stage.pressure:g} bar | k={stage.restraints.force_constant:g}"
            )
        self.timeline_box.configure(state="normal")
        self.timeline_box.delete("1.0", "end")
        self.timeline_box.insert("end", "\n".join(lines))
        self.timeline_box.configure(state="disabled")

    def _generate(self):
        system = self._collect_system()
        pipeline = self._collect_pipeline()
        package_dir = self.package_var.get().strip()
        if not package_dir:
            messagebox.showerror("Error", "Select a package directory.")
            return
        try:
            result = generate_package(system, pipeline, package_dir, self._collect_slurm())
        except Exception as e:
            self._set_log(str(e))
            messagebox.showerror("NAMD package", str(e))
            return
        self._set_log(
            "Generated NAMD package:\n"
            f"{result['package_dir']}\n\n"
            f"Configs: {len(result['confs'])}\n"
            f"Run: {result['run_sh']}\n"
            f"SLURM: {result['submit_slurm']}\n"
            f"Protocol: {result['protocol']}"
        )
        messagebox.showinfo("NAMD package", f"Generated:\n{result['package_dir']}")

    def _set_log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", text)
        self.log_box.configure(state="disabled")
