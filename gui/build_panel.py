import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

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


class BuildPanel(ctk.CTkFrame):
    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.config = config
        self.ligand_topology_files: list[str] = []
        self.ligand_parameter_files: list[str] = []

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.steps = ctk.CTkTabview(self)
        self.steps.pack(fill="both", expand=True)

        self.steps.add("1. Build PSF")
        self.steps.add("2. Solvate")
        self.steps.add("3. Ionize")

        self._build_psf_tab(self.steps.tab("1. Build PSF"))
        self._build_solvate_tab(self.steps.tab("2. Solvate"))
        self._build_ionize_tab(self.steps.tab("3. Ionize"))

        # Log and Run shared at the bottom
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
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _browse_pdb(self):
        path = filedialog.askopenfilename(filetypes=[("PDB files", "*.pdb"), ("All files", "*.*")])
        if path:
            self.pdb_var.set(path)

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
