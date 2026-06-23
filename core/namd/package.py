from __future__ import annotations

import json
import os
import shutil

from core.namd.conf_writer import write_stage_conf
from core.namd.inspection import (
    external_restart_source,
    has_explicit_restart_files,
    inspect_package_plan,
    restart_files,
    stage_restart_files,
    stage_restart_source,
)
from core.namd.models import SystemConfig, to_dict
from core.namd.pipeline import Pipeline
from core.namd.protocol import write_protocol
from core.namd.provenance import package_provenance
from core.namd.validation import validate_pipeline, validate_pipeline_report

__all__ = [
    "generate_package",
    "inspect_package_plan",
    "validate_pipeline",
    "validate_pipeline_report",
]


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
        restart_inputs = restart_files(system.restart_prefix) if system.start_mode == "restart" else []
        stage_restart_inputs = [
            file
            for stage in stages
            for file in (
                stage_restart_files(stage)
                if has_explicit_restart_files(stage)
                else restart_files(stage.restart_prefix)
            )
        ]
        _copy_unique([
            system.psf, system.pdb, system.cell_file,
            *system.parameter_files, *restraint_refs, *restart_inputs, *stage_restart_inputs,
        ], system_dir)

    confs = []
    previous_prefix = external_restart_source(system.restart_prefix) if system.start_mode == "restart" else None
    for index, stage in enumerate(stages, start=1):
        confs.append(write_stage_conf(
            system,
            stage,
            index,
            stage_restart_source(stage, previous_prefix),
            conf_dir,
        ))
        previous_prefix = stage.output_prefix(index)

    pipeline_path = os.path.join(template_dir, "pipeline.json")
    pipeline.save(pipeline_path)
    inspection = inspect_package_plan(system, pipeline)
    provenance = package_provenance()
    summary_path = os.path.join(package_dir, "namd_config_summary.json")
    with open(summary_path, "w") as f:
        json.dump({
            "provenance": provenance.to_dict(),
            "system": to_dict(system),
            "pipeline": pipeline.to_dict(),
            "expanded_stages": [to_dict(stage) for stage in stages],
            "inspection": inspection.to_dict(),
            "warnings": warnings,
        }, f, indent=2)
    readme = _write_readme(package_dir, pipeline)
    protocol = write_protocol(
        os.path.join(package_dir, "protocol.md"),
        system,
        pipeline,
        warnings,
        provenance,
        inspection,
    )

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


def _write_readme(package_dir: str, pipeline: Pipeline) -> str:
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
