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

# common coordinating metal ion resnames (PDB / CHARMM)
METAL_RESNAMES = {
    "ZN", "ZN2", "CD", "CD2", "CO", "NI", "FE", "FE2", "FE3",
    "MN", "MN3", "CU", "CU1", "CU2", "HG", "MG", "CA", "CAL",
}
CYS_CUTOFF = 3.0   # Å, metal–SG
HIS_CUTOFF = 3.0   # Å, metal–N


@dataclass
class ZnCys:
    chain: str
    resid: str


@dataclass
class ZnHis:
    chain: str
    resid: str
    protonation: str   # HSD or HSE


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _xyz(line):
    try:
        return (float(line[30:38]), float(line[38:46]), float(line[46:54]))
    except ValueError:
        return None


def detect_zinc_coordination(pdb_file: str):
    """Return (list[ZnCys], list[ZnHis]) for residues coordinating a zinc ion."""
    zincs = []                          # [xyz]
    cys_sg = {}                         # (chain, resid) -> xyz of SG
    his_n  = {}                         # (chain, resid) -> {"ND1": xyz, "NE2": xyz}

    with open(pdb_file) as f:
        for line in f:
            if line[:6].strip() not in ("ATOM", "HETATM"):
                continue
            xyz = _xyz(line)
            if xyz is None:
                continue
            resname = line[17:20].strip()
            atom    = line[12:16].strip()
            chain   = line[21].strip() if len(line) > 21 else ""
            resid   = line[22:26].strip() if len(line) > 25 else ""

            if resname in METAL_RESNAMES:
                zincs.append(xyz)
            elif resname == "CYS" and atom == "SG":
                cys_sg[(chain, resid)] = xyz
            elif resname in ("HIS", "HID", "HIE", "HIP", "HSD", "HSE", "HSP") \
                    and atom in ("ND1", "NE2"):
                his_n.setdefault((chain, resid), {})[atom] = xyz

    if not zincs:
        return [], []

    # cysteines whose SG is within cutoff of any zinc
    cys_result = []
    c2 = CYS_CUTOFF ** 2
    for (chain, resid), sg in cys_sg.items():
        if any(_dist2(sg, zn) <= c2 for zn in zincs):
            cys_result.append(ZnCys(chain=chain, resid=resid))

    # histidines coordinating a zinc → tautomer with proton on the far nitrogen
    his_result = []
    h2 = HIS_CUTOFF ** 2
    for (chain, resid), ns in his_n.items():
        nd1, ne2 = ns.get("ND1"), ns.get("NE2")
        nearest_zn = None
        best = None
        for zn in zincs:
            for n in (nd1, ne2):
                if n is None:
                    continue
                d = _dist2(n, zn)
                if best is None or d < best:
                    best, nearest_zn = d, zn
        if best is None or best > h2:
            continue
        # whichever N is closer to the zinc coordinates it (deprotonated);
        # the proton goes on the other N
        d_nd1 = min((_dist2(nd1, zn) for zn in zincs), default=1e9) if nd1 else 1e9
        d_ne2 = min((_dist2(ne2, zn) for zn in zincs), default=1e9) if ne2 else 1e9
        prot = "HSD" if d_ne2 < d_nd1 else "HSE"   # NE2 coordinates → HSD
        his_result.append(ZnHis(chain=chain, resid=resid, protonation=prot))

    return cys_result, his_result
