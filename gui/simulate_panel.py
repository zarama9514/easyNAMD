import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from core.namd import (
    Pipeline, Stage, SystemConfig, default_pipeline, template_library,
    pressure_control_for_ensemble,
)
from core.namd.conf_writer import stage_conf_text
from core.namd.models import dataclass_from_dict, to_dict
from core.namd.package import generate_package, validate_pipeline_report
from core.namd.tools import (
    detect_system,
    inspect_restart,
    lint_conf_text,
    write_restraint_pdb,
)

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
    def __init__(self, parent, stage: Stage, on_remove, on_duplicate, on_up,
                 on_down, on_change):
        super().__init__(parent, fg_color="transparent")
        self.stage = stage
        self._on_change = on_change
        self._widgets_to_bind = []
        self.enabled_var = tk.BooleanVar(value=stage.enabled)
        self.name_var = tk.StringVar(value=stage.name)
        self.type_var = tk.StringVar(value=stage.stage_type)
        self.ensemble_var = tk.StringVar(value=stage.ensemble)
        duration = stage.duration_value if stage.stage_type == "md" else stage.step_count()
        self.duration_var = tk.StringVar(value=_num(duration))
        self.unit_var = tk.StringVar(value=stage.duration_unit if stage.stage_type == "md" else "steps")
        self.timestep_var = tk.StringVar(value=_num(stage.timestep))
        self.temp_var = tk.StringVar(value=_num(stage.temperature))
        self.pressure_var = tk.StringVar(value=_num(stage.pressure))
        self.ramp_var = tk.BooleanVar(value=stage.temperature_ramp)
        self.ramp_start_var = tk.StringVar(value=_num(stage.ramp_start))
        self.ramp_end_var = tk.StringVar(value=_num(stage.ramp_end))
        self.ramp_increment_var = tk.StringVar(value=_num(stage.ramp_increment))
        self.ramp_freq_var = tk.StringVar(value=_num(stage.ramp_freq))
        self.chunks_var = tk.StringVar(value=_num(max(1, int(stage.chunk_count))))
        self.restraint_var = tk.StringVar(value=_num(stage.restraints.force_constant))
        self.restart_var = tk.StringVar(value=_num(stage.output.restart_freq))
        self.dcd_var = tk.StringVar(value=_num(stage.output.dcd_freq))
        self.energy_var = tk.StringVar(value=_num(stage.output.output_energies))

        ctk.CTkCheckBox(self, text="", variable=self.enabled_var, width=26,
                        command=self._commit).grid(row=0, column=0, padx=2)
        self._entry(self.name_var, 130, 1)
        ctk.CTkOptionMenu(self, variable=self.type_var, values=["minimize", "md"],
                          width=92, command=lambda _: self._commit()).grid(row=0, column=2, padx=2)
        ctk.CTkOptionMenu(self, variable=self.ensemble_var,
                          values=["NVE", "NVT", "NPT", "NPAT", "NPgT"], width=78,
                          command=lambda _: self._commit()).grid(row=0, column=3, padx=2)
        self._entry(self.duration_var, 70, 4)
        ctk.CTkOptionMenu(self, variable=self.unit_var, values=["steps", "ps", "ns"],
                          width=70, command=lambda _: self._commit()).grid(row=0, column=5, padx=2)
        self._entry(self.timestep_var, 58, 6)
        self._entry(self.temp_var, 62, 7)
        self._entry(self.pressure_var, 72, 8)
        ctk.CTkCheckBox(self, text="", variable=self.ramp_var, width=26,
                        command=self._toggle_ramp_details).grid(row=0, column=9, padx=2)
        self._entry(self.chunks_var, 54, 10)
        self._entry(self.restraint_var, 58, 11)
        self._entry(self.restart_var, 72, 12)
        self._entry(self.dcd_var, 72, 13)
        self._entry(self.energy_var, 72, 14)

        ctk.CTkButton(self, text="↑", width=28, command=lambda: on_up(self)).grid(row=0, column=15, padx=1)
        ctk.CTkButton(self, text="↓", width=28, command=lambda: on_down(self)).grid(row=0, column=16, padx=1)
        ctk.CTkButton(self, text="+", width=28, command=lambda: on_duplicate(self)).grid(row=0, column=17, padx=1)
        ctk.CTkButton(self, text="✕", width=28, fg_color="transparent",
                      text_color="red", command=lambda: on_remove(self)).grid(row=0, column=18, padx=1)

        self.ramp_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.ramp_frame.grid(row=1, column=1, columnspan=14, sticky="w", padx=2, pady=(3, 0))
        self._ramp_entry("T0", self.ramp_start_var, 0)
        self._ramp_entry("Tend", self.ramp_end_var, 2)
        self._ramp_entry("dT", self.ramp_increment_var, 4)
        self._ramp_entry("rFreq", self.ramp_freq_var, 6)

        for widget in self._widgets_to_bind:
            widget.bind("<KeyRelease>", self._commit)
            widget.bind("<FocusOut>", self._commit)
        self._toggle_ramp_details(commit=False)

    def _entry(self, var, width: int, column: int):
        entry = ctk.CTkEntry(self, textvariable=var, width=width)
        entry.grid(row=0, column=column, padx=2, sticky="ew")
        self._widgets_to_bind.append(entry)

    def _ramp_entry(self, label: str, var, column: int):
        ctk.CTkLabel(self.ramp_frame, text=label, text_color="gray").grid(
            row=0, column=column, sticky="w", padx=(2, 3))
        entry = ctk.CTkEntry(self.ramp_frame, textvariable=var, width=64)
        entry.grid(row=0, column=column + 1, sticky="w", padx=(0, 8))
        self._widgets_to_bind.append(entry)

    def _toggle_ramp_details(self, commit: bool = True):
        if self.ramp_var.get():
            self.ramp_frame.grid()
        else:
            self.ramp_frame.grid_remove()
        if commit:
            self._commit(resize_table=True)

    def to_stage(self) -> Stage:
        duration = _float_value(self.duration_var, self.stage.duration_value)
        unit = self.unit_var.get()
        temperature = _float_value(self.temp_var, self.stage.temperature)
        dcd_freq = _int_value(self.dcd_var, self.stage.output.dcd_freq)
        energy_freq = _int_value(self.energy_var, self.stage.output.output_energies)
        stage = Stage(
            name=self.name_var.get().strip() or "stage",
            stage_type=self.type_var.get(),
            ensemble=self.ensemble_var.get(),
            enabled=self.enabled_var.get(),
            steps=max(1, int(round(duration))),
            minimize_steps=max(1, int(round(duration))),
            duration_value=duration,
            duration_unit=unit,
            timestep=_float_value(self.timestep_var, self.stage.timestep, 0.001),
            temperature=temperature,
            pressure=_float_value(self.pressure_var, self.stage.pressure),
            temperature_ramp=self.ramp_var.get(),
            pressure_control=self.stage.pressure_control,
            chunk_count=_int_value(self.chunks_var, self.stage.chunk_count, 1),
            ramp_start=_float_value(self.ramp_start_var, self.stage.ramp_start),
            ramp_end=_float_value(self.ramp_end_var, temperature),
            ramp_increment=_float_value(self.ramp_increment_var, self.stage.ramp_increment, 0.001),
            ramp_freq=_int_value(self.ramp_freq_var, self.stage.ramp_freq, 1),
        )
        stage.sync_steps_from_duration()
        stage.restraints.selection = self.stage.restraints.selection
        stage.restraints.reference_pdb = self.stage.restraints.reference_pdb
        stage.restraints.force_constant = _float_value(
            self.restraint_var, self.stage.restraints.force_constant)
        stage.restraints.enabled = stage.restraints.force_constant > 0.0
        stage.output.restart_freq = _int_value(self.restart_var, self.stage.output.restart_freq, 1)
        stage.output.dcd_freq = dcd_freq
        stage.output.xst_freq = dcd_freq
        stage.output.output_energies = energy_freq
        stage.output.output_timing = energy_freq
        return stage

    def _commit(self, event=None, resize_table: bool = False):
        self.stage = self.to_stage()
        self._on_change(self, resize_table)


def _num(value) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _float_value(var, fallback: float, minimum: float | None = None) -> float:
    try:
        value = float(str(var.get()).strip().replace(",", "."))
    except (TypeError, ValueError, tk.TclError):
        value = float(fallback)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _int_value(var, fallback: int, minimum: int = 1) -> int:
    try:
        value = int(round(float(str(var.get()).strip().replace(",", "."))))
    except (TypeError, ValueError, tk.TclError):
        value = int(fallback)
    return max(minimum, value)


class SimulatePanel(ctk.CTkFrame):
    def __init__(self, parent, config: dict, build_system_provider=None):
        super().__init__(parent)
        self.config = config
        self._build_system_provider = build_system_provider
        self.pipeline = default_pipeline()
        self.stage_rows: list[StageRow] = []
        self.parameter_files: list[str] = collect_parameter_files()
        self._timeline_after_id = None
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
        self.system_type_var = tk.StringVar(value=self.config.get("namd_system_type", "soluble"))

        row = self._file_row(scroll, row, "PSF:", self.psf_var, self._browse_psf)
        row = self._file_row(scroll, row, "PDB:", self.pdb_var, self._browse_pdb)
        row = self._file_row(scroll, row, "Cell:", self.cell_var, self._browse_cell)
        row = self._file_row(scroll, row, "Package dir:", self.package_var, self._browse_package_dir)

        type_row = ctk.CTkFrame(scroll, fg_color="transparent")
        type_row.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=2)
        ctk.CTkLabel(type_row, text="System type:", width=90, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            type_row,
            variable=self.system_type_var,
            values=["soluble", "membrane", "ligand"],
            width=130,
            command=lambda _: self._apply_system_type_defaults(),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            type_row,
            text="Membrane defaults",
            width=140,
            command=self._apply_membrane_defaults,
        ).pack(side="left", padx=6)
        row += 1

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
        ctk.CTkButton(param_row, text="Analyze", width=80,
                      command=self._analyze_system).pack(side="left", padx=2)
        row += 1

        ctk.CTkLabel(scroll, text="Global MD defaults", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, columnspan=4, sticky="w", padx=8, pady=(12, 2))
        row += 1
        globals_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        globals_frame.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8)
        row += 1

        self.temp_var = tk.DoubleVar(value=310.0)
        self.cutoff_var = tk.DoubleVar(value=12.0)
        self.switch_var = tk.DoubleVar(value=10.0)
        self.pairlist_var = tk.DoubleVar(value=14.0)
        self.pme_var = tk.DoubleVar(value=1.0)
        self.damping_var = tk.DoubleVar(value=1.0)
        self.piston_period_var = tk.DoubleVar(value=50.0)
        self.piston_decay_var = tk.DoubleVar(value=25.0)
        self.surface_tension_var = tk.DoubleVar(value=float(self.config.get("namd_surface_tension", 0.0)))
        self.rigid_bonds_var = tk.StringVar(value=self.config.get("namd_rigid_bonds", "all"))
        self.nonbonded_freq_var = tk.IntVar(value=int(self.config.get("namd_nonbonded_freq", 1)))
        self.full_elect_var = tk.IntVar(value=int(self.config.get("namd_full_elect_freq", 2)))
        self.steps_cycle_var = tk.IntVar(value=int(self.config.get("namd_steps_per_cycle", 20)))
        self.pairlists_cycle_var = tk.IntVar(value=int(self.config.get("namd_pairlists_per_cycle", 2)))
        self.margin_var = tk.DoubleVar(value=float(self.config.get("namd_margin", 2.0)))
        self.exclude_var = tk.StringVar(value=self.config.get("namd_exclude", "scaled1-4"))
        self.scaling_var = tk.DoubleVar(value=float(self.config.get("namd_one_four_scaling", 1.0)))
        self.switching_var = tk.BooleanVar(value=bool(self.config.get("namd_switching", True)))
        self.vdw_switch_var = tk.BooleanVar(value=bool(self.config.get("namd_vdw_force_switching", True)))
        self.use_settle_var = tk.BooleanVar(value=bool(self.config.get("namd_use_settle", True)))
        self.pme_enabled_var = tk.BooleanVar(value=bool(self.config.get("namd_pme", True)))
        self.langevin_enabled_var = tk.BooleanVar(value=bool(self.config.get("namd_langevin", True)))
        self.langevin_hydrogen_var = tk.BooleanVar(value=bool(self.config.get("namd_langevin_hydrogen", False)))
        self.group_pressure_var = tk.BooleanVar(value=bool(self.config.get("namd_group_pressure", True)))
        self.flexible_cell_var = tk.BooleanVar(value=bool(self.config.get("namd_flexible_cell", False)))
        self.constant_area_var = tk.BooleanVar(value=bool(self.config.get("namd_constant_area", False)))
        self.wrap_all_var = tk.BooleanVar(value=bool(self.config.get("namd_wrap_all", True)))
        self.wrap_water_var = tk.BooleanVar(value=bool(self.config.get("namd_wrap_water", True)))
        self.wrap_nearest_var = tk.BooleanVar(value=bool(self.config.get("namd_wrap_nearest", True)))
        self.binary_output_var = tk.BooleanVar(value=bool(self.config.get("namd_binary_output", True)))
        self.binary_restart_var = tk.BooleanVar(value=bool(self.config.get("namd_binary_restart", True)))
        self.cuda_soa_var = tk.StringVar(value=self.config.get("namd_cuda_soa_integrate", "auto"))
        self.device_migration_var = tk.StringVar(value=self.config.get("namd_device_migration", "off"))

        self._small_field(globals_frame, "Temp K", self.temp_var, 0, 0, 80)
        self._small_field(globals_frame, "cutoff", self.cutoff_var, 0, 2, 80)
        self._small_field(globals_frame, "switch", self.switch_var, 0, 4, 80)
        self._small_field(globals_frame, "pairlist", self.pairlist_var, 1, 0, 80)
        self._small_field(globals_frame, "PME A", self.pme_var, 1, 2, 80)
        self._small_field(globals_frame, "Langevin gamma", self.damping_var, 1, 4, 80)
        self._small_field(globals_frame, "Piston period", self.piston_period_var, 2, 0, 80)
        self._small_field(globals_frame, "Piston decay", self.piston_decay_var, 2, 2, 80)
        self._small_field(globals_frame, "Surface tension", self.surface_tension_var, 2, 4, 80)

        ctk.CTkLabel(scroll, text="Advanced MD settings", font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, columnspan=4, sticky="w", padx=8, pady=(12, 2))
        row += 1
        advanced = ctk.CTkFrame(scroll, fg_color="transparent")
        advanced.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8)
        row += 1
        self._small_menu(advanced, "rigidBonds", self.rigid_bonds_var,
                         ["all", "water", "none"], 0, 0, 90)
        self._small_field(advanced, "nonbondedFreq", self.nonbonded_freq_var, 0, 2, 70)
        self._small_field(advanced, "fullElectFreq", self.full_elect_var, 0, 4, 70)
        self._small_field(advanced, "steps/cycle", self.steps_cycle_var, 1, 0, 70)
        self._small_field(advanced, "pairlists/cycle", self.pairlists_cycle_var, 1, 2, 70)
        self._small_field(advanced, "margin", self.margin_var, 1, 4, 70)
        self._small_menu(advanced, "exclude", self.exclude_var,
                         ["scaled1-4", "1-4", "none"], 2, 0, 110)
        self._small_field(advanced, "1-4 scaling", self.scaling_var, 2, 2, 70)
        self._small_menu(advanced, "CUDASOAintegrate", self.cuda_soa_var,
                         ["auto", "on", "off"], 2, 4, 90)
        self._small_menu(advanced, "DeviceMigration", self.device_migration_var,
                         ["off", "on"], 3, 0, 80)
        checks = ctk.CTkFrame(scroll, fg_color="transparent")
        checks.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=(2, 0))
        row += 1
        for index, (text, var) in enumerate([
            ("switching", self.switching_var),
            ("vdwForceSwitching", self.vdw_switch_var),
            ("useSettle", self.use_settle_var),
            ("PME", self.pme_enabled_var),
            ("Langevin", self.langevin_enabled_var),
            ("Langevin H", self.langevin_hydrogen_var),
            ("group pressure", self.group_pressure_var),
            ("flexible cell", self.flexible_cell_var),
            ("constant area", self.constant_area_var),
            ("wrap all", self.wrap_all_var),
            ("wrap water", self.wrap_water_var),
            ("wrap nearest", self.wrap_nearest_var),
            ("binary output", self.binary_output_var),
            ("binary restart", self.binary_restart_var),
        ]):
            ctk.CTkCheckBox(checks, text=text, variable=var).grid(
                row=index // 4, column=index % 4, sticky="w", padx=5, pady=2)

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
        ctk.CTkButton(toolbar, text="Restraints", width=95,
                      command=self._generate_restraints).pack(side="left", padx=3)
        ctk.CTkButton(toolbar, text="Schedule", width=90,
                      command=self._add_restraint_schedule).pack(side="left", padx=3)

        self.table_scroll = ctk.CTkScrollableFrame(
            scroll, orientation="horizontal", height=230, fg_color="transparent")
        self.table_scroll.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=(4, 0))
        self.table_scroll.columnconfigure(0, weight=1)
        row += 1
        header = ctk.CTkFrame(self.table_scroll, fg_color="transparent")
        header.grid(row=0, column=0, sticky="w", pady=(0, 2))
        labels = [
            "on", "name", "type", "ens", "dur", "unit", "dt", "T", "P",
            "ramp", "chunks", "k", "restart", "dcd", "energy",
        ]
        widths = [28, 130, 92, 78, 70, 70, 58, 62, 72, 34, 54, 58, 72, 72, 72]
        for col, (label, width) in enumerate(zip(labels, widths)):
            ctk.CTkLabel(header, text=label, width=width, text_color="gray").grid(row=0, column=col, padx=2)
        self.stages_frame = ctk.CTkFrame(self.table_scroll, fg_color="transparent")
        self.stages_frame.grid(row=1, column=0, sticky="w")

        self.timeline_box = ctk.CTkTextbox(scroll, height=120, wrap="none")
        self.timeline_box.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=(6, 2))
        row += 1

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkButton(actions, text="Validate", width=90, command=self._validate).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Report", width=90, command=self._report).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Restart", width=90, command=self._inspect_restart).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Lint", width=70, command=self._lint_preview).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Timeline", width=90, command=self._refresh_timeline).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Preview package", width=130,
                      command=self._preview_package).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Save project", width=105,
                      command=self._save_project).pack(side="left", padx=5)
        ctk.CTkButton(actions, text="Load project", width=105,
                      command=self._load_project).pack(side="left", padx=5)
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

    def _small_menu(self, parent, label, var, values, row, col, width):
        ctk.CTkLabel(parent, text=label, text_color="gray").grid(row=row, column=col, sticky="w", padx=4, pady=3)
        ctk.CTkOptionMenu(parent, variable=var, values=values, width=width).grid(
            row=row, column=col + 1, sticky="w", padx=4, pady=3)

    def _populate_stages(self):
        for widget in self.stages_frame.winfo_children():
            widget.destroy()
        self.stage_rows.clear()
        for stage in self.pipeline.stages:
            row = StageRow(self.stages_frame, stage, self._remove_stage,
                           self._duplicate_stage, self._move_up, self._move_down,
                           self._stage_changed)
            row.pack(fill="x", pady=2)
            self.stage_rows.append(row)
        self._resize_stage_table()
        self._refresh_timeline()

    def _set_pipeline(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self._populate_stages()

    def _apply_library_template(self):
        self._set_pipeline(self._with_stage_pressure_defaults(template_library()[self.template_var.get()]))

    def _collect_pipeline(self) -> Pipeline:
        return self._with_stage_pressure_defaults(
            Pipeline(name=self.pipeline.name, stages=[row.to_stage() for row in self.stage_rows])
        )

    def _with_stage_pressure_defaults(self, pipeline: Pipeline) -> Pipeline:
        system_type = self.system_type_var.get()
        for stage in pipeline.stages:
            stage.pressure_control = pressure_control_for_ensemble(stage.ensemble, system_type)
            stage.pressure_control.use_group_pressure = self.group_pressure_var.get()
            try:
                stage.pressure_control.surface_tension_target = float(self.surface_tension_var.get())
            except (TypeError, ValueError, tk.TclError):
                pass
        return pipeline

    def _stage_changed(self, changed_row: StageRow | None = None,
                       resize_table: bool = False):
        if changed_row is not None and changed_row in self.stage_rows:
            index = self.stage_rows.index(changed_row)
            if index < len(self.pipeline.stages):
                self.pipeline.stages[index] = changed_row.stage
            else:
                self.pipeline = self._collect_pipeline()
        else:
            self.pipeline = self._collect_pipeline()
        if resize_table:
            self._resize_stage_table()
        if self._timeline_after_id:
            self.after_cancel(self._timeline_after_id)
        self._timeline_after_id = self.after(250, self._refresh_timeline)

    def _resize_stage_table(self):
        if not hasattr(self, "table_scroll"):
            return
        height = 46 + sum(68 if row.ramp_var.get() else 38 for row in self.stage_rows)
        self.table_scroll.configure(height=max(120, height))

    def _collect_system(self) -> SystemConfig:
        system = SystemConfig(
            psf=self.psf_var.get().strip(),
            pdb=self.pdb_var.get().strip(),
            cell_file=self.cell_var.get().strip(),
            parameter_files=list(self.parameter_files),
            output_dir=self.package_var.get().strip(),
            system_type=self.system_type_var.get(),
            start_mode=self.start_mode_var.get(),
            restart_prefix=self.restart_prefix_var.get().strip(),
            first_timestep=max(0, int(self.first_timestep_var.get())),
        )
        system.forcefield.cutoff = float(self.cutoff_var.get())
        system.forcefield.switchdist = float(self.switch_var.get())
        system.forcefield.pairlistdist = float(self.pairlist_var.get())
        system.forcefield.rigid_bonds = self.rigid_bonds_var.get()
        system.forcefield.nonbonded_freq = max(1, int(self.nonbonded_freq_var.get()))
        system.forcefield.full_elect_frequency = max(1, int(self.full_elect_var.get()))
        system.forcefield.steps_per_cycle = max(1, int(self.steps_cycle_var.get()))
        system.forcefield.pairlists_per_cycle = max(1, int(self.pairlists_cycle_var.get()))
        system.forcefield.margin = float(self.margin_var.get())
        system.forcefield.exclude = self.exclude_var.get()
        system.forcefield.one_four_scaling = float(self.scaling_var.get())
        system.forcefield.switching = self.switching_var.get()
        system.forcefield.vdw_force_switching = self.vdw_switch_var.get()
        system.forcefield.use_settle = self.use_settle_var.get()
        system.forcefield.wrap_all = self.wrap_all_var.get()
        system.forcefield.wrap_water = self.wrap_water_var.get()
        system.forcefield.wrap_nearest = self.wrap_nearest_var.get()
        system.forcefield.binary_output = self.binary_output_var.get()
        system.forcefield.binary_restart = self.binary_restart_var.get()
        system.forcefield.cuda_soa_integrate = self.cuda_soa_var.get()
        system.forcefield.device_migration = self.device_migration_var.get()
        system.pme.enabled = self.pme_enabled_var.get()
        system.pme.grid_spacing = float(self.pme_var.get())
        system.langevin.enabled = self.langevin_enabled_var.get()
        system.langevin.damping = float(self.damping_var.get())
        system.langevin.hydrogen = self.langevin_hydrogen_var.get()
        system.barostat.piston_period = float(self.piston_period_var.get())
        system.barostat.piston_decay = float(self.piston_decay_var.get())
        system.barostat.surface_tension_target = float(self.surface_tension_var.get())
        system.barostat.use_group_pressure = self.group_pressure_var.get()
        system.barostat.use_flexible_cell = self.flexible_cell_var.get()
        system.barostat.use_constant_area = self.constant_area_var.get()
        system.infer_stem()
        return system

    def _apply_system_type_defaults(self):
        if self.system_type_var.get() == "membrane":
            self._apply_membrane_defaults(update_template=False)

    def _apply_membrane_defaults(self, update_template: bool = True):
        self.system_type_var.set("membrane")
        self.group_pressure_var.set(True)
        self.flexible_cell_var.set(True)
        self.constant_area_var.set(False)
        if float(self.surface_tension_var.get()) == 0.0:
            self.surface_tension_var.set(0.0)
        if update_template and "Membrane gentle relax" in template_library():
            self.template_var.set("Membrane gentle relax")
            self._set_pipeline(self._with_stage_pressure_defaults(template_library()["Membrane gentle relax"]))

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
        stage = Stage(name="new_stage", ensemble="NPT")
        stage.pressure_control = pressure_control_for_ensemble(stage.ensemble, self.system_type_var.get())
        self.pipeline.stages.append(stage)
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

    def _project_dict(self) -> dict:
        return {
            "version": 1,
            "system": to_dict(self._collect_system()),
            "pipeline": self._collect_pipeline().to_dict(),
            "parameter_files": list(self.parameter_files),
        }

    def _save_project(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".easynamd.json",
            filetypes=[("easyNAMD project", "*.easynamd.json"), ("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        with open(path, "w") as f:
            json.dump(self._project_dict(), f, indent=2)
        self._set_log(f"Saved project:\n{path}")

    def _load_project(self):
        path = filedialog.askopenfilename(
            filetypes=[("easyNAMD project", "*.easynamd.json *.json"), ("All files", "*.*")])
        if not path:
            return
        with open(path) as f:
            data = json.load(f)
        system = dataclass_from_dict(SystemConfig, data.get("system", {}))
        self._apply_system(system)
        self.parameter_files = list(data.get("parameter_files") or system.parameter_files)
        self.params_label.configure(text=self._params_text())
        self.pipeline = Pipeline.from_dict(data.get("pipeline", {}))
        self._populate_stages()
        self._set_log(f"Loaded project:\n{path}")

    def _apply_system(self, system: SystemConfig):
        self.psf_var.set(system.psf)
        self.pdb_var.set(system.pdb)
        self.cell_var.set(system.cell_file)
        self.package_var.set(system.output_dir)
        self.system_type_var.set(system.system_type)
        self.start_mode_var.set(system.start_mode)
        self.restart_prefix_var.set(system.restart_prefix)
        self.first_timestep_var.set(system.first_timestep)
        ff = system.forcefield
        self.cutoff_var.set(ff.cutoff)
        self.switch_var.set(ff.switchdist)
        self.pairlist_var.set(ff.pairlistdist)
        self.rigid_bonds_var.set(ff.rigid_bonds)
        self.nonbonded_freq_var.set(ff.nonbonded_freq)
        self.full_elect_var.set(ff.full_elect_frequency)
        self.steps_cycle_var.set(ff.steps_per_cycle)
        self.pairlists_cycle_var.set(ff.pairlists_per_cycle)
        self.margin_var.set(ff.margin)
        self.exclude_var.set(ff.exclude)
        self.scaling_var.set(ff.one_four_scaling)
        self.switching_var.set(ff.switching)
        self.vdw_switch_var.set(ff.vdw_force_switching)
        self.use_settle_var.set(ff.use_settle)
        self.wrap_all_var.set(ff.wrap_all)
        self.wrap_water_var.set(ff.wrap_water)
        self.wrap_nearest_var.set(ff.wrap_nearest)
        self.binary_output_var.set(ff.binary_output)
        self.binary_restart_var.set(ff.binary_restart)
        self.cuda_soa_var.set(ff.cuda_soa_integrate)
        self.device_migration_var.set(ff.device_migration)
        self.pme_enabled_var.set(system.pme.enabled)
        self.pme_var.set(system.pme.grid_spacing)
        self.langevin_enabled_var.set(system.langevin.enabled)
        self.damping_var.set(system.langevin.damping)
        self.langevin_hydrogen_var.set(system.langevin.hydrogen)
        self.piston_period_var.set(system.barostat.piston_period)
        self.piston_decay_var.set(system.barostat.piston_decay)
        self.surface_tension_var.set(system.barostat.surface_tension_target)
        self.group_pressure_var.set(system.barostat.use_group_pressure)
        self.flexible_cell_var.set(system.barostat.use_flexible_cell)
        self.constant_area_var.set(system.barostat.use_constant_area)

    def _analyze_system(self):
        summary = detect_system(self.pdb_var.get().strip())
        lines = ["System composition", *summary.lines()]
        if self.system_type_var.get() == "membrane" and summary.lipid_atoms == 0:
            lines.append("Warning: membrane mode is selected, but no known lipid residue names were detected.")
        if self.system_type_var.get() == "ligand" and summary.ligand_atoms == 0:
            lines.append("Warning: ligand mode is selected, but no ligand-like residue names were detected.")
        self._set_log("\n".join(lines))

    def _inspect_restart(self):
        self._set_log("\n".join(inspect_restart(self.restart_prefix_var.get().strip())))

    def _lint_preview(self):
        system = self._collect_system()
        pipeline = self._collect_pipeline()
        previous = None
        warnings = []
        if system.start_mode == "restart" and system.restart_prefix:
            previous = f"../system/{os.path.basename(system.restart_prefix)}"
        for i, stage in enumerate(pipeline.expanded_stages(), start=1):
            text = stage_conf_text(system, stage, i, previous)
            for warning in lint_conf_text(text):
                warnings.append(f"{stage.output_prefix(i)}: {warning}")
            previous = stage.output_prefix(i)
        self._set_log("\n".join(warnings) if warnings else "Config lint OK.")

    def _report(self):
        system = self._collect_system()
        pipeline = self._collect_pipeline()
        errors, warnings = validate_pipeline_report(system, pipeline)
        summary = detect_system(system.pdb)
        lines = [
            "Simulation report",
            f"System type: {system.system_type}",
            f"Pipeline: {pipeline.name}",
            f"Expanded stages: {len(pipeline.expanded_stages())}",
            f"Total MD: {pipeline.total_duration_ns():g} ns",
            "",
            *summary.lines(),
            "",
            "Validation",
        ]
        lines.extend(f"ERROR: {item}" for item in errors)
        lines.extend(f"WARN: {item}" for item in warnings)
        if not errors and not warnings:
            lines.append("OK")
        self._set_log("\n".join(lines))

    def _generate_restraints(self):
        pdb = self.pdb_var.get().strip()
        if not pdb or not os.path.isfile(pdb):
            messagebox.showerror("Restraints", "Select an input PDB first.")
            return
        selection = simpledialog.askstring(
            "Restraints",
            "Selection (examples: protein and backbone, protein and heavy, lipid and headgroup, ligand):",
            initialvalue="protein and backbone",
        )
        if not selection:
            return
        k = simpledialog.askfloat("Restraints", "Force constant:", initialvalue=5.0, minvalue=0.0)
        if k is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save restraint PDB",
            defaultextension=".pdb",
            filetypes=[("PDB", "*.pdb"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            selected = write_restraint_pdb(pdb, path, selection, k)
        except Exception as exc:
            messagebox.showerror("Restraints", str(exc))
            return
        for row in self.stage_rows:
            if row.restraint_var.get().strip() not in ("", "0", "0.0"):
                row.stage.restraints.reference_pdb = path
                row.stage.restraints.selection = selection
                row.stage.restraints.force_constant = k
        self.pipeline = self._collect_pipeline()
        self._set_log(f"Generated restraint PDB:\n{path}\nSelected atoms: {selected}")

    def _add_restraint_schedule(self):
        spec = simpledialog.askstring(
            "Restraint schedule",
            "Format: k_start,k_end,count,duration_ns,selection",
            initialvalue="10,0,5,0.5,protein and backbone",
        )
        if not spec:
            return
        parts = [p.strip() for p in spec.split(",", 4)]
        if len(parts) != 5:
            messagebox.showerror("Restraint schedule", "Expected: k_start,k_end,count,duration_ns,selection")
            return
        try:
            k_start = float(parts[0])
            k_end = float(parts[1])
            count = max(1, int(parts[2]))
            duration = max(0.001, float(parts[3]))
        except ValueError as exc:
            messagebox.showerror("Restraint schedule", str(exc))
            return
        selection = parts[4]
        stages = [row.to_stage() for row in self.stage_rows]
        denom = max(1, count - 1)
        for i in range(count):
            k = k_start + (k_end - k_start) * i / denom
            ensemble = "NPAT" if self.system_type_var.get() == "membrane" else "NPT"
            stage = Stage(
                name=f"schedule_k{k:g}".replace(".", "_"),
                stage_type="md",
                ensemble=ensemble,
                duration_value=duration,
                duration_unit="ns",
                timestep=2.0,
                pressure_control=pressure_control_for_ensemble(ensemble, self.system_type_var.get()),
            )
            stage.restraints.selection = selection
            stage.restraints.force_constant = k
            stage.restraints.enabled = k > 0.0
            stage.sync_steps_from_duration()
            stages.append(stage)
        self.pipeline.stages = stages
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
        self._set_log("".join(chunks))

    def _refresh_timeline(self):
        self._timeline_after_id = None
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
                f"{i:02d}. {stage.output_prefix(i)} | {stage.stage_type}/{stage.ensemble} "
                f"({stage.pressure_control.mode}) | "
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
            result = generate_package(system, pipeline, package_dir)
        except Exception as e:
            self._set_log(str(e))
            messagebox.showerror("NAMD package", str(e))
            return
        self._set_log(
            "Generated NAMD package:\n"
            f"{result['package_dir']}\n\n"
            f"Configs: {len(result['confs'])}\n"
            f"Protocol: {result['protocol']}\n"
            f"Summary: {result['summary']}"
        )
        messagebox.showinfo("NAMD package", f"Generated:\n{result['package_dir']}")

    def _set_log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", text)
        self.log_box.configure(state="disabled")
