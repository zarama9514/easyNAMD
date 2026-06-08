# easyNAMD

GUI for preparing molecular dynamics systems in VMD for subsequent simulation in NAMD.

A Python tool designed to simplify work with VMD/NAMD. Its main features include preparing data for creating .psf/.pdb files and generating configuration files.
This tool is in the early stages of development. Please do not use this product for commercial purposes without the author's personal permission.

## Current features

### Prepare PDB tab

Clean up a raw PDB before building:

- Group atoms into protein chains, ligands/cofactors, metal ions and water; keep or drop each group.
- Interactive 3D viewer (3Dmol.js in a persistent window): protein as cartoon, het groups as VDW spheres; toggle groups live.
- Alternative locations (altLoc): pick which conformer to keep per residue, or a global default; focus a residue in 3D.
- Assign a chain id to each group independently.
- Atoms are renumbered from 1 on save.
- Export a ligand to `.mol2` (via Open Babel).
- On save, hand the cleaned PDB straight to the Build tab.

### Build tab (step-by-step)

1. **Build PSF** — build PSF/PDB from a local `.pdb` using `psfgen`:
   - per-chain N/C terminus patches, histidine protonation (HSD/HSE/HSP) with an RDKit-rendered legend and a 3D view of each histidine's environment,
   - disulfide bonds auto-detected from `SSBOND`, plus free-form custom patches,
   - warnings for ALTLOC, insertion codes, missing residues (REMARK 465), missing atoms (REMARK 470) and chain gaps,
   - `guesscoord` / `regenerate` options.
2. **Solvate** — TIP3P water box with a given padding; optional rotate-to-minimize-volume and move-center-of-mass-to-origin.
3. **Ionize** — neutralize the system, optionally at a set NaCl concentration.

Generates a Tcl script (previewable before running) and runs VMD headlessly with the log streamed live; the psfgen log is scanned for problems. Periodic cell vectors are written to `cell.txt` for the NAMD config.

## Dependencies

- [VMD](https://www.ks.uiuc.edu/Research/vmd/) (configured on first launch)
- [Open Babel](https://openbabel.org/) (`obabel`, for ligand → mol2)
- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

Python packages (installed via `uv`): customtkinter, pywebview, py3Dmol, pillow, rdkit.

## Usage

```bash
uv run python main.py
```

On first launch the app will attempt to detect VMD automatically. The path can be changed in the **Settings** tab.

## Force fields

CHARMM36 topology and parameter files are stored in:

```
topologies/          # .rtf, .str — protein, water, lipids, nucleic acids
└── ligands/         # ligand topologies

parameters/          # .prm, .str
└── ligands/         # ligand parameters
```

Ligand files (from CGenFF or equivalent) are loaded via the **Add** buttons on the Build PSF tab.

## Project structure

```
main.py
gui/
  app.py             # main window, tabs, Prepare → Build handoff
  prepare_panel.py   # Prepare PDB tab (groups, chains, altLoc, mol2)
  build_panel.py     # step-by-step build tabs
  webview_window.py  # standalone pywebview process for the 3D viewer
core/
  pdb_parser.py      # PDB parsing (chains, SS bonds, HIS, missing res/atoms, gaps)
  molecule_groups.py # group splitting, chain/altLoc-aware saving
  viewer_html.py     # 3Dmol.js page generation
  his_images.py      # RDKit-rendered HSD/HSE/HSP legend
  mol2.py            # PDB → mol2 via Open Babel
  tcl_writer.py      # Tcl generation (psfgen, solvate, autoionize, cell, recenter)
  vmd_runner.py      # VMD execution via subprocess
topologies/
parameters/
```
