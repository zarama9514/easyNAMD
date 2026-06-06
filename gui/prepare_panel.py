import json
import os
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.molecule_groups import (
    AltLocResidue, MolGroup, find_altlocs, parse_groups, save_selected_groups,
)
from core.viewer_html import build_altloc_html, build_html

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))

TYPE_ICONS = {
    'protein': '🔵', 'ligand': '🟠', 'metal': '🟡', 'water': '🩵', 'other': '⚪',
}


class GroupRow(ctk.CTkFrame):
    """One row: [checkbox] [icon + label] [atom count]."""

    def __init__(self, parent, group: MolGroup):
        super().__init__(parent, fg_color='transparent')
        self.group = group
        self.enabled_var = tk.BooleanVar(value=group.group_type != 'water')

        icon = TYPE_ICONS.get(group.group_type, '⚪')
        ctk.CTkCheckBox(self, variable=self.enabled_var, text='', width=24).pack(side='left', padx=(4, 0))
        ctk.CTkLabel(self, text=f'{icon}  {group.label}', anchor='w', width=240).pack(side='left', padx=6)
        ctk.CTkLabel(self, text=f'{group.atom_count()} atoms', anchor='e',
                     text_color='gray', width=80).pack(side='left')

    def is_selected(self) -> bool:
        return self.enabled_var.get()


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
        self._viewer_proc: subprocess.Popen | None = None
        self._selection_file: str | None = None

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

        ctk.CTkLabel(body, text='Molecular groups',
                     font=ctk.CTkFont(weight='bold')).pack(anchor='w', padx=8, pady=(6, 2))

        self._list_frame = ctk.CTkScrollableFrame(body)
        self._list_frame.pack(fill='both', expand=True, padx=4, pady=4)
        ctk.CTkLabel(self._list_frame, text='Load a PDB file to see groups',
                     text_color='gray').pack(anchor='w', padx=8, pady=8)

        ctk.CTkButton(body, text='Show in 3D', command=self._show_in_3d).pack(pady=6)

        # ── Alternative locations ─────────────────────────────────────── #
        alt_header = ctk.CTkFrame(body, fg_color='transparent')
        alt_header.pack(fill='x', padx=8, pady=(8, 2))
        ctk.CTkLabel(alt_header, text='Alternative locations',
                     font=ctk.CTkFont(weight='bold')).pack(side='left')
        ctk.CTkLabel(alt_header, text='   default keep:', text_color='gray').pack(side='left')
        self._altloc_default = tk.StringVar(value='A')
        ctk.CTkOptionMenu(alt_header, variable=self._altloc_default,
                          values=['A', 'B', 'C', 'D'], width=60).pack(side='left', padx=6)
        ctk.CTkButton(alt_header, text='Apply to all', width=100,
                      command=self._apply_default_altloc).pack(side='left', padx=6)

        self._altloc_frame = ctk.CTkScrollableFrame(body, height=140)
        self._altloc_frame.pack(fill='x', padx=4, pady=4)
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
            row = GroupRow(self._list_frame, group)
            row.pack(fill='x', pady=2, padx=4)
            self._rows.append(row)

    def _selected_ids(self) -> set[str]:
        return {r.group.group_id for r in self._rows if r.is_selected()}

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
        if self._viewer_proc and self._viewer_proc.poll() is None:
            messagebox.showinfo('3D viewer', 'A 3D window is already open.')
            return
        tmp_dir = tempfile.mkdtemp(prefix='easynamd_')
        html_path = os.path.join(tmp_dir, 'altloc.html')
        build_altloc_html(self._pdb_file, residue, html_path)
        self._viewer_proc = subprocess.Popen(
            [sys.executable, '-m', 'gui.webview_window', html_path],
            cwd=ROOT_DIR,
        )

    # ------------------------------------------------------------------ #
    #  3D viewer (separate process)                                        #
    # ------------------------------------------------------------------ #

    def _show_in_3d(self):
        if not self._pdb_file:
            messagebox.showerror('Error', 'Load a PDB file first.')
            return
        if self._viewer_proc and self._viewer_proc.poll() is None:
            messagebox.showinfo('3D viewer', 'A 3D window is already open.')
            return

        tmp_dir = tempfile.mkdtemp(prefix='easynamd_')
        html_path = os.path.join(tmp_dir, 'viewer.html')
        self._selection_file = os.path.join(tmp_dir, 'selection.json')

        build_html(self._pdb_file, self._groups, self._selected_ids(), html_path)

        self._viewer_proc = subprocess.Popen(
            [sys.executable, '-m', 'gui.webview_window', html_path, self._selection_file],
            cwd=ROOT_DIR,
        )
        self._poll_viewer()

    def _poll_viewer(self):
        """While the 3D window is open, keep checking; when it closes, sync the
        selection back into the checkboxes."""
        if self._viewer_proc is None:
            return
        if self._viewer_proc.poll() is None:
            self.after(500, self._poll_viewer)
            return

        # Window closed — read back selection if present
        self._viewer_proc = None
        if self._selection_file and os.path.isfile(self._selection_file):
            try:
                with open(self._selection_file) as f:
                    ids = set(json.load(f))
                self._apply_selection(ids)
            except (json.JSONDecodeError, OSError):
                pass

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
                             altloc_choices=self._altloc_choices())
        messagebox.showinfo('Saved', f'Cleaned PDB saved to:\n{outpath}')
