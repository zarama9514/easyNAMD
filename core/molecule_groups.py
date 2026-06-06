from dataclasses import dataclass, field

WATER_RESNAMES = frozenset({'HOH', 'WAT', 'TIP3', 'SOL', 'H2O', 'TIP'})

METAL_RESNAMES = frozenset({
    'ZN', 'MG', 'CA', 'FE', 'MN', 'NA', 'K', 'CU', 'NI', 'CO',
    'HG', 'CD', 'PB', 'PT', 'AU', 'AG', 'SR', 'BA', 'CS', 'RB',
    'LI', 'BE', 'AL', 'CR', 'FE2', 'FE3', 'CU1', 'IOD', 'CLA',
    'POT', 'SOD', 'CAL', 'MN3',
})

TYPE_ORDER  = {'protein': 0, 'ligand': 1, 'metal': 2, 'water': 3, 'other': 4}
TYPE_COLORS = {
    'protein': '#5599ff', 'ligand': '#ff9944',
    'metal':   '#ffdd44', 'water':  '#aaddff', 'other': '#cccccc',
}


@dataclass
class AltLocResidue:
    chain:        str
    resid:        str
    icode:        str
    resname:      str
    codes:        list[str]               = field(default_factory=list)   # e.g. ['A', 'B']
    indices_by_code: dict[str, list[int]] = field(default_factory=dict)
    choice:       str                     = ""   # which code to keep

    def key(self) -> tuple:
        return (self.chain, self.resid, self.icode)

    def label(self) -> str:
        return f"{self.chain}:{self.resname}{self.resid}  (alt {'/'.join(self.codes)})"


@dataclass
class MolGroup:
    group_id:     str
    label:        str
    group_type:   str          # 'protein' | 'ligand' | 'metal' | 'water' | 'other'
    chain:        str = ""
    resnames:     set = field(default_factory=set)
    line_indices: list[int] = field(default_factory=list)

    def atom_count(self) -> int:
        return len(self.line_indices)

    def color(self) -> str:
        return TYPE_COLORS.get(self.group_type, '#cccccc')

    def selection(self) -> dict:
        """3Dmol AtomSpec describing this group."""
        if self.group_type == 'protein':
            return {'chain': self.chain, 'hetflag': False}
        return {'resn': sorted(self.resnames)}


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

        if rec == 'ATOM':
            key = f'protein_{chain}'
            if key not in groups:
                groups[key] = MolGroup(
                    group_id=key, label=f'Chain {chain} (protein)',
                    group_type='protein', chain=chain,
                )
        elif resname in WATER_RESNAMES:
            key = 'water'
            if key not in groups:
                groups[key] = MolGroup(
                    group_id=key, label='Water (HOH)', group_type='water')
        elif resname in METAL_RESNAMES:
            key = f'metal_{resname}'
            if key not in groups:
                groups[key] = MolGroup(
                    group_id=key, label=f'{resname} (metal ion)', group_type='metal')
        else:
            key = f'ligand_{resname}'
            if key not in groups:
                groups[key] = MolGroup(
                    group_id=key, label=f'{resname} (ligand / cofactor)', group_type='ligand')

        g = groups[key]
        g.line_indices.append(idx)
        g.resnames.add(resname)

    return sorted(
        groups.values(),
        key=lambda g: (TYPE_ORDER.get(g.group_type, 5), g.label),
    )


def find_altlocs(pdb_file: str) -> list[AltLocResidue]:
    """Find residues that have alternative location indicators (altLoc, col 17)."""
    residues: dict[tuple, AltLocResidue] = {}

    with open(pdb_file) as f:
        lines = f.readlines()

    for idx, line in enumerate(lines):
        rec = line[:6].strip()
        if rec not in ('ATOM', 'HETATM'):
            continue
        altloc = line[16] if len(line) > 16 else ' '
        if not altloc.strip():
            continue

        chain   = line[21].strip() if len(line) > 21 else ''
        resid   = line[22:26].strip() if len(line) > 25 else ''
        icode   = line[26].strip() if len(line) > 26 else ''
        resname = line[17:20].strip() if len(line) > 19 else ''
        key = (chain, resid, icode)

        if key not in residues:
            residues[key] = AltLocResidue(chain=chain, resid=resid, icode=icode, resname=resname)
        res = residues[key]
        if altloc not in res.codes:
            res.codes.append(altloc)
            res.indices_by_code[altloc] = []
        res.indices_by_code[altloc].append(idx)

    result = list(residues.values())
    for res in result:
        res.codes.sort()
        res.choice = res.codes[0]   # default: keep the first (usually 'A')
    return result


def _altloc_key_from_line(line: str) -> tuple:
    chain = line[21].strip() if len(line) > 21 else ''
    resid = line[22:26].strip() if len(line) > 25 else ''
    icode = line[26].strip() if len(line) > 26 else ''
    return (chain, resid, icode)


def save_selected_groups(
    pdb_file: str,
    groups: list[MolGroup],
    selected_ids: set[str],
    output_path: str,
    altloc_choices: dict[tuple, str] | None = None,
):
    """Write a cleaned PDB containing only selected groups.

    For atoms carrying an altLoc indicator, keep only the chosen conformer and
    blank the altLoc column so it becomes the single (main) position.
    Non-coordinate records (HEADER, REMARK, SSBOND…) are always preserved."""
    altloc_choices = altloc_choices or {}

    with open(pdb_file) as f:
        all_lines = f.readlines()

    selected_indices: set[int] = set()
    for group in groups:
        if group.group_id in selected_ids:
            selected_indices.update(group.line_indices)

    with open(output_path, 'w') as out:
        for i, line in enumerate(all_lines):
            rec = line[:6].strip()
            if rec not in ('ATOM', 'HETATM'):
                out.write(line)
                continue
            if i not in selected_indices:
                continue

            altloc = line[16] if len(line) > 16 else ' '
            if altloc.strip():
                chosen = altloc_choices.get(_altloc_key_from_line(line))
                if chosen is not None and altloc != chosen:
                    continue   # drop the non-chosen conformer
                line = line[:16] + ' ' + line[17:]   # blank the altLoc column

            out.write(line)

        if not all_lines or not all_lines[-1].startswith('END'):
            out.write('END\n')
