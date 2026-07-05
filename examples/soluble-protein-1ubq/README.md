# 1UBQ Soluble-Protein Demo

This is the recommended first public demo for easyNAMD because ubiquitin is
small, familiar, and quick to inspect.

Input PDB:

- RCSB PDB ID: `1UBQ`
- Direct download: <https://files.rcsb.org/download/1UBQ.pdb>

## Steps

1. Download `1UBQ.pdb`.
2. Launch easyNAMD:

```bash
uv run python main.py
```

3. Open **Prepare PDB** and load `1UBQ.pdb`.
4. Keep the protein chain and any crystal waters you want to preserve.
5. Resolve any warnings shown by Prepare, then save a cleaned PDB.
6. Send the cleaned PDB to **Build**.
7. In **Build**, check termini, histidines, disulfides, hetero groups, and
   warnings.
8. Solvate, ionize, preview Tcl, and run Build.
9. Send the built PSF/PDB/cell triplet to **Simulate**.
10. Choose **Standard protein in water** or **Quick smoke test**.
11. Validate, preview configs, and generate the NAMD package.

## Expected Package

```text
namd/
  conf/
  system/
  results/
  templates/pipeline.json
  namd_config_summary.json
  protocol.md
  README_run.txt
  <system>_run.sh
```

## What To Show In A Demo

- VMD inspection of the prepared structure.
- Build log reaching successful PSF/PDB generation.
- Simulate package preview.
- `protocol.md` stage table.
- `<system>_run.sh` showing sequential stage execution.

## Notes

The default production stage is intentionally realistic (`500 ns` at `2 fs`) and
is not meant to be run during a quick GUI demo. Use **Quick smoke test** if you
only want to verify package generation and short local execution.
