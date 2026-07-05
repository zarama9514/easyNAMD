# TODO

## Beta stabilization

- [ ] Test the full soluble-protein workflow on a second macOS machine.
- [ ] Collect Linux/NAMD3 GPU launch feedback from beta testers.
- [x] Add one small public demo system or documented test input.
- [ ] Add smoke fixtures for ligand and membrane-ish systems.
- [ ] Keep expanding tests around VMD Tcl generation and psfgen script output.
- [x] Add public beta release notes, architecture notes, and example workflows.

## Internal cleanup

- [ ] Split BuildPanel into smaller state, view, and runner modules.
- [ ] Move more fixed-width PDB handling onto the shared `core.pdb_fields` helpers.
- [ ] Add a topology/parameter manager that explains which residues are covered.

## VMD viewing

- [ ] Improve altLoc focus views with conformer labels or a clearer color/material preset.
- [ ] Consider optional persistent VMD annotations for selected residues.

## Restraints and constraints

- [ ] Design a native restraint builder for atom selections and generated restraint PDBs.
- [ ] Add harmonic bond/angle/torsion potential support in a way that maps cleanly to NAMD input.
- [ ] Revisit restraint schedules after the basic builder is stable.

## Advanced sampling

- [ ] Design, but do not rush, Colvars/enhanced-sampling support.
- [ ] Evaluate aMD, metadynamics and ABF as separate advanced workflows.
