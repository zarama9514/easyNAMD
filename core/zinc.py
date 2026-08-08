"""Detect metal coordination to assign CYS deprotonation and HIS tautomers.

Catalytic/structural metal sites (zinc fingers, metallo-enzymes like NDM-1) bind
cysteine thiolates and histidines. Metals are often substituted in crystals
(e.g. NDM-1 in 3ZR9 holds Cd in its Cys site), so we look at all common
transition-metal cations, not just zinc.

Typical first-shell distances:
  metal–S(Cys)  ≈ 2.3–2.6 Å
  metal–N(His)  ≈ 2.0–2.3 Å
A 3.0 Å cutoff captures the first shell without catching the next (~4 Å+).
"""

from dataclasses import dataclass

from core import pdb_fields as pdbf
from core.charmm import COORDINATING_METAL_RESNAMES

CYS_CUTOFF = 3.0   # Å, metal–SG
HIS_CUTOFF = 3.0   # Å, metal–N


@dataclass
class ZnCys:
    chain: str
    resid: str
    metal: str = ""            # coordinating metal resname, e.g. ZN / CD
    metal_resid: str = ""
    distance: float = 0.0      # Å, SG–metal

    def describe(self) -> str:
        return (f"CYS {self.chain}:{self.resid} SG — {self.metal} {self.metal_resid}"
                f"  {self.distance:.2f} Å")


@dataclass
class ZnHis:
    chain: str
    resid: str
    protonation: str           # HSD or HSE
    metal: str = ""
    metal_resid: str = ""
    coordinating_atom: str = ""   # ND1 or NE2 — the one bound to the metal
    distance: float = 0.0         # Å, coordinating N–metal

    def describe(self) -> str:
        return (f"HIS {self.chain}:{self.resid} {self.coordinating_atom} — "
                f"{self.metal} {self.metal_resid}  {self.distance:.2f} Å → {self.protonation}")


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _xyz(line):
    return pdbf.xyz(line)


def _closest_metal(point, metals):
    """Return (squared_distance, metal) for the metal nearest to `point`."""
    best_d2, best_metal = None, None
    for metal in metals:
        d2 = _dist2(point, metal[0])
        if best_d2 is None or d2 < best_d2:
            best_d2, best_metal = d2, metal
    return best_d2, best_metal


def detect_zinc_coordination(pdb_file: str):
    """Return (list[ZnCys], list[ZnHis]) for residues coordinating a metal ion.

    Distances and the coordinating metal are reported so the result can be
    checked by eye — a wrong cutoff is otherwise a silent error."""
    metals = []                         # [(xyz, resname, resid)]
    cys_sg = {}                         # (chain, resid) -> xyz of SG
    his_n  = {}                         # (chain, resid) -> {"ND1": xyz, "NE2": xyz}

    with open(pdb_file) as f:
        for line in f:
            if not pdbf.is_atom_record(line):
                continue
            xyz = _xyz(line)
            if xyz is None:
                continue
            resname = pdbf.resname(line)
            atom = pdbf.atom_name(line)
            chain = pdbf.chain_id(line)
            resid = pdbf.resid(line)

            if resname in COORDINATING_METAL_RESNAMES:
                metals.append((xyz, resname, resid))
            elif resname == "CYS" and atom == "SG":
                cys_sg[(chain, resid)] = xyz
            elif resname in ("HIS", "HID", "HIE", "HIP", "HSD", "HSE", "HSP") \
                    and atom in ("ND1", "NE2"):
                his_n.setdefault((chain, resid), {})[atom] = xyz

    if not metals:
        return [], []

    # cysteines whose SG is within cutoff of any metal → thiolate (CYSD)
    cys_result = []
    c2 = CYS_CUTOFF ** 2
    for (chain, resid), sg in cys_sg.items():
        d2, metal = _closest_metal(sg, metals)
        if d2 is not None and d2 <= c2:
            cys_result.append(ZnCys(
                chain=chain, resid=resid,
                metal=metal[1], metal_resid=metal[2], distance=d2 ** 0.5,
            ))

    # histidines coordinating a metal → proton goes on the far nitrogen
    his_result = []
    h2 = HIS_CUTOFF ** 2
    for (chain, resid), ns in his_n.items():
        candidates = []
        for name in ("ND1", "NE2"):
            point = ns.get(name)
            if point is None:
                continue
            d2, metal = _closest_metal(point, metals)
            if d2 is not None:
                candidates.append((d2, name, metal))
        if not candidates:
            continue
        best_d2, best_atom, best_metal = min(candidates)
        if best_d2 > h2:
            continue
        # the nitrogen closer to the metal coordinates it (deprotonated);
        # the proton sits on the other one
        prot = "HSD" if best_atom == "NE2" else "HSE"
        his_result.append(ZnHis(
            chain=chain, resid=resid, protonation=prot,
            metal=best_metal[1], metal_resid=best_metal[2],
            coordinating_atom=best_atom, distance=best_d2 ** 0.5,
        ))

    return cys_result, his_result
