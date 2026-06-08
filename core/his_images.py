"""Render histidine tautomers (HSD/HSE/HSP) to PNG images via RDKit."""

import os

from rdkit import Chem
from rdkit.Chem import Draw
from rdkit.Chem.Draw import rdMolDraw2D

# Imidazole ring order CG–ND1–CE1–NE2–CD2 (the leading C is the Cβ stub)
HIS_TAUTOMERS = {
    "HSD": "Cc1[nH]cnc1",      # proton on Nδ1 (neutral)
    "HSE": "Cc1nc[nH]c1",      # proton on Nε2 (neutral)
    "HSP": "Cc1[nH]c[nH+]c1",  # both protonated (+1)
}

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "his")


def _render(smiles: str, path: str, size: int = 150):
    mol = Chem.MolFromSmiles(smiles)
    drawer = rdMolDraw2D.MolDraw2DCairo(size, size)
    opts = drawer.drawOptions()
    opts.setBackgroundColour((1, 1, 1, 0))   # transparent
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    drawer.FinishDrawing()
    with open(path, "wb") as f:
        f.write(drawer.GetDrawingText())


def tautomer_images() -> dict[str, str]:
    """Generate (once) and return {name: png_path} for HSD/HSE/HSP."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    paths = {}
    for name, smiles in HIS_TAUTOMERS.items():
        path = os.path.join(CACHE_DIR, f"{name}.png")
        if not os.path.isfile(path):
            _render(smiles, path)
        paths[name] = path
    return paths
