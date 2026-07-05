from __future__ import annotations

import json
import os
import shlex
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
    namd_command: str = "namd3",
    namd_threads: int = 8,
    copy_inputs: bool = True,
) -> dict[str, list[str] | str]:
    problems, warnings = validate_pipeline_report(system, pipeline)
    if problems:
        raise ValueError("\n".join(problems))

    system.infer_stem()
    conf_dir = os.path.join(package_dir, "conf")
    results_dir = os.path.join(package_dir, "results")
    system_dir = os.path.join(package_dir, "system")
    template_dir = os.path.join(package_dir, "templates")
    for path in (conf_dir, results_dir, system_dir, template_dir):
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
            output_dir="../results",
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
    run_script = _write_run_script(package_dir, system, confs, namd_command, namd_threads)
    readme = _write_readme(package_dir, pipeline, os.path.basename(run_script))
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
        "run_script": run_script,
    }


def _copy_unique(paths: list[str], dest_dir: str):
    seen: dict[str, str] = {}
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        name = os.path.basename(path)
        existing = seen.get(name)
        if existing == os.path.abspath(path):
            continue
        if existing is not None:
            raise ValueError(
                f"Input filename collision: both '{existing}' and '{path}' would copy as '{name}'."
            )
        seen[name] = os.path.abspath(path)
        shutil.copy2(path, os.path.join(dest_dir, name))


def _write_run_script(
    package_dir: str,
    system: SystemConfig,
    confs: list[str],
    namd_command: str,
    namd_threads: int,
) -> str:
    script_name = f"{_safe_script_stem(system.stem or os.path.basename(package_dir))}_run.sh"
    path = os.path.join(package_dir, script_name)
    command = namd_command.strip() if namd_command else "namd3"
    threads = max(1, int(namd_threads or 1))
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'cd "$(dirname "$0")"',
        "",
        f"NAMD_DEFAULT={shlex.quote(command)}",
        f"NAMD_THREADS_DEFAULT={threads}",
        'NAMD="${NAMD:-$NAMD_DEFAULT}"',
        'NAMD_THREADS="${NAMD_THREADS:-$NAMD_THREADS_DEFAULT}"',
        "",
        "mkdir -p results",
        "",
        "run_stage() {",
        '  local conf="$1"',
        "  local stem",
        '  stem="$(basename "$conf" .conf)"',
        '  echo "[$(date)] easyNAMD: running $conf"',
        '  "$NAMD" +p"$NAMD_THREADS" "$conf" > "results/${stem}.log" 2>&1',
        '  echo "[$(date)] easyNAMD: finished $conf"',
        "}",
        "",
    ]
    for conf in confs:
        lines.append(f"run_stage {shlex.quote(os.path.join('conf', os.path.basename(conf)))}")
    lines += [
        "",
        'echo "easyNAMD: all stages finished. Results are in ./results"',
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o755)
    return path


def _safe_script_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip())
    return cleaned.strip("_") or "system"


def _write_readme(package_dir: str, pipeline: Pipeline, run_script_name: str) -> str:
    path = os.path.join(package_dir, "README_run.txt")
    lines = [
        "easyNAMD NAMD package",
        "",
        "Run the whole pipeline sequentially:",
        f"  ./{run_script_name}",
        "",
        "Override the launch command or thread count when needed:",
        f"  NAMD=/path/to/namd3 NAMD_THREADS=16 ./{run_script_name}",
        "",
        "The generated script uses NAMD's +p<N> multicore flag and stops on the first failed stage.",
        "Examples:",
        f"  ./{run_script_name}",
        f"  CUDA_VISIBLE_DEVICES=0 NAMD_THREADS=8 ./{run_script_name}",
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
        "Trajectories, restarts, and logs are written to results/.",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path
