from __future__ import annotations

import os

from core.namd.inspection import stage_pressure_mode
from core.namd.models import Stage, SystemConfig
from core.namd.pipeline import Pipeline
from core.namd.tools import count_pdb_atoms, count_psf_atoms, detect_system


def validate_pipeline(system: SystemConfig, pipeline: Pipeline) -> list[str]:
    return validate_pipeline_report(system, pipeline)[0]


def validate_pipeline_report(system: SystemConfig, pipeline: Pipeline) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    if not system.psf or not os.path.isfile(system.psf):
        problems.append("PSF file is missing.")
    if not system.pdb or not os.path.isfile(system.pdb):
        problems.append("PDB file is missing.")
    if system.psf and os.path.isfile(system.psf) and system.pdb and os.path.isfile(system.pdb):
        psf_atoms = count_psf_atoms(system.psf)
        pdb_atoms = count_pdb_atoms(system.pdb)
        if psf_atoms <= 0:
            warnings.append("Could not read atom count from PSF !NATOM section.")
        if pdb_atoms <= 0:
            problems.append("PDB has no ATOM/HETATM records.")
        if psf_atoms > 0 and pdb_atoms > 0 and psf_atoms != pdb_atoms:
            problems.append(f"PSF/PDB atom count mismatch: PSF has {psf_atoms}, PDB has {pdb_atoms}.")
    if not system.cell_file or not os.path.isfile(system.cell_file):
        problems.append("cell.txt file is missing.")
    elif not _cell_lines(system.cell_file):
        problems.append("cell.txt does not contain cellBasisVector/cellOrigin lines.")
    else:
        cell_keywords = _cell_keywords(system.cell_file)
        missing_vectors = [
            key for key in ("cellBasisVector1", "cellBasisVector2", "cellBasisVector3")
            if key not in cell_keywords
        ]
        if missing_vectors:
            problems.append(f"cell.txt is missing required vectors: {', '.join(missing_vectors)}.")
        if "cellOrigin" not in cell_keywords:
            warnings.append("cell.txt has no cellOrigin line.")
    if system.start_mode == "restart":
        if not system.restart_prefix:
            problems.append("Restart mode is enabled but restart prefix is empty.")
        else:
            for ext in ("coor", "vel", "xsc"):
                path = f"{system.restart_prefix}.restart.{ext}"
                if not os.path.isfile(path):
                    problems.append(f"Restart file is missing: {path}")
                elif os.path.getsize(path) == 0:
                    problems.append(f"Restart file is empty: {path}")
    for path in system.parameter_files:
        if not os.path.isfile(path):
            problems.append(f"Parameter file is missing: {path}")
        elif os.path.getsize(path) == 0:
            warnings.append(f"Parameter file is empty: {path}")
    _validate_input_basenames(
        [system.psf, system.pdb, system.cell_file, *system.parameter_files],
        problems,
    )

    stages = pipeline.expanded_stages()
    if not stages:
        problems.append("Pipeline has no enabled stages.")
    _validate_stages(system, stages, problems, warnings)
    _validate_global_settings(system, stages, warnings)
    return problems, warnings


def _validate_input_basenames(paths: list[str], problems: list[str]):
    seen: dict[str, str] = {}
    for path in paths:
        if not path:
            continue
        name = os.path.basename(path)
        absolute = os.path.abspath(path)
        existing = seen.get(name)
        if existing is None:
            seen[name] = absolute
        elif existing != absolute:
            problems.append(
                f"Input filename collision: both '{existing}' and '{absolute}' would copy as '{name}'."
            )


def _validate_stages(
    system: SystemConfig,
    stages: list[Stage],
    problems: list[str],
    warnings: list[str],
):
    seen = set()
    for stage in stages:
        slug = stage.slug()
        if slug in seen:
            problems.append(f"Duplicate stage name/slug after expansion: {slug}")
        seen.add(slug)
        if stage.stage_type not in ("minimize", "md"):
            problems.append(f"{stage.name}: stage_type must be minimize or md.")
        if stage.ensemble not in ("NVE", "NVT", "NPT", "NPAT", "NPgT"):
            problems.append(f"{stage.name}: ensemble must be NVE, NVT, NPT, NPAT, or NPgT.")
        pressure_mode = stage_pressure_mode(system, stage)
        if pressure_mode not in ("off", "isotropic", "semiisotropic", "npat", "surface_tension"):
            problems.append(
                f"{stage.name}: pressure mode must be off, isotropic, semiisotropic, npat, "
                "surface_tension, or auto."
            )
        if stage.timestep <= 0:
            problems.append(f"{stage.name}: timestep must be positive.")
        if stage.stage_type == "md" and stage.steps <= 0:
            problems.append(f"{stage.name}: MD steps must be positive.")
        if stage.stage_type == "minimize" and stage.minimize_steps <= 0:
            problems.append(f"{stage.name}: minimization steps must be positive.")
        if stage.stage_type == "minimize" and system.forcefield.cuda_soa_integrate == "on":
            problems.append(f"{stage.name}: CUDASOAintegrate on is incompatible with minimization.")
        if stage.timestep >= 2.0 and system.forcefield.rigid_bonds == "none":
            problems.append(f"{stage.name}: 2 fs timestep should use rigidBonds all.")
        if pressure_mode != "off" and (
            not system.cell_file or not _cell_lines(system.cell_file)
        ):
            problems.append(f"{stage.name}: pressure control requires periodic cell vectors.")
        if stage.ensemble in ("NPT", "NPAT", "NPgT") and pressure_mode == "off":
            warnings.append(f"{stage.name}: {stage.ensemble} selected but pressure control is off.")
        if pressure_mode in ("npat", "surface_tension") and system.system_type != "membrane":
            warnings.append(f"{stage.name}: {pressure_mode} pressure mode is intended for membrane systems.")
        if pressure_mode == "surface_tension" and _surface_tension_target(system, stage) == 0.0:
            warnings.append(f"{stage.name}: surface-tension mode selected with surfaceTensionTarget 0.")
        if pressure_mode == "npat" and stage.pressure_control.use_flexible_cell:
            problems.append(f"{stage.name}: NPAT pressure mode must not use flexible cell.")
        if pressure_mode == "surface_tension" and stage.pressure_control.use_constant_area:
            problems.append(f"{stage.name}: surface-tension mode must not use constant area.")
        _validate_stage_restart(stage, problems)
        _validate_output_freqs(stage, problems, warnings)
        _validate_restraints(system, stage, problems, warnings)
        if stage.temperature_ramp and stage.ensemble == "NPT":
            warnings.append(f"{stage.name}: heating ramps are usually safer in NVT than NPT.")


def _validate_output_freqs(stage: Stage, problems: list[str], warnings: list[str]):
    for label, freq in (
        ("restartfreq", stage.output.restart_freq),
        ("dcdfreq", stage.output.dcd_freq),
        ("outputEnergies", stage.output.output_energies),
    ):
        if freq <= 0:
            problems.append(f"{stage.name}: {label} must be positive.")
        elif freq > stage.step_count():
            warnings.append(f"{stage.name}: {label} is larger than the stage length.")


def _validate_stage_restart(stage: Stage, problems: list[str]):
    explicit = [
        ("coordinates", stage.restart_coordinates),
        ("velocities", stage.restart_velocities),
        ("xsc", stage.restart_xsc),
    ]
    filled = [(label, path) for label, path in explicit if path]
    if filled and len(filled) != 3:
        missing = [label for label, path in explicit if not path]
        problems.append(
            f"{stage.name}: explicit restart input is incomplete; missing {', '.join(missing)}."
        )
        return
    if len(filled) == 3:
        for label, path in filled:
            if not os.path.isfile(path):
                problems.append(f"{stage.name}: restart {label} file is missing: {path}")
            elif os.path.getsize(path) == 0:
                problems.append(f"{stage.name}: restart {label} file is empty: {path}")
        return
    if not stage.restart_prefix:
        return
    for ext in ("coor", "vel", "xsc"):
        path = f"{stage.restart_prefix}.restart.{ext}"
        if not os.path.isfile(path):
            problems.append(f"{stage.name}: stage restart file is missing: {path}")
        elif os.path.getsize(path) == 0:
            problems.append(f"{stage.name}: stage restart file is empty: {path}")


def _validate_restraints(
    system: SystemConfig,
    stage: Stage,
    problems: list[str],
    warnings: list[str],
):
    if stage.restraints.force_constant > 0 and not stage.restraints.reference_pdb:
        warnings.append(
            f"{stage.name}: restraint k={stage.restraints.force_constant:g} is set, "
            "but no restraint reference PDB is attached; constraints will be off."
        )
    if not stage.restraints.reference_pdb:
        return
    if not os.path.isfile(stage.restraints.reference_pdb):
        problems.append(f"{stage.name}: restraint reference PDB is missing: {stage.restraints.reference_pdb}")
        return
    ref_atoms = count_pdb_atoms(stage.restraints.reference_pdb)
    pdb_atoms = count_pdb_atoms(system.pdb)
    if ref_atoms <= 0:
        problems.append(f"{stage.name}: restraint reference PDB has no atoms.")
    elif pdb_atoms > 0 and ref_atoms != pdb_atoms:
        problems.append(
            f"{stage.name}: restraint reference atom count ({ref_atoms}) "
            f"does not match system PDB atom count ({pdb_atoms})."
        )


def _validate_global_settings(system: SystemConfig, stages: list[Stage], warnings: list[str]):
    if system.pme.enabled and system.forcefield.cutoff < 8.0:
        warnings.append("cutoff is unusually small for explicit-water PME MD.")
    if system.system_type == "membrane":
        _validate_membrane_system(system, stages, warnings)
    if system.forcefield.cuda_soa_integrate == "auto":
        warnings.append(
            "CUDASOAintegrate auto writes off for minimization and on for MD stages. "
            "Use off for CPU-only runs."
        )


def _validate_membrane_system(system: SystemConfig, stages: list[Stage], warnings: list[str]):
    summary = detect_system(system.pdb)
    if summary.lipid_atoms == 0:
        warnings.append("Membrane mode is selected, but no known lipid residue names were detected.")
    if summary.water_atoms == 0:
        warnings.append("Membrane mode is selected, but no water atoms were detected.")
    if summary.ion_atoms == 0:
        warnings.append("Membrane mode is selected, but no ions were detected.")
    modes = [stage_pressure_mode(system, stage) for stage in stages]
    if not any(mode in ("npat", "surface_tension") for mode in modes):
        warnings.append("Membrane system has no NPAT or NPgT stage; semi-isotropic NPT only may be fine after area equilibration.")
    if system.barostat.surface_tension_target != 0.0 and "surface_tension" not in modes:
        warnings.append("surfaceTensionTarget is set but no NPgT stage is present.")
    cell = _cell_geometry(system.cell_file)
    if cell:
        x, y, z = cell
        if z <= min(x, y):
            warnings.append(
                "Membrane mode assumes the bilayer normal is along Z, but cellBasisVector3 "
                "is not longer than the XY vectors."
            )


def _cell_lines(path: str) -> list[str]:
    if not path or not os.path.isfile(path):
        return []
    with open(path) as f:
        return [
            line.strip() for line in f
            if line.strip().startswith(("cellBasisVector", "cellOrigin"))
        ]


def _cell_keywords(path: str) -> set[str]:
    keywords: set[str] = set()
    for line in _cell_lines(path):
        parts = line.split()
        if parts:
            keywords.add(parts[0])
    return keywords


def _cell_geometry(path: str) -> tuple[float, float, float] | None:
    lines = _cell_lines(path)
    vectors: dict[str, float] = {}
    for line in lines:
        parts = line.split()
        if len(parts) != 4 or not parts[0].startswith("cellBasisVector"):
            continue
        try:
            values = [float(v) for v in parts[1:]]
        except ValueError:
            continue
        vectors[parts[0]] = sum(v * v for v in values) ** 0.5
    if all(key in vectors for key in ("cellBasisVector1", "cellBasisVector2", "cellBasisVector3")):
        return vectors["cellBasisVector1"], vectors["cellBasisVector2"], vectors["cellBasisVector3"]
    return None


def _surface_tension_target(system: SystemConfig, stage: Stage) -> float:
    target = stage.pressure_control.surface_tension_target
    return target if target != 0.0 else system.barostat.surface_tension_target
