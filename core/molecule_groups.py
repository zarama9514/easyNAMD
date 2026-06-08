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
    indices_by_code:  dict[str, list[int]] = field(default_factory=dict)
    serials_by_code:  dict[str, list[int]] = field(default_factory=dict)  # PDB atom serials
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
    chains:       set = field(default_factory=set)
    line_indices: list[int] = field(default_factory=list)

    def atom_count(self) -> int:
        return len(self.line_indices)

    def current_chain(self) -> str:
        """Single chain id if the group sits on one chain, else '' (mixed)."""
        return next(iter(self.chains)) if len(self.chains) == 1 else ''

    def color(self) -> str:
        return TYPE_COLORS.get(self.group_type, '#cccccc')

    def selection(self) -> dict:
        """3Dmol AtomSpec describing this group."""
        if self.group_type == 'protein':
            return {'chain': self.chain, 'hetflag': False}
        return {'resn': sorted(self.resnames)}


def find_chains(pdb_file: str) -> list[str]:
    """Return the distinct chain ids present in ATOM/HETATM records, in order."""
    chains: list[str] = []
    seen: set[str] = set()
    with open(pdb_file) as f:
        for line in f:
            if line[:6].strip() not in ('ATOM', 'HETATM'):
                continue
            chain = line[21].strip() if len(line) > 21 else ''
            if chain and chain not in seen:
                seen.add(chain)
                chains.append(chain)
    return chains


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
        if chain:
            g.chains.add(chain)

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

        try:
            serial = int(line[6:11])
        except ValueError:
            serial = -1

        if key not in residues:
            residues[key] = AltLocResidue(chain=chain, resid=resid, icode=icode, resname=resname)
        res = residues[key]
        if altloc not in res.codes:
            res.codes.append(altloc)
            res.indices_by_code[altloc] = []
            res.serials_by_code[altloc] = []
        res.indices_by_code[altloc].append(idx)
        res.serials_by_code[altloc].append(serial)

    result = list(residues.values())
    for res in result:
        res.codes.sort()
        res.choice = res.codes[0]   # default: keep the first (usually 'A')
    return result


def _atom_xyz(line: str):
    try:
        return (float(line[30:38]), float(line[38:46]), float(line[46:54]))
    except ValueError:
        return None


def build_focus_scene_pdb(pdb_file: str, residue: AltLocResidue,
                          radius: float = 5.0) -> tuple[str, list[tuple]]:
    """Build a self-contained PDB for the focus view: the residue's conformers
    plus every residue with an atom within `radius` of it. Everything lives in
    one model so 3Dmol re-derives all bonds by distance (peptide bonds to
    neighbours stay intact).

    Conformer atoms are moved onto private numeric chains ('0' = common/backbone,
    '1','2',… = each altLoc code); environment atoms keep their original chain.
    altLoc is blanked everywhere so no conformer is dropped.

    Returns (pdb_text, [(code, chain), …]) mapping each altLoc code to its chain.
    """
    key = residue.key()
    conf_chain = {code: str(i + 1) for i, code in enumerate(residue.codes)}

    # parse all coordinate atoms once
    atoms = []   # (line, key, altloc, xyz, is_residue)
    with open(pdb_file) as f:
        for line in f:
            if line[:6].strip() not in ('ATOM', 'HETATM'):
                continue
            xyz = _atom_xyz(line)
            if xyz is None:
                continue
            k = _altloc_key_from_line(line)
            altloc = line[16] if len(line) > 16 else ' '
            atoms.append((line, k, altloc, xyz, k == key))

    res_coords = [a[3] for a in atoms if a[4]]
    r2 = radius * radius

    # find environment residues (any atom within radius of the residue)
    env_keys = set()
    for line, k, altloc, (x, y, z), is_res in atoms:
        if is_res or k in env_keys:
            continue
        for rx, ry, rz in res_coords:
            dx, dy, dz = x - rx, y - ry, z - rz
            if dx * dx + dy * dy + dz * dz <= r2:
                env_keys.add(k)
                break

    out = []
    # residue conformers → private chains, altLoc blanked
    for line, k, altloc, xyz, is_res in atoms:
        if not is_res:
            continue
        ch = conf_chain[altloc] if altloc.strip() else '0'
        out.append(line[:16] + ' ' + line[17:21] + ch + line[22:])

    # environment → original chain, single conformer (blank/'A'), altLoc blanked
    for line, k, altloc, xyz, is_res in atoms:
        if is_res or k not in env_keys:
            continue
        if altloc.strip() and altloc != 'A':
            continue
        out.append(line[:16] + ' ' + line[17:])

    return ''.join(out), [(c, conf_chain[c]) for c in residue.codes]


def _altloc_key_from_line(line: str) -> tuple:
    chain = line[21].strip() if len(line) > 21 else ''
    resid = line[22:26].strip() if len(line) > 25 else ''
    icode = line[26].strip() if len(line) > 26 else ''
    return (chain, resid, icode)


def _set_serial(line: str, serial: int) -> str:
    """Write a sequential serial into columns 7-11."""
    return line[:6] + f'{serial:>5}' + line[11:]


def _set_chain(line: str, chain: str) -> str:
    """Write a chain id into column 22."""
    return line[:21] + (chain[:1] if chain else ' ') + line[22:]


def save_selected_groups(
    pdb_file: str,
    groups: list[MolGroup],
    selected_ids: set[str],
    output_path: str,
    altloc_choices: dict[tuple, str] | None = None,
    group_chains: dict[str, str] | None = None,
    renumber: bool = True,
):
    """Write a cleaned PDB containing only selected groups.

    - altLoc: keep only the chosen conformer, blank the column so it becomes the
      single (main) position.
    - group_chains: map group_id → chain id; every atom of that group is moved
      onto the given chain.
    - renumber: rewrite atom serials sequentially from 1.
    Non-coordinate records (HEADER, REMARK, SSBOND…) are always preserved."""
    altloc_choices = altloc_choices or {}
    group_chains   = group_chains or {}

    with open(pdb_file) as f:
        all_lines = f.readlines()

    selected_indices: set[int] = set()
    idx_to_chain: dict[int, str] = {}
    for group in groups:
        if group.group_id in selected_ids:
            selected_indices.update(group.line_indices)
            if group.group_id in group_chains:
                for idx in group.line_indices:
                    idx_to_chain[idx] = group_chains[group.group_id]

    serial = 0
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

            if i in idx_to_chain:
                line = _set_chain(line, idx_to_chain[i])

            if renumber:
                serial += 1
                line = _set_serial(line, serial)

            out.write(line)

        if not all_lines or not all_lines[-1].startswith('END'):
            out.write('END\n')


def write_group_pdb(pdb_file: str, group: MolGroup, output_path: str,
                    renumber: bool = True):
    """Write a PDB containing only one group's atoms, optionally renumbered from 1.
    Used as the source for ligand → mol2 conversion."""
    with open(pdb_file) as f:
        all_lines = f.readlines()

    wanted = set(group.line_indices)
    serial = 0
    with open(output_path, 'w') as out:
        for i in sorted(wanted):
            line = all_lines[i]
            altloc = line[16] if len(line) > 16 else ' '
            if altloc.strip():
                line = line[:16] + ' ' + line[17:]   # keep all, blank altLoc col
            if renumber:
                serial += 1
                line = _set_serial(line, serial)
            out.write(line)
        out.write('END\n')
