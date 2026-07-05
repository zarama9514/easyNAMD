# Changelog

## 0.1.0-beta - 2026-07-05

Public beta stabilization snapshot.

### Added

- README landing page with beta scope, package layout, and workflow overview.
- Beta release checklist and tester feedback notes.
- Architecture notes for contributors and reviewers.
- Example workflow docs, including a first 1UBQ soluble-protein demo.
- Smoke tests for core CHARMM aliases, psfgen input splitting, altLoc focus
  output, NAMD GPU integration defaults, and package filename collisions.

### Improved

- NAMD package generation now writes staged configs, `results/`, protocol
  summary, provenance, package summary JSON, and a sequential run script.
- Default production pipeline uses `500 ns` at `2 fs`; heating uses `0.125 ns`.
- `CUDASOAintegrate auto` is documented as `off` for minimization and `on` for
  MD stages.
- Build and Simulate flows document known beta limitations instead of exposing
  unfinished restraints/enhanced-sampling features as core functionality.

### Known Beta Limitations

- Native restraint builders, harmonic bond/angle/torsion restraints, Colvars,
  aMD, metadynamics, ABF, and scheduler wrappers remain roadmap items.
- Ligand and membrane scientific correctness still require expert review.
