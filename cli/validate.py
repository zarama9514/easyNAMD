"""`easynamd validate` — check a built system before it leaves the workstation.

Everything here is cheap and local, which is the point: the next stop is a
cluster, where the same mistake costs a file transfer, a queue wait and a
puzzling NAMD crash. A structure that fails these checks is not safe to hand on,
even though psfgen exited cleanly and every file looks plausible.

The result is recorded against the hashes of the files it inspected, so editing
a .psf afterwards expires the verdict instead of silently inheriting it.
"""

import os

from cli.common import EXIT_FAIL, EXIT_OK, add_json_flag, error, print_json
from cli.status import resolve_run_dir
from core.namd.tools import count_pdb_atoms, count_psf_atoms, psf_total_charge
from core.run_dir import RunDir
from core.vmd_runner import scan_problems

# Ions are whole, so a neutralised system lands within one elementary charge of
# zero rather than exactly on it. Anything beyond that means the build, not the
# rounding, is wrong.
CHARGE_TOLERANCE = 1.0


def _final_prefix(run: RunDir) -> str | None:
    """The last structure the build produced, from the recorded outputs."""
    for path in run.outputs_of("build"):
        if path.endswith(".psf"):
            return path[: -len(".psf")]
    return None


def validate_run(path: str) -> dict:
    run = RunDir.open(path)
    checks, inspected = [], []

    def add(name, ok, detail, fix=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fix": fix})

    prefix = _final_prefix(run)
    if prefix is None:
        add("build", False, "no build step is recorded for this run",
            "run `easynamd build` first")
        return {"ok": False, "checks": checks, "run_dir": run.path, "inspected": []}

    psf, pdb = prefix + ".psf", prefix + ".pdb"
    missing = [p for p in (psf, pdb) if not os.path.isfile(p)]
    if missing:
        add("outputs", False,
            "missing: " + ", ".join(os.path.basename(p) for p in missing),
            "re-run `easynamd build`")
        return {"ok": False, "checks": checks, "run_dir": run.path, "inspected": []}
    add("outputs", True, f"{os.path.basename(psf)} and .pdb are present")
    inspected += [psf, pdb]

    psf_atoms, pdb_atoms = count_psf_atoms(psf), count_pdb_atoms(pdb)
    add("atom count", psf_atoms == pdb_atoms,
        f"psf {psf_atoms} vs pdb {pdb_atoms}",
        "" if psf_atoms == pdb_atoms else
        "the topology and coordinates disagree; NAMD will refuse them — rebuild")

    charge = psf_total_charge(psf)
    if charge is None:
        add("net charge", False, "could not read charges from the psf",
            "the file may be truncated; rebuild")
    else:
        within = abs(charge) < CHARGE_TOLERANCE
        add("net charge", within,
            f"{charge:+.3f} e (ions are whole, so |q| < {CHARGE_TOLERANCE} is expected)",
            "" if within else "ionization did not neutralise the system — check the build log")

    log = os.path.join(run.path, os.path.basename(prefix).split("_solvated")[0] + "_build.log")
    if os.path.isfile(log):
        problems = scan_problems(open(log, errors="replace").read().splitlines())
        add("build log", not problems,
            "no problems reported" if not problems
            else f"{len(problems)} problem line(s): " + "; ".join(problems[:3]),
            "" if not problems else f"read {log}")
        inspected.append(log)

    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "run_dir": run.path,
        "inspected": inspected,
    }


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "validate", help="check a built system and record the verdict")
    parser.add_argument("target", help="run directory, or any structure file inside it")
    parser.add_argument("--no-record", action="store_true",
                        help="report without writing the result to the manifest")
    add_json_flag(parser)
    parser.set_defaults(func=run)


def run(args) -> int:
    path = resolve_run_dir(args.target)
    try:
        report = validate_run(path)
    except FileNotFoundError as exc:
        return error("E_NO_RUN", str(exc), "run `easynamd build` on the structure first")

    if not args.no_record:
        run_dir = RunDir.open(path)
        run_dir.record_validation(
            report["ok"], files=report["inspected"],
            problems=[c["detail"] for c in report["checks"] if not c["ok"]],
        )
        run_dir.save()

    if args.json:
        print_json(report)
    else:
        print(render(report))
    return EXIT_OK if report["ok"] else EXIT_FAIL


def render(report: dict) -> str:
    out = [f"Validating {report['run_dir']}", ""]
    for check in report["checks"]:
        out.append(f"  [{'ok  ' if check['ok'] else 'FAIL'}] {check['name']}: {check['detail']}")
        if check["fix"] and not check["ok"]:
            out.append(f"         fix: {check['fix']}")
    out.append("")
    out.append("Ready to package for the cluster."
               if report["ok"] else "Not safe to hand on — fix the failures above.")
    return "\n".join(out)
