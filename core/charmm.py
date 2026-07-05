"""Shared CHARMM/PDB naming tables used by GUI, psfgen, and validation."""

PROTEIN_RESNAMES = frozenset({
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    "HID", "HIE", "HIP", "HSD", "HSE", "HSP", "MSE", "CYX", "CYM",
})

WATER_RESNAMES = frozenset({"HOH", "WAT", "TIP3", "SOL", "H2O", "TIP"})

METAL_RESNAMES = frozenset({
    "ZN", "ZN2", "MG", "CA", "CAL", "FE", "FE2", "FE3", "MN", "MN3",
    "NA", "SOD", "K", "POT", "CU", "CU1", "CU2", "NI", "NI2P", "CO",
    "CO2P", "HG",
    "CD", "CD2", "PB", "PT", "AU", "AG", "SR", "BA", "CS", "RB",
    "LI", "BE", "AL", "CR", "IOD", "CLA",
})

COORDINATING_METAL_RESNAMES = frozenset({
    "ZN", "ZN2", "CD", "CD2", "CO", "CO2P", "NI", "NI2P", "FE", "FE2",
    "FE3", "MN", "MN3", "CU", "CU1", "CU2", "HG", "MG", "CA", "CAL",
})

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

DEFAULT_TOPOLOGY_STREAMS = (
    "toppar_water_ions.str",
    "toppar_ions_won.str",
)

# PDB residue name -> CHARMM topology residue name, preserving the case psfgen
# expects in Tcl. Use RESIDUE_ALIAS_LOOKUP_UPPER for case-insensitive checks.
PDB_TO_CHARMM_RESIDUE_ALIASES = (
    ("HIS", "HSD"),
    ("HOH", "TIP3"),
    ("HID", "HSD"),
    ("HIE", "HSE"),
    ("HIP", "HSP"),
    ("NA", "SOD"),
    ("CL", "CLA"),
    ("K", "POT"),
    ("CA", "CAL"),
    ("MG", "MG"),
    ("ZN", "ZN2"),
    ("CD", "CD2"),
    ("CO", "Co2p"),
    ("NI", "Ni2p"),
    ("LI", "LIT"),
    ("RB", "RUB"),
    ("CS", "CES"),
    ("BA", "BAR"),
)

PDB_TO_CHARMM_ATOM_ALIASES = (
    ("ILE", "CD1", "CD"),
    ("HOH", "O", "OH2"),
    ("CO", "CO", "Co2p"),
    ("NI", "NI", "Ni2p"),
    ("*", "OXT", "OT2"),
    ("*", "H", "HN"),
    ("*", "O1", "OT1"),
    ("*", "O2", "OT2"),
)

RESIDUE_ALIAS_LOOKUP_UPPER = {
    pdb.upper(): charmm.upper()
    for pdb, charmm in PDB_TO_CHARMM_RESIDUE_ALIASES
}


def charmm_residue_name_for_check(pdb_resname: str) -> str:
    """Return uppercase CHARMM residue name used by topology coverage checks."""
    name = (pdb_resname or "").strip().upper()
    return RESIDUE_ALIAS_LOOKUP_UPPER.get(name, name)


def is_protein_resname(resname: str) -> bool:
    return (resname or "").strip().upper() in PROTEIN_RESNAMES


def is_water_resname(resname: str) -> bool:
    return (resname or "").strip().upper() in WATER_RESNAMES


def is_lipid_resname(resname: str) -> bool:
    return (resname or "").strip().upper() in LIPID_RESNAMES


def is_metal_resname(resname: str) -> bool:
    return (resname or "").strip().upper() in METAL_RESNAMES
