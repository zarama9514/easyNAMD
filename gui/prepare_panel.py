import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.molecule_groups import MolGroup, parse_groups, save_selected_groups
from gui.viewer3d import MolViewer

TYPE_ICONS = {
    'protein': '🔵',
    'ligand':  '🟠',
    'metal':   '🟡',
    'water':   '🩵',
    'other':   '⚪',
}


class GroupRow(ctk.CTkFrame):
    """One row in the group list: [checkbox] [icon label] [atom count] [Focus]"""

    def __init__(self, parent, group: MolGroup, on_focus, on_toggle):
        super().__init__(parent, fg_color='transparent')
        self.group = group

        self.enabled_var = tk.BooleanVar(value=group.group_type != 'water')

        icon  = TYPE_ICONS.get(group.group_type, '⚪')
        count = f'{group.atom_count():>6} atoms'

        ctk.CTkCheckBox(
            self, variable=self.enabled_var, text='',
            width=24, command=on_toggle,
        ).pack(side='left', padx=(4, 0))

        ctk.CTkLabel(self, text=f'{icon}  {group.label}', anchor='w', width=240).pack(side='left', padx=6)
        ctk.CTkLabel(self, text=count, anchor='e', text_color='gray', width=80).pack(side='left')
        ctk.CTkButton(
            self, text='Focus', width=60,
            command=on_focus,
        ).pack(side='left', padx=6)

    def is_selected(self) -> bool:
        return self.enabled_var.get()


class PreparePanel(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self._pdb_file:  str | None        = None
        self._groups:    list[MolGroup]    = []
        self._rows:      list[GroupRow]    = []
        self._focused_id: str | None       = None

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  Layout                                                              #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        # ── Top bar: PDB file selection ──────────────────────────────── #
        top = ctk.CTkFrame(self)
        top.pack(fill='x', padx=10, pady=8)

        ctk.CTkLabel(top, text='PDB file:').pack(side='left', padx=(6, 4))
        self._pdb_var = tk.StringVar()
        ctk.CTkEntry(top, textvariable=self._pdb_var, width=380).pack(side='left', padx=4)
        ctk.CTkButton(top, text='Browse', width=80, command=self._browse_pdb).pack(side='left', padx=4)

        # ── Main area: group list (left) + 3D viewer (right) ─────────── #
        main = tk.PanedWindow(self, orient='horizontal', sashwidth=6,
                              bg='#2b2b2b', bd=0)
        main.pack(fill='both', expand=True, padx=10, pady=(0, 4))

        # Left pane — group list
        left = ctk.CTkFrame(main, width=380)
        main.add(left, minsize=280)

        ctk.CTkLabel(left, text='Molecular groups', font=ctk.CTkFont(weight='bold')).pack(
            anchor='w', padx=8, pady=(6, 2))

        self._list_frame = ctk.CTkScrollableFrame(left)
        self._list_frame.pack(fill='both', expand=True, padx=4, pady=4)

        self._placeholder = ctk.CTkLabel(
            self._list_frame, text='Load a PDB file to see groups', text_color='gray')
        self._placeholder.pack(anchor='w', padx=8, pady=8)

        # Right pane — 3D viewer
        self._viewer = MolViewer(main)
        main.add(self._viewer, minsize=300)

        # ── Bottom bar: output + save ─────────────────────────────────── #
        bottom = ctk.CTkFrame(self)
        bottom.pack(fill='x', padx=10, pady=(0, 8))

        ctk.CTkLabel(bottom, text='Save to:').pack(side='left', padx=(6, 4))
        self._outpath_var = tk.StringVar()
        ctk.CTkEntry(bottom, textvariable=self._outpath_var, width=340).pack(side='left', padx=4)
        ctk.CTkButton(bottom, text='Browse', width=80, command=self._browse_output).pack(side='left', padx=4)
        ctk.CTkButton(bottom, text='Save cleaned PDB', fg_color='green',
                      command=self._save).pack(side='left', padx=12)

    # ------------------------------------------------------------------ #
    #  Group list population                                               #
    # ------------------------------------------------------------------ #

    def _populate_list(self):
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._rows.clear()
        self._focused_id = None

        if not self._groups:
            ctk.CTkLabel(self._list_frame, text='No ATOM/HETATM records found',
                         text_color='gray').pack(anchor='w', padx=8)
            return

        for group in self._groups:
            row = GroupRow(
                self._list_frame, group,
                on_focus=lambda g=group: self._focus_group(g.group_id),
                on_toggle=self._viewer.clear,
            )
            row.pack(fill='x', pady=2, padx=4)
            self._rows.append(row)

        # Initial render: all groups faded, nothing highlighted
        self._viewer.show_groups(self._groups, highlighted_id=None)

    # ------------------------------------------------------------------ #
    #  Interaction                                                         #
    # ------------------------------------------------------------------ #

    def _focus_group(self, group_id: str):
        """Highlight one group in VDW, fade everything else."""
        if self._focused_id == group_id:
            # Second click on same → unfocus
            self._focused_id = None
        else:
            self._focused_id = group_id
        self._viewer.show_groups(self._groups, highlighted_id=self._focused_id)

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
        # Auto-suggest output path
        base, _ = os.path.splitext(path)
        self._outpath_var.set(base + '_clean.pdb')
        # Parse and display
        self._groups = parse_groups(path)
        self._populate_list()

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.pdb',
            filetypes=[('PDB files', '*.pdb'), ('All files', '*.*')],
        )
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

        selected_ids = {
            row.group.group_id for row in self._rows if row.is_selected()
        }
        if not selected_ids:
            messagebox.showerror('Error', 'No groups selected.')
            return

        save_selected_groups(self._pdb_file, self._groups, selected_ids, outpath)
        messagebox.showinfo('Saved', f'Cleaned PDB saved to:\n{outpath}')
