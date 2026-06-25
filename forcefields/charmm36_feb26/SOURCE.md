# CHARMM36 February 2026 Toppar Source

This directory mirrors the official CHARMM additive toppar release:

- Source page: https://mackerell.umaryland.edu/charmm_ff.shtml
- Download: `toppar_c36_feb26.tgz`
- Upstream archive path: `CHARMM_ff_params_files/toppar_c36_feb26.tgz`

Only text force-field files needed by easyNAMD are vendored here:
`.rtf`, `.prm`, `.str`, `00toppar_file_format.txt`, and
`toppar_all.history`.

The GUI auto-loads a curated subset from the project-level `topologies/` and
`parameters/` folders. The complete official mirror is kept here for manual
selection, future template logic, and traceability.
