import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from core.namd import Stage


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
        restart_frame = ctk.CTkFrame(self, fg_color="transparent")
        restart_frame.grid(row=0, column=12, padx=2, sticky="ew")
        self.restart_input_button = ctk.CTkButton(
            restart_frame,
            text=self._restart_input_label(),
            width=140,
            command=self._choose_restart_files,
        )
        self.restart_input_button.pack(side="left")
        ctk.CTkButton(
            restart_frame,
            text="x",
            width=28,
            fg_color="transparent",
            command=self._clear_restart_files,
        ).pack(side="left", padx=(2, 0))
        self._entry(self.restart_var, 72, 13)
        self._entry(self.dcd_var, 72, 14)
        self._entry(self.energy_var, 72, 15)

        ctk.CTkButton(self, text="↑", width=28, command=lambda: on_up(self)).grid(row=0, column=16, padx=1)
        ctk.CTkButton(self, text="↓", width=28, command=lambda: on_down(self)).grid(row=0, column=17, padx=1)
        ctk.CTkButton(self, text="+", width=28, command=lambda: on_duplicate(self)).grid(row=0, column=18, padx=1)
        ctk.CTkButton(self, text="✕", width=28, fg_color="transparent",
                      text_color="red", command=lambda: on_remove(self)).grid(row=0, column=19, padx=1)

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
            restart_prefix=self.stage.restart_prefix,
            restart_coordinates=self.stage.restart_coordinates,
            restart_velocities=self.stage.restart_velocities,
            restart_xsc=self.stage.restart_xsc,
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

    def _choose_restart_files(self):
        coor = filedialog.askopenfilename(
            title="Select NAMD restart coordinates (.coor)",
            filetypes=[("NAMD coordinates", "*.coor"), ("All files", "*.*")],
        )
        if not coor:
            return
        vel = filedialog.askopenfilename(
            title="Select NAMD restart velocities (.vel)",
            filetypes=[("NAMD velocities", "*.vel"), ("All files", "*.*")],
        )
        if not vel:
            return
        xsc = filedialog.askopenfilename(
            title="Select NAMD extended system (.xsc)",
            filetypes=[("NAMD extended system", "*.xsc"), ("All files", "*.*")],
        )
        if not xsc:
            return
        self.stage.restart_prefix = ""
        self.stage.restart_coordinates = coor
        self.stage.restart_velocities = vel
        self.stage.restart_xsc = xsc
        self.restart_input_button.configure(text=self._restart_input_label())
        self._commit()

    def _clear_restart_files(self):
        self.stage.restart_prefix = ""
        self.stage.restart_coordinates = ""
        self.stage.restart_velocities = ""
        self.stage.restart_xsc = ""
        self.restart_input_button.configure(text=self._restart_input_label())
        self._commit()

    def _restart_input_label(self) -> str:
        if self.stage.restart_coordinates and self.stage.restart_velocities and self.stage.restart_xsc:
            return "3 files"
        if self.stage.restart_prefix:
            return "prefix"
        return "none"


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
