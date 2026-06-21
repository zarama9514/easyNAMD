from __future__ import annotations

import os

from core.namd.models import SlurmConfig, Stage, SystemConfig


def write_run_sh(path: str, system: SystemConfig, stages: list[Stage]) -> str:
    _write_executable(path, render_run_sh(system, stages))
    return path


def render_run_sh(system: SystemConfig, stages: list[Stage]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'cd "$(dirname "$0")"',
        "mkdir -p logs output",
        "",
        f'NAMD_CMD="${{NAMD_CMD:-{system.namd_command}}}"',
        f'NAMD_CPUS="${{NAMD_CPUS:-{system.cpu_count}}}"',
        'NAMD_EXTRA_ARGS="${NAMD_EXTRA_ARGS:-}"',
        "",
    ]
    for i, stage in enumerate(stages, start=1):
        prefix = stage.output_prefix(i)
        lines += [
            f'echo "[easyNAMD] running {prefix}"',
            f'"$NAMD_CMD" +p"$NAMD_CPUS" $NAMD_EXTRA_ARGS "conf/{prefix}.conf" > "logs/{prefix}.log"',
            "",
        ]
    lines.append('echo "[easyNAMD] pipeline complete"')
    return "\n".join(lines) + "\n"


def write_slurm(path: str, cfg: SlurmConfig, stages: list[Stage]) -> str:
    _write_executable(path, render_slurm(cfg, stages))
    return path


def render_slurm(cfg: SlurmConfig, stages: list[Stage]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        f"#SBATCH --job-name={cfg.job_name}",
        f"#SBATCH --nodes={cfg.nodes}",
        f"#SBATCH --ntasks={cfg.ntasks}",
        f"#SBATCH --cpus-per-task={cfg.cpus_per_task}",
        f"#SBATCH --time={cfg.time}",
        "#SBATCH --output=logs/%x_%j.out",
        "#SBATCH --error=logs/%x_%j.err",
    ]
    if cfg.partition:
        lines.append(f"#SBATCH --partition={cfg.partition}")
    if cfg.account:
        lines.append(f"#SBATCH --account={cfg.account}")
    if cfg.gpus_per_node > 0:
        lines.append(f"#SBATCH --gres=gpu:{cfg.gpus_per_node}")
    lines.extend(f"#SBATCH {item}" for item in cfg.extra_sbatch if item.strip())

    lines += [
        "",
        "set -euo pipefail",
        'cd "$SLURM_SUBMIT_DIR"',
        "mkdir -p logs output",
        "",
    ]
    lines.extend(line for line in cfg.modules if line.strip())
    if cfg.modules:
        lines.append("")

    namd_args = [f"+p{cfg.cpus_per_task}"]
    if cfg.set_cpu_affinity:
        namd_args.append("+setcpuaffinity")
    if cfg.gpu_devices:
        namd_args.append(f"+devices {cfg.gpu_devices}")
    if cfg.extra_namd_args.strip():
        namd_args.append(cfg.extra_namd_args.strip())
    launcher = f"srun {cfg.command}" if cfg.use_srun else cfg.command
    args = " ".join(namd_args)
    for i, stage in enumerate(stages, start=1):
        prefix = stage.output_prefix(i)
        lines += [
            f'echo "[easyNAMD] running {prefix}"',
            f'{launcher} {args} "conf/{prefix}.conf" > "logs/{prefix}.log"',
            "",
        ]
    lines.append('echo "[easyNAMD] pipeline complete"')
    return "\n".join(lines) + "\n"


def _write_executable(path: str, text: str):
    with open(path, "w") as f:
        f.write(text)
    mode = os.stat(path).st_mode
    os.chmod(path, mode | 0o755)
