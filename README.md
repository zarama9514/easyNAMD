# easyNAMD

![easyNAMD logo](docs/assets/easyNAMD_logo_wide.png)

**easyNAMD** is a desktop GUI for preparing VMD/NAMD molecular dynamics projects:
clean a PDB, build PSF/PDB systems with VMD/psfgen, and generate staged NAMD
configuration packages.

The project is currently a **beta preview**. It is intended for real-world testing
by users who already understand VMD/NAMD workflows. Please do not use this product
commercially without the author's personal permission.

## What It Does

- Prepare raw PDB files: choose molecular groups, remove unwanted components,
  resolve altLoc conformers, assign chains, renumber atoms, and export ligands to
  `.mol2` through Open Babel.
- Show molecular context in VMD: group views, histidine environments, and focused
  altLoc views.
- Build CHARMM-style systems through VMD/psfgen: protein chains, termini,
  histidine protonation, disulfides, hetero segments, crystal water, ligands,
  solvation, ionization, charge/atom-count checks, and cell-vector export.
- Generate NAMD packages: one `.conf` per enabled stage, restart chaining,
  editable MD defaults, membrane-aware pressure control, package validation,
  previews, a sequential `*_run.sh`, and protocol/provenance summaries.
- Keep cluster-specific choices outside the GUI: GPU selection, scheduler
  scripts, modules, and extra NAMD launch flags can be added around the generated
  run script.

## Beta Status

Tested locally on macOS with VMD. Linux/server-side NAMD execution, GPU launch
conventions, and larger production systems need more beta feedback.

Known limitations:

- Restraints are currently limited to per-stage positional force constants.
  Native restraint-PDB generation, restraint schedules, and selection builders are
  planned but not part of the beta core.
- Bond/angle/torsion harmonic restraints, Colvars, aMD, metadynamics, ABF, and
  other enhanced-sampling workflows are future advanced features.
- The generated package includes a local sequential shell script, but not SLURM,
  PBS, module-loading, or site-specific GPU wrapper scripts.
- Ligand correctness still depends on the user providing valid topology and
  parameter files.
- VMD visualization is a helper for inspection, not a replacement for careful
  molecular validation.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- [VMD](https://www.ks.uiuc.edu/Research/vmd/) on the machine running the GUI
- [NAMD](https://www.ks.uiuc.edu/Research/namd/) where generated configs will run
- [Open Babel](https://openbabel.org/) (`obabel`) for ligand `.pdb -> .mol2`

Python dependencies are intentionally small: `customtkinter`.

## Run

```bash
uv run python main.py
```

On first launch, set the VMD and NAMD binaries in **Settings**. These paths can be
changed later.

## Main Tabs

### Prepare PDB

Use this before Build when the input PDB has extra chains, ligands, crystal
waters, alternative locations, or model records.

Key actions:

- Load a PDB.
- Keep/drop protein chains, ligands/cofactors, metals, and water.
- Choose which altLoc conformer to keep.
- View selected groups or focused altLoc residues in VMD.
- Optionally export a ligand to `.mol2`.
- Save a cleaned PDB and send it to Build.

### Build

Build produces the final `.psf`, `.pdb`, and `*_cell.txt` files.

Key actions:

- Select a cleaned or raw PDB.
- Choose chain termini and histidine states (`HSD`, `HSE`, `HSP`).
- Review disulfide bonds, Zn/Cys/HIS suggestions, hetero segments, and warnings.
- Add ligand topology/parameter files.
- Solvate and ionize.
- Preview the generated Tcl script.
- Run VMD headlessly and inspect the live log.

### Simulate

Simulate creates a server-ready NAMD package.

Key actions:

- Load PSF/PDB/cell files manually or from a successful Build run.
- Pick a pipeline template.
- Edit stages: minimization, heating, equilibration, production, restart files,
  timestep, duration, ensemble, temperature, pressure, output frequencies, and
  chunking.
- Tune global MD defaults and advanced NAMD options, including
  `CUDASOAintegrate auto/on/off`.
- Validate, preview configs, inspect the package plan, and generate the package.

Generated package layout:

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

## Force Fields

Bundled CHARMM topology/parameter files live in:

```text
topologies/
parameters/
```

Ligand files can be added from the Build tab. Put reusable ligand files in:

```text
topologies/ligands/
parameters/ligands/
```

## Beta Checklist

Before giving easyNAMD to a tester, check:

- macOS GUI launches with `uv run python main.py`.
- VMD path is configured in **Settings**.
- NAMD path and default `+p` thread count are configured in **Settings**.
- Prepare can open a representative PDB and save a cleaned PDB.
- Build can preview Tcl and either complete or fail with a readable VMD/psfgen log.
- Simulate can generate a package, write `protocol.md`, and create executable
  `<system>_run.sh`.
- Linux/NAMD GPU execution is treated as tester feedback territory: device
  selection should be done outside easyNAMD with `CUDA_VISIBLE_DEVICES`, `+devices`,
  scheduler options, or local wrapper scripts.

## Sample Workflows

### 1. Soluble Protein In Water

1. Open **Prepare PDB** and load the raw PDB.
2. Keep the protein chain(s), required cofactors/metals, and optionally crystal
   waters.
3. Resolve altLoc residues if present.
4. Save the cleaned PDB and send it to **Build**.
5. In **Build**, check termini, histidines, disulfides, hetero segments, and
   warnings.
6. Solvate, ionize, preview the Tcl script, then run Build.
7. Send the built system to **Simulate**.
8. Choose **Standard protein in water**, validate, preview, and generate the
   NAMD package.

### 2. Protein With Ligand

1. Prepare the protein/ligand PDB and keep the ligand group.
2. Export the ligand to `.mol2` if needed for external parameterization.
3. Add ligand topology and parameter files in **Build**.
4. Enable the ligand as a hetero segment and verify its segname.
5. Build, then inspect the log for missing topology/parameter warnings.
6. Generate a NAMD package from **Simulate**.

### 3. Membrane System

1. Build or load a system with PSF/PDB/cell files.
2. In **Simulate**, set **System type** to `membrane`.
3. Choose a membrane template or set stage ensembles manually.
4. Use membrane-aware `NPT`, `NPAT`, or `NPgT` stages as appropriate.
5. Validate before generating the package. Check pressure mode and surface tension
   in the preview/report.

### 4. Restart Or Continuation

For a full pipeline continuation, set **Start** to `restart` and choose a restart
prefix matching:

```text
prefix.restart.coor
prefix.restart.vel
prefix.restart.xsc
```

For a single stage override, use the `restart files` button in the stage table and
select the `.coor`, `.vel`, and `.xsc` files for that stage.

### 5. GPU Runs

`CUDASOAintegrate auto` writes GPU-resident integration `on` for MD stages and
`off` for minimization. The generated `<system>_run.sh` uses the configured NAMD
binary and `+p` thread count. Select the actual GPU outside easyNAMD, for example:

```bash
CUDA_VISIBLE_DEVICES=0 NAMD_THREADS=8 ./system_run.sh
```

Cluster launch details are intentionally left to your site-specific wrapper or
scheduler script.
