"""Small fixed-width PDB helpers shared across easyNAMD.

This is intentionally lightweight. It centralizes the column slicing we need
until we decide to depend on a full structural parser.
"""

from core.charmm import LIPID_RESNAMES, METAL_RESNAMES, PROTEIN_RESNAMES, WATER_RESNAMES


def record_name(line: str) -> str:
    return line[:6].strip()


def is_atom_record(line: str) -> bool:
    return record_name(line) in ("ATOM", "HETATM")


def atom_name(line: str) -> str:
    return line[12:16].strip().upper() if len(line) >= 16 else ""


def resname(line: str) -> str:
    """Return a best-effort residue name, including common 4-char CHARMM names."""
    candidates = []
    for start, end in ((17, 21), (17, 20), (16, 20), (16, 19)):
        if len(line) >= end:
            value = line[start:end].strip()
            if value:
                candidates.append(value)
    known = PROTEIN_RESNAMES | WATER_RESNAMES | LIPID_RESNAMES | METAL_RESNAMES
    for value in sorted(candidates, key=len, reverse=True):
        if len(value.strip()) >= 3 and value.upper() in known:
            return value.upper()
    for value in candidates:
        upper = value.upper()
        if len(upper) == 3 and upper.isalnum():
            return upper
    for value in candidates:
        if value.upper() in known:
            return value.upper()
    return candidates[0].upper() if candidates else ""


def chain_id(line: str) -> str:
    return line[21].strip() if len(line) > 21 else ""


def resid(line: str) -> str:
    return line[22:26].strip() if len(line) >= 26 else ""


def icode(line: str) -> str:
    return line[26].strip() if len(line) > 26 else ""


def altloc(line: str) -> str:
    return line[16] if len(line) > 16 else " "


def segname(line: str) -> str:
    return line[72:76].strip() if len(line) >= 76 else ""


def xyz(line: str) -> tuple[float, float, float] | None:
    try:
        return (float(line[30:38]), float(line[38:46]), float(line[46:54]))
    except ValueError:
        return None


def set_serial(line: str, serial: int) -> str:
    return line[:6] + f"{serial:>5}" + line[11:]


def set_chain(line: str, chain: str) -> str:
    return line[:21] + (chain[:1] if chain else " ") + line[22:]


def blank_altloc(line: str) -> str:
    return line[:16] + " " + line[17:]
