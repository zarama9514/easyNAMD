"""`easynamd inspect` — everything needed to decide how to build a system.

This is the first command an agent runs on a structure. It answers, in one pass:
what chains and ligands are present, which residues have alternate conformers or
several deposited models, where the disulfides and metal sites are, and what the
bundled topologies do not cover.

Geometry-derived findings (metal coordination, disulfides by distance) are
reported **with their distances**. A wrong cutoff is otherwise a silent error:
the report looks equally confident whether the bond is at 2.1 Å or 2.9 Å, and
only the printed number lets a reader catch it.
"""

import os

from cli.common import (
    EXIT_FAIL, EXIT_OK, add_json_flag, error, print_json, topology_files,
)
from core import pdb_fields as pdbf
from core.charmm import is_protein_resname
from core.coverage import uncovered_residues
from core.molecule_groups import find_altlocs, find_models, parse_groups
from core.pdb_parser import find_disulfides_by_distance, parse_pdb
from core.zinc import detect_zinc_coordination


def _protein_residue_counts(pdb_file: str) -> dict[str, int]:
    """Amino-acid residues per chain. Waters and ions usually share the protein's
    chain id, so counting every residue would badly overstate the chain length."""
    seen: dict[str, set] = {}
    with open(pdb_file) as f:
        for line in f:
            if not pdbf.is_atom_record(line):
                continue
            if not is_protein_resname(pdbf.resname(line)):
                continue
            chain = pdbf.chain_id(line)
            seen.setdefault(chain, set()).add((pdbf.resid(line), pdbf.icode(line)))
    return {chain: len(residues) for chain, residues in seen.items()}


def inspect_structure(pdb_file: str) -> dict:
    info = parse_pdb(pdb_file)
    groups = parse_groups(pdb_file)
    altlocs = find_altlocs(pdb_file)
    models = find_models(pdb_file)
    residues_per_chain = _protein_residue_counts(pdb_file)

    ss_header = [
        {"chain1": b.chain1, "resid1": b.resid1,
         "chain2": b.chain2, "resid2": b.resid2, "source": "SSBOND record"}
        for b in info.ss_bonds
    ]
    header_keys = {
        frozenset({(b.chain1, b.resid1), (b.chain2, b.resid2)}) for b in info.ss_bonds
    }
    ss_distance = [
        {"chain1": b.chain1, "resid1": b.resid1,
         "chain2": b.chain2, "resid2": b.resid2, "source": "SG–SG distance"}
        for b in find_disulfides_by_distance(pdb_file)
        if frozenset({(b.chain1, b.resid1), (b.chain2, b.resid2)}) not in header_keys
    ]

    metal_cys, metal_his = detect_zinc_coordination(pdb_file)

    warnings = []
    if len(models) > 1:
        warnings.append(f"{len(models)} models — keep one, or merge them deliberately")
    if info.has_altloc:
        warnings.append("alternate conformers present — choose one per residue before building")
    if info.has_insercodes:
        warnings.append("insertion codes present — consider `regenerate resids`")
    if info.missing_residues:
        warnings.append(f"{info.missing_residues} missing residue(s) (REMARK 465) — "
                        "guesscoord will invent approximate coordinates")
    if info.missing_atoms:
        warnings.append(f"{info.missing_atoms} residue(s) with missing atoms (REMARK 470)")
    if info.chain_gaps:
        warnings.append(f"{len(info.chain_gaps)} chain numbering gap(s): "
                        + ", ".join(info.chain_gaps[:4]))

    return {
        "file": os.path.abspath(pdb_file),
        "models": models,
        "protein_chains": [
            {"chain": chain, "residues": residues_per_chain.get(chain, 0),
             "atoms": sum(g.atom_count() for g in groups
                          if g.group_type == "protein" and g.current_chain() == chain)}
            for chain in info.chains
        ],
        "groups": [
            {"id": g.group_id, "label": g.label, "type": g.group_type,
             "chain": g.current_chain(), "chains": sorted(g.chains),
             "atoms": g.atom_count(), "resnames": sorted(g.resnames)}
            for g in groups
        ],
        "altlocs": [
            {"chain": a.chain, "resid": a.resid, "resname": a.resname, "codes": a.codes}
            for a in altlocs
        ],
        "disulfides": ss_header + ss_distance,
        "metal_coordination": {
            "cysteines": [
                {"chain": c.chain, "resid": c.resid, "metal": c.metal,
                 "metal_resid": c.metal_resid, "distance": round(c.distance, 2),
                 "suggests": "CYSD patch (thiolate)"}
                for c in metal_cys
            ],
            "histidines": [
                {"chain": h.chain, "resid": h.resid, "metal": h.metal,
                 "metal_resid": h.metal_resid, "coordinating_atom": h.coordinating_atom,
                 "distance": round(h.distance, 2), "suggests": h.protonation}
                for h in metal_his
            ],
        },
        "histidines": [{"chain": h.chain, "resid": h.resid} for h in info.histidines],
        "uncovered_residues": uncovered_residues(pdb_file, topology_files()),
        "warnings": warnings,
    }


def render(report: dict) -> str:
    out = [f"Structure: {report['file']}"]
    if len(report["models"]) > 1:
        out.append(f"Models: {', '.join(str(m) for m in report['models'])}")

    out += ["", "Protein chains"]
    if report["protein_chains"]:
        for c in report["protein_chains"]:
            out.append(f"  {c['chain']:<3} {c['residues']:>5} residues, {c['atoms']:>6} atoms")
    else:
        out.append("  (none)")

    others = [g for g in report["groups"] if g["type"] != "protein"]
    if others:
        out += ["", "Other groups"]
        for g in others:
            chains = g.get("chains") or []
            if len(chains) == 1:
                where = f"chain {chains[0]}"
            elif chains:
                where = f"chains {','.join(chains)}"
            else:
                where = "no chain"
            plural = "atom" if g["atoms"] == 1 else "atoms"
            out.append(f"  {g['label']:<30} {where:<16} {g['atoms']:>6} {plural}")

    if report["altlocs"]:
        out += ["", f"Alternate conformers ({len(report['altlocs'])})"]
        for a in report["altlocs"]:
            out.append(f"  {a['chain']}:{a['resname']}{a['resid']:<6} codes {'/'.join(a['codes'])}")

    out += ["", "Disulfide bonds"]
    if report["disulfides"]:
        for b in report["disulfides"]:
            out.append(f"  {b['chain1']}:{b['resid1']} — {b['chain2']}:{b['resid2']}"
                       f"   ({b['source']})")
    else:
        out.append("  (none)")

    metals = report["metal_coordination"]
    if metals["cysteines"] or metals["histidines"]:
        out += ["", "Metal coordination"]
        for c in metals["cysteines"]:
            out.append(f"  CYS {c['chain']}:{c['resid']} SG — {c['metal']} {c['metal_resid']}"
                       f"  {c['distance']:.2f} Å   → {c['suggests']}")
        for h in metals["histidines"]:
            out.append(f"  HIS {h['chain']}:{h['resid']} {h['coordinating_atom']} — "
                       f"{h['metal']} {h['metal_resid']}  {h['distance']:.2f} Å   → {h['suggests']}")

    if report["histidines"]:
        listed = " ".join(f"{h['chain']}:{h['resid']}" for h in report["histidines"])
        out += ["", f"Histidines ({len(report['histidines'])})", f"  {listed}"]

    if report["uncovered_residues"]:
        out += ["", "Not covered by the bundled topologies",
                "  " + ", ".join(report["uncovered_residues"]),
                "  (harmless if these are dropped; needs parameters if they are built)"]

    if report["warnings"]:
        out += ["", "Warnings"]
        out += [f"  ! {w}" for w in report["warnings"]]

    return "\n".join(out)


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "inspect", help="report chains, ligands, altLocs, disulfides and metal sites")
    parser.add_argument("pdb", help="input PDB file")
    add_json_flag(parser)
    parser.set_defaults(func=run)


def run(args) -> int:
    if not os.path.isfile(args.pdb):
        return error("E_NO_INPUT", f"{args.pdb} does not exist",
                     "pass the path to a PDB file")
    report = inspect_structure(args.pdb)
    if args.json:
        print_json(report)
    else:
        print(render(report))
    return EXIT_OK
