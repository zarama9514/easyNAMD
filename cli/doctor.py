"""`easynamd doctor` — check the environment before anything expensive happens.

Discovering a missing VMD or an empty topology directory here costs a second;
discovering it halfway through a build costs a confusing psfgen log. Required
and optional dependencies are separated on purpose:

  required  VMD, topologies, parameters — nothing can be built without them
  optional  NAMD, Open Babel — easyNAMD only *generates* NAMD input, and the
            simulation itself runs on the cluster, so a missing (or, on macOS,
            quarantined) local NAMD is not an error
"""

import os
import shutil
import subprocess
import tempfile

from cli.common import (
    EXIT_FAIL, EXIT_OK, add_json_flag, load_config, parameter_files,
    print_json, topology_files, PARAMETERS_DIR, TOPOLOGIES_DIR,
)

VMD_PROBE_TIMEOUT = 30   # seconds; VMD start-up is slow but bounded
NAMD_PROBE_TIMEOUT = 10


def _check(name, required, status, detail, fix=""):
    return {"name": name, "required": required, "status": status,
            "detail": detail, "fix": fix}


def _resolve(configured: str, fallback_names: tuple) -> str:
    """Prefer the configured path, else look the binary up on PATH."""
    if configured and os.path.isfile(os.path.expanduser(configured)):
        return os.path.expanduser(configured)
    for name in fallback_names:
        found = shutil.which(name)
        if found:
            return found
    return ""


def _vmd_version(vmd_path: str) -> tuple[bool, str]:
    """Run VMD on a script that does nothing but quit, and read its banner."""
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "probe.tcl")
        with open(script, "w") as f:
            f.write("quit\n")
        try:
            proc = subprocess.run(
                [vmd_path, "-dispdev", "none", "-e", script],
                capture_output=True, text=True, timeout=VMD_PROBE_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"could not run: {exc}"
    for line in (proc.stdout + proc.stderr).splitlines():
        if "VMD for" in line:
            return True, line.split("Info)")[-1].strip()
    return proc.returncode == 0, "ran, but reported no version banner"


def _namd_runnable(namd_path: str) -> tuple[bool, str]:
    """Check the local NAMD actually starts. A present-but-unrunnable binary
    (macOS quarantine kills it with SIGKILL) would otherwise look healthy."""
    try:
        proc = subprocess.run([namd_path, "--version"], capture_output=True,
                              text=True, timeout=NAMD_PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not run: {exc}"
    if proc.returncode < 0 or proc.returncode == 137:
        return False, "found, but the process was killed on start-up"
    banner = (proc.stdout + proc.stderr).strip().splitlines()
    return True, banner[0] if banner else "runs (used only for optional local preflight)"


def check_environment() -> dict:
    config = load_config()
    checks = []

    # --- VMD (required) ---
    vmd = _resolve(config.get("vmd_path", ""), ("vmd",))
    if not vmd:
        checks.append(_check(
            "vmd", True, "missing", "not found in config.json or on PATH",
            'install VMD, then set "vmd_path" in config.json',
        ))
    else:
        ok, detail = _vmd_version(vmd)
        checks.append(_check("vmd", True, "ok" if ok else "missing",
                             f"{vmd} — {detail}",
                             "" if ok else "check that the binary runs in a terminal"))

    # --- force field files (required) ---
    tops, params = topology_files(), parameter_files()
    checks.append(_check(
        "topologies", True, "ok" if tops else "missing",
        f"{len(tops)} file(s) in {TOPOLOGIES_DIR}" if tops else f"no .rtf/.top/.str in {TOPOLOGIES_DIR}",
        "" if tops else "add CHARMM36 topology files (a full toppar_water_ions.str, not *_params_only)",
    ))
    checks.append(_check(
        "parameters", True, "ok" if params else "missing",
        f"{len(params)} file(s) in {PARAMETERS_DIR}" if params else f"no .prm/.str in {PARAMETERS_DIR}",
        "" if params else "add CHARMM36 parameter files",
    ))

    # --- NAMD (optional) ---
    namd = _resolve(config.get("namd_path", ""), ("namd3", "namd2"))
    if not namd:
        checks.append(_check(
            "namd", False, "warn", "not found locally",
            "not required — easyNAMD generates NAMD input; run the simulation on the cluster",
        ))
    else:
        runnable, note = _namd_runnable(namd)
        checks.append(_check(
            "namd", False, "ok" if runnable else "warn",
            f"{namd} — {note}",
            "" if runnable else
            f'if macOS quarantined it: xattr -d com.apple.quarantine "{namd}" '
            "— optional either way, since simulations run on the cluster",
        ))

    # --- Open Babel (optional) ---
    obabel = shutil.which("obabel")
    checks.append(_check("obabel", False, "ok" if obabel else "warn",
                         obabel or "not found",
                         "" if obabel else "only needed to export ligands to .mol2"))

    blocking = [c for c in checks if c["required"] and c["status"] != "ok"]
    return {
        "ok": not blocking,
        "checks": checks,
        "blocking": [c["name"] for c in blocking],
    }


def render(report: dict) -> str:
    marks = {"ok": "ok  ", "warn": "warn", "missing": "FAIL"}
    lines = ["Environment check", ""]
    for c in report["checks"]:
        tag = "" if c["required"] else "  (optional)"
        lines.append(f"  [{marks[c['status']]}] {c['name']}{tag}")
        lines.append(f"         {c['detail']}")
        if c["fix"] and c["status"] != "ok":
            lines.append(f"         fix: {c['fix']}")
    lines.append("")
    lines.append("Ready to build." if report["ok"]
                 else "Cannot build — resolve: " + ", ".join(report["blocking"]))
    return "\n".join(lines)


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "doctor", help="check that VMD and the force field files are usable")
    add_json_flag(parser)
    parser.set_defaults(func=run)


def run(args) -> int:
    report = check_environment()
    if args.json:
        print_json(report)
    else:
        print(render(report))
    return EXIT_OK if report["ok"] else EXIT_FAIL
