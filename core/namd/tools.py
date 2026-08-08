from __future__ import annotations

import os
from dataclasses import dataclass

from core import pdb_fields as pdbf
from core.charmm import (
    BACKBONE_ATOMS,
    LIPID_HEADGROUP_ATOMS,
    LIPID_RESNAMES,
    METAL_RESNAMES,
    PROTEIN_RESNAMES,
    WATER_RESNAMES,
)


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
            if not pdbf.is_atom_record(line):
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


def count_pdb_atoms(path: str) -> int:
    if not path or not os.path.isfile(path):
        return 0
    count = 0
    with open(path) as f:
        for line in f:
            if pdbf.is_atom_record(line):
                count += 1
    return count


def count_psf_atoms(path: str) -> int:
    if not path or not os.path.isfile(path):
        return 0
    with open(path, errors="replace") as f:
        for line in f:
            if "!NATOM" not in line:
                continue
            parts = line.split()
            if not parts:
                continue
            try:
                return int(parts[0])
            except ValueError:
                return 0
    return 0


def inspect_restart(prefix: str) -> list[str]:
    if not prefix:
        return ["Restart prefix is empty."]
    lines = [f"Restart prefix: {prefix}"]
    ok = True
    for ext in ("coor", "vel", "xsc"):
        path = f"{prefix}.restart.{ext}"
        if os.path.isfile(path):
            size = os.path.getsize(path)
            if size > 0:
                lines.append(f"OK {os.path.basename(path)} ({size} bytes)")
            else:
                ok = False
                lines.append(f"EMPTY {path}")
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
            if pdbf.is_atom_record(line):
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
    resid = _resid(line)
    segname = _segname(line).lower()
    is_hydrogen = atom.upper().startswith("H") or (len(line) > 77 and line[76:78].strip().upper() == "H")

    clauses = [part.strip() for part in text.split(" and ") if part.strip()]
    return all(_match_clause(clause, resname, atom, chain, resid, segname, is_hydrogen) for clause in clauses)


def validate_selection(selection: str) -> None:
    text = _normalize_selection(selection)
    if not text or text == "all":
        return
    for clause in [part.strip() for part in text.split(" and ") if part.strip()]:
        if not _known_clause(clause):
            raise ValueError(
                f"Unsupported selection clause: '{clause}'. Supported clauses: "
                "all, protein, backbone, heavy, lipid, headgroup, tail, water, ion, "
                "ligand, name ATOM, resname NAME, resid ID, resid START to END, "
                "chain ID, segname NAME, hydrogen, not CLAUSE."
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


def _match_clause(
    clause: str,
    resname: str,
    atom: str,
    chain: str,
    resid: str,
    segname: str,
    is_hydrogen: bool,
) -> bool:
    if clause == "protein":
        return resname in PROTEIN_RESNAMES
    if clause == "backbone":
        return atom in BACKBONE_ATOMS
    if clause == "heavy":
        return not is_hydrogen
    if clause == "hydrogen":
        return is_hydrogen
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
    if clause.startswith("name "):
        return atom == clause.split(None, 1)[1].strip().upper()
    if clause.startswith("resid "):
        return _match_resid_clause(clause, resid)
    if clause.startswith("chain "):
        return chain == clause.split(None, 1)[1].strip().lower()
    if clause.startswith("segname "):
        return segname == clause.split(None, 1)[1].strip().lower()
    if clause.startswith("not "):
        return not _match_clause(clause[4:].strip(), resname, atom, chain, resid, segname, is_hydrogen)
    raise ValueError(f"Unsupported selection clause: '{clause}'.")


def _known_clause(clause: str) -> bool:
    if clause in {
        "protein", "backbone", "heavy", "lipid", "headgroup", "tail",
        "water", "ion", "ions", "ligand", "hydrogen",
    }:
        return True
    if clause.startswith("resname ") and clause.split(None, 1)[1].strip():
        return True
    if clause.startswith("name ") and clause.split(None, 1)[1].strip():
        return True
    if clause.startswith("resid ") and _valid_resid_clause(clause):
        return True
    if clause.startswith("chain ") and clause.split(None, 1)[1].strip():
        return True
    if clause.startswith("segname ") and clause.split(None, 1)[1].strip():
        return True
    if clause.startswith("not "):
        return _known_clause(clause[4:].strip())
    return False


def _normalize_selection(selection: str) -> str:
    text = (selection or "").strip().lower()
    aliases = {
        "protein backbone": "protein and backbone",
        "protein heavy": "protein and heavy",
        "not hydrogen": "not hydrogen",
        "lipid headgroups": "lipid and headgroup",
        "lipid tails": "lipid and tail",
    }
    return aliases.get(text, text)


def _match_resid_clause(clause: str, resid: str) -> bool:
    value = clause.split(None, 1)[1].strip()
    parts = value.split()
    if len(parts) == 3 and parts[1] == "to":
        try:
            start = int(parts[0])
            end = int(parts[2])
            current = int(resid)
        except ValueError:
            return False
        lo, hi = sorted((start, end))
        return lo <= current <= hi
    return resid == value


def _valid_resid_clause(clause: str) -> bool:
    value = clause.split(None, 1)[1].strip()
    if not value:
        return False
    parts = value.split()
    if len(parts) == 1:
        return True
    if len(parts) == 3 and parts[1] == "to":
        try:
            int(parts[0])
            int(parts[2])
        except ValueError:
            return False
        return True
    return False


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
    return pdbf.atom_name(line)


def _resname(line: str) -> str:
    return pdbf.resname(line)


def _chain(line: str) -> str:
    return pdbf.chain_id(line)


def _resid(line: str) -> str:
    return pdbf.resid(line)


def _segname(line: str) -> str:
    return pdbf.segname(line)


def psf_total_charge(path: str) -> float | None:
    """Sum the charge column of a PSF's atom section.

    Recomputed from the file rather than trusted from the build log, because a
    validation has to describe the file that is on disk now — that is the whole
    point of being able to run it again later.
    """
    if not path or not os.path.isfile(path):
        return None
    total = 0.0
    remaining = 0
    with open(path, errors="replace") as f:
        for line in f:
            if remaining <= 0:
                if "!NATOM" in line:
                    try:
                        remaining = int(line.split()[0])
                    except (IndexError, ValueError):
                        return None
                continue
            parts = line.split()
            # ... segid resid resname name type charge mass ...
            if len(parts) < 7:
                continue
            try:
                total += float(parts[6])
            except ValueError:
                return None
            remaining -= 1
    return None if remaining > 0 else total
