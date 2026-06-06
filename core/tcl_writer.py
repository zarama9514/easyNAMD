import os


# ------------------------------------------------------------------ #
#  Individual Tcl blocks                                               #
# ------------------------------------------------------------------ #

def tcl_build_psf(
    pdb_file: str,
    topology_files: list[str],
    parameter_files: list[str],
    out_prefix: str,
) -> str:
    """Return a Tcl block that runs psfgen on a plain PDB (no aliases, no patches)."""
    top_lines = "\n".join(f'    topology "{t}"' for t in topology_files)
    param_lines = "\n".join(f'    readparameters "{p}"' for p in parameter_files)
    param_block = f"\n{param_lines}" if param_lines else ""
    return f"""\
# --- Build PSF ---
package require psfgen
psfgen {{
{top_lines}{param_block}
    readpdb "{pdb_file}"
    writepsf "{out_prefix}.psf"
    writepdb "{out_prefix}.pdb"
}}
"""


def tcl_solvate(in_prefix: str, out_prefix: str, padding: float) -> str:
    """Return a Tcl block that wraps a structure in a TIP3P water box."""
    return f"""\
# --- Solvate ---
package require solvate
mol load psf "{in_prefix}.psf" pdb "{in_prefix}.pdb"
solvate "{in_prefix}.psf" "{in_prefix}.pdb" \\
    -t {padding} \\
    -o "{out_prefix}"
mol delete all
"""


def tcl_ionize(in_prefix: str, out_prefix: str, salt_concentration: float = 0.0) -> str:
    """Return a Tcl block that neutralizes the system and optionally sets salt concentration."""
    salt_flag = f"-sc {salt_concentration} " if salt_concentration > 0.0 else ""
    return f"""\
# --- Ionize ---
package require autoionize
mol load psf "{in_prefix}.psf" pdb "{in_prefix}.pdb"
autoionize -psf "{in_prefix}.psf" -pdb "{in_prefix}.pdb" \\
    -neutralize {salt_flag}\\
    -o "{out_prefix}"
mol delete all
"""


# ------------------------------------------------------------------ #
#  Assembler                                                           #
# ------------------------------------------------------------------ #

def write_build_script(
    pdb_file: str,
    topology_files: list[str],
    parameter_files: list[str],
    output_dir: str,
    padding: float,
    ionize: bool,
    salt_concentration: float = 0.0,
) -> str:
    """Assemble individual Tcl blocks into a single build script.
    Returns the path to the written script."""

    os.makedirs(output_dir, exist_ok=True)

    psf_prefix      = os.path.join(output_dir, "structure")
    solvated_prefix = os.path.join(output_dir, "solvated")
    ionized_prefix  = os.path.join(output_dir, "ionized")
    final_prefix    = ionized_prefix if ionize else solvated_prefix

    blocks = [
        "# easyNAMD — auto-generated build script\n",
        tcl_build_psf(pdb_file, topology_files, parameter_files, psf_prefix),
        tcl_solvate(psf_prefix, solvated_prefix, padding),
    ]

    if ionize:
        blocks.append(tcl_ionize(solvated_prefix, ionized_prefix, salt_concentration))

    blocks.append(f'puts "easyNAMD: done. Final structure: {final_prefix}"\n')
    blocks.append("quit\n")

    script_path = os.path.join(output_dir, "build.tcl")
    with open(script_path, "w") as f:
        f.write("\n".join(blocks))

    return script_path
