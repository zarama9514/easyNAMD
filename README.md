# easyNAMD

GUI for preparing molecular dynamics systems in VMD for subsequent simulation in NAMD.

A Python tool designed to simplify work with VMD/NAMD. Its main features include preparing data for creating .psf/.pdb files and generating configuration files.
This tool is in the early stages of development. Please do not use this product for commercial purposes without the author's personal permission.

## Current features

Step-by-step system assembly via tabs:

1. **Build PSF** — build PSF/PDB from a local `.pdb` file using `psfgen`
2. **Solvate** — hydrate in a TIP3P water box with a given padding
3. **Ionize** — neutralize the system, optionally with a set salt concentration (NaCl)

Generates a Tcl script and runs VMD headlessly. VMD log is streamed in real time.

## Dependencies

- [VMD](https://www.ks.uiuc.edu/Research/vmd/) (configured on first launch)
- Python 3.12+
- [uv](https://github.com/astral-sh/uv)

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

Ligand files (from CGenFF or equivalent) are loaded via the **Add** button on the Build PSF tab.

## Project structure

```
main.py
gui/
  app.py             # main window, Build / Settings tabs
  build_panel.py     # step-by-step system assembly tabs
core/
  tcl_writer.py      # Tcl script generation (psfgen, solvate, autoionize)
  vmd_runner.py      # VMD execution via subprocess
topologies/
parameters/
```
