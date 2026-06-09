import os
from core.pdb_parser import HeteroSegment, HisResidue, Patch, SegmentConfig


# ------------------------------------------------------------------ #
#  Standard CHARMM36 aliases                                           #
# ------------------------------------------------------------------ #

# These cover the most common PDB→CHARMM36 name mismatches.
_RESIDUE_ALIASES = [
    ("HIS", "HSD"),   # default HIS protonation; per-residue overrides via mutate
    ("HOH", "TIP3"),
    ("HID", "HSD"),
    ("HIE", "HSE"),
    ("HIP", "HSP"),
    # ions: PDB name → CHARMM36 toppar_water_ions resname
    ("NA",  "SOD"),
    ("CL",  "CLA"),
    ("K",   "POT"),
    ("CA",  "CAL"),
    ("MG",  "MG"),
    ("ZN",  "ZN2"),
    ("CD",  "CD2"),
    ("LI",  "LIT"),
    ("RB",  "RUB"),
    ("CS",  "CES"),
    ("BA",  "BAR"),
]

_ATOM_ALIASES = [
    ("ILE", "CD1", "CD"),    # ILE delta carbon
    ("HOH", "O",   "OH2"),   # TIP3 oxygen
    ("*",   "OXT", "OT2"),   # C-terminal oxygen
    ("*",   "H",   "HN"),    # backbone amide H (many PDBs use H instead of HN)
    ("*",   "O1",  "OT1"),
    ("*",   "O2",  "OT2"),
]


def _tcl_aliases() -> str:
    lines = ["# --- Standard CHARMM36 aliases ---"]
    for pdb_name, charmm_name in _RESIDUE_ALIASES:
        lines.append(f"pdbalias residue {pdb_name} {charmm_name}")
    lines.append("")
    for resname, pdb_atom, charmm_atom in _ATOM_ALIASES:
        lines.append(f"pdbalias atom {resname} {pdb_atom} {charmm_atom}")
    return "\n".join(lines)


# ------------------------------------------------------------------ #
#  Chain splitting                                                     #
# ------------------------------------------------------------------ #

def _hetero_pdb(tmp_dir: str, seg: HeteroSegment) -> str:
    return os.path.join(tmp_dir, f"het_{seg.segname}.pdb")


def _tcl_split_chains(pdb_file: str, chains: list[str], tmp_dir: str,
                      hetero_segments: list[HeteroSegment] | None = None) -> str:
    """VMD commands to write one PDB per protein chain and per hetero segment."""
    hetero_segments = hetero_segments or []
    lines = [
        "# --- Split PDB by chain / hetero residue ---",
        f'mol load pdb "{pdb_file}"',
    ]
    for chain in chains:
        out = os.path.join(tmp_dir, f"chain_{chain}.pdb")
        lines.append(f'[atomselect top "protein and chain {chain}"] writepdb "{out}"')
    for seg in hetero_segments:
        if seg.selection:
            sel = seg.selection
        else:
            sel = f'resname {seg.resname}'
            if seg.chain:
                sel += f' and chain {seg.chain}'
        lines.append(f'[atomselect top "{sel}"] writepdb "{_hetero_pdb(tmp_dir, seg)}"')
    lines.append("mol delete all")
    return "\n".join(lines)


def _tcl_hetero_segment(seg: HeteroSegment, pdb_file: str) -> str:
    """Segment block for a single hetero residue (ligand / cofactor / ion)."""
    return (
        f'segment {seg.segname} {{\n'
        f'    pdb "{pdb_file}"\n'
        f'    first none\n'
        f'    last  none\n'
        f'}}'
    )


# ------------------------------------------------------------------ #
#  Segment block                                                       #
# ------------------------------------------------------------------ #

def _tcl_segment(
    seg: SegmentConfig,
    pdb_file: str,
    his_mutations: list[HisResidue],
) -> str:
    """Return a segment block for one chain."""
    mutations = [
        f'    mutate {h.resid} {h.protonation}'
        for h in his_mutations
        if h.chain == seg.chain and h.protonation != "HSD"
    ]
    mutation_block = ("\n" + "\n".join(mutations)) if mutations else ""

    first_line = f"    first {seg.first_patch}" if seg.first_patch != "none" else ""
    last_line  = f"    last  {seg.last_patch}"  if seg.last_patch  != "none" else ""
    terminus_block = ""
    if first_line or last_line:
        terminus_block = "\n" + "\n".join(l for l in [first_line, last_line] if l)

    return (
        f'segment {seg.chain} {{\n'
        f'    pdb "{pdb_file}"{terminus_block}{mutation_block}\n'
        f'}}'
    )


# ------------------------------------------------------------------ #
#  Patches                                                             #
# ------------------------------------------------------------------ #

def _tcl_patches(patches: list[Patch]) -> str:
    if not patches:
        return ""
    lines = ["# --- Patches ---"]
    for p in patches:
        if p.is_two_residue():
            lines.append(f"patch {p.name} {p.chain1}:{p.resid1} {p.chain2}:{p.resid2}")
        else:
            lines.append(f"patch {p.name} {p.chain1}:{p.resid1}")
    return "\n".join(lines)


# ------------------------------------------------------------------ #
#  Individual pipeline blocks                                          #
# ------------------------------------------------------------------ #

def tcl_build_psf(
    pdb_file: str,
    topology_files: list[str],
    parameter_files: list[str],
    segments: list[SegmentConfig],
    patches: list[Patch],
    histidines: list[HisResidue],
    out_prefix: str,
    tmp_dir: str,
    hetero_segments: list[HeteroSegment] | None = None,
    guesscoord: bool = True,
    regenerate_angles: bool = True,
    regenerate_dihedrals: bool = True,
    regenerate_resids: bool = False,
) -> str:
    """Return a complete Tcl block that builds a PSF/PDB using psfgen."""
    hetero_segments = hetero_segments or []

    topology_lines   = "\n".join(f'topology "{t}"' for t in topology_files)
    parameter_lines  = "\n".join(f'readparameters "{p}"' for p in parameter_files)

    chain_pdbs = {
        seg.chain: os.path.join(tmp_dir, f"chain_{seg.chain}.pdb")
        for seg in segments
    }

    segment_blocks = "\n\n".join(
        [_tcl_segment(seg, chain_pdbs[seg.chain], histidines) for seg in segments]
        + [_tcl_hetero_segment(h, _hetero_pdb(tmp_dir, h)) for h in hetero_segments]
    )

    patch_block = _tcl_patches(patches)

    coordpdb_lines = "\n".join(
        [f'coordpdb "{chain_pdbs[seg.chain]}" {seg.chain}' for seg in segments]
        + [f'coordpdb "{_hetero_pdb(tmp_dir, h)}" {h.segname}' for h in hetero_segments]
    )

    options_lines = []
    if guesscoord:
        options_lines.append("guesscoord")
    regen_parts = []
    if regenerate_angles:
        regen_parts.append("angles")
    if regenerate_dihedrals:
        regen_parts.append("dihedrals")
    if regenerate_resids:
        regen_parts.append("resids")
    if regen_parts:
        options_lines.append(f"regenerate {' '.join(regen_parts)}")
    options_block = "\n".join(options_lines)

    parts = [
        "# --- Build PSF ---",
        "package require psfgen",
        "",
        "# Topologies",
        topology_lines,
    ]
    if parameter_lines:
        parts += ["", "# Parameters", parameter_lines]

    parts += [
        "",
        _tcl_aliases(),
        "",
        "# Segments",
        segment_blocks,
    ]
    if patch_block:
        parts += ["", patch_block]

    parts += [
        "",
        "# Coordinates",
        coordpdb_lines,
    ]
    if options_block:
        parts += ["", options_block]

    parts += [
        "",
        f'writepsf "{out_prefix}.psf"',
        f'writepdb "{out_prefix}.pdb"',
        "",
        "# Cleanup temporary chain files",
    ]
    for seg in segments:
        parts.append(f'file delete "{chain_pdbs[seg.chain]}"')
    for h in hetero_segments:
        parts.append(f'file delete "{_hetero_pdb(tmp_dir, h)}"')

    return "\n".join(parts)


def tcl_solvate(in_prefix: str, out_prefix: str, padding: float,
                rotate: bool = False) -> str:
    """Return a Tcl block that wraps a structure in a TIP3P water box.
    If rotate is set, the solute is rotated to minimize the box volume."""
    rotate_flag = " -rotate" if rotate else ""
    return "\n".join([
        "# --- Solvate ---",
        "package require solvate",
        f'mol load psf "{in_prefix}.psf" pdb "{in_prefix}.pdb"',
        f'solvate "{in_prefix}.psf" "{in_prefix}.pdb" \\',
        f'    -t {padding}{rotate_flag} \\',
        f'    -o "{out_prefix}"',
        "mol delete all",
    ])


def tcl_recenter(prefix: str) -> str:
    """Return a Tcl block that moves the system's center of mass to the origin
    and overwrites the PDB coordinates."""
    return "\n".join([
        "# --- Recenter to origin ---",
        f'mol load psf "{prefix}.psf" pdb "{prefix}.pdb"',
        'set _all [atomselect top all]',
        'set _com [measure center $_all weight mass]',
        '$_all moveby [vecscale -1.0 $_com]',
        f'$_all writepdb "{prefix}.pdb"',
        '$_all delete',
        "mol delete all",
    ])


def tcl_write_cell(prefix: str, cell_file: str) -> str:
    """Return a Tcl block that measures the periodic cell of the final system and
    writes NAMD cellBasisVector / cellOrigin lines to a file."""
    return "\n".join([
        "# --- Periodic cell (for NAMD) ---",
        f'mol load psf "{prefix}.psf" pdb "{prefix}.pdb"',
        'set _all [atomselect top all]',
        'set _mm [measure minmax $_all]',
        'set _min [lindex $_mm 0]',
        'set _max [lindex $_mm 1]',
        'set _size [vecsub $_max $_min]',
        'set _cen [measure center $_all]',
        f'set _fp [open "{cell_file}" w]',
        'puts $_fp "cellBasisVector1 [lindex $_size 0] 0 0"',
        'puts $_fp "cellBasisVector2 0 [lindex $_size 1] 0"',
        'puts $_fp "cellBasisVector3 0 0 [lindex $_size 2]"',
        'puts $_fp "cellOrigin $_cen"',
        'close $_fp',
        '$_all delete',
        "mol delete all",
    ])


def tcl_ionize(in_prefix: str, out_prefix: str, salt_concentration: float = 0.0,
               cation: str = "SOD", anion: str = "CLA") -> str:
    """Return a Tcl block that neutralizes the system and optionally sets salt
    concentration, using the given ion types (CHARMM resnames)."""
    salt_flag = f"-sc {salt_concentration} " if salt_concentration > 0.0 else ""
    return "\n".join([
        "# --- Ionize ---",
        "package require autoionize",
        f'mol load psf "{in_prefix}.psf" pdb "{in_prefix}.pdb"',
        f'autoionize -psf "{in_prefix}.psf" -pdb "{in_prefix}.pdb" \\',
        f'    -neutralize {salt_flag}-cation {cation} -anion {anion} \\',
        f'    -o "{out_prefix}"',
        "mol delete all",
    ])


def tcl_summary(prefix: str) -> str:
    """Return a Tcl block that reports total charge and atom count of the final
    system (the charge should be ~0 after neutralization)."""
    return "\n".join([
        "# --- System summary ---",
        f'mol load psf "{prefix}.psf" pdb "{prefix}.pdb"',
        'set _all [atomselect top all]',
        'set _q [eval vecadd [$_all get charge]]',
        'puts [format "easyNAMD: total charge = %.4f" $_q]',
        'puts "easyNAMD: atom count = [$_all num]"',
        '$_all delete',
        "mol delete all",
    ])


# ------------------------------------------------------------------ #
#  Assembler                                                           #
# ------------------------------------------------------------------ #

def write_build_script(
    pdb_file: str,
    topology_files: list[str],
    parameter_files: list[str],
    segments: list[SegmentConfig],
    patches: list[Patch],
    histidines: list[HisResidue],
    output_dir: str,
    padding: float,
    ionize: bool,
    salt_concentration: float = 0.0,
    cation: str = "SOD",
    anion: str = "CLA",
    rotate: bool = False,
    recenter: bool = False,
    hetero_segments: list[HeteroSegment] | None = None,
    guesscoord: bool = True,
    regenerate_angles: bool = True,
    regenerate_dihedrals: bool = True,
    regenerate_resids: bool = False,
) -> str:
    """Assemble all Tcl blocks into a single build script.
    Returns the path to the written script."""
    hetero_segments = hetero_segments or []

    os.makedirs(output_dir, exist_ok=True)

    psf_prefix      = os.path.join(output_dir, "structure")
    solvated_prefix = os.path.join(output_dir, "solvated")
    ionized_prefix  = os.path.join(output_dir, "ionized")
    final_prefix    = ionized_prefix if ionize else solvated_prefix

    blocks = [
        "# easyNAMD — auto-generated build script",
        "",
        _tcl_split_chains(pdb_file, [s.chain for s in segments], output_dir,
                          hetero_segments),
        "",
        tcl_build_psf(
            pdb_file=pdb_file,
            topology_files=topology_files,
            parameter_files=parameter_files,
            segments=segments,
            patches=patches,
            histidines=histidines,
            out_prefix=psf_prefix,
            tmp_dir=output_dir,
            hetero_segments=hetero_segments,
            guesscoord=guesscoord,
            regenerate_angles=regenerate_angles,
            regenerate_dihedrals=regenerate_dihedrals,
            regenerate_resids=regenerate_resids,
        ),
        "",
        tcl_solvate(psf_prefix, solvated_prefix, padding, rotate=rotate),
    ]

    if ionize:
        blocks += ["", tcl_ionize(solvated_prefix, ionized_prefix,
                                   salt_concentration, cation, anion)]

    if recenter:
        blocks += ["", tcl_recenter(final_prefix)]

    cell_file = os.path.join(output_dir, "cell.txt")
    blocks += ["", tcl_write_cell(final_prefix, cell_file)]
    blocks += ["", tcl_summary(final_prefix)]

    blocks += [
        "",
        f'puts "easyNAMD: done. Final structure: {final_prefix}"',
        f'puts "easyNAMD: periodic cell written to: {cell_file}"',
        "quit",
    ]

    script_path = os.path.join(output_dir, "build.tcl")
    with open(script_path, "w") as f:
        f.write("\n".join(blocks))

    return script_path
