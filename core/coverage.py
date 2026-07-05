"""Check that every residue in the PDB is defined in the loaded topology files."""

from core.charmm import charmm_residue_name_for_check
from core import pdb_fields as pdbf


def topology_resnames(topology_files: list[str]) -> set[str]:
    """Collect RESI names defined in CHARMM topology (.rtf/.str) files."""
    names: set[str] = set()
    for path in topology_files:
        try:
            with open(path, errors="ignore") as f:
                for line in f:
                    if line[:4].upper() == "RESI":
                        parts = line.split()
                        if len(parts) >= 2:
                            names.add(parts[1].upper())
        except OSError:
            continue
    return names


def pdb_resnames(pdb_file: str) -> set[str]:
    names: set[str] = set()
    with open(pdb_file) as f:
        for line in f:
            if pdbf.is_atom_record(line):
                rn = pdbf.resname(line)
                if rn:
                    names.add(rn)
    return names


def uncovered_built_residues(resnames: list[str], topology_files: list[str]) -> list[str]:
    """Of the given residue names (those actually being built), return the ones
    not defined in the loaded topologies (after applying standard aliases)."""
    covered = topology_resnames(topology_files)
    missing = []
    for rn in resnames:
        rn = rn.upper()
        mapped = charmm_residue_name_for_check(rn)
        if mapped not in covered and rn not in missing:
            missing.append(rn)
    return missing


def uncovered_residues(pdb_file: str, topology_files: list[str]) -> list[str]:
    """Return PDB residue names that are not defined in the loaded topologies
    (after applying the standard aliases). These would trigger 'unknown residue'
    errors during psfgen."""
    covered = topology_resnames(topology_files)
    missing = []
    for rn in sorted(pdb_resnames(pdb_file)):
        mapped = charmm_residue_name_for_check(rn)
        if mapped not in covered:
            missing.append(rn)
    return missing
