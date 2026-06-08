import os
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.pdb_parser import (
    HisResidue, Patch, PDBInfo, SegmentConfig, parse_pdb,
)
from core.tcl_writer import write_build_script
from core.vmd_runner import run_vmd
from core.viewer_html import build_residue_focus_html
from core.his_images import tautomer_images

from PIL import Image

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))

ROOT_DIR       = os.path.dirname(os.path.dirname(__file__))
TOPOLOGIES_DIR = os.path.join(ROOT_DIR, "topologies")
PARAMETERS_DIR = os.path.join(ROOT_DIR, "parameters")

NTER_OPTIONS = ["NTER", "GLYP", "PROP", "ACE", "none"]
CTER_OPTIONS = ["CTER", "CT1", "CT2", "CT3", "none"]
HIS_OPTIONS  = ["HSD", "HSE", "HSP"]


def collect_files(folder: str, extensions: tuple) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.endswith(extensions)
    )


def section_label(parent, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(weight="bold"))


class PatchRow(ctk.CTkFrame):
    def __init__(self, parent, on_remove):
        super().__init__(parent, fg_color="transparent")
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
        ctk.CTkButton(self, text="✕", width=28, fg_color="transparent",
                      text_color="red", command=on_remove).pack(side="left", padx=4)

    def to_patch(self) -> Patch | None:
        name   = self.name_var.get().strip()
        chain1 = self.chain1_var.get().strip()
        resid1 = self.resid1_var.get().strip()
        if not name or not chain1 or not resid1:
            return None
        return Patch(name, chain1, resid1,
                     self.chain2_var.get().strip(),
                     self.resid2_var.get().strip())


class BuildPanel(ctk.CTkFrame):
    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.config = config
        self.pdb_info: PDBInfo | None = None

        # dynamic widget state
        self.segment_rows: list[dict] = []   # {chain, first_var, last_var}
        self.his_rows:     list[dict] = []   # {his, prot_var}
        self.ss_rows:      list[dict] = []   # {bond, enabled_var}
        self.patch_rows:   list[PatchRow] = []
        self.ligand_topology_files:  list[str] = []
        self.ligand_parameter_files: list[str] = []

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  Top-level UI                                                        #
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

        ctk.CTkButton(bottom, text="Build", fg_color="green", command=self._run).pack(pady=(8, 4))
        self.log_box = ctk.CTkTextbox(bottom, height=180, wrap="none")
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)

    # ------------------------------------------------------------------ #
    #  Tab 1 — Build PSF                                                   #
    # ------------------------------------------------------------------ #

    def _build_psf_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent)
        scroll.pack(fill="both", expand=True)
        scroll.columnconfigure(1, weight=1)
        self._psf_scroll = scroll
        row = 0

        # File selection
        section_label(scroll, "Input files").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 2))
        row += 1

        ctk.CTkLabel(scroll, text="PDB file:").grid(row=row, column=0, sticky="w", padx=10, pady=4)
        self.pdb_var = tk.StringVar()
        ctk.CTkEntry(scroll, textvariable=self.pdb_var).grid(row=row, column=1, padx=5, pady=4, sticky="ew")
        ctk.CTkButton(scroll, text="Browse", width=80, command=self._browse_pdb).grid(row=row, column=2, padx=5)
        row += 1

        ctk.CTkLabel(scroll, text="Output dir:").grid(row=row, column=0, sticky="w", padx=10, pady=4)
        self.outdir_var = tk.StringVar(value=self.config.get("default_output_dir", ""))
        ctk.CTkEntry(scroll, textvariable=self.outdir_var).grid(row=row, column=1, padx=5, pady=4, sticky="ew")
        ctk.CTkButton(scroll, text="Browse", width=80, command=self._browse_outdir).grid(row=row, column=2, padx=5)
        row += 1

        # Warnings area (hidden until PDB is loaded)
        self._warn_row = row
        self.warn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.warn_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        row += 1

        # Segments / chains
        section_label(scroll, "Segments (chains)").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2))
        row += 1
        self.segments_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.segments_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        ctk.CTkLabel(self.segments_frame, text="Load a PDB to detect chains", text_color="gray").pack(anchor="w")
        row += 1

        # Histidine protonation
        section_label(scroll, "Histidine protonation").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2))
        row += 1
        self._build_his_legend(scroll, row)
        row += 1
        self.his_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.his_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        ctk.CTkLabel(self.his_frame, text="No histidines found", text_color="gray").pack(anchor="w")
        row += 1

        # Ligand files
        section_label(scroll, "Ligand files").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2))
        row += 1
        ctk.CTkLabel(scroll, text="Ligand tops:").grid(row=row, column=0, sticky="w", padx=10, pady=4)
        self.ligand_topo_label = ctk.CTkLabel(scroll, text="None", anchor="w")
        self.ligand_topo_label.grid(row=row, column=1, padx=5, sticky="w")
        ctk.CTkButton(scroll, text="Add", width=80, command=self._add_ligand_topologies).grid(row=row, column=2, padx=5)
        row += 1

        ctk.CTkLabel(scroll, text="Ligand params:").grid(row=row, column=0, sticky="w", padx=10, pady=4)
        self.ligand_param_label = ctk.CTkLabel(scroll, text="None", anchor="w")
        self.ligand_param_label.grid(row=row, column=1, padx=5, sticky="w")
        ctk.CTkButton(scroll, text="Add", width=80, command=self._add_ligand_parameters).grid(row=row, column=2, padx=5)
        row += 1

        # Build options
        section_label(scroll, "Build options").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2))
        row += 1
        opts = ctk.CTkFrame(scroll, fg_color="transparent")
        opts.grid(row=row, column=0, columnspan=3, sticky="w", padx=8)
        self.guesscoord_var     = tk.BooleanVar(value=True)
        self.regen_angles_var   = tk.BooleanVar(value=True)
        self.regen_dihedrals_var = tk.BooleanVar(value=True)
        self.regen_resids_var   = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts, text="guesscoord",           variable=self.guesscoord_var).grid(row=0, column=0, padx=8, pady=2, sticky="w")
        ctk.CTkCheckBox(opts, text="regenerate angles",    variable=self.regen_angles_var).grid(row=0, column=1, padx=8, pady=2, sticky="w")
        ctk.CTkCheckBox(opts, text="regenerate dihedrals", variable=self.regen_dihedrals_var).grid(row=0, column=2, padx=8, pady=2, sticky="w")
        ctk.CTkCheckBox(opts, text="regenerate resids",    variable=self.regen_resids_var).grid(row=0, column=3, padx=8, pady=2, sticky="w")
        row += 1

        # Disulfide bonds
        section_label(scroll, "Disulfide bonds").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2))
        row += 1
        self.ss_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.ss_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        ctk.CTkLabel(self.ss_frame, text="No SS bonds found", text_color="gray").pack(anchor="w")
        row += 1

        # Custom patches
        section_label(scroll, "Custom patches").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2))
        row += 1
        ctk.CTkLabel(scroll, text="Patch    Chain  ResID  /  Chain2  ResID2",
                     text_color="gray", font=ctk.CTkFont(size=11)).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=10)
        row += 1
        self.patches_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.patches_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        row += 1
        ctk.CTkButton(scroll, text="+ Add patch", width=110,
                      command=self._add_patch_row).grid(row=row, column=0, columnspan=3, pady=6)

    # ------------------------------------------------------------------ #
    #  Tab 2 — Solvate                                                     #
    # ------------------------------------------------------------------ #

    def _build_his_legend(self, parent, row):
        """Show HSD/HSE/HSP structures (rendered by RDKit) as a quick reference."""
        captions = {
            "HSD": "proton on Nδ1 (neutral)",
            "HSE": "proton on Nε2 (neutral)",
            "HSP": "both protonated (+1)",
        }
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 6))

        self._his_imgs = []   # keep references so images aren't garbage-collected
        try:
            paths = tautomer_images()
        except Exception:
            paths = {}

        for col, name in enumerate(("HSD", "HSE", "HSP")):
            cell = ctk.CTkFrame(frame, fg_color="transparent")
            cell.grid(row=0, column=col, padx=10)
            if name in paths:
                img = ctk.CTkImage(light_image=Image.open(paths[name]), size=(120, 120))
                self._his_imgs.append(img)
                ctk.CTkLabel(cell, image=img, text="").pack()
            ctk.CTkLabel(cell, text=name, font=ctk.CTkFont(weight="bold")).pack()
            ctk.CTkLabel(cell, text=captions[name], text_color="gray",
                         font=ctk.CTkFont(size=11)).pack()

    def _build_solvate_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        ctk.CTkLabel(parent, text="Box padding (Å):").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        self.padding_var = tk.DoubleVar(value=10.0)
        ctk.CTkEntry(parent, textvariable=self.padding_var, width=80).grid(row=0, column=1, padx=5, sticky="w")

        self.rotate_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(parent, text="Rotate solute to minimize box volume",
                        variable=self.rotate_var).grid(row=1, column=0, columnspan=2,
                                                       sticky="w", padx=10, pady=8)

        self.recenter_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(parent, text="Move system center of mass to origin (0, 0, 0)",
                        variable=self.recenter_var).grid(row=2, column=0, columnspan=2,
                                                         sticky="w", padx=10, pady=8)

    # ------------------------------------------------------------------ #
    #  Tab 3 — Ionize                                                      #
    # ------------------------------------------------------------------ #

    def _build_ionize_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        self.ionize_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(parent, text="Ionize (neutralize)", variable=self.ionize_var,
                        command=self._toggle_salt).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=8)
        ctk.CTkLabel(parent, text="Salt conc. (M):").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        self.salt_var = tk.DoubleVar(value=0.0)
        self.salt_entry = ctk.CTkEntry(parent, textvariable=self.salt_var, width=80)
        self.salt_entry.grid(row=1, column=1, padx=5, sticky="w")

    # ------------------------------------------------------------------ #
    #  PDB loading — populates all dynamic sections                        #
    # ------------------------------------------------------------------ #

    def _load_pdb(self, path: str):
        self.pdb_info = parse_pdb(path)
        self._refresh_warnings()
        self._refresh_segments()
        self._refresh_histidines()
        self._refresh_ss_bonds()

    def _refresh_warnings(self):
        for w in self.warn_frame.winfo_children():
            w.destroy()

        info = self.pdb_info
        if info.has_altloc:
            ctk.CTkLabel(
                self.warn_frame,
                text="⚠  ALTLOC detected — keep only one conformer before building",
                text_color="orange",
            ).pack(anchor="w", pady=2)

        if info.has_insercodes:
            row = ctk.CTkFrame(self.warn_frame, fg_color="transparent")
            row.pack(anchor="w", pady=2)
            ctk.CTkLabel(row, text="⚠  Insertion codes detected —", text_color="orange").pack(side="left")
            ctk.CTkCheckBox(row, text="regenerate resids", variable=self.regen_resids_var).pack(side="left", padx=6)

    def _refresh_segments(self):
        for w in self.segments_frame.winfo_children():
            w.destroy()
        self.segment_rows.clear()

        if not self.pdb_info.chains:
            ctk.CTkLabel(self.segments_frame, text="No ATOM chains found", text_color="gray").pack(anchor="w")
            return

        header = ctk.CTkFrame(self.segments_frame, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text="Chain", width=50).pack(side="left", padx=4)
        ctk.CTkLabel(header, text="N-terminus", width=100).pack(side="left", padx=4)
        ctk.CTkLabel(header, text="C-terminus", width=100).pack(side="left", padx=4)

        for chain in self.pdb_info.chains:
            row_frame = ctk.CTkFrame(self.segments_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)
            ctk.CTkLabel(row_frame, text=chain, width=50).pack(side="left", padx=4)
            first_var = tk.StringVar(value="NTER")
            last_var  = tk.StringVar(value="CTER")
            ctk.CTkOptionMenu(row_frame, variable=first_var, values=NTER_OPTIONS, width=100).pack(side="left", padx=4)
            ctk.CTkOptionMenu(row_frame, variable=last_var,  values=CTER_OPTIONS, width=100).pack(side="left", padx=4)
            self.segment_rows.append({"chain": chain, "first_var": first_var, "last_var": last_var})

    def _refresh_histidines(self):
        for w in self.his_frame.winfo_children():
            w.destroy()
        self.his_rows.clear()

        if not self.pdb_info.histidines:
            ctk.CTkLabel(self.his_frame, text="No histidines found", text_color="gray").pack(anchor="w")
            return

        for his in self.pdb_info.histidines:
            row_frame = ctk.CTkFrame(self.his_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)
            ctk.CTkLabel(row_frame, text=str(his), width=80).pack(side="left", padx=4)
            prot_var = tk.StringVar(value="HSD")
            ctk.CTkOptionMenu(row_frame, variable=prot_var, values=HIS_OPTIONS, width=90).pack(side="left", padx=4)
            ctk.CTkButton(row_frame, text="View 3D", width=80,
                          command=lambda h=his: self._view_residue(h.chain, h.resid)).pack(side="left", padx=4)
            self.his_rows.append({"his": his, "prot_var": prot_var})

    def _refresh_ss_bonds(self):
        for w in self.ss_frame.winfo_children():
            w.destroy()
        self.ss_rows.clear()

        if not self.pdb_info.ss_bonds:
            ctk.CTkLabel(self.ss_frame, text="No SS bonds found", text_color="gray").pack(anchor="w")
            return

        for bond in self.pdb_info.ss_bonds:
            var = tk.BooleanVar(value=True)
            ctk.CTkCheckBox(self.ss_frame, text=str(bond), variable=var).pack(anchor="w", pady=2)
            self.ss_rows.append({"bond": bond, "enabled_var": var})

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _browse_pdb(self):
        path = filedialog.askopenfilename(filetypes=[("PDB files", "*.pdb"), ("All files", "*.*")])
        if path:
            self.pdb_var.set(path)
            self._load_pdb(path)

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
        self.salt_entry.configure(state="normal" if self.ionize_var.get() else "disabled")

    def _add_patch_row(self):
        row = PatchRow(self.patches_frame, on_remove=lambda r=None: self._remove_patch_row(row))
        row.pack(fill="x", pady=2)
        self.patch_rows.append(row)

    def _remove_patch_row(self, row: PatchRow):
        self.patch_rows.remove(row)
        row.destroy()

    def _view_residue(self, chain: str, resid: str):
        """Open a 3D viewer focused on a residue (heavy atoms + 5 Å environment)."""
        pdb = self.pdb_var.get().strip()
        if not pdb or not os.path.isfile(pdb):
            messagebox.showerror("Error", "Select a valid PDB file first.")
            return
        tmp_dir = tempfile.mkdtemp(prefix="easynamd_")
        html = os.path.join(tmp_dir, "residue.html")
        build_residue_focus_html(pdb, chain, resid, html, title=f"{chain}:{resid}")
        subprocess.Popen(
            [sys.executable, "-m", "gui.webview_window", html],
            cwd=ROOT_DIR,
        )

    def _collect_topology_files(self) -> list[str]:
        return collect_files(TOPOLOGIES_DIR, (".rtf", ".top")) + self.ligand_topology_files

    def _collect_parameter_files(self) -> list[str]:
        return collect_files(PARAMETERS_DIR, (".prm", ".str")) + self.ligand_parameter_files

    def _collect_segments(self) -> list[SegmentConfig]:
        return [
            SegmentConfig(
                chain=r["chain"],
                first_patch=r["first_var"].get(),
                last_patch=r["last_var"].get(),
            )
            for r in self.segment_rows
        ]

    def _collect_histidines(self) -> list[HisResidue]:
        result = []
        for r in self.his_rows:
            his = r["his"]
            his.protonation = r["prot_var"].get()
            result.append(his)
        return result

    def _collect_patches(self) -> list[Patch]:
        patches = []
        for r in self.ss_rows:
            if r["enabled_var"].get():
                b = r["bond"]
                patches.append(Patch("DISU", b.chain1, b.resid1, b.chain2, b.resid2))
        for row in self.patch_rows:
            p = row.to_patch()
            if p:
                patches.append(p)
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

        segments = self._collect_segments()
        if not segments:
            messagebox.showerror("Error", "No chains detected. Load a PDB file first.")
            return

        script = write_build_script(
            pdb_file=pdb,
            topology_files=topology_files,
            parameter_files=self._collect_parameter_files(),
            segments=segments,
            patches=self._collect_patches(),
            histidines=self._collect_histidines(),
            output_dir=outdir,
            padding=self.padding_var.get(),
            rotate=self.rotate_var.get(),
            recenter=self.recenter_var.get(),
            ionize=self.ionize_var.get(),
            salt_concentration=self.salt_var.get(),
            guesscoord=self.guesscoord_var.get(),
            regenerate_angles=self.regen_angles_var.get(),
            regenerate_dihedrals=self.regen_dihedrals_var.get(),
            regenerate_resids=self.regen_resids_var.get(),
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
