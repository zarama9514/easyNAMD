from __future__ import annotations

import os

from core.namd.inspection import (
    PackageInspection,
    inspect_package_plan,
    stage_pressure_mode,
)
from core.namd.models import SystemConfig
from core.namd.pipeline import Pipeline
from core.namd.provenance import PackageProvenance, package_provenance


def write_protocol(
    path: str,
    system: SystemConfig,
    pipeline: Pipeline,
    warnings: list[str] | None = None,
    provenance: PackageProvenance | None = None,
    inspection: PackageInspection | None = None,
) -> str:
    stages = pipeline.expanded_stages()
    ff = system.forcefield
    provenance = provenance or package_provenance()
    inspection = inspection or inspect_package_plan(system, pipeline)
    lines = [
        "# easyNAMD Simulation Protocol",
        "",
        "## Provenance",
        f"- Generated at UTC: `{provenance.generated_at_utc}`",
        f"- easyNAMD git commit: `{provenance.git_commit}`",
        f"- Working tree dirty at generation: `{provenance.git_dirty}`",
        f"- Platform: `{provenance.platform}`",
        f"- Python: `{provenance.python}`",
        "",
        "## System",
        f"- PSF: `{os.path.basename(system.psf)}`",
        f"- Initial PDB: `{os.path.basename(system.pdb)}`",
        f"- Cell file: `{os.path.basename(system.cell_file)}`",
        f"- System type: `{system.system_type}`",
        f"- Start mode: `{system.start_mode}`",
        f"- Parameters: {len(system.parameter_files)} file(s)",
        f"- PSF atoms: {inspection.psf_atoms}",
        f"- PDB atoms: {inspection.pdb_atoms}",
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
            f"{stage_pressure_mode(system, stage)} | {stage.step_count()} | "
            f"{stage.duration_label()} | {stage.temperature:g} | "
            f"{stage.pressure:g} | {stage.restraints.force_constant:g} |"
        )
    lines += [
        "",
        "## Package Inspection",
        "| Stage | Config | Pressure | CUDA SOA | Constraints | Restart source |",
        "|---|---|---|---|---|---|",
    ]
    for row in inspection.stages:
        lines.append(
            f"| {row.stage} | `{row.prefix}.conf` | {row.pressure_mode} | "
            f"{row.cuda_soa_integrate} | {'on' if row.constraints else 'off'} | "
            f"{row.restart_source or 'initial coordinates'} |"
        )
    lines += [
        "",
        "## Input Files",
    ]
    for item in inspection.input_files:
        status = "OK" if item.exists and item.size > 0 else "MISSING/EMPTY"
        lines.append(f"- {status}: `{item.path}` ({item.size} bytes)")
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
