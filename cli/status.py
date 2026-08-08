"""`easynamd status` — what has been done to a structure, and is it still valid.

This is how a later session picks the work back up. An agent returning to a
structure should read the run directory rather than trust what it remembers of
an earlier conversation: the files are the record, the chat is not.
"""

import os

from cli.common import EXIT_OK, add_json_flag, error, print_json
from core.naming import structure_dir
from core.run_dir import RunDir

VALIDATION_NOTES = {
    "missing": "not validated yet",
    "ok": "passed",
    "failed": "failed — see problems",
    "stale": "STALE — files changed after it ran, so it no longer says anything",
}


def resolve_run_dir(target: str) -> str:
    """Accept either the run directory itself or any structure file inside it."""
    return target if os.path.isdir(target) else structure_dir(target)


def status_report(path: str) -> dict:
    run = RunDir.open(path)
    state, changed = run.validation_state()
    record = run.manifest.get("validation") or {}
    return {
        "run_id": run.manifest.get("run_id", ""),
        "directory": run.path,
        "input": run.manifest.get("input", {}),
        "created": run.manifest.get("created", ""),
        "updated": run.manifest.get("updated", ""),
        "steps": [
            {"step": s["step"], "at": s["at"],
             "outputs": [o["path"] for o in s["outputs"]]}
            for s in run.manifest.get("steps", ())
        ],
        "decisions": run.decisions.get("decisions", []),
        "validation": {
            "state": state,
            "at": record.get("at", ""),
            "problems": record.get("problems", []),
            "changed_files": changed,
        },
    }


def render(report: dict) -> str:
    out = [f"Run: {report['run_id']}", f"Directory: {report['directory']}"]
    source = report.get("input") or {}
    if source:
        out.append(f"Input: {source.get('path','?')}  ({source.get('sha256','')[:12]}…)")

    out += ["", "Steps"]
    if report["steps"]:
        for s in report["steps"]:
            produced = ", ".join(s["outputs"]) or "(no files)"
            out.append(f"  {s['step']:<10} {s['at']}   → {produced}")
    else:
        out.append("  (none yet)")

    decisions = report["decisions"]
    if decisions:
        out += ["", f"Decisions ({len(decisions)})"]
        for d in decisions:
            line = f"  {d['kind']:<10} {d['target']:<10} {d['value']:<6} {d['source']}"
            if d.get("evidence"):
                line += f"   — {d['evidence']}"
            out.append(line)

    validation = report["validation"]
    note = VALIDATION_NOTES.get(validation["state"], validation["state"])
    stamp = f" ({validation['at']})" if validation["at"] else ""
    out += ["", f"Validation: {note}{stamp}"]
    for path in validation["changed_files"]:
        out.append(f"  changed: {path}")
    for problem in validation["problems"]:
        out.append(f"  problem: {problem}")

    return "\n".join(out)


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "status", help="show what has been done to a structure and whether it is still valid")
    parser.add_argument("target", help="run directory, or any structure file inside it")
    add_json_flag(parser)
    parser.set_defaults(func=run)


def run(args) -> int:
    path = resolve_run_dir(args.target)
    try:
        report = status_report(path)
    except FileNotFoundError as exc:
        return error("E_NO_RUN", str(exc),
                     "run `easynamd prepare` or `easynamd build` on the structure first")
    if args.json:
        print_json(report)
    else:
        print(render(report))
    return EXIT_OK
