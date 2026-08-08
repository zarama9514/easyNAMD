"""`easynamd build` — psfgen, solvate and ionize a cleaned structure.

Most of what a build needs can be read off the coordinates: which chains are
protein, which cysteines form disulfides, which residues coordinate a metal and
therefore what their protonation must be. Those are applied as rules and
recorded with the distance that justified them, so the reasoning stays in the
run directory instead of in someone's head. Everything a rule cannot settle
(a plain histidine) takes a documented default that the caller can override.

The build is only as trustworthy as its log: VMD exits 0 even when psfgen
skipped a residue or invented a coordinate, so the log is scanned for those
lines and they are reported, not buried.
"""

import os

from cli.common import (
    EXIT_FAIL, EXIT_OK, add_json_flag, error, load_config, parameter_files,
    print_json, topology_files,
)
from cli.prepare import _parse_pairs
from core.coverage import uncovered_built_residues
from core.naming import stem
from core.pdb_parser import (
    HeteroSegment, HisResidue, Patch, SegmentConfig,
    find_disulfides_by_distance, parse_pdb,
)
from core.run_dir import DETERMINISTIC_RULE, DOMAIN_DEFAULT, USER_DECISION, RunDir
from core.tcl_writer import write_build_script
from core.vmd_runner import run_vmd_sync, scan_problems
from core.zinc import detect_zinc_coordination

BUILD_TIMEOUT = 3600   # seconds; solvating a large system is slow but not endless


def decide(pdb_file: str, his_overrides=None, extra_patches=(), use_disulfides=True):
    """Derive segments, patches and protonation from the structure itself."""
    his_overrides = his_overrides or {}
    info = parse_pdb(pdb_file)
    metal_cys, metal_his = detect_zinc_coordination(pdb_file)
    decisions = []

    segments = [SegmentConfig(chain=chain) for chain in info.chains]

    # Histidine tautomers: a coordinating nitrogen is deprotonated, so the proton
    # sits on the other one. Anything else takes the default.
    by_metal = {(h.chain, h.resid): h for h in metal_his}
    histidines = []
    for his in info.histidines:
        target = f"{his.chain}:{his.resid}"
        if target in his_overrides:
            value, source, evidence = his_overrides[target], USER_DECISION, "requested"
        elif (his.chain, his.resid) in by_metal:
            bound = by_metal[(his.chain, his.resid)]
            value, source = bound.protonation, DETERMINISTIC_RULE
            evidence = (f"{bound.coordinating_atom} {bound.distance:.2f} A from "
                        f"{bound.metal} {bound.metal_resid}")
        else:
            value, source, evidence = "HSD", DOMAIN_DEFAULT, "no metal or explicit choice"
        histidines.append(HisResidue(chain=his.chain, resid=his.resid, protonation=value))
        decisions.append(("histidine", target, value, source, evidence))

    patches = []
    if use_disulfides:
        header = {frozenset({(b.chain1, b.resid1), (b.chain2, b.resid2)}): b
                  for b in info.ss_bonds}
        for bond in find_disulfides_by_distance(pdb_file):
            header.setdefault(
                frozenset({(bond.chain1, bond.resid1), (bond.chain2, bond.resid2)}), bond)
        for key, bond in header.items():
            patches.append(Patch("DISU", bond.chain1, bond.resid1, bond.chain2, bond.resid2))
            in_header = any(frozenset({(b.chain1, b.resid1), (b.chain2, b.resid2)}) == key
                            for b in info.ss_bonds)
            decisions.append((
                "disulfide", f"{bond.chain1}:{bond.resid1}-{bond.chain2}:{bond.resid2}",
                "DISU", DETERMINISTIC_RULE,
                "SSBOND record" if in_header else "SG-SG within bonding distance",
            ))

    # A cysteine bound to a metal is a thiolate.
    for cys in metal_cys:
        patches.append(Patch("CYSD", cys.chain, cys.resid))
        decisions.append((
            "patch", f"{cys.chain}:{cys.resid}", "CYSD", DETERMINISTIC_RULE,
            f"SG {cys.distance:.2f} A from {cys.metal} {cys.metal_resid}",
        ))

    for patch in extra_patches:
        patches.append(patch)
        target = f"{patch.chain1}:{patch.resid1}"
        if patch.is_two_residue():
            target += f"-{patch.chain2}:{patch.resid2}"
        decisions.append(("patch", target, patch.name, USER_DECISION, "requested"))

    return segments, histidines, patches, decisions


def _parse_patch(text: str) -> Patch:
    """NAME:SEGID:RESID or NAME:SEGID:RESID:SEGID2:RESID2."""
    parts = [p.strip() for p in text.split(":")]
    if len(parts) == 3:
        return Patch(parts[0], parts[1], parts[2])
    if len(parts) == 5:
        return Patch(parts[0], parts[1], parts[2], parts[3], parts[4])
    raise ValueError(f"--patch expects NAME:SEGID:RESID[:SEGID2:RESID2], got {text!r}")


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "build", help="run psfgen, solvate and ionize on a cleaned PDB")
    parser.add_argument("pdb", help="cleaned PDB file")
    parser.add_argument("--pad", type=float, default=10.0, help="water box padding, A (default 10)")
    parser.add_argument("--salt", type=float, default=0.0,
                        help="salt concentration in M; 0 neutralizes only (default 0)")
    parser.add_argument("--cation", default="SOD", help="cation resname (default SOD)")
    parser.add_argument("--anion", default="CLA", help="anion resname (default CLA)")
    parser.add_argument("--no-ionize", action="store_true", help="stop after solvation")
    parser.add_argument("--rotate", action="store_true", help="rotate solute to shrink the box")
    parser.add_argument("--recenter", action="store_true", help="move centre of mass to origin")
    parser.add_argument("--his", action="append", metavar="CHAIN:RESID=STATE",
                        help="override a histidine tautomer (repeatable)")
    parser.add_argument("--patch", action="append", metavar="NAME:SEGID:RESID",
                        help="apply an extra patch (repeatable)")
    parser.add_argument("--hetero", action="append", metavar="RESNAME=SEGNAME",
                        help="build a ligand or ion as its own segment (repeatable)")
    parser.add_argument("--no-ss", action="store_true", help="do not apply disulfide patches")
    parser.add_argument("--dry-run", action="store_true",
                        help="write the Tcl script but do not run VMD")
    add_json_flag(parser)
    parser.set_defaults(func=run)


def run(args) -> int:
    if not os.path.isfile(args.pdb):
        return error("E_NO_INPUT", f"{args.pdb} does not exist", "pass a cleaned PDB file")

    vmd = os.path.expanduser(load_config().get("vmd_path", ""))
    if not args.dry_run and not os.path.isfile(vmd):
        return error("E_NO_VMD", "VMD was not found", "run `easynamd doctor` to see why")

    try:
        his_overrides = _parse_pairs(args.his, "--his")
        hetero_pairs = _parse_pairs(args.hetero, "--hetero")
        extra = [_parse_patch(text) for text in (args.patch or ())]
    except ValueError as exc:
        return error("E_BAD_OPTION", str(exc))

    tops, params = topology_files(), parameter_files()
    if not tops:
        return error("E_NO_TOPOLOGY", "no topology files found",
                     "run `easynamd doctor`")

    hetero_segments = [HeteroSegment(segname=seg, resname=res, chain="")
                       for res, seg in hetero_pairs.items()]
    uncovered = uncovered_built_residues([h.resname for h in hetero_segments], tops)
    if uncovered:
        return error("E_NO_PARAMETERS",
                     f"no topology defines {', '.join(uncovered)}, but they were "
                     "requested as segments",
                     "load matching topology/parameters, or drop the --hetero flag")

    segments, histidines, patches, decisions = decide(
        args.pdb, his_overrides, extra, use_disulfides=not args.no_ss)
    if not segments:
        return error("E_NO_PROTEIN", "no protein chains were found in this file",
                     "check the input with `easynamd inspect`")

    run_dir = RunDir.for_input(args.pdb)
    base = stem(args.pdb)
    script = write_build_script(
        pdb_file=os.path.abspath(args.pdb),
        topology_files=tops, parameter_files=params,
        segments=segments, patches=patches, histidines=histidines,
        hetero_segments=hetero_segments,
        output_dir=run_dir.path, padding=args.pad,
        ionize=not args.no_ionize, salt_concentration=args.salt,
        cation=args.cation, anion=args.anion,
        rotate=args.rotate, recenter=args.recenter, base_stem=base,
    )

    final = base + ("_solvated" if args.no_ionize else "_solvated_ionized")
    report = {
        "run_dir": run_dir.path,
        "script": script,
        "segments": [s.chain for s in segments],
        "patches": [f"{p.name} {p.chain1}:{p.resid1}" for p in patches],
        "hetero_segments": [h.segname for h in hetero_segments],
        "decisions": [{"kind": k, "target": t, "value": v, "source": s, "evidence": e}
                      for k, t, v, s, e in decisions],
        "dry_run": bool(args.dry_run),
        "outputs": [], "problems": [], "charge": None, "atoms": None,
    }

    if args.dry_run:
        _emit(args, report)
        return EXIT_OK

    code, lines = run_vmd_sync(vmd, script, cwd=run_dir.path, timeout=BUILD_TIMEOUT)
    report["problems"] = scan_problems(lines)
    for line in lines:
        if "total charge =" in line:
            report["charge"] = float(line.split("=")[-1])
        elif "atom count =" in line:
            report["atoms"] = int(line.split("=")[-1])

    log_path = os.path.join(run_dir.path, base + "_build.log")
    with open(log_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    produced = [os.path.join(run_dir.path, final + ext) for ext in (".psf", ".pdb")]
    missing = [p for p in produced if not os.path.isfile(p)]
    if code != 0 or missing:
        return error("E_BUILD_FAILED",
                     f"VMD exited {code} and {final}.psf/.pdb "
                     f"{'were not written' if missing else 'may be incomplete'}",
                     f"read {log_path}")

    report["outputs"] = produced
    for kind, target, value, source, evidence in decisions:
        run_dir.record_decision(kind, target, value, source, evidence)
    run_dir.record_step("build", outputs=produced + [script, log_path], params={
        "padding": args.pad, "ionize": not args.no_ionize, "salt": args.salt,
        "cation": args.cation, "anion": args.anion,
    })
    run_dir.save()

    _emit(args, report)
    return EXIT_OK


def _emit(args, report: dict) -> None:
    if args.json:
        print_json(report)
    else:
        print(render(report))


def render(report: dict) -> str:
    out = []
    if report["dry_run"]:
        out.append("(dry run — the Tcl script was written but not executed)")
    out += [f"Run directory: {report['run_dir']}", f"Script: {report['script']}", ""]
    out.append(f"Segments: {', '.join(report['segments'])}")
    if report["hetero_segments"]:
        out.append(f"Hetero segments: {', '.join(report['hetero_segments'])}")
    if report["patches"]:
        out.append(f"Patches: {', '.join(report['patches'])}")
    if report["outputs"]:
        out += ["", "Produced"]
        out += [f"  {os.path.basename(p)}" for p in report["outputs"]]
    if report["charge"] is not None:
        out.append("")
        out.append(f"Net charge: {report['charge']:+.3f}   Atoms: {report['atoms']}")
    if report["problems"]:
        out += ["", f"Log reported {len(report['problems'])} problem line(s):"]
        out += [f"  {p}" for p in report["problems"][:10]]
        if len(report["problems"]) > 10:
            out.append(f"  … and {len(report['problems']) - 10} more")
    return "\n".join(out)
