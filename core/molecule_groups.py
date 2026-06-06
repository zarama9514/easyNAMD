from dataclasses import dataclass, field

WATER_RESNAMES = frozenset({'HOH', 'WAT', 'TIP3', 'SOL', 'H2O', 'TIP'})

METAL_RESNAMES = frozenset({
    'ZN', 'MG', 'CA', 'FE', 'MN', 'NA', 'K', 'CU', 'NI', 'CO',
    'HG', 'CD', 'PB', 'PT', 'AU', 'AG', 'SR', 'BA', 'CS', 'RB',
    'LI', 'BE', 'AL', 'CR', 'FE2', 'FE3', 'CU1', 'IOD', 'CLA',
    'POT', 'SOD', 'CAL', 'MN3',
})

VDW_RADII: dict[str, float] = {
    'H': 1.20, 'C': 1.70, 'N': 1.55, 'O': 1.52, 'F': 1.47,
    'P': 1.80, 'S': 1.80, 'CL': 1.75, 'BR': 1.85, 'I': 1.98,
    'ZN': 1.39, 'MG': 1.73, 'CA': 1.97, 'FE': 1.25, 'NA': 2.27,
    'K':  2.75, 'CU': 1.40, 'MN': 1.61, 'NI': 1.63, 'CO': 1.26,
}
DEFAULT_RADIUS = 1.70

# CPK colors as (R, G, B) in 0–255
CPK_COLORS: dict[str, tuple] = {
    'H':  (220, 220, 220), 'C':  (100, 100, 100), 'N':  ( 50,  50, 200),
    'O':  (200,  50,  50), 'S':  (200, 180,  50), 'P':  (200, 100,   0),
    'F':  ( 50, 200,  50), 'CL': ( 50, 200,  50), 'BR': (150,  50,   0),
    'I':  (100,   0, 150), 'ZN': (100, 120, 200), 'MG': ( 50, 200,  50),
    'CA': (100, 100, 220), 'FE': (200, 100,  30), 'NA': (160,   0, 200),
    'K':  (160,   0, 200), 'MN': (150,  80, 200), 'CU': (180, 100,  30),
}
DEFAULT_COLOR = (150, 150, 150)

TYPE_ORDER  = {'protein': 0, 'ligand': 1, 'metal': 2, 'water': 3, 'other': 4}
TYPE_COLORS = {
    'protein': '#5599ff', 'ligand': '#ff9944',
    'metal':   '#ffdd44', 'water':  '#aaddff', 'other': '#cccccc',
}


def _element_from_atom_name(name: str) -> str:
    """Infer element symbol from PDB atom name (columns 13-16)."""
    name = name.strip()
    # PDB stores element in cols 77-78; if not available, infer from name
    if not name:
        return 'C'
    # Remove leading digits (e.g. "1HG" → "HG")
    stripped = name.lstrip('0123456789')
    if not stripped:
        return 'C'
    # Return up to 2 chars, upper-cased
    return stripped[:2].upper()


@dataclass
class MolGroup:
    group_id:    str
    label:       str
    group_type:  str          # 'protein' | 'ligand' | 'metal' | 'water' | 'other'
    chain:       str = ""
    resnames:    set = field(default_factory=set)
    line_indices: list[int]         = field(default_factory=list)
    positions:   list[tuple]        = field(default_factory=list)   # (x, y, z)
    vdw_radii:   list[float]        = field(default_factory=list)
    cpk_colors:  list[tuple]        = field(default_factory=list)   # (R, G, B) 0-255

    def atom_count(self) -> int:
        return len(self.line_indices)

    def color(self) -> str:
        return TYPE_COLORS.get(self.group_type, '#cccccc')


def _parse_atom_line(line: str) -> tuple[tuple, float, tuple]:
    """Return (xyz, vdw_radius, cpk_color) from an ATOM/HETATM line."""
    try:
        x = float(line[30:38])
        y = float(line[38:46])
        z = float(line[46:54])
    except ValueError:
        x, y, z = 0.0, 0.0, 0.0

    # Element from column 77-78 (0-indexed: 76-78), fallback to atom name
    raw_element = line[76:78].strip() if len(line) > 76 else ''
    if not raw_element:
        raw_element = _element_from_atom_name(line[12:16] if len(line) > 15 else '')
    element = raw_element.upper()

    radius = VDW_RADII.get(element, DEFAULT_RADIUS)
    color  = CPK_COLORS.get(element, DEFAULT_COLOR)
    return (x, y, z), radius, color


def parse_groups(pdb_file: str) -> list[MolGroup]:
    """Parse a PDB file into selectable molecular groups."""
    groups: dict[str, MolGroup] = {}

    with open(pdb_file) as f:
        lines = f.readlines()

    for idx, line in enumerate(lines):
        rec = line[:6].strip()
        if rec not in ('ATOM', 'HETATM'):
            continue

        chain   = line[21].strip() if len(line) > 21 else ''
        resname = line[17:20].strip() if len(line) > 19 else ''
        xyz, radius, color = _parse_atom_line(line)

        if rec == 'ATOM':
            key = f'protein_{chain}'
            if key not in groups:
                groups[key] = MolGroup(
                    group_id=key,
                    label=f'Chain {chain} (protein)',
                    group_type='protein',
                    chain=chain,
                )
        else:
            if resname in WATER_RESNAMES:
                key = 'water'
                if key not in groups:
                    groups[key] = MolGroup(
                        group_id=key, label='Water (HOH)', group_type='water',
                    )
            elif resname in METAL_RESNAMES:
                key = f'metal_{resname}'
                if key not in groups:
                    groups[key] = MolGroup(
                        group_id=key, label=f'{resname} (metal ion)', group_type='metal',
                    )
            else:
                key = f'ligand_{resname}'
                if key not in groups:
                    groups[key] = MolGroup(
                        group_id=key, label=f'{resname} (ligand / cofactor)', group_type='ligand',
                    )

        g = groups[key]
        g.line_indices.append(idx)
        g.positions.append(xyz)
        g.vdw_radii.append(radius)
        g.cpk_colors.append(color)
        g.resnames.add(resname)

    return sorted(
        groups.values(),
        key=lambda g: (TYPE_ORDER.get(g.group_type, 5), g.label),
    )


def save_selected_groups(
    pdb_file: str,
    groups: list[MolGroup],
    selected_ids: set[str],
    output_path: str,
):
    """Write a cleaned PDB containing only selected groups.
    Non-coordinate records (HEADER, REMARK, SSBOND…) are always preserved."""
    with open(pdb_file) as f:
        all_lines = f.readlines()

    selected_indices: set[int] = set()
    for group in groups:
        if group.group_id in selected_ids:
            selected_indices.update(group.line_indices)

    with open(output_path, 'w') as out:
        for i, line in enumerate(all_lines):
            rec = line[:6].strip()
            if rec in ('ATOM', 'HETATM'):
                if i in selected_indices:
                    out.write(line)
            else:
                out.write(line)
        if not all_lines or not all_lines[-1].startswith('END'):
            out.write('END\n')
