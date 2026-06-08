import json
import os
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.molecule_groups import (
    AltLocResidue, MolGroup, build_focus_scene_pdb, find_altlocs,
    parse_groups, save_selected_groups, write_group_pdb,
)
from core.mol2 import pdb_to_mol2
from core.viewer_html import build_viewer_html

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))

TYPE_ICONS = {
    'protein': '🔵', 'ligand': '🟠', 'metal': '🟡', 'water': '🩵', 'other': '⚪',
}


class GroupRow(ctk.CTkFrame):
    """One row: [checkbox] [icon + label] [count] [chain rename | →mol2]."""

    def __init__(self, parent, group: MolGroup, on_toggle, on_mol2):
        super().__init__(parent, fg_color='transparent')
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
        super().__init__(parent, fg_color='transparent')
        self.residue = residue
        self.choice_var = tk.StringVar(value=residue.choice)

        ctk.CTkLabel(self, text=residue.label(), anchor='w', width=220).pack(side='left', padx=6)
        ctk.CTkLabel(self, text='keep:', text_color='gray').pack(side='left')
        ctk.CTkOptionMenu(self, variable=self.choice_var,
                          values=residue.codes, width=70).pack(side='left', padx=6)
        ctk.CTkButton(self, text='View 3D', width=80, command=on_view).pack(side='left', padx=6)

    def choice(self) -> str:
        return self.choice_var.get()


class PreparePanel(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self._pdb_file:  str | None     = None
        self._groups:    list[MolGroup] = []
        self._rows:      list[GroupRow] = []
        self._altlocs:   list[AltLocResidue] = []
        self._altloc_rows: list[AltLocRow]   = []

        # one persistent 3D window per session
        self._viewer_proc:    subprocess.Popen | None = None
        self._tmp_dir:        str | None = None
        self._selection_file: str | None = None
        self._command_file:   str | None = None
        self._cmd_counter:    int = 0

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  Layout                                                              #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        top = ctk.CTkFrame(self)
        top.pack(fill='x', padx=10, pady=8)
        ctk.CTkLabel(top, text='PDB file:').pack(side='left', padx=(6, 4))
        self._pdb_var = tk.StringVar()
        ctk.CTkEntry(top, textvariable=self._pdb_var, width=420).pack(side='left', padx=4)
        ctk.CTkButton(top, text='Browse', width=80, command=self._browse_pdb).pack(side='left', padx=4)

        body = ctk.CTkFrame(self)
        body.pack(fill='both', expand=True, padx=10, pady=(0, 4))

        # ── Left column: molecular groups ─────────────────────────────── #
        left = ctk.CTkFrame(body, fg_color='transparent')
        left.pack(side='left', fill='both', expand=True)

        ctk.CTkLabel(left, text='Molecular groups',
                     font=ctk.CTkFont(weight='bold')).pack(anchor='w', padx=8, pady=(6, 2))
        self._list_frame = ctk.CTkScrollableFrame(left)
        self._list_frame.pack(fill='both', expand=True, padx=4, pady=4)
        ctk.CTkLabel(self._list_frame, text='Load a PDB file to see groups',
                     text_color='gray').pack(anchor='w', padx=8, pady=8)
        ctk.CTkButton(left, text='Show in 3D', command=self._show_in_3d).pack(pady=6)

        # ── Right column: alternative locations ───────────────────────── #
        right = ctk.CTkFrame(body, width=280)
        right.pack(side='right', fill='y', padx=(8, 0))
        right.pack_propagate(False)

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

        self._altloc_frame = ctk.CTkScrollableFrame(right)
        self._altloc_frame.pack(fill='both', expand=True, padx=4, pady=4)
        ctk.CTkLabel(self._altloc_frame, text='Load a PDB file to detect altLocs',
                     text_color='gray').pack(anchor='w', padx=8, pady=4)

        bottom = ctk.CTkFrame(self)
        bottom.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(bottom, text='Save to:').pack(side='left', padx=(6, 4))
        self._outpath_var = tk.StringVar()
        ctk.CTkEntry(bottom, textvariable=self._outpath_var, width=340).pack(side='left', padx=4)
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
        """Live-update the open 3D window when a group checkbox changes."""
        if self._is_window_open():
            self._send_js(f'showGroups({json.dumps(sorted(self._selected_ids()))})')

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
        """Focus a residue's altLoc conformers inside the (single) 3D window."""
        if not self._ensure_window():
            return
        focus_pdb, conf_map = build_focus_scene_pdb(self._pdb_file, residue)
        conf_chains = [chain for _code, chain in conf_map]
        self._send_js(
            f'focusAltloc({json.dumps(residue.chain)}, {int(residue.resid)}, '
            f'{json.dumps(focus_pdb)}, {json.dumps(conf_chains)}, '
            f'{json.dumps(residue.codes)})'
        )

    # ------------------------------------------------------------------ #
    #  Persistent 3D window                                                #
    # ------------------------------------------------------------------ #

    def _is_window_open(self) -> bool:
        return self._viewer_proc is not None and self._viewer_proc.poll() is None

    def _ensure_window(self) -> bool:
        """Open the 3D window if it isn't already. Returns True on success."""
        if not self._pdb_file:
            messagebox.showerror('Error', 'Load a PDB file first.')
            return False
        if self._is_window_open():
            return True

        self._tmp_dir = tempfile.mkdtemp(prefix='easynamd_')
        html_path            = os.path.join(self._tmp_dir, 'viewer.html')
        self._selection_file = os.path.join(self._tmp_dir, 'selection.json')
        self._command_file   = os.path.join(self._tmp_dir, 'command.json')
        self._cmd_counter    = 0

        build_viewer_html(self._pdb_file, self._groups, self._selected_ids(),
                          self._altlocs, html_path)

        self._viewer_proc = subprocess.Popen(
            [sys.executable, '-m', 'gui.webview_window',
             html_path, self._selection_file, self._command_file],
            cwd=ROOT_DIR,
        )
        self._poll_viewer()
        return True

    def _send_js(self, js: str):
        """Queue a JS snippet for the watcher thread in the 3D window."""
        if not self._command_file:
            return
        self._cmd_counter += 1
        payload = {'n': self._cmd_counter, 'js': js}
        with open(self._command_file, 'w') as f:
            json.dump(payload, f)

    def _show_in_3d(self):
        if self._ensure_window():
            self._send_js(f'showGroups({json.dumps(sorted(self._selected_ids()))})')

    def _poll_viewer(self):
        """When the window closes, sync the selection back into the checkboxes."""
        if self._viewer_proc is None:
            return
        if self._viewer_proc.poll() is None:
            self.after(500, self._poll_viewer)
            return

        # Window closed — read back selection if present, then reset session
        if self._selection_file and os.path.isfile(self._selection_file):
            try:
                with open(self._selection_file) as f:
                    self._apply_selection(set(json.load(f)))
            except (json.JSONDecodeError, OSError):
                pass

        self._viewer_proc    = None
        self._command_file   = None
        self._selection_file = None
        self._tmp_dir        = None

    def _apply_selection(self, ids: set[str]):
        for row in self._rows:
            row.enabled_var.set(row.group.group_id in ids)

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
        base, _ = os.path.splitext(path)
        self._outpath_var.set(base + '_clean.pdb')
        self._groups = parse_groups(path)
        self._altlocs = find_altlocs(path)
        self._populate_list()
        self._populate_altlocs()

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
                             renumber=True)
        messagebox.showinfo('Saved', f'Cleaned PDB saved to:\n{outpath}')
