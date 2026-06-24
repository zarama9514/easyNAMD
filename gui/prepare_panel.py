import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.molecule_groups import (
    AltLocResidue, MolGroup, build_focus_scene_pdb, find_altlocs, find_models,
    parse_groups, save_selected_groups, write_group_pdb,
)
from core.mol2 import pdb_to_mol2
from core.naming import stem as file_stem, structure_dir
from core.vmd_viewer import VMDViewerController
from gui.scrolling import XYScrollableFrame

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))

TYPE_ICONS = {
    'protein': '🔵', 'ligand': '🟠', 'metal': '🟡', 'water': '🩵', 'other': '⚪',
}


class GroupRow(ctk.CTkFrame):
    """One row: [checkbox] [icon + label] [count] [chain rename | →mol2]."""

    def __init__(self, parent, group: MolGroup, on_toggle, on_mol2):
        super().__init__(parent, fg_color='transparent', height=1)
        self.group = group
        self.enabled_var = tk.BooleanVar(value=group.group_type != 'water')

        icon = TYPE_ICONS.get(group.group_type, '⚪')
        ctk.CTkCheckBox(self, variable=self.enabled_var, text='', width=24,
                        command=on_toggle).pack(side='left', padx=(4, 0))
        ctk.CTkLabel(self, text=f'{icon}  {group.label}', anchor='w', width=210).pack(side='left', padx=6)
        ctk.CTkLabel(self, text=f'{group.atom_count()} atoms', anchor='e',
                     text_color='gray', width=70).pack(side='left')

        ctk.CTkLabel(self, text='chain:', text_color='gray').pack(side='left', padx=(8, 2))
        self.chain_var = tk.StringVar(value=group.current_chain())
        ctk.CTkEntry(self, textvariable=self.chain_var, width=40).pack(side='left')

        if group.group_type == 'ligand':
            ctk.CTkButton(self, text='→ mol2', width=70, command=on_mol2).pack(side='left', padx=8)

    def is_selected(self) -> bool:
        return self.enabled_var.get()

    def chain_value(self) -> str:
        return self.chain_var.get().strip()


class AltLocRow(ctk.CTkFrame):
    """One row: [label] [choice dropdown] [View 3D]."""

    def __init__(self, parent, residue: AltLocResidue, on_view):
        super().__init__(parent, fg_color='transparent', height=1)
        self.residue = residue
        self.choice_var = tk.StringVar(value=residue.choice)

        ctk.CTkLabel(self, text=residue.label(), anchor='w', width=250).pack(side='left', padx=6)
        ctk.CTkLabel(self, text='keep:', text_color='gray').pack(side='left')
        ctk.CTkOptionMenu(self, variable=self.choice_var,
                          values=residue.codes, width=70).pack(side='left', padx=6)
        ctk.CTkButton(self, text='View 3D', width=80, command=on_view).pack(side='left', padx=6)

    def choice(self) -> str:
        return self.choice_var.get()


class PreparePanel(ctk.CTkFrame):
    def __init__(self, parent, config: dict, vmd_viewer: VMDViewerController, on_saved=None):
        super().__init__(parent)
        self.config = config
        self.vmd_viewer = vmd_viewer
        self._on_saved = on_saved          # called with the cleaned PDB path
        self._pdb_file:  str | None     = None
        self._groups:    list[MolGroup] = []
        self._rows:      list[GroupRow] = []
        self._altlocs:   list[AltLocResidue] = []
        self._altloc_rows: list[AltLocRow]   = []

        self._models: list[int] = []
        self._model_vars: dict[int, tk.BooleanVar] = {}

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  Layout                                                              #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        top = ctk.CTkFrame(self)
        top.pack(fill='x', padx=10, pady=8)
        top.columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text='PDB file:').pack(side='left', padx=(6, 4))
        self._pdb_var = tk.StringVar()
        ctk.CTkEntry(top, textvariable=self._pdb_var, width=520).pack(side='left', fill='x', expand=True, padx=4)
        ctk.CTkButton(top, text='Browse', width=80, command=self._browse_pdb).pack(side='left', padx=4)

        body = ctk.CTkFrame(self)
        body.pack(fill='both', expand=True, padx=10, pady=(0, 4))

        # ── Left column: molecular groups ─────────────────────────────── #
        left = ctk.CTkFrame(body, fg_color='transparent')
        left.pack(side='left', fill='both', expand=True)

        ctk.CTkLabel(left, text='Molecular groups',
                     font=ctk.CTkFont(weight='bold')).pack(anchor='w', padx=8, pady=(6, 2))
        list_scroll = XYScrollableFrame(left)
        list_scroll.pack(fill='both', expand=True, padx=4, pady=4)
        self._list_frame = list_scroll.content
        ctk.CTkLabel(self._list_frame, text='Load a PDB file to see groups',
                     text_color='gray').pack(anchor='w', padx=8, pady=8)
        self._show_3d_button = ctk.CTkButton(left, text='Show in 3D', command=self._show_in_3d)

        # ── Right column: models + alternative locations ──────────────── #
        right = ctk.CTkFrame(body, width=430)
        right.pack(side='right', fill='y', padx=(8, 0))
        right.pack_propagate(False)

        ctk.CTkLabel(right, text='Models',
                     font=ctk.CTkFont(weight='bold')).pack(anchor='w', padx=8, pady=(8, 0))
        ctk.CTkLabel(right, text='tick to keep; keeping several merges them into one system',
                     text_color='gray', font=ctk.CTkFont(size=11)).pack(anchor='w', padx=8)
        self._models_frame = ctk.CTkFrame(right, fg_color='transparent', height=1)
        self._models_frame.pack(fill='x', padx=4, pady=2)
        ctk.CTkLabel(self._models_frame, text='single model',
                     text_color='gray').pack(anchor='w', padx=8)

        alt_header = ctk.CTkFrame(right, fg_color='transparent')
        alt_header.pack(fill='x', padx=8, pady=(10, 2))
        ctk.CTkLabel(alt_header, text='Alternative locations',
                     font=ctk.CTkFont(weight='bold')).pack(anchor='w')
        alt_ctrl = ctk.CTkFrame(right, fg_color='transparent')
        alt_ctrl.pack(fill='x', padx=8, pady=(0, 2))
        ctk.CTkLabel(alt_ctrl, text='default keep:', text_color='gray').pack(side='left')
        self._altloc_default = tk.StringVar(value='A')
        ctk.CTkOptionMenu(alt_ctrl, variable=self._altloc_default,
                          values=['A', 'B', 'C', 'D'], width=60).pack(side='left', padx=6)
        ctk.CTkButton(alt_ctrl, text='Apply to all', width=90,
                      command=self._apply_default_altloc).pack(side='left')

        altloc_scroll = XYScrollableFrame(right)
        altloc_scroll.pack(fill='both', expand=True, padx=4, pady=4)
        self._altloc_frame = altloc_scroll.content
        ctk.CTkLabel(self._altloc_frame, text='Load a PDB file to detect altLocs',
                     text_color='gray').pack(anchor='w', padx=8, pady=4)

        bottom = ctk.CTkFrame(self)
        bottom.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(bottom, text='Save to:').pack(side='left', padx=(6, 4))
        self._outpath_var = tk.StringVar()
        ctk.CTkEntry(bottom, textvariable=self._outpath_var, width=520).pack(side='left', fill='x', expand=True, padx=4)
        ctk.CTkButton(bottom, text='Browse', width=80, command=self._browse_output).pack(side='left', padx=4)
        ctk.CTkButton(bottom, text='Save cleaned PDB', fg_color='green',
                      command=self._save).pack(side='left', padx=12)

    # ------------------------------------------------------------------ #
    #  Group list                                                          #
    # ------------------------------------------------------------------ #

    def _populate_list(self):
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._rows.clear()

        if not self._groups:
            ctk.CTkLabel(self._list_frame, text='No ATOM/HETATM records found',
                         text_color='gray').pack(anchor='w', padx=8)
            return

        for group in self._groups:
            row = GroupRow(self._list_frame, group,
                           on_toggle=self._on_group_toggle,
                           on_mol2=lambda g=group: self._export_mol2(g))
            row.pack(fill='x', pady=2, padx=4)
            self._rows.append(row)

    def _selected_ids(self) -> set[str]:
        return {r.group.group_id for r in self._rows if r.is_selected()}

    def _group_chains(self) -> dict[str, str]:
        """group_id → chain id, for groups whose chain field differs from current."""
        result = {}
        for r in self._rows:
            new = r.chain_value()
            if new and new != r.group.current_chain():
                result[r.group.group_id] = new
        return result

    def _export_mol2(self, group: MolGroup):
        if not self._pdb_file:
            messagebox.showerror('Error', 'Load a PDB file first.')
            return
        out = filedialog.asksaveasfilename(
            defaultextension='.mol2',
            initialfile=f'{group.label.split()[0]}.mol2',
            filetypes=[('mol2 files', '*.mol2'), ('All files', '*.*')])
        if not out:
            return
        tmp_pdb = out + '.tmp.pdb'
        write_group_pdb(self._pdb_file, group, tmp_pdb, renumber=True)
        ok, msg = pdb_to_mol2(tmp_pdb, out)
        try:
            os.remove(tmp_pdb)
        except OSError:
            pass
        if ok:
            messagebox.showinfo('Saved', f'Ligand mol2 saved to:\n{out}')
        else:
            messagebox.showerror('mol2 failed', msg)

    def _on_group_toggle(self):
        """Refresh the open VMD scene after a group checkbox changes."""
        if not self._pdb_file or not self.vmd_viewer.is_open():
            return
        try:
            self.vmd_viewer.show_groups(self._vmd_path(), self._pdb_file, self._groups, self._selected_ids())
        except Exception as exc:
            messagebox.showerror('VMD viewer', str(exc))

    # ------------------------------------------------------------------ #
    #  Alternative locations                                               #
    # ------------------------------------------------------------------ #

    def _populate_altlocs(self):
        for w in self._altloc_frame.winfo_children():
            w.destroy()
        self._altloc_rows.clear()

        if not self._altlocs:
            ctk.CTkLabel(self._altloc_frame, text='No alternative locations found',
                         text_color='gray').pack(anchor='w', padx=8, pady=4)
            return

        for res in self._altlocs:
            row = AltLocRow(self._altloc_frame, res,
                            on_view=lambda r=res: self._view_altloc(r))
            row.pack(fill='x', pady=2, padx=4)
            self._altloc_rows.append(row)

    def _apply_default_altloc(self):
        code = self._altloc_default.get()
        for row in self._altloc_rows:
            if code in row.residue.codes:
                row.choice_var.set(code)

    def _altloc_choices(self) -> dict[tuple, str]:
        return {row.residue.key(): row.choice() for row in self._altloc_rows}

    def _view_altloc(self, residue: AltLocResidue):
        """Open VMD focused on a residue's altLoc conformers."""
        if not self._pdb_file:
            messagebox.showerror('Error', 'Load a PDB file first.')
            return
        focus_pdb, conf_map = build_focus_scene_pdb(self._pdb_file, residue)
        title = f"{residue.chain}:{residue.resname}{residue.resid} alt {'/'.join(residue.codes)}"
        try:
            self.vmd_viewer.show_altloc_focus(self._vmd_path(), focus_pdb, title, residue.codes)
        except Exception as exc:
            messagebox.showerror('VMD viewer', str(exc))

    # ------------------------------------------------------------------ #
    #  VMD view                                                            #
    # ------------------------------------------------------------------ #

    def _show_in_3d(self):
        if not self._pdb_file:
            messagebox.showerror('Error', 'Load a PDB file first.')
            return
        try:
            self.vmd_viewer.show_groups(self._vmd_path(), self._pdb_file, self._groups, self._selected_ids())
        except Exception as exc:
            messagebox.showerror('VMD viewer', str(exc))

    def _vmd_path(self) -> str:
        return self.config.get('vmd_path', '').strip()

    # ------------------------------------------------------------------ #
    #  File helpers                                                        #
    # ------------------------------------------------------------------ #

    def _browse_pdb(self):
        path = filedialog.askopenfilename(
            filetypes=[('PDB files', '*.pdb'), ('All files', '*.*')])
        if not path:
            return
        self._pdb_file = path
        self._pdb_var.set(path)
        # output goes into <input dir>/<root>/<stem>_clean.pdb
        self._outpath_var.set(os.path.join(structure_dir(path),
                                           file_stem(path) + '_clean.pdb'))
        self._models = find_models(path)
        self._populate_models()
        self._reparse()

    def _reparse(self):
        """(Re)parse groups/altlocs respecting the current model selection."""
        allowed = self._selected_models()
        self._groups = parse_groups(self._pdb_file, allowed_models=allowed)
        self._altlocs = find_altlocs(self._pdb_file)
        self._populate_list()
        self._populate_altlocs()
        if self._pdb_file:
            self._show_3d_button.pack(pady=6)

    def _populate_models(self):
        for w in self._models_frame.winfo_children():
            w.destroy()
        self._model_vars.clear()
        if len(self._models) <= 1:
            ctk.CTkLabel(self._models_frame, text='single model',
                         text_color='gray').pack(anchor='w', padx=8)
            return
        for m in self._models:
            var = tk.BooleanVar(value=True)   # keep all by default (= aggregate)
            ctk.CTkCheckBox(self._models_frame, text=f'Model {m}', variable=var,
                            command=self._reparse).pack(anchor='w', padx=8, pady=1)
            self._model_vars[m] = var

    def _selected_models(self) -> set | None:
        if not self._model_vars:
            return None
        return {m for m, v in self._model_vars.items() if v.get()}

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.pdb',
            filetypes=[('PDB files', '*.pdb'), ('All files', '*.*')])
        if path:
            self._outpath_var.set(path)

    def _save(self):
        if not self._pdb_file:
            messagebox.showerror('Error', 'Load a PDB file first.')
            return
        outpath = self._outpath_var.get().strip()
        if not outpath:
            messagebox.showerror('Error', 'Specify an output path.')
            return
        selected = self._selected_ids()
        if not selected:
            messagebox.showerror('Error', 'No groups selected.')
            return

        save_selected_groups(self._pdb_file, self._groups, selected, outpath,
                             altloc_choices=self._altloc_choices(),
                             group_chains=self._group_chains(),
                             renumber=True,
                             allowed_models=self._selected_models())

        if self._on_saved and messagebox.askyesno(
                'Saved', f'Cleaned PDB saved to:\n{outpath}\n\nUse it in the Build tab?'):
            self._on_saved(outpath)
        else:
            messagebox.showinfo('Saved', f'Cleaned PDB saved to:\n{outpath}')
