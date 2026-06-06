import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.pdb_parser import Patch, SSBond, find_disulfide_bonds
from core.tcl_writer import write_build_script
from core.vmd_runner import run_vmd

ROOT_DIR       = os.path.dirname(os.path.dirname(__file__))
TOPOLOGIES_DIR = os.path.join(ROOT_DIR, "topologies")
PARAMETERS_DIR = os.path.join(ROOT_DIR, "parameters")


def collect_files(folder: str, extensions: tuple) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.endswith(extensions)
    )


class PatchRow(ctk.CTkFrame):
    """A single row for a user-defined patch: name, chain1, resid1, chain2, resid2."""

    def __init__(self, parent, on_remove):
        super().__init__(parent)

        self.name_var   = tk.StringVar()
        self.chain1_var = tk.StringVar()
        self.resid1_var = tk.StringVar()
        self.chain2_var = tk.StringVar()
        self.resid2_var = tk.StringVar()

        ctk.CTkEntry(self, textvariable=self.name_var,   width=80,  placeholder_text="Patch").pack(side="left", padx=2)
        ctk.CTkEntry(self, textvariable=self.chain1_var, width=50,  placeholder_text="Chain").pack(side="left", padx=2)
        ctk.CTkEntry(self, textvariable=self.resid1_var, width=60,  placeholder_text="ResID").pack(side="left", padx=2)
        ctk.CTkLabel(self, text="/").pack(side="left")
        ctk.CTkEntry(self, textvariable=self.chain2_var, width=50,  placeholder_text="Chain2").pack(side="left", padx=2)
        ctk.CTkEntry(self, textvariable=self.resid2_var, width=60,  placeholder_text="ResID2").pack(side="left", padx=2)
        ctk.CTkLabel(self, text="(optional)", text_color="gray").pack(side="left", padx=2)
        ctk.CTkButton(self, text="✕", width=30, fg_color="transparent",
                      text_color="red", command=on_remove).pack(side="left", padx=4)

    def to_patch(self) -> Patch | None:
        name   = self.name_var.get().strip()
        chain1 = self.chain1_var.get().strip()
        resid1 = self.resid1_var.get().strip()
        chain2 = self.chain2_var.get().strip()
        resid2 = self.resid2_var.get().strip()
        if not name or not chain1 or not resid1:
            return None
        return Patch(name=name, chain1=chain1, resid1=resid1, chain2=chain2, resid2=resid2)


class BuildPanel(ctk.CTkFrame):
    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.config = config
        self.ligand_topology_files: list[str] = []
        self.ligand_parameter_files: list[str] = []
        self.detected_ss_bonds: list[SSBond] = []
        self.ss_bond_vars: list[tk.BooleanVar] = []
        self.patch_rows: list[PatchRow] = []

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        self.steps = ctk.CTkTabview(self)
        self.steps.pack(fill="both", expand=True)

        self.steps.add("1. Build PSF")
        self.steps.add("2. Solvate")
        self.steps.add("3. Ionize")

        self._build_psf_tab(self.steps.tab("1. Build PSF"))
        self._build_solvate_tab(self.steps.tab("2. Solvate"))
        self._build_ionize_tab(self.steps.tab("3. Ionize"))

        bottom = ctk.CTkFrame(self)
        bottom.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        bottom.columnconfigure(0, weight=1)

        ctk.CTkButton(bottom, text="Build", fg_color="green", command=self._run).pack(pady=(8, 4))

        self.log_box = ctk.CTkTextbox(bottom, height=180, wrap="none")
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)

    # --- Tab 1: Build PSF ---

    def _build_psf_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        row = 0

        ctk.CTkLabel(parent, text="PDB file:").grid(row=row, column=0, sticky="w", padx=10, pady=6)
        self.pdb_var = tk.StringVar()
        ctk.CTkEntry(parent, textvariable=self.pdb_var).grid(row=row, column=1, padx=5, pady=6, sticky="ew")
        ctk.CTkButton(parent, text="Browse", width=80, command=self._browse_pdb).grid(row=row, column=2, padx=5, pady=6)
        row += 1

        ctk.CTkLabel(parent, text="Output dir:").grid(row=row, column=0, sticky="w", padx=10, pady=6)
        self.outdir_var = tk.StringVar(value=self.config.get("default_output_dir", ""))
        ctk.CTkEntry(parent, textvariable=self.outdir_var).grid(row=row, column=1, padx=5, pady=6, sticky="ew")
        ctk.CTkButton(parent, text="Browse", width=80, command=self._browse_outdir).grid(row=row, column=2, padx=5, pady=6)
        row += 1

        ctk.CTkLabel(parent, text="Ligand tops:").grid(row=row, column=0, sticky="w", padx=10, pady=6)
        self.ligand_topo_label = ctk.CTkLabel(parent, text="None", anchor="w")
        self.ligand_topo_label.grid(row=row, column=1, padx=5, pady=6, sticky="w")
        ctk.CTkButton(parent, text="Add", width=80, command=self._add_ligand_topologies).grid(row=row, column=2, padx=5, pady=6)
        row += 1

        ctk.CTkLabel(parent, text="Ligand params:").grid(row=row, column=0, sticky="w", padx=10, pady=6)
        self.ligand_param_label = ctk.CTkLabel(parent, text="None", anchor="w")
        self.ligand_param_label.grid(row=row, column=1, padx=5, pady=6, sticky="w")
        ctk.CTkButton(parent, text="Add", width=80, command=self._add_ligand_parameters).grid(row=row, column=2, padx=5, pady=6)
        row += 1

        # Disulfide bonds
        ctk.CTkLabel(parent, text="Disulfide bonds:").grid(row=row, column=0, sticky="nw", padx=10, pady=6)
        self.ss_frame = ctk.CTkFrame(parent)
        self.ss_frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=5, pady=6)
        self.ss_placeholder = ctk.CTkLabel(self.ss_frame, text="Load a PDB file to detect SS bonds", text_color="gray")
        self.ss_placeholder.pack(anchor="w", padx=6, pady=4)
        row += 1

        # Custom patches
        ctk.CTkLabel(parent, text="Patches:").grid(row=row, column=0, sticky="nw", padx=10, pady=6)
        patch_ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        patch_ctrl.grid(row=row, column=1, columnspan=2, sticky="ew", padx=5, pady=(6, 0))
        ctk.CTkLabel(patch_ctrl, text="Patch name   Chain  ResID  /  Chain2  ResID2",
                     text_color="gray", font=("", 11)).pack(anchor="w", padx=4)
        self.patches_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.patches_frame.grid(row=row + 1, column=0, columnspan=3, sticky="ew", padx=10)
        ctk.CTkButton(parent, text="+ Add patch", width=100, command=self._add_patch_row).grid(
            row=row + 2, column=0, columnspan=3, pady=4)

    # --- Tab 2: Solvate ---

    def _build_solvate_tab(self, parent):
        parent.columnconfigure(1, weight=1)

        ctk.CTkLabel(parent, text="Box padding (Å):").grid(row=0, column=0, sticky="w", padx=10, pady=6)
        self.padding_var = tk.DoubleVar(value=10.0)
        ctk.CTkEntry(parent, textvariable=self.padding_var, width=80).grid(row=0, column=1, padx=5, pady=6, sticky="w")

    # --- Tab 3: Ionize ---

    def _build_ionize_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        row = 0

        self.ionize_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(parent, text="Ionize (neutralize)", variable=self.ionize_var,
                        command=self._toggle_salt).grid(row=row, column=0, columnspan=2, sticky="w", padx=10, pady=6)
        row += 1

        ctk.CTkLabel(parent, text="Salt conc. (M):").grid(row=row, column=0, sticky="w", padx=10, pady=6)
        self.salt_var = tk.DoubleVar(value=0.0)
        self.salt_entry = ctk.CTkEntry(parent, textvariable=self.salt_var, width=80)
        self.salt_entry.grid(row=row, column=1, padx=5, pady=6, sticky="w")

    # ------------------------------------------------------------------ #
    #  Disulfide bond detection                                            #
    # ------------------------------------------------------------------ #

    def _load_ss_bonds(self, pdb_file: str):
        self.detected_ss_bonds = find_disulfide_bonds(pdb_file)
        self.ss_bond_vars.clear()

        for widget in self.ss_frame.winfo_children():
            widget.destroy()

        if not self.detected_ss_bonds:
            ctk.CTkLabel(self.ss_frame, text="No disulfide bonds found", text_color="gray").pack(anchor="w", padx=6, pady=4)
            return

        for bond in self.detected_ss_bonds:
            var = tk.BooleanVar(value=True)
            self.ss_bond_vars.append(var)
            ctk.CTkCheckBox(self.ss_frame, text=str(bond), variable=var).pack(anchor="w", padx=6, pady=2)

    # ------------------------------------------------------------------ #
    #  Custom patch rows                                                   #
    # ------------------------------------------------------------------ #

    def _add_patch_row(self):
        row = PatchRow(self.patches_frame, on_remove=lambda r=None: self._remove_patch_row(row))
        row.pack(fill="x", pady=2)
        self.patch_rows.append(row)

    def _remove_patch_row(self, row: PatchRow):
        self.patch_rows.remove(row)
        row.destroy()

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _browse_pdb(self):
        path = filedialog.askopenfilename(filetypes=[("PDB files", "*.pdb"), ("All files", "*.*")])
        if path:
            self.pdb_var.set(path)
            self._load_ss_bonds(path)

    def _browse_outdir(self):
        path = filedialog.askdirectory()
        if path:
            self.outdir_var.set(path)

    def _add_ligand_topologies(self):
        paths = filedialog.askopenfilenames(
            title="Select ligand topology files",
            initialdir=os.path.join(TOPOLOGIES_DIR, "ligands"),
            filetypes=[("CHARMM topology", "*.rtf *.top"), ("All files", "*.*")],
        )
        if paths:
            self.ligand_topology_files.extend(paths)
            self.ligand_topo_label.configure(text=f"{len(self.ligand_topology_files)} file(s)")

    def _add_ligand_parameters(self):
        paths = filedialog.askopenfilenames(
            title="Select ligand parameter files",
            initialdir=os.path.join(PARAMETERS_DIR, "ligands"),
            filetypes=[("CHARMM parameters", "*.prm *.str"), ("All files", "*.*")],
        )
        if paths:
            self.ligand_parameter_files.extend(paths)
            self.ligand_param_label.configure(text=f"{len(self.ligand_parameter_files)} file(s)")

    def _toggle_salt(self):
        state = "normal" if self.ionize_var.get() else "disabled"
        self.salt_entry.configure(state=state)

    def _collect_topology_files(self) -> list[str]:
        standard = collect_files(TOPOLOGIES_DIR, (".rtf", ".top"))
        return standard + self.ligand_topology_files

    def _collect_parameter_files(self) -> list[str]:
        standard = collect_files(PARAMETERS_DIR, (".prm", ".str"))
        return standard + self.ligand_parameter_files

    def _collect_patches(self) -> list[Patch]:
        patches = []

        # SS bonds that are checked
        for bond, var in zip(self.detected_ss_bonds, self.ss_bond_vars):
            if var.get():
                patches.append(Patch(
                    name="DISU",
                    chain1=bond.chain1, resid1=bond.resid1,
                    chain2=bond.chain2, resid2=bond.resid2,
                ))

        # User-defined patches
        for row in self.patch_rows:
            patch = row.to_patch()
            if patch:
                patches.append(patch)

        return patches

    def _log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------ #
    #  Build                                                               #
    # ------------------------------------------------------------------ #

    def _run(self):
        pdb    = self.pdb_var.get().strip()
        outdir = self.outdir_var.get().strip()
        vmd    = self.config.get("vmd_path", "").strip()

        if not pdb or not os.path.isfile(pdb):
            messagebox.showerror("Error", "Select a valid PDB file.")
            return
        if not outdir:
            messagebox.showerror("Error", "Select an output directory.")
            return
        if not vmd or not os.path.isfile(vmd):
            messagebox.showerror("Error", "VMD binary not found. Check Settings.")
            return

        topology_files = self._collect_topology_files()
        if not topology_files:
            messagebox.showerror("Error", "No topology files found in topologies/.")
            return

        script = write_build_script(
            pdb_file=pdb,
            topology_files=topology_files,
            parameter_files=self._collect_parameter_files(),
            patches=self._collect_patches(),
            output_dir=outdir,
            padding=self.padding_var.get(),
            ionize=self.ionize_var.get(),
            salt_concentration=self.salt_var.get(),
        )

        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._log(f"Running VMD: {script}")

        run_vmd(
            vmd_path=vmd,
            tcl_script=script,
            on_output=lambda line: self.after(0, self._log, line),
            on_done=lambda ok: self.after(0, self._on_done, ok),
        )

    def _on_done(self, success: bool):
        if success:
            self._log("\nBuild complete.")
            messagebox.showinfo("Done", "Structure built successfully.")
        else:
            self._log("\nBuild failed. Check the log above.")
            messagebox.showerror("Failed", "VMD exited with an error.")
