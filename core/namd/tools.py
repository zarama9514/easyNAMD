from __future__ import annotations

import os
from dataclasses import dataclass

from core.molecule_groups import METAL_RESNAMES, PROTEIN_RESNAMES, WATER_RESNAMES

LIPID_RESNAMES = frozenset({
    "DLPC", "DMPC", "DPPC", "DSPC", "DOPC", "POPC", "SOPC", "PLPC",
    "POPE", "DOPE", "DPPE", "POPG", "DOPG", "POPS", "DOPS", "POPA",
    "DOPA", "CARD", "TOCL", "CHL1", "CHOL", "ERG", "CER", "SPH",
    # Common 3-character truncations seen in fixed-width PDB exports.
    "DLP", "DMP", "DPP", "DSP", "DOP", "POP", "SOP", "PLP", "POE",
    "DOG", "POS", "DOS", "POA", "DOA", "CAR", "TOC", "CHL",
})

BACKBONE_ATOMS = frozenset({"N", "CA", "C", "O", "HN", "HA"})
LIPID_HEADGROUP_ATOMS = frozenset({
    "P", "O11", "O12", "O13", "O14", "N", "C11", "C12", "C13", "C14",
    "C15", "O21", "O22", "O31", "O32",
})


@dataclass
class SystemSummary:
    atoms: int = 0
    protein_atoms: int = 0
    lipid_atoms: int = 0
    water_atoms: int = 0
    ion_atoms: int = 0
    ligand_atoms: int = 0
    protein_chains: int = 0
    lipid_residues: int = 0
    cholesterol_residues: int = 0
    ligand_resnames: list[str] | None = None
    lipid_resnames: list[str] | None = None

    def lines(self) -> list[str]:
        ligands = ", ".join(self.ligand_resnames or []) or "none"
        lipids = ", ".join(self.lipid_resnames or []) or "none"
        return [
            f"Atoms: {self.atoms}",
            f"Protein atoms: {self.protein_atoms} in {self.protein_chains} chain(s)",
            f"Lipid atoms: {self.lipid_atoms}; lipid residues: {self.lipid_residues}; types: {lipids}",
            f"Cholesterol residues: {self.cholesterol_residues}",
            f"Water atoms: {self.water_atoms}",
            f"Ion atoms: {self.ion_atoms}",
            f"Ligand atoms: {self.ligand_atoms}; ligand residue names: {ligands}",
        ]


def detect_system(pdb_path: str) -> SystemSummary:
    summary = SystemSummary(ligand_resnames=[], lipid_resnames=[])
    if not pdb_path or not os.path.isfile(pdb_path):
        return summary

    protein_chains: set[str] = set()
    lipid_residues: set[tuple[str, str, str]] = set()
    cholesterol_residues: set[tuple[str, str, str]] = set()
    ligand_names: set[str] = set()
    lipid_names: set[str] = set()

    with open(pdb_path) as f:
        for line in f:
            if line[:6].strip() not in ("ATOM", "HETATM"):
                continue
            summary.atoms += 1
            atom = _atom_name(line)
            resname = _resname(line)
            chain = _chain(line)
            resid = _resid(line)
            residue_key = (chain, resid, resname)
            if resname in PROTEIN_RESNAMES:
                summary.protein_atoms += 1
                if chain:
                    protein_chains.add(chain)
            elif resname in LIPID_RESNAMES:
                summary.lipid_atoms += 1
                lipid_names.add(resname)
                lipid_residues.add(residue_key)
                if resname in {"CHL1", "CHOL"}:
                    cholesterol_residues.add(residue_key)
            elif resname in WATER_RESNAMES:
                summary.water_atoms += 1
            elif resname in METAL_RESNAMES or atom in {"NA", "CL", "K", "CA", "MG"}:
                summary.ion_atoms += 1
            else:
                summary.ligand_atoms += 1
                ligand_names.add(resname)

    summary.protein_chains = len(protein_chains)
    summary.lipid_residues = len(lipid_residues)
    summary.cholesterol_residues = len(cholesterol_residues)
    summary.ligand_resnames = sorted(ligand_names)
    summary.lipid_resnames = sorted(lipid_names)
    return summary


def inspect_restart(prefix: str) -> list[str]:
    if not prefix:
        return ["Restart prefix is empty."]
    lines = [f"Restart prefix: {prefix}"]
    ok = True
    for ext in ("coor", "vel", "xsc"):
        path = f"{prefix}.restart.{ext}"
        if os.path.isfile(path):
            lines.append(f"OK {os.path.basename(path)} ({os.path.getsize(path)} bytes)")
        else:
            ok = False
            lines.append(f"MISSING {path}")
    if ok:
        lines.append("Restart triplet looks complete.")
    return lines


def write_restraint_pdb(input_pdb: str, output_pdb: str, selection: str, force_constant: float) -> int:
    validate_selection(selection)
    selected = 0
    with open(input_pdb) as src, open(output_pdb, "w") as dst:
        for line in src:
            if line[:6].strip() in ("ATOM", "HETATM"):
                k = force_constant if atom_matches_selection(line, selection) else 0.0
                if k > 0:
                    selected += 1
                line = _with_beta(line, k)
            dst.write(line)
    return selected


def atom_matches_selection(line: str, selection: str) -> bool:
    text = _normalize_selection(selection)
    if not text or text == "all":
        return True
    resname = _resname(line)
    atom = _atom_name(line)
    chain = _chain(line).lower()
    is_hydrogen = atom.upper().startswith("H") or (len(line) > 77 and line[76:78].strip().upper() == "H")

    clauses = [part.strip() for part in text.split(" and ") if part.strip()]
    return all(_match_clause(clause, resname, atom, chain, is_hydrogen) for clause in clauses)


def validate_selection(selection: str) -> None:
    text = _normalize_selection(selection)
    if not text or text == "all":
        return
    for clause in [part.strip() for part in text.split(" and ") if part.strip()]:
        if not _known_clause(clause):
            raise ValueError(
                f"Unsupported selection clause: '{clause}'. Supported clauses: "
                "all, protein, backbone, heavy, lipid, headgroup, tail, water, ion, "
                "ligand, resname NAME, chain ID, not CLAUSE."
            )


def lint_conf_text(text: str) -> list[str]:
    warnings: list[str] = []
    keywords = _conf_keywords(text)
    structure = keywords.get("structure", "")
    if structure.strip('"').rstrip("/").endswith("../system"):
        warnings.append("Empty structure path.")
    if _is_on(keywords.get("pme")) and "pmegridspacing" not in keywords:
        warnings.append("PME is on but PMEGridSpacing is absent.")
    has_cell = "extendedsystem" in keywords or any(
        key.startswith("cellbasisvector") for key in keywords
    )
    if _is_on(keywords.get("langevinpiston")) and not has_cell:
        warnings.append("Pressure control is on but no cell basis vectors or extendedSystem are present.")
    if "surfacetensiontarget" in keywords and not _is_on(keywords.get("useflexiblecell")):
        warnings.append("surfaceTensionTarget requires useFlexibleCell on.")
    if _is_on(keywords.get("useconstantarea")) and _is_on(keywords.get("useflexiblecell")):
        warnings.append("NPAT constant area has flexible cell on; check ensemble intent.")
    return warnings


def _match_clause(clause: str, resname: str, atom: str, chain: str, is_hydrogen: bool) -> bool:
    if clause == "protein":
        return resname in PROTEIN_RESNAMES
    if clause == "backbone":
        return atom in BACKBONE_ATOMS
    if clause == "heavy":
        return not is_hydrogen
    if clause == "lipid":
        return resname in LIPID_RESNAMES
    if clause == "headgroup":
        return atom in LIPID_HEADGROUP_ATOMS
    if clause == "tail":
        return resname in LIPID_RESNAMES and atom not in LIPID_HEADGROUP_ATOMS and not is_hydrogen
    if clause == "water":
        return resname in WATER_RESNAMES
    if clause in ("ion", "ions"):
        return resname in METAL_RESNAMES
    if clause == "ligand":
        return resname not in PROTEIN_RESNAMES | WATER_RESNAMES | LIPID_RESNAMES | METAL_RESNAMES
    if clause.startswith("resname "):
        return resname == clause.split(None, 1)[1].strip().upper()
    if clause.startswith("chain "):
        return chain == clause.split(None, 1)[1].strip().lower()
    if clause.startswith("not "):
        return not _match_clause(clause[4:].strip(), resname, atom, chain, is_hydrogen)
    raise ValueError(f"Unsupported selection clause: '{clause}'.")


def _known_clause(clause: str) -> bool:
    if clause in {
        "protein", "backbone", "heavy", "lipid", "headgroup", "tail",
        "water", "ion", "ions", "ligand",
    }:
        return True
    if clause.startswith("resname ") and clause.split(None, 1)[1].strip():
        return True
    if clause.startswith("chain ") and clause.split(None, 1)[1].strip():
        return True
    if clause.startswith("not "):
        return _known_clause(clause[4:].strip())
    return False


def _normalize_selection(selection: str) -> str:
    text = (selection or "").strip().lower()
    aliases = {
        "protein backbone": "protein and backbone",
        "protein heavy": "protein and heavy",
        "lipid headgroups": "lipid and headgroup",
        "lipid tails": "lipid and tail",
    }
    return aliases.get(text, text)


def _conf_keywords(text: str) -> dict[str, str]:
    keywords: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 1:
            keywords[parts[0].lower()] = ""
        else:
            keywords[parts[0].lower()] = parts[1].strip()
    return keywords


def _is_on(value: str | None) -> bool:
    return (value or "").strip().strip('"').lower() == "on"


def _with_beta(line: str, beta: float) -> str:
    line = line.rstrip("\n")
    if len(line) < 66:
        line = line.ljust(66)
    return f"{line[:60]}{beta:6.2f}{line[66:]}\n"


def _atom_name(line: str) -> str:
    return line[12:16].strip().upper() if len(line) >= 16 else ""


def _resname(line: str) -> str:
    candidates = []
    for start, end in ((17, 21), (16, 20), (17, 20), (16, 19)):
        if len(line) >= end:
            value = line[start:end].strip().upper()
            if value:
                candidates.append(value)
    known = PROTEIN_RESNAMES | WATER_RESNAMES | LIPID_RESNAMES | METAL_RESNAMES
    for value in sorted(candidates, key=len, reverse=True):
        if len(value) >= 3 and value in known:
            return value
    for value in candidates:
        if len(value) == 3 and value.isalnum():
            return value
    for value in sorted(candidates, key=len, reverse=True):
        if value in known:
            return value
    return candidates[0] if candidates else ""


def _chain(line: str) -> str:
    return line[21].strip() if len(line) > 21 else ""


def _resid(line: str) -> str:
    return line[22:26].strip() if len(line) >= 26 else ""
