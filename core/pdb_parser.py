from dataclasses import dataclass


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


def find_disulfide_bonds(pdb_file: str) -> list[SSBond]:
    """Parse SSBOND records from a PDB file and return a list of SSBond objects."""
    bonds = []
    with open(pdb_file) as f:
        for line in f:
            if not line.startswith("SSBOND"):
                continue
            # SSBOND format:
            # cols 1-6:   record name
            # cols 8-10:  serial number
            # cols 12-14: residue name 1
            # col  16:    chain 1
            # cols 18-21: resid 1
            # cols 26-28: residue name 2
            # col  30:    chain 2
            # cols 32-35: resid 2
            try:
                chain1 = line[15].strip()
                resid1 = line[17:21].strip()
                chain2 = line[29].strip()
                resid2 = line[31:35].strip()
                bonds.append(SSBond(chain1, resid1, chain2, resid2))
            except IndexError:
                continue
    return bonds
