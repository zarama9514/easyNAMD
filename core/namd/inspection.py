from __future__ import annotations

import os
from dataclasses import asdict, dataclass

from core.namd.models import Stage, SystemConfig
from core.namd.pipeline import Pipeline
from core.namd.tools import count_pdb_atoms, count_psf_atoms


@dataclass
class InputFileInspection:
    path: str
    exists: bool
    size: int


@dataclass
class StageInspection:
    index: int
    prefix: str
    stage: str
    type: str
    ensemble: str
    pressure_mode: str
    cuda_soa_integrate: str
    constraints: bool
    restart_source: str | None
    steps: int
    duration_ps: float


@dataclass
class PackageInspection:
    input_files: list[InputFileInspection]
    pdb_atoms: int
    psf_atoms: int
    stages: list[StageInspection]

    def to_dict(self) -> dict:
        return asdict(self)


def inspect_package_plan(system: SystemConfig, pipeline: Pipeline) -> PackageInspection:
    stages = pipeline.expanded_stages()
    copied_inputs = [
        system.psf,
        system.pdb,
        system.cell_file,
        *system.parameter_files,
    ]
    copied_inputs.extend(
        stage.restraints.reference_pdb for stage in stages
        if stage.restraints.reference_pdb
    )
    if system.start_mode == "restart":
        copied_inputs.extend(restart_files(system.restart_prefix))
    for stage in stages:
        if has_explicit_restart_files(stage):
            copied_inputs.extend(stage_restart_files(stage))
        elif stage.restart_prefix:
            copied_inputs.extend(restart_files(stage.restart_prefix))

    input_files = []
    seen = set()
    for path in copied_inputs:
        if not path or path in seen:
            continue
        seen.add(path)
        input_files.append(InputFileInspection(
            path=path,
            exists=os.path.isfile(path),
            size=os.path.getsize(path) if os.path.isfile(path) else 0,
        ))

    previous = external_restart_source(system.restart_prefix) if system.start_mode == "restart" else None
    stage_rows = []
    for index, stage in enumerate(stages, start=1):
        restart_source = stage_restart_source(stage, previous)
        stage_rows.append(StageInspection(
            index=index,
            prefix=stage.output_prefix(index),
            stage=stage.name,
            type=stage.stage_type,
            ensemble=stage.ensemble,
            pressure_mode=stage_pressure_mode(system, stage),
            cuda_soa_integrate=cuda_soa_value(system.forcefield.cuda_soa_integrate, stage),
            constraints=bool(stage.restraints.enabled and stage.restraints.reference_pdb),
            restart_source=restart_source,
            steps=stage.step_count(),
            duration_ps=stage.duration_ps(),
        ))
        previous = stage.output_prefix(index)

    return PackageInspection(
        input_files=input_files,
        pdb_atoms=count_pdb_atoms(system.pdb),
        psf_atoms=count_psf_atoms(system.psf),
        stages=stage_rows,
    )


def restart_files(prefix: str) -> list[str]:
    if not prefix:
        return []
    return [f"{prefix}.restart.{ext}" for ext in ("coor", "vel", "xsc")]


def external_restart_source(prefix: str) -> str | None:
    if not prefix:
        return None
    return f"../system/{os.path.basename(prefix)}"


def stage_restart_source(stage: Stage, previous_prefix: str | None) -> str | None:
    if has_explicit_restart_files(stage):
        return explicit_restart_source(stage)
    if stage.restart_prefix:
        return external_restart_source(stage.restart_prefix)
    return previous_prefix


def has_explicit_restart_files(stage: Stage) -> bool:
    return bool(stage.restart_coordinates and stage.restart_velocities and stage.restart_xsc)


def stage_restart_files(stage: Stage) -> list[str]:
    return [
        path for path in (
            stage.restart_coordinates,
            stage.restart_velocities,
            stage.restart_xsc,
        ) if path
    ]


def explicit_restart_source(stage: Stage) -> str:
    return (
        f"coor={os.path.basename(stage.restart_coordinates)}, "
        f"vel={os.path.basename(stage.restart_velocities)}, "
        f"xsc={os.path.basename(stage.restart_xsc)}"
    )


def stage_pressure_mode(system: SystemConfig, stage: Stage) -> str:
    mode = (stage.pressure_control.mode or "auto").lower()
    if stage.stage_type != "md" or stage.ensemble in ("NVE", "NVT"):
        return "off"
    if mode == "auto":
        if stage.ensemble == "NPAT":
            return "npat"
        if stage.ensemble == "NPgT":
            return "surface_tension"
        if stage.ensemble == "NPT" and system.system_type == "membrane":
            return "semiisotropic"
        if stage.ensemble == "NPT":
            return "isotropic"
        return "off"
    return mode


def cuda_soa_value(mode: str, stage: Stage) -> str:
    mode = (mode or "auto").lower()
    if mode in ("on", "off"):
        return mode
    return "off" if stage.stage_type == "minimize" else "on"
