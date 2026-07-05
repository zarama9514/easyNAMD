# easyNAMD Beta Release Notes

Date: 2026-07-05

This document defines the public beta boundary for easyNAMD. It is written for
testers and for anyone evaluating whether the project is mature enough to try on
their own VMD/NAMD systems.

## Beta Positioning

easyNAMD is a desktop assistant for preparing VMD/NAMD projects. The beta is
aimed at users who already understand molecular dynamics workflows and want a
faster, more inspectable way to move from PDB cleanup to psfgen build and staged
NAMD configs.

The beta goal is not to hide molecular modeling decisions. The goal is to make
those decisions visible, editable, and reproducible.

## Tested Before Public Sharing

Run these checks before posting or sending the repository to testers:

```bash
uv run python -m unittest discover -s tests
uv run python -B -m py_compile main.py gui/*.py core/*.py core/namd/*.py
git diff --check
git status --short
```

Manual smoke checklist:

- macOS GUI launches with `uv run python main.py`.
- VMD path is configured in **Settings**.
- NAMD path and default `+p` thread count are configured in **Settings**.
- Prepare can open a representative PDB and save a cleaned PDB.
- Build can preview Tcl and either complete or fail with a readable VMD/psfgen
  log.
- A successful Build auto-fills PSF/PDB/cell inputs in Simulate.
- Simulate can generate a package with `protocol.md`,
  `namd_config_summary.json`, `README_run.txt`, and executable `<system>_run.sh`.

## What Testers Should Try

- Soluble protein in water.
- Protein with a small ligand or cofactor, using user-provided topology and
  parameter files.
- Metal-containing systems, especially zinc/cadmium/cobalt/nickel edge cases.
- Membrane systems where `NPAT`, semi-isotropic `NPT`, or `NPgT` configs should
  be inspected carefully.
- Restart/continuation packages using `.coor`, `.vel`, and `.xsc` inputs.
- Linux/NAMD3 GPU launches using local wrappers, `CUDA_VISIBLE_DEVICES`,
  `+devices`, or scheduler scripts outside easyNAMD.

## Known Limitations

- Ligand correctness depends on valid user-supplied topology and parameter
  files.
- VMD visualization is an inspection helper, not a scientific validator.
- Restraints are limited to existing per-stage positional restraint fields.
  Native restraint-PDB generation and schedules are future work.
- Harmonic bond/angle/torsion restraints are not implemented.
- Colvars, aMD, metadynamics, ABF, umbrella sampling, and related enhanced
  sampling workflows are future advanced modules.
- No built-in SLURM, PBS, module-loading, or site-specific GPU launch templates.
- The GUI is optimized for package generation and local VMD/psfgen use, not for
  remote job monitoring yet.

## Feedback To Collect

Ask beta users for:

- operating system, VMD version, NAMD version, and GPU launch method;
- whether Build produced a usable PSF/PDB/cell triplet;
- full VMD/psfgen log if Build failed;
- generated `protocol.md` and `namd_config_summary.json` for package issues;
- missing topology/parameter cases, especially ligands, metals, and membrane
  components;
- GUI screens that felt confusing or too crowded.

## Public Demo Checklist

Before posting a LinkedIn demo:

- Use a clean git status and a named beta commit or tag.
- Record a short run through Prepare -> Build -> Simulate.
- Show the generated `protocol.md` and package layout.
- State clearly that restraints, constraints, enhanced sampling, and cluster
  wrappers are roadmap features.
- Ask for beta testers who already use VMD/NAMD and can share logs when
  something breaks.
