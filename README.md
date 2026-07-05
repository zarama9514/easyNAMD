# easyNAMD

![easyNAMD logo](docs/assets/easyNAMD_logo_wide.png)

**easyNAMD** is a desktop beta GUI for preparing VMD/NAMD molecular dynamics
projects. It helps clean PDB inputs, inspect molecular edge cases in VMD, build
CHARMM-style PSF/PDB systems with psfgen, and generate staged NAMD configuration
packages with a reproducible run script.

This is a **beta preview for experienced VMD/NAMD users**. It is ready for
feedback on real systems, but it is not a replacement for scientific validation
of topology, parameters, protonation states, restraints, membranes, ligands, or
production MD choices.

Commercial use is not permitted without the author's personal permission. See
[LICENSE](LICENSE).

## Core Capabilities

- PDB cleanup: chains, hetero groups, crystal water, metals, altLocs, atom
  renumbering, and ligand `.mol2` export through Open Babel.
- VMD inspection helpers: selected groups, histidine environments, and focused
  altLoc views.
- psfgen build flow: termini, histidine states, disulfides, hetero segments,
  topology/parameter inputs, solvation, ionization, charge checks, and cell
  export.
- NAMD package generation: staged `.conf` files, restart chaining, editable MD
  defaults, membrane-aware pressure modes, package validation, protocol summary,
  provenance, and an executable `<system>_run.sh`.
- GPU-aware defaults: `CUDASOAintegrate auto` writes `off` for minimization and
  `on` for MD stages. Device selection and scheduler details stay outside the
  GUI.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- [VMD](https://www.ks.uiuc.edu/Research/vmd/) on the GUI machine
- [NAMD](https://www.ks.uiuc.edu/Research/namd/) where generated configs run
- [Open Babel](https://openbabel.org/) (`obabel`) for ligand `.pdb -> .mol2`

Python dependency surface is intentionally small: `customtkinter`.

## Quick Start

```bash
uv run python main.py
```

On first launch, set the VMD and NAMD paths in **Settings**. The generated NAMD
package can be moved to another machine after it is created.

## Typical Workflow

1. **Prepare PDB**: load a raw PDB, keep the needed groups, resolve altLocs, and
   save a cleaned PDB.
2. **Build**: choose termini, histidines, disulfides, hetero segments, ligand
   files, solvation, and ionization; then run VMD/psfgen.
3. **Simulate**: load or auto-fill the built PSF/PDB/cell files, choose a
   pipeline, validate, preview, and generate the NAMD package.
4. Run the generated shell script locally or wrap it in your own cluster script:

```bash
CUDA_VISIBLE_DEVICES=0 NAMD_THREADS=8 ./system_run.sh
```

## Generated Package

```text
namd/
  conf/                     # one .conf per enabled/expanded stage
  system/                   # copied psf/pdb/cell/parameter/restart inputs
  results/                  # trajectories, restarts, and logs
  templates/pipeline.json
  namd_config_summary.json
  protocol.md
  README_run.txt
  <system>_run.sh
```

## Bundled CHARMM Files

The default topology/parameter files in `topologies/` and `parameters/` are
refreshed from the official MacKerell Lab CHARMM36 February 2026
`toppar_c36_feb26.tgz` release. A full text mirror is kept under
`forcefields/charmm36_feb26/toppar/`.

Ligand-specific files can be added from the Build tab or kept in:

```text
topologies/ligands/
parameters/ligands/
```

## Beta Scope

Currently in scope:

- soluble protein and protein/ligand system preparation;
- membrane-aware NAMD config generation;
- restart-aware staged packages;
- local sequential NAMD run scripts.

Not yet core features:

- native restraint-PDB generation and restraint schedules;
- harmonic bond/angle/torsion restraints;
- Colvars, aMD, metadynamics, ABF, and other enhanced-sampling workflows;
- SLURM/PBS/module wrappers;
- automated ligand parameter correctness checks.

More detail: [Beta release notes](docs/BETA_RELEASE.md).

## Examples And Docs

- [Example workflows](examples/README.md)
- [1UBQ soluble-protein demo](examples/soluble-protein-1ubq/README.md)
- [Architecture notes](docs/ARCHITECTURE.md)
- [Beta release checklist](docs/BETA_RELEASE.md)
- [Development TODO](TODO.md)

## Smoke Tests

```bash
uv run python -m unittest discover -s tests
uv run python -B -m py_compile main.py gui/*.py core/*.py core/namd/*.py
```

The smoke suite covers shared CHARMM aliases, Python-written psfgen input PDBs,
altLoc focus PDB generation, package filename-collision checks, and NAMD GPU
integration defaults.
