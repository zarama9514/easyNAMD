from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "stage"


@dataclass
class ForceFieldConfig:
    """Global nonbonded/integrator defaults for CHARMM36 explicit-water MD."""

    para_type_charmm: bool = True
    exclude: str = "scaled1-4"
    one_four_scaling: float = 1.0
    cutoff: float = 12.0
    switching: bool = True
    switchdist: float = 10.0
    pairlistdist: float = 14.0
    margin: float = 2.0
    steps_per_cycle: int = 20
    pairlists_per_cycle: int = 2
    nonbonded_freq: int = 1
    full_elect_frequency: int = 2
    rigid_bonds: str = "all"
    use_settle: bool = True
    vdw_force_switching: bool = True
    wrap_all: bool = True
    wrap_water: bool = True
    wrap_nearest: bool = True
    binary_output: bool = True
    binary_restart: bool = True


@dataclass
class PmeConfig:
    enabled: bool = True
    grid_spacing: float = 1.0


@dataclass
class LangevinConfig:
    enabled: bool = True
    damping: float = 1.0
    hydrogen: bool = False


@dataclass
class BarostatConfig:
    target_pressure: float = 1.01325
    piston_period: float = 50.0
    piston_decay: float = 25.0
    use_group_pressure: bool = True
    use_flexible_cell: bool = False
    use_constant_area: bool = False


@dataclass
class OutputConfig:
    restart_freq: int = 5000
    dcd_freq: int = 5000
    xst_freq: int = 5000
    output_energies: int = 1000
    output_timing: int = 1000


@dataclass
class RestraintConfig:
    """Optional positional restraints.

    `reference_pdb` is expected to contain force constants in `column` (usually
    beta). The GUI can later generate this file from a VMD selection.
    """

    enabled: bool = False
    reference_pdb: str = ""
    column: str = "B"
    selection: str = "protein and backbone"
    force_constant: float = 0.0


@dataclass
class Stage:
    name: str
    stage_type: str = "md"          # minimize | md
    ensemble: str = "NPT"           # NVE | NVT | NPT
    enabled: bool = True
    steps: int = 250000
    duration_value: float = 0.5
    duration_unit: str = "ns"       # steps | ps | ns
    timestep: float = 2.0
    temperature: float = 310.0
    pressure: float = 1.01325
    minimize_steps: int = 10000
    temperature_ramp: bool = False
    ramp_start: float = 0.0
    ramp_end: float = 310.0
    ramp_increment: float = 5.0
    ramp_freq: int = 1000
    restraints: RestraintConfig = field(default_factory=RestraintConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    custom_lines: list[str] = field(default_factory=list)
    chunk_count: int = 1            # split long MD stages into restart-chained chunks

    def slug(self) -> str:
        return slugify(self.name)

    def step_count(self) -> int:
        return self.minimize_steps if self.stage_type == "minimize" else self.steps

    def sync_steps_from_duration(self):
        """Update `steps` from duration fields for MD stages."""
        if self.stage_type == "minimize":
            return
        if self.duration_unit == "steps":
            self.steps = max(1, int(round(self.duration_value)))
        elif self.duration_unit == "ps":
            self.steps = max(1, int(round(self.duration_value * 1000.0 / self.timestep)))
        elif self.duration_unit == "ns":
            self.steps = max(1, int(round(self.duration_value * 1_000_000.0 / self.timestep)))

    def duration_ps(self) -> float:
        if self.stage_type == "minimize":
            return 0.0
        return self.steps * self.timestep / 1000.0

    def duration_label(self) -> str:
        ps = self.duration_ps()
        if ps >= 1000.0:
            return f"{ps / 1000.0:g} ns"
        return f"{ps:g} ps"

    def output_prefix(self, index: int) -> str:
        return f"{index:02d}_{self.slug()}"


@dataclass
class SlurmConfig:
    profile: str = "slurm_cpu"      # slurm_cpu | slurm_gpu | custom
    job_name: str = "easynamd"
    partition: str = ""
    account: str = ""
    nodes: int = 1
    ntasks: int = 1
    cpus_per_task: int = 16
    time: str = "24:00:00"
    modules: list[str] = field(default_factory=lambda: ["module load namd"])
    command: str = "namd3"
    use_srun: bool = True
    set_cpu_affinity: bool = False
    gpu_devices: str = ""           # e.g. 0 or 0,1; exported as +devices
    gpus_per_node: int = 0
    extra_namd_args: str = ""
    extra_sbatch: list[str] = field(default_factory=list)


@dataclass
class SystemConfig:
    psf: str = ""
    pdb: str = ""
    cell_file: str = ""
    parameter_files: list[str] = field(default_factory=list)
    output_dir: str = ""
    stem: str = "system"
    namd_command: str = "namd3"
    cpu_count: int = 16
    start_mode: str = "initial"     # initial | restart
    restart_prefix: str = ""        # prefix without .restart.coor/.vel/.xsc
    first_timestep: int = 0
    forcefield: ForceFieldConfig = field(default_factory=ForceFieldConfig)
    pme: PmeConfig = field(default_factory=PmeConfig)
    langevin: LangevinConfig = field(default_factory=LangevinConfig)
    barostat: BarostatConfig = field(default_factory=BarostatConfig)

    def infer_stem(self):
        if self.pdb:
            self.stem = os.path.splitext(os.path.basename(self.pdb))[0]


def dataclass_from_dict(cls, data: dict[str, Any]):
    """Small recursive loader for our dataclass tree."""
    if cls is Stage:
        data = dict(data)
        data["restraints"] = dataclass_from_dict(
            RestraintConfig, data.get("restraints", {}))
        data["output"] = dataclass_from_dict(OutputConfig, data.get("output", {}))
        return Stage(**_known_kwargs(Stage, data))
    if cls is SystemConfig:
        data = dict(data)
        data["forcefield"] = dataclass_from_dict(
            ForceFieldConfig, data.get("forcefield", {}))
        data["pme"] = dataclass_from_dict(PmeConfig, data.get("pme", {}))
        data["langevin"] = dataclass_from_dict(
            LangevinConfig, data.get("langevin", {}))
        data["barostat"] = dataclass_from_dict(
            BarostatConfig, data.get("barostat", {}))
        return SystemConfig(**_known_kwargs(SystemConfig, data))
    return cls(**_known_kwargs(cls, dict(data)))


def _known_kwargs(cls, data: dict[str, Any]) -> dict[str, Any]:
    names = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    return {k: v for k, v in data.items() if k in names}


def to_dict(obj) -> dict[str, Any]:
    return asdict(obj)
