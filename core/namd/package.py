from __future__ import annotations

import json
import os
import shutil

from core.namd.conf_writer import write_stage_conf
from core.namd.models import Stage, SystemConfig, to_dict
from core.namd.pipeline import Pipeline


def validate_pipeline(system: SystemConfig, pipeline: Pipeline) -> list[str]:
    return validate_pipeline_report(system, pipeline)[0]


def validate_pipeline_report(system: SystemConfig, pipeline: Pipeline) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    if not system.psf or not os.path.isfile(system.psf):
        problems.append("PSF file is missing.")
    if not system.pdb or not os.path.isfile(system.pdb):
        problems.append("PDB file is missing.")
    if not system.cell_file or not os.path.isfile(system.cell_file):
        problems.append("cell.txt file is missing.")
    elif not _cell_lines(system.cell_file):
        problems.append("cell.txt does not contain cellBasisVector/cellOrigin lines.")
    if system.start_mode == "restart":
        if not system.restart_prefix:
            problems.append("Restart mode is enabled but restart prefix is empty.")
        else:
            for ext in ("coor", "vel", "xsc"):
                path = f"{system.restart_prefix}.restart.{ext}"
                if not os.path.isfile(path):
                    problems.append(f"Restart file is missing: {path}")
    for path in system.parameter_files:
        if not os.path.isfile(path):
            problems.append(f"Parameter file is missing: {path}")
    stages = pipeline.expanded_stages()
    if not stages:
        problems.append("Pipeline has no enabled stages.")
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
        pressure_mode = _stage_pressure_mode(system, stage)
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
        for label, freq in (
            ("restartfreq", stage.output.restart_freq),
            ("dcdfreq", stage.output.dcd_freq),
            ("outputEnergies", stage.output.output_energies),
        ):
            if freq <= 0:
                problems.append(f"{stage.name}: {label} must be positive.")
            elif freq > stage.step_count():
                warnings.append(f"{stage.name}: {label} is larger than the stage length.")
        if stage.restraints.force_constant > 0 and not stage.restraints.reference_pdb:
            warnings.append(
                f"{stage.name}: restraint k={stage.restraints.force_constant:g} is set, "
                "but no restraint reference PDB is attached; constraints will be off."
            )
        if stage.temperature_ramp and stage.ensemble == "NPT":
            warnings.append(f"{stage.name}: heating ramps are usually safer in NVT than NPT.")
    if system.pme.enabled and system.forcefield.cutoff < 8.0:
        warnings.append("cutoff is unusually small for explicit-water PME MD.")
    if system.system_type == "membrane":
        modes = [_stage_pressure_mode(system, stage) for stage in stages]
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
    if system.forcefield.cuda_soa_integrate == "auto":
        warnings.append(
            "CUDASOAintegrate auto writes off for minimization and on for MD stages. "
            "Use off for CPU-only runs."
        )
    return problems, warnings


def generate_package(
    system: SystemConfig,
    pipeline: Pipeline,
    package_dir: str,
    copy_inputs: bool = True,
) -> dict[str, list[str] | str]:
    problems, warnings = validate_pipeline_report(system, pipeline)
    if problems:
        raise ValueError("\n".join(problems))

    system.infer_stem()
    conf_dir = os.path.join(package_dir, "conf")
    output_dir = os.path.join(package_dir, "output")
    system_dir = os.path.join(package_dir, "system")
    template_dir = os.path.join(package_dir, "templates")
    for path in (conf_dir, output_dir, system_dir, template_dir):
        os.makedirs(path, exist_ok=True)

    stages = pipeline.expanded_stages()
    if copy_inputs:
        restraint_refs = [
            stage.restraints.reference_pdb for stage in stages
            if stage.restraints.reference_pdb
        ]
        restart_files = _restart_files(system.restart_prefix) if system.start_mode == "restart" else []
        _copy_unique([
            system.psf, system.pdb, system.cell_file,
            *system.parameter_files, *restraint_refs, *restart_files,
        ], system_dir)

    confs = []
    previous_prefix = None
    if system.start_mode == "restart" and system.restart_prefix:
        previous_prefix = f"../system/{os.path.basename(system.restart_prefix)}"
    for index, stage in enumerate(stages, start=1):
        confs.append(write_stage_conf(system, stage, index, previous_prefix, conf_dir))
        previous_prefix = stage.output_prefix(index)

    pipeline_path = os.path.join(template_dir, "pipeline.json")
    pipeline.save(pipeline_path)
    summary_path = os.path.join(package_dir, "namd_config_summary.json")
    with open(summary_path, "w") as f:
        json.dump({
            "system": to_dict(system),
            "pipeline": pipeline.to_dict(),
            "expanded_stages": [to_dict(stage) for stage in stages],
            "warnings": warnings,
        }, f, indent=2)
    readme = _write_readme(package_dir, system, pipeline)
    protocol = write_protocol(os.path.join(package_dir, "protocol.md"),
                              system, pipeline, warnings)

    return {
        "package_dir": package_dir,
        "confs": confs,
        "pipeline_template": pipeline_path,
        "summary": summary_path,
        "readme": readme,
        "protocol": protocol,
    }


def _copy_unique(paths: list[str], dest_dir: str):
    seen = set()
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        name = os.path.basename(path)
        if name in seen:
            continue
        seen.add(name)
        shutil.copy2(path, os.path.join(dest_dir, name))


def _restart_files(prefix: str) -> list[str]:
    if not prefix:
        return []
    return [f"{prefix}.restart.{ext}" for ext in ("coor", "vel", "xsc")]


def _cell_lines(path: str) -> list[str]:
    if not path or not os.path.isfile(path):
        return []
    with open(path) as f:
        return [
            line.strip() for line in f
            if line.strip().startswith(("cellBasisVector", "cellOrigin"))
        ]


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


def _stage_pressure_mode(system: SystemConfig, stage: Stage) -> str:
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


def _surface_tension_target(system: SystemConfig, stage: Stage) -> float:
    target = stage.pressure_control.surface_tension_target
    return target if target != 0.0 else system.barostat.surface_tension_target


def write_protocol(path: str, system: SystemConfig, pipeline: Pipeline,
                   warnings: list[str] | None = None) -> str:
    stages = pipeline.expanded_stages()
    ff = system.forcefield
    lines = [
        "# easyNAMD Simulation Protocol",
        "",
        "## System",
        f"- PSF: `{os.path.basename(system.psf)}`",
        f"- Initial PDB: `{os.path.basename(system.pdb)}`",
        f"- Cell file: `{os.path.basename(system.cell_file)}`",
        f"- System type: `{system.system_type}`",
        f"- Start mode: `{system.start_mode}`",
        f"- Parameters: {len(system.parameter_files)} file(s)",
        "",
        "## Global MD Settings",
        f"- Timestep: stage-specific, default 2 fs with `rigidBonds {ff.rigid_bonds}`",
        f"- Nonbonded: cutoff {ff.cutoff:g} A, switch {ff.switchdist:g} A, pairlist {ff.pairlistdist:g} A",
        f"- PME: {'on' if system.pme.enabled else 'off'}, grid spacing {system.pme.grid_spacing:g} A",
        f"- Langevin damping: {system.langevin.damping:g} 1/ps",
        f"- Langevin piston: target {system.barostat.target_pressure:g} bar, "
        f"period {system.barostat.piston_period:g} fs, decay {system.barostat.piston_decay:g} fs",
        f"- Surface tension target: {system.barostat.surface_tension_target:g} dyn/cm",
        f"- CUDASOAintegrate: `{ff.cuda_soa_integrate}`",
        f"- DeviceMigration: `{ff.device_migration}`",
        "",
        "## Pipeline",
        f"- Stages after chunk expansion: {len(stages)}",
        f"- Total MD duration: {pipeline.total_duration_ns():g} ns",
        "",
        "| # | Stage | Type | Ensemble | Pressure mode | Steps | Duration | T (K) | P (bar) | Restraint k |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for i, stage in enumerate(stages, start=1):
        lines.append(
            f"| {i:02d} | {stage.name} | {stage.stage_type} | {stage.ensemble} | "
            f"{_stage_pressure_mode(system, stage)} | {stage.step_count()} | "
            f"{stage.duration_label()} | {stage.temperature:g} | "
            f"{stage.pressure:g} | {stage.restraints.force_constant:g} |"
        )
    lines += [
        "",
        "## Running",
        "Run the generated `conf/*.conf` files sequentially with the NAMD command "
        "appropriate for your server or cluster scheduler.",
    ]
    if warnings:
        lines += ["", "## Warnings"]
        lines.extend(f"- {w}" for w in warnings)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _write_readme(package_dir: str, system: SystemConfig, pipeline: Pipeline) -> str:
    path = os.path.join(package_dir, "README_run.txt")
    lines = [
        "easyNAMD NAMD package",
        "",
        "Run the configs sequentially with the NAMD command used on your server.",
        "Examples:",
        "  namd3 conf/01_minimize.conf > 01_minimize.log",
        "  namd3 +p8 conf/02_heat.conf > 02_heat.log",
        "  CUDA_VISIBLE_DEVICES=0 namd3 +p4 conf/03_production.conf > 03_production.log",
        "",
        "For SLURM, wrap those commands in your local sbatch script.",
        "",
        "Pipeline:",
    ]
    for i, stage in enumerate(pipeline.expanded_stages(), start=1):
        lines.append(f"  {i:02d}. {stage.name} ({stage.stage_type}, {stage.ensemble})")
    lines += [
        "",
        "Protocol summary: protocol.md",
        "Edit conf/*.conf or templates/pipeline.json if your cluster requires changes.",
        "Trajectories and restarts are written to output/.",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path
