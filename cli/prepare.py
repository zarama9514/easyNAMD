"""`easynamd prepare` — turn a deposited structure into something psfgen can read.

Drops what will not be simulated, resolves alternate conformers, optionally
reassigns chains, and renumbers atoms from 1.

Two rules shape the interface. First, defaults rather than menus: crystal water
goes unless asked for, the first alternate conformer wins, and both choices are
recorded with their provenance so a reader can see they were defaults and not
findings. Second, an ambiguity that materially changes the system is *not*
silently defaulted — several deposited models can mean an NMR ensemble or a
docked complex split across models, and guessing wrong produces a plausible,
wrong system. That case stops with an error naming the options, because a
command an agent runs has nobody to ask at the terminal.
"""

import os

from cli.common import EXIT_OK, add_json_flag, error, print_json
from core.molecule_groups import (
    find_altlocs, find_models, parse_groups, save_selected_groups,
)
from core.naming import stem
from core.run_dir import DOMAIN_DEFAULT, USER_DECISION, RunDir

DROPPED_BY_DEFAULT = ("water",)


def _split(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _matches(group, token: str) -> bool:
    """A token selects a group by type ('water', 'ligand') or by residue name."""
    token = token.upper()
    return (group.group_type.upper() == token
            or token in {name.upper() for name in group.resnames})


def _parse_pairs(values, what: str) -> dict:
    """Parse repeated KEY=VALUE options into a dict."""
    pairs = {}
    for item in values or ():
        if "=" not in item:
            raise ValueError(f"{what} must be KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        pairs[key.strip()] = value.strip()
    return pairs


def plan(pdb_file: str, drop=(), keep=(), models=None,
         altloc_default: str = "", altloc_choices=None, chains=None) -> dict:
    """Work out what prepare would do, without writing anything."""
    groups = parse_groups(pdb_file)
    available_models = find_models(pdb_file)
    altlocs = find_altlocs(pdb_file)
    altloc_choices = altloc_choices or {}
    chains = chains or {}

    decisions = []
    selected, dropped = [], []
    for group in groups:
        if any(_matches(group, token) for token in keep):
            selected.append(group)
        elif any(_matches(group, token) for token in drop):
            dropped.append(group)
            decisions.append(("group", group.label, "drop", USER_DECISION, "requested"))
        elif any(_matches(group, token) for token in DROPPED_BY_DEFAULT):
            dropped.append(group)
            decisions.append(("group", group.label, "drop", DOMAIN_DEFAULT,
                              "crystal water is not kept unless asked for"))
        else:
            selected.append(group)

    resolved_altlocs = {}
    for residue in altlocs:
        target = f"{residue.chain}:{residue.resid}"
        chosen = altloc_choices.get(target)
        if chosen:
            source, evidence = USER_DECISION, "requested"
        else:
            chosen = altloc_default or residue.codes[0]
            source = DOMAIN_DEFAULT
            evidence = (f"default conformer of {'/'.join(residue.codes)}"
                        if not altloc_default else f"--altloc {altloc_default}")
        if chosen not in residue.codes:
            raise ValueError(
                f"{target} has conformers {'/'.join(residue.codes)}, not {chosen!r}")
        resolved_altlocs[residue.key()] = chosen
        decisions.append(("altloc", target, chosen, source, evidence))

    for group_id, chain in chains.items():
        decisions.append(("chain", group_id, chain, USER_DECISION, "requested"))

    if models is not None:
        for model in sorted(models):
            decisions.append(("model", "file", str(model), USER_DECISION, "requested"))

    return {
        "groups_kept": [g.group_id for g in selected],
        "groups_dropped": [g.group_id for g in dropped],
        "labels_kept": [g.label for g in selected],
        "labels_dropped": [g.label for g in dropped],
        "models_available": available_models,
        "models_kept": sorted(models) if models is not None else available_models,
        "altlocs": resolved_altlocs,
        "chains": chains,
        "decisions": decisions,
        "_groups": groups,
    }


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "prepare", help="drop unwanted groups, resolve conformers, renumber atoms")
    parser.add_argument("pdb", help="input PDB file")
    parser.add_argument("--drop", default="",
                        help="comma-separated groups to drop, by type or residue name "
                             "(water is dropped by default)")
    parser.add_argument("--keep", default="",
                        help="comma-separated groups to keep even if dropped by default")
    parser.add_argument("--models", default="",
                        help="comma-separated model numbers to keep; several are merged")
    parser.add_argument("--altloc", default="",
                        help="alternate conformer to keep everywhere, e.g. A")
    parser.add_argument("--altloc-choice", action="append", metavar="CHAIN:RESID=CODE",
                        help="override the conformer for one residue (repeatable)")
    parser.add_argument("--chain", action="append", metavar="GROUP=CHAIN",
                        help="move a group onto a chain id (repeatable)")
    parser.add_argument("--out", default="",
                        help="output PDB (default: <run dir>/<stem>_clean.pdb)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen without writing anything")
    add_json_flag(parser)
    parser.set_defaults(func=run)


def run(args) -> int:
    if not os.path.isfile(args.pdb):
        return error("E_NO_INPUT", f"{args.pdb} does not exist", "pass a PDB file")

    try:
        altloc_choices = _parse_pairs(args.altloc_choice, "--altloc-choice")
        chains = _parse_pairs(args.chain, "--chain")
    except ValueError as exc:
        return error("E_BAD_OPTION", str(exc))

    available = find_models(args.pdb)
    models = None
    if args.models:
        try:
            models = {int(m) for m in _split(args.models)}
        except ValueError:
            return error("E_BAD_OPTION", f"--models expects numbers, got {args.models!r}")
        unknown = models - set(available)
        if unknown:
            return error("E_NO_SUCH_MODEL",
                         f"model(s) {sorted(unknown)} not in this file; it has {available}")
    elif len(available) > 1:
        # Materially different systems hide behind this choice, so it is not defaulted.
        return error(
            "E_CHOICE_MODELS",
            f"the file has {len(available)} models {available} and no choice was given",
            f"pick with --models N (one model), or --models {','.join(map(str, available))} "
            "to merge them into one system, e.g. a protein and a ligand deposited separately",
        )

    try:
        decided = plan(args.pdb, drop=_split(args.drop), keep=_split(args.keep),
                       models=models, altloc_default=args.altloc,
                       altloc_choices=altloc_choices, chains=chains)
    except ValueError as exc:
        return error("E_BAD_OPTION", str(exc))

    if not decided["groups_kept"]:
        return error("E_NOTHING_KEPT", "every group was dropped",
                     "loosen --drop, or name what to keep with --keep")

    run_dir = RunDir.for_input(args.pdb)
    out_path = args.out or os.path.join(run_dir.path, stem(args.pdb) + "_clean.pdb")

    report = {
        "input": os.path.abspath(args.pdb),
        "output": os.path.abspath(out_path),
        "run_dir": run_dir.path,
        "kept": decided["labels_kept"],
        "dropped": decided["labels_dropped"],
        "models_kept": decided["models_kept"],
        "altlocs": {f"{c}:{r}": code for (c, r, _i), code in decided["altlocs"].items()},
        "decisions": [
            {"kind": k, "target": t, "value": v, "source": s, "evidence": e}
            for k, t, v, s, e in decided["decisions"]
        ],
        "dry_run": bool(args.dry_run),
    }

    if not args.dry_run:
        save_selected_groups(
            args.pdb, decided["_groups"], set(decided["groups_kept"]), out_path,
            altloc_choices=decided["altlocs"],
            group_chains=decided["chains"],
            renumber=True,
            allowed_models=set(decided["models_kept"]) if available else None,
        )
        for kind, target, value, source, evidence in decided["decisions"]:
            run_dir.record_decision(kind, target, value, source, evidence)
        run_dir.record_step("prepare", outputs=[out_path], params={
            "drop": _split(args.drop), "keep": _split(args.keep),
            "models": decided["models_kept"], "altloc_default": args.altloc,
        })
        run_dir.save()

    if args.json:
        print_json(report)
    else:
        print(render(report))
    return EXIT_OK


def render(report: dict) -> str:
    out = []
    if report["dry_run"]:
        out.append("(dry run — nothing was written)")
    out += [f"Input:  {report['input']}", f"Output: {report['output']}", ""]
    out.append("Kept")
    out += [f"  {label}" for label in report["kept"]] or ["  (nothing)"]
    if report["dropped"]:
        out += ["", "Dropped"]
        out += [f"  {label}" for label in report["dropped"]]
    if len(report["models_kept"]) > 1:
        out += ["", f"Models merged: {', '.join(map(str, report['models_kept']))}"]
    if report["altlocs"]:
        out += ["", "Alternate conformers kept"]
        out += [f"  {target} → {code}" for target, code in sorted(report["altlocs"].items())]
    return "\n".join(out)
