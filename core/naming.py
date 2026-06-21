"""Derive output names and the per-structure folder from the input PDB name.

Pipeline naming:
    name.pdb
      → name_clean.pdb                      (Prepare)
      → name_clean.psf / .pdb               (Build: psfgen)
      → name_clean_solvated.psf / .pdb      (Build: solvate)
      → name_clean_solvated_ionized.psf/.pdb(Build: ionize)

Everything lives in a folder named after the structure root — the file stem with
the trailing clean / solvated / ionized tokens removed. If none of those tokens
are present (e.g. grozd_vodichka_ioni.pdb) the whole stem is used.
"""

import os

_PIPELINE_TOKENS = {"clean", "solvated", "ionized"}


def stem(path: str) -> str:
    """File name without directory or extension."""
    return os.path.splitext(os.path.basename(path))[0]


def root_name(path: str) -> str:
    """Structure root: stem with trailing clean/solvated/ionized tokens removed."""
    tokens = stem(path).split("_")
    while len(tokens) > 1 and tokens[-1].lower() in _PIPELINE_TOKENS:
        tokens.pop()
    return "_".join(tokens)


def structure_dir(path: str) -> str:
    """Folder for this structure: <dir of input>/<root>.
    If the file already sits in a folder named after the root (e.g. a cleaned
    PDB inside its structure folder), reuse that folder instead of nesting."""
    parent = os.path.dirname(os.path.abspath(path))
    root = root_name(path)
    if os.path.basename(parent) == root:
        return parent
    return os.path.join(parent, root)
