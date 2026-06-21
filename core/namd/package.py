from __future__ import annotations

import json
import os
import shutil

from core.namd.conf_writer import write_stage_conf
from core.namd.models import SlurmConfig, Stage, SystemConfig, to_dict
from core.namd.pipeline import Pipeline
from core.namd.run_scripts import write_run_sh, write_slurm


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
        if stage.ensemble not in ("NVE", "NVT", "NPT"):
            problems.append(f"{stage.name}: ensemble must be NVE, NVT, or NPT.")
        if stage.timestep <= 0:
            problems.append(f"{stage.name}: timestep must be positive.")
        if stage.stage_type == "md" and stage.steps <= 0:
            problems.append(f"{stage.name}: MD steps must be positive.")
        if stage.stage_type == "minimize" and stage.minimize_steps <= 0:
            problems.append(f"{stage.name}: minimization steps must be positive.")
        if stage.timestep >= 2.0 and system.forcefield.rigid_bonds == "none":
            problems.append(f"{stage.name}: 2 fs timestep should use rigidBonds all.")
        if stage.ensemble == "NPT" and (not system.cell_file or not _cell_lines(system.cell_file)):
            problems.append(f"{stage.name}: NPT requires periodic cell vectors.")
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
    return problems, warnings


def generate_package(
    system: SystemConfig,
    pipeline: Pipeline,
    package_dir: str,
    slurm: SlurmConfig | None = None,
    copy_inputs: bool = True,
) -> dict[str, list[str] | str]:
    problems, warnings = validate_pipeline_report(system, pipeline)
    if problems:
        raise ValueError("\n".join(problems))

    system.infer_stem()
    slurm = slurm or SlurmConfig(job_name=system.stem)
    conf_dir = os.path.join(package_dir, "conf")
    logs_dir = os.path.join(package_dir, "logs")
    output_dir = os.path.join(package_dir, "output")
    system_dir = os.path.join(package_dir, "system")
    template_dir = os.path.join(package_dir, "templates")
    scripts_dir = os.path.join(package_dir, "scripts")
    for path in (conf_dir, logs_dir, output_dir, system_dir, template_dir, scripts_dir):
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

    run_sh = write_run_sh(os.path.join(package_dir, "run.sh"), system, stages)
    submit = write_slurm(os.path.join(package_dir, "submit.slurm"), slurm, stages)
    pipeline_path = os.path.join(template_dir, "pipeline.json")
    pipeline.save(pipeline_path)
    summary_path = os.path.join(package_dir, "namd_config_summary.json")
    with open(summary_path, "w") as f:
        json.dump({
            "system": to_dict(system),
            "pipeline": pipeline.to_dict(),
            "expanded_stages": [to_dict(stage) for stage in stages],
            "slurm": to_dict(slurm),
            "warnings": warnings,
        }, f, indent=2)
    readme = _write_readme(package_dir, system, pipeline)
    protocol = write_protocol(os.path.join(package_dir, "protocol.md"),
                              system, pipeline, slurm, warnings)

    return {
        "package_dir": package_dir,
        "confs": confs,
        "run_sh": run_sh,
        "submit_slurm": submit,
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


def write_protocol(path: str, system: SystemConfig, pipeline: Pipeline,
                   slurm: SlurmConfig, warnings: list[str] | None = None) -> str:
    stages = pipeline.expanded_stages()
    ff = system.forcefield
    lines = [
        "# easyNAMD Simulation Protocol",
        "",
        "## System",
        f"- PSF: `{os.path.basename(system.psf)}`",
        f"- Initial PDB: `{os.path.basename(system.pdb)}`",
        f"- Cell file: `{os.path.basename(system.cell_file)}`",
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
        "",
        "## Pipeline",
        f"- Stages after chunk expansion: {len(stages)}",
        f"- Total MD duration: {pipeline.total_duration_ns():g} ns",
        "",
        "| # | Stage | Type | Ensemble | Steps | Duration | T (K) | P (bar) | Restraint k |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for i, stage in enumerate(stages, start=1):
        lines.append(
            f"| {i:02d} | {stage.name} | {stage.stage_type} | {stage.ensemble} | "
            f"{stage.step_count()} | {stage.duration_label()} | {stage.temperature:g} | "
            f"{stage.pressure:g} | {stage.restraints.force_constant:g} |"
        )
    lines += [
        "",
        "## Server Runner",
        f"- Bash command: `{system.namd_command}` with `{system.cpu_count}` CPU thread(s)",
        f"- SLURM profile: `{slurm.profile}`",
        f"- SLURM command: `{slurm.command}`",
        f"- SLURM resources: nodes={slurm.nodes}, ntasks={slurm.ntasks}, "
        f"cpus-per-task={slurm.cpus_per_task}, gpus-per-node={slurm.gpus_per_node}",
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
        "Local bash run:",
        "  ./run.sh",
        "",
        "SLURM run:",
        "  sbatch submit.slurm",
        "",
        "Pipeline:",
    ]
    for i, stage in enumerate(pipeline.expanded_stages(), start=1):
        lines.append(f"  {i:02d}. {stage.name} ({stage.stage_type}, {stage.ensemble})")
    lines += [
        "",
        "Protocol summary: protocol.md",
        "Edit conf/*.conf or templates/pipeline.json if your cluster requires changes.",
        "Logs are written to logs/, trajectories and restarts to output/.",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path
