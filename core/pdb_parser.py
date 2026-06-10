from dataclasses import dataclass, field


# ------------------------------------------------------------------ #
#  Data classes                                                        #
# ------------------------------------------------------------------ #

@dataclass
class SSBond:
    chain1: str
    resid1: str
    chain2: str
    resid2: str

    def __str__(self):
        return f"{self.chain1}:{self.resid1} — {self.chain2}:{self.resid2}"


@dataclass
class Patch:
    name: str
    chain1: str
    resid1: str
    chain2: str = ""
    resid2: str = ""

    def is_two_residue(self) -> bool:
        return bool(self.chain2 and self.resid2)


@dataclass
class HisResidue:
    chain: str
    resid: str
    protonation: str = "HSD"   # HSD | HSE | HSP

    def __str__(self):
        return f"{self.chain}:{self.resid}"


@dataclass
class SegmentConfig:
    chain: str
    first_patch: str = "NTER"  # NTER | GLYP | PROP | ACE | none
    last_patch: str  = "CTER"  # CTER | CT1  | CT2  | CT3  | none


@dataclass
class HeteroResidue:
    """A non-protein, non-water residue type (ligand, cofactor or ion)."""
    resname: str
    chain:   str
    count:   int = 0

    def label(self) -> str:
        return f"{self.resname} (chain {self.chain}, {self.count} atoms)"

    def default_segname(self) -> str:
        return (self.resname[:3] + self.chain).upper()[:4] or "HET"


@dataclass
class HeteroSegment:
    """A hetero residue chosen to be built as its own psfgen segment.
    `selection`, if set, overrides the default `resname …` atomselect
    (used e.g. to build crystal water with the `water` selection)."""
    segname:   str
    resname:   str
    chain:     str
    selection: str = ""


@dataclass
class PDBInfo:
    chains:           list[str]
    ss_bonds:         list[SSBond]
    histidines:       list[HisResidue]
    has_altloc:       bool
    has_insercodes:   bool
    missing_residues: int = 0          # from REMARK 465
    missing_atoms:    int = 0          # from REMARK 470
    chain_gaps:       list[str] = field(default_factory=list)  # "A: 56→61 (4 missing)"


# ------------------------------------------------------------------ #
#  Parsers                                                             #
# ------------------------------------------------------------------ #

_STANDARD_AA = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    "HID", "HIE", "HIP", "HSD", "HSE", "HSP", "MSE",
}
_WATER = {"HOH", "WAT", "TIP3", "SOL", "H2O", "TIP"}


def find_hetero_residues(pdb_file: str) -> list[HeteroResidue]:
    """Find non-protein, non-water residue types (ligands, cofactors, ions)."""
    found: dict[tuple, HeteroResidue] = {}
    with open(pdb_file) as f:
        for line in f:
            if line[:6].strip() not in ("ATOM", "HETATM"):
                continue
            resname = line[17:20].strip()
            chain   = line[21].strip() if len(line) > 21 else ""
            if resname in _STANDARD_AA or resname in _WATER:
                continue
            key = (resname, chain)
            if key not in found:
                found[key] = HeteroResidue(resname=resname, chain=chain)
            found[key].count += 1
    return sorted(found.values(), key=lambda h: (h.resname, h.chain))


def parse_pdb(pdb_file: str) -> PDBInfo:
    """Single-pass parse of a PDB file — returns all info the GUI needs."""
    chains: list[str]         = []
    ss_bonds: list[SSBond]    = []
    histidines: list[HisResidue] = []
    has_altloc                = False
    has_insercodes            = False

    missing_residues          = 0
    missing_atoms             = 0

    seen_chains: set[str]     = set()
    seen_his: set[tuple]      = set()
    in_remark_465             = False
    in_remark_470             = False
    last_ca: dict[str, int]   = {}     # chain → last CA resSeq, for gap detection
    chain_gaps: list[str]     = []
    chain_residues: dict[str, set] = {}   # chain → set of residues (for size filter)

    HIS_NAMES = {"HIS", "HID", "HIE", "HIP", "HSD", "HSE", "HSP"}

    with open(pdb_file) as f:
        for line in f:
            record = line[:6].strip()

            # REMARK 465 = missing residues, REMARK 470 = missing atoms.
            # Count only data rows (those whose 3-letter resname slot is filled
            # and whose resSeq is numeric), skipping the table headers.
            if line.startswith("REMARK 465"):
                in_remark_465, in_remark_470 = True, False
                if line[18:26].strip() and line[21:26].strip().lstrip("-").isdigit():
                    missing_residues += 1
                continue
            if line.startswith("REMARK 470"):
                in_remark_465, in_remark_470 = False, True
                if line[18:26].strip() and line[20:24].strip().lstrip("-").isdigit():
                    missing_atoms += 1
                continue

            if record in ("ATOM", "HETATM"):
                chain  = line[21]   if len(line) > 21 else " "
                resid  = line[22:26].strip() if len(line) > 25 else ""
                resname = line[17:20].strip() if len(line) > 19 else ""
                altloc = line[16]   if len(line) > 16 else " "
                icode  = line[26]   if len(line) > 26 else " "

                # protein chains for segment building — classify by residue name
                # (MD-frame PDBs write everything as ATOM, so record type is
                # unreliable; only standard amino acids count as protein)
                if resname in _STANDARD_AA and chain.strip():
                    if chain not in seen_chains:
                        seen_chains.add(chain)
                        chains.append(chain)
                    chain_residues.setdefault(chain, set()).add((resid, icode))

                # residue-numbering gaps within a chain (CA atoms only)
                if record == "ATOM" and line[12:16].strip() == "CA" and resid.lstrip("-").isdigit():
                    n = int(resid)
                    prev = last_ca.get(chain)
                    if prev is not None and n - prev > 1:
                        chain_gaps.append(f"{chain.strip()}: {prev}→{n} ({n - prev - 1} missing)")
                    last_ca[chain] = n

                # altloc
                if altloc.strip():
                    has_altloc = True

                # insertion codes
                if icode.strip():
                    has_insercodes = True

                # histidines
                if resname in HIS_NAMES:
                    key = (chain, resid)
                    if key not in seen_his:
                        seen_his.add(key)
                        histidines.append(HisResidue(chain=chain.strip(), resid=resid))

            elif record == "SSBOND":
                try:
                    chain1 = line[15].strip()
                    resid1 = line[17:21].strip()
                    chain2 = line[29].strip()
                    resid2 = line[31:35].strip()
                    ss_bonds.append(SSBond(chain1, resid1, chain2, resid2))
                except IndexError:
                    pass

    # drop single-residue "chains" (cofactors/caps, not real protein segments)
    chains = [c for c in chains if len(chain_residues.get(c, ())) > 1]

    return PDBInfo(
        chains=chains,
        ss_bonds=ss_bonds,
        histidines=histidines,
        has_altloc=has_altloc,
        has_insercodes=has_insercodes,
        missing_residues=missing_residues,
        missing_atoms=missing_atoms,
        chain_gaps=chain_gaps,
    )
