"""PDB → mol2 conversion via Open Babel."""

import shutil
import subprocess


def obabel_path() -> str | None:
    return shutil.which('obabel')


def pdb_to_mol2(pdb_path: str, mol2_path: str) -> tuple[bool, str]:
    """Convert a PDB file to mol2 using Open Babel.
    Returns (success, message)."""
    obabel = obabel_path()
    if not obabel:
        return False, "Open Babel (obabel) not found in PATH."

    try:
        result = subprocess.run(
            [obabel, pdb_path, '-O', mol2_path],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"obabel failed: {e}"

    if result.returncode != 0:
        return False, result.stderr.strip() or "obabel returned an error."
    return True, mol2_path
