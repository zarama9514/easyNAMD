# easyNAMD Example Workflows

These examples are public-beta smoke paths. They are intentionally small and
manual: the goal is to make it easy to compare what a tester did with what the
application generated.

## 1. Soluble Protein

Start here when testing easyNAMD for the first time:

- [1UBQ soluble-protein demo](soluble-protein-1ubq/README.md)

Expected result:

- cleaned PDB from Prepare;
- PSF/PDB/cell from Build;
- NAMD package with `conf/`, `system/`, `results/`, `protocol.md`,
  `namd_config_summary.json`, and `<system>_run.sh`.

## 2. Protein With Ligand

Use this path when the protein contains a ligand, inhibitor, cofactor, or custom
hetero residue.

Checklist:

1. Keep the ligand in Prepare.
2. Export `.mol2` if external parameterization is needed.
3. Add ligand `.rtf/.str` and `.prm/.str` files in Build.
4. Confirm the ligand is enabled as a hetero segment.
5. Build and inspect the VMD/psfgen log for unknown residue or missing parameter
   messages.
6. Generate the NAMD package from Simulate.

Current beta limitation: easyNAMD checks file presence and some residue coverage,
but it does not prove that ligand parameters are scientifically correct.

## 3. Membrane System

Use this path for already assembled or buildable membrane systems.

Checklist:

1. Load or build PSF/PDB/cell files.
2. In Simulate, set system type to `membrane`.
3. Choose a membrane pipeline or use stages with `NPAT`, semi-isotropic `NPT`, or
   `NPgT`.
4. Validate and inspect pressure-control lines in the generated config preview.
5. Check `protocol.md` before running.

Current beta limitation: easyNAMD can generate membrane-aware configs, but it
does not decide whether a particular bilayer protocol is scientifically
appropriate for your system.

## 4. Restart Or Continuation

Use explicit restart files when a stage should start from external coordinates:

- `.restart.coor`
- `.restart.vel`
- `.restart.xsc`

In Simulate, attach the restart triplet to the stage that should use it. If no
stage override is provided, stages chain from the previous stage output.

## 5. Linux Or GPU Server Run

The generated package is local and sequential by design. Pick the actual GPU and
scheduler details outside easyNAMD, for example:

```bash
CUDA_VISIBLE_DEVICES=0 NAMD_THREADS=8 ./system_run.sh
```

For clusters, wrap the same command in your local `sbatch`, `qsub`, or site
launcher script.
