import os
from dataclasses import dataclass, field

from core.charmm import METAL_RESNAMES, PROTEIN_RESNAMES, WATER_RESNAMES
from core import pdb_fields as pdbf

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
        """Small structured selection descriptor for downstream viewers/tools."""
        if self.group_type == 'protein':
            return {'chain': self.chain, 'hetflag': False}
        return {'resn': sorted(self.resnames)}


def find_chains(pdb_file: str) -> list[str]:
    """Return the distinct chain ids present in ATOM/HETATM records, in order."""
    chains: list[str] = []
    seen: set[str] = set()
    with open(pdb_file) as f:
        for line in f:
            if not pdbf.is_atom_record(line):
                continue
            chain = pdbf.chain_id(line)
            if chain and chain not in seen:
                seen.add(chain)
                chains.append(chain)
    return chains


def find_models(pdb_file: str) -> list[int]:
    """Return the MODEL ids present in the PDB (empty if it has no MODEL records)."""
    models = []
    with open(pdb_file) as f:
        for line in f:
            if line[:6].strip() == 'MODEL':
                try:
                    models.append(int(line[10:14]))
                except ValueError:
                    models.append(len(models) + 1)
    return models


def _line_models(lines) -> list[int]:
    """Map each line index to its MODEL id (0 = outside any MODEL block)."""
    mapping = []
    cur = 0
    for line in lines:
        rec = pdbf.record_name(line)
        if rec == 'MODEL':
            try:
                cur = int(line[10:14])
            except ValueError:
                cur += 1
        mapping.append(cur)
        if rec == 'ENDMDL':
            cur = 0
    return mapping


def parse_groups(pdb_file: str, allowed_models: set | None = None) -> list[MolGroup]:
    """Parse a PDB file into selectable molecular groups.
    If `allowed_models` is given, only atoms in those MODEL ids are considered."""
    groups: dict[str, MolGroup] = {}
    group_residues: dict[str, set] = {}

    with open(pdb_file) as f:
        lines = f.readlines()

    line_model = _line_models(lines)

    for idx, line in enumerate(lines):
        rec = pdbf.record_name(line)
        if rec not in ('ATOM', 'HETATM'):
            continue
        if allowed_models is not None and line_model[idx] not in allowed_models:
            continue

        chain = pdbf.chain_id(line)
        resname = pdbf.resname(line)

        # Classify by residue name, not ATOM/HETATM record type — MD-frame PDBs
        # often write everything as ATOM, losing the HETATM distinction.
        # Anything that isn't protein or water is treated as a ligand.
        if resname in PROTEIN_RESNAMES:
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
        else:
            key = f'ligand_{resname}'
            if key not in groups:
                groups[key] = MolGroup(
                    group_id=key, label=f'{resname} (ligand)', group_type='ligand')

        g = groups[key]
        g.line_indices.append(idx)
        g.resnames.add(resname)
        if chain:
            g.chains.add(chain)
        group_residues.setdefault(key, set()).add((pdbf.resid(line), pdbf.icode(line)))

    # A "protein" chain with a single residue is almost certainly a cap or a
    # ligand, not a protein — reclassify it as a ligand.
    for key, g in groups.items():
        if g.group_type == 'protein' and len(group_residues.get(key, ())) <= 1:
            g.group_type = 'ligand'
            resn = next(iter(g.resnames), '')
            g.label = f'{resn} (ligand)'

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
        rec = pdbf.record_name(line)
        if rec not in ('ATOM', 'HETATM'):
            continue
        altloc = pdbf.altloc(line)
        if not altloc.strip():
            continue

        chain = pdbf.chain_id(line)
        resid = pdbf.resid(line)
        icode = pdbf.icode(line)
        resname = pdbf.resname(line)
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
    return pdbf.xyz(line)


def build_focus_scene_pdb(pdb_file: str, residue: AltLocResidue,
                          radius: float = 5.0) -> tuple[str, list[tuple]]:
    """Build a compact PDB with altLoc conformers and nearby context.

    Each conformer is moved onto a private numeric chain ('1','2',...), and
    atoms without an altLoc are copied into every conformer. AltLoc is blanked so
    VMD does not drop conformers. Nearby residues are included once to preserve
    visual context without loading the whole structure.

    Returns (pdb_text, [(code, chain), …]) mapping each altLoc code to its chain.
    """
    key = residue.key()
    conf_chain = {code: str(i + 1) for i, code in enumerate(residue.codes)}

    atoms = []
    residue_atoms = []
    with open(pdb_file) as f:
        for line in f:
            if not pdbf.is_atom_record(line):
                continue
            xyz = _atom_xyz(line)
            if xyz is None:
                continue
            k = _altloc_key_from_line(line)
            altloc = pdbf.altloc(line)
            atoms.append((line, k, altloc, xyz))
            if k == key:
                residue_atoms.append((line, altloc, xyz))

    res_coords = [xyz for _, _, xyz in residue_atoms]
    r2 = radius * radius
    env_keys = set()
    for _line, k, altloc, (x, y, z) in atoms:
        if k == key or k in env_keys:
            continue
        for rx, ry, rz in res_coords:
            dx, dy, dz = x - rx, y - ry, z - rz
            if dx * dx + dy * dy + dz * dz <= r2:
                env_keys.add(k)
                break

    out = []
    for code, chain in conf_chain.items():
        for line, altloc, _xyz in residue_atoms:
            if altloc.strip() and altloc != code:
                continue
            out.append(line[:16] + ' ' + line[17:21] + chain + line[22:])

    for line, k, altloc, _xyz in atoms:
        if k not in env_keys:
            continue
        if altloc.strip() and altloc != residue.codes[0]:
            continue
        out.append(line[:16] + ' ' + line[17:])

    return _renumber_pdb_atoms(out), [(c, conf_chain[c]) for c in residue.codes]


def build_residue_focus_scene_pdb(pdb_file: str, chain: str, resid: str,
                                  radius: float = 5.0) -> str:
    """Build a small PDB containing a residue and nearby context."""
    target_key = None
    atoms = []
    with open(pdb_file) as f:
        for line in f:
            if not pdbf.is_atom_record(line):
                continue
            xyz = _atom_xyz(line)
            if xyz is None:
                continue
            k = _altloc_key_from_line(line)
            altloc = pdbf.altloc(line)
            if altloc.strip() and altloc != 'A':
                continue
            atoms.append((line[:16] + ' ' + line[17:], k, xyz))
            if k[0] == chain and k[1] == resid:
                target_key = k

    if target_key is None:
        return ""

    target_coords = [xyz for _line, k, xyz in atoms if k == target_key]
    r2 = radius * radius
    keep_keys = {target_key}
    for _line, k, (x, y, z) in atoms:
        if k in keep_keys:
            continue
        for rx, ry, rz in target_coords:
            dx, dy, dz = x - rx, y - ry, z - rz
            if dx * dx + dy * dy + dz * dz <= r2:
                keep_keys.add(k)
                break

    return _renumber_pdb_atoms([line for line, k, _xyz in atoms if k in keep_keys])


def _altloc_key_from_line(line: str) -> tuple:
    return (pdbf.chain_id(line), pdbf.resid(line), pdbf.icode(line))


def _set_serial(line: str, serial: int) -> str:
    """Write a sequential serial into columns 7-11."""
    return pdbf.set_serial(line, serial)


def _renumber_pdb_atoms(lines: list[str]) -> str:
    out = []
    for serial, line in enumerate(lines, start=1):
        out.append(_set_serial(line, serial))
    if out and not out[-1].endswith('\n'):
        out[-1] += '\n'
    out.append('END\n')
    return ''.join(out)


def _set_chain(line: str, chain: str) -> str:
    """Write a chain id into column 22."""
    return pdbf.set_chain(line, chain)


def save_selected_groups(
    pdb_file: str,
    groups: list[MolGroup],
    selected_ids: set[str],
    output_path: str,
    altloc_choices: dict[tuple, str] | None = None,
    group_chains: dict[str, str] | None = None,
    renumber: bool = True,
    allowed_models: set | None = None,
):
    """Write a cleaned PDB containing only selected groups.

    - altLoc: keep only the chosen conformer, blank the column so it becomes the
      single (main) position.
    - group_chains: map group_id → chain id; every atom of that group is moved
      onto the given chain.
    - renumber: rewrite atom serials sequentially from 1.
    - allowed_models: keep only atoms from these MODEL ids (kept models are
      merged into one — MODEL/ENDMDL records are dropped from the output).
    Non-coordinate records (HEADER, REMARK, SSBOND…) are preserved."""
    altloc_choices = altloc_choices or {}
    group_chains   = group_chains or {}

    with open(pdb_file) as f:
        all_lines = f.readlines()

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    line_model = _line_models(all_lines)
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
            rec = pdbf.record_name(line)
            if rec in ('MODEL', 'ENDMDL', 'NUMMDL'):
                continue   # collapse to a single model
            if rec not in ('ATOM', 'HETATM'):
                out.write(line)
                continue
            if i not in selected_indices:
                continue
            if allowed_models is not None and line_model[i] not in allowed_models:
                continue

            altloc = pdbf.altloc(line)
            if altloc.strip():
                chosen = altloc_choices.get(_altloc_key_from_line(line))
                if chosen is not None and altloc != chosen:
                    continue   # drop the non-chosen conformer
                line = pdbf.blank_altloc(line)

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
            altloc = pdbf.altloc(line)
            if altloc.strip():
                line = pdbf.blank_altloc(line)
            if renumber:
                serial += 1
                line = _set_serial(line, serial)
            out.write(line)
        out.write('END\n')
