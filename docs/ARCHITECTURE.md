# easyNAMD Architecture Notes

easyNAMD is intentionally split into GUI orchestration and pure-ish core modules.
The most important design rule is that scientific file generation should live in
`core/`, while `gui/` should collect user choices and present validation.

## Layers

```text
main.py
  gui/
    app.py                  # top-level desktop shell
    prepare_panel.py        # PDB cleanup workflow
    build_panel.py          # psfgen build workflow
    simulate_panel.py       # NAMD package workflow
    namd_stage_row.py       # stage-table UI row widgets
    scrolling.py            # shared scroll containers

  core/
    pdb_fields.py           # fixed-width PDB helpers
    charmm.py               # shared CHARMM residue/atom aliases and groups
    molecule_groups.py      # PDB group/altLoc/histidine inspection helpers
    pdb_parser.py           # Build-tab PDB inspection models
    tcl_writer.py           # psfgen Tcl generation and split input PDBs
    vmd_runner.py           # headless VMD execution
    vmd_viewer.py           # VMD visualization helper scripts
    coverage.py             # residue/topology coverage checks
    zinc.py                 # Zn/Cys/His coordination suggestions
    namd/                   # NAMD pipeline, validation, configs, packaging
```

## NAMD Package Flow

```text
SystemConfig + Pipeline
        |
        v
validate_pipeline_report()
        |
        v
write_stage_conf() for each expanded stage
        |
        v
copy input files into system/
        |
        v
write protocol.md, summary JSON, README_run.txt, and *_run.sh
```

The generated package is designed to be movable. Runtime machine choices such as
GPU device, scheduler wrapper, modules, and extra launch flags are intentionally
kept outside the GUI.

## Build Flow

```text
PDB inspection
        |
        v
user choices: chains, histidines, patches, hetero segments, ligands
        |
        v
Python writes psfgen input PDB fragments
        |
        v
tcl_writer.py writes build.tcl
        |
        v
VMD/psfgen builds PSF/PDB/cell
```

The current implementation avoids relying on broad VMD selections for segment
splitting; Python writes chain and hetero PDB fragments explicitly before
psfgen sees them.

## Current Refactor Targets

- `gui/build_panel.py` should be split into state, table/view, VMD preview, and
  build-runner modules.
- `gui/simulate_panel.py` should separate table model, package controller, and
  validation display.
- VMD viewer code should keep improving toward stable persistent sessions and
  clearer failure recovery.
- Topology/parameter coverage should become a visible manager instead of a set
  of separate warnings.
