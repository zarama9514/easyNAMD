import os
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

import json

from core.pdb_parser import (
    HeteroResidue, HeteroSegment, HisResidue, Patch, PDBInfo, SegmentConfig,
    find_hetero_residues, parse_pdb,
)
from core.coverage import uncovered_built_residues
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

# label → CHARMM resname
CATION_TYPES = {"Na+ (SOD)": "SOD", "K+ (POT)": "POT", "Ca2+ (CAL)": "CAL",
                "Mg2+ (MG)": "MG", "Cs+ (CES)": "CES"}
ANION_TYPES  = {"Cl- (CLA)": "CLA"}


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

        ctk.CTkEntry(self, textvariable=self.name_var,   width=90,  placeholder_text="CYSD").pack(side="left", padx=2)
        ctk.CTkEntry(self, textvariable=self.chain1_var, width=70,  placeholder_text="segid L").pack(side="left", padx=2)
        ctk.CTkEntry(self, textvariable=self.resid1_var, width=70,  placeholder_text="resid 211").pack(side="left", padx=2)
        ctk.CTkLabel(self, text="2nd residue:", text_color="gray").pack(side="left", padx=(6, 2))
        ctk.CTkEntry(self, textvariable=self.chain2_var, width=70,  placeholder_text="segid").pack(side="left", padx=2)
        ctk.CTkEntry(self, textvariable=self.resid2_var, width=60,  placeholder_text="resid").pack(side="left", padx=2)
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
        self.hetero_rows:  list[dict] = []   # {hetero, include_var, segname_var}
        self.patch_rows:   list[PatchRow] = []
        self.ligand_topology_files:  list[str] = []
        self.ligand_parameter_files: list[str] = []
        self._problems: list[str] = []

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

        btn_row = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_row.pack(pady=(8, 4))
        ctk.CTkButton(btn_row, text="Summary", width=90,
                      command=self._show_summary).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Save preset", width=100,
                      command=self._save_preset).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Load preset", width=100,
                      command=self._load_preset).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Preview script", width=120,
                      command=self._preview_script).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Build", fg_color="green", command=self._run).pack(side="left", padx=6)
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

        # Hetero segments (ligands / cofactors / ions built as their own segment)
        section_label(scroll, "Hetero segments (ligands / ions)").grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2))
        row += 1
        ctk.CTkLabel(scroll,
                     text="tick to build into the PSF as its own segment (needs matching "
                          "topology/parameters above).  segname = segid, ≤4 chars",
                     text_color="gray", font=ctk.CTkFont(size=11)).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=10)
        row += 1
        self.hetero_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.hetero_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        ctk.CTkLabel(self.hetero_frame, text="Load a PDB to detect hetero residues",
                     text_color="gray").pack(anchor="w")
        row += 1

        # Crystal water
        cwater = ctk.CTkFrame(scroll, fg_color="transparent")
        cwater.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 0))
        self.keep_water_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(cwater, text="Keep crystal water (build as segment)",
                        variable=self.keep_water_var).pack(side="left")
        ctk.CTkLabel(cwater, text="segname:", text_color="gray").pack(side="left", padx=(8, 2))
        self.water_segname_var = tk.StringVar(value="XWAT")
        ctk.CTkEntry(cwater, textvariable=self.water_segname_var, width=70).pack(side="left")
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
        ctk.CTkLabel(
            scroll,
            text="patch name (e.g. CYSD)   ·   segid (protein = chain, e.g. L; hetero = segname)   ·   "
                 "resid (e.g. 211)   —   2nd residue only for two-residue patches (e.g. DISU)",
            text_color="gray", font=ctk.CTkFont(size=11),
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 2))
        row += 1
        self.patches_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.patches_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        # "+ Add patch" lives inside patches_frame and is always kept last, so each
        # new patch row appears above it and pushes it down.
        self._add_patch_btn = ctk.CTkButton(self.patches_frame, text="+ Add patch",
                                            width=110, command=self._add_patch_row)
        self._add_patch_btn.pack(anchor="w", pady=6)

    # ------------------------------------------------------------------ #
    #  Tab 2 — Solvate                                                     #
    # ------------------------------------------------------------------ #

    def load_pdb_external(self, path: str):
        """Load a PDB into the Build tab (used by the Prepare → Build handoff)."""
        if not os.path.isfile(path):
            return
        self.pdb_var.set(path)
        if not self.outdir_var.get().strip():
            self.outdir_var.set(os.path.dirname(path))
        self._load_pdb(path)

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

        ctk.CTkLabel(parent, text="Cation:").grid(row=2, column=0, sticky="w", padx=10, pady=4)
        self.cation_var = tk.StringVar(value="Na+ (SOD)")
        ctk.CTkOptionMenu(parent, variable=self.cation_var, values=list(CATION_TYPES),
                          width=140).grid(row=2, column=1, padx=5, sticky="w")

        ctk.CTkLabel(parent, text="Anion:").grid(row=3, column=0, sticky="w", padx=10, pady=4)
        self.anion_var = tk.StringVar(value="Cl- (CLA)")
        ctk.CTkOptionMenu(parent, variable=self.anion_var, values=list(ANION_TYPES),
                          width=140).grid(row=3, column=1, padx=5, sticky="w")

    # ------------------------------------------------------------------ #
    #  PDB loading — populates all dynamic sections                        #
    # ------------------------------------------------------------------ #

    def _load_pdb(self, path: str):
        self.pdb_info = parse_pdb(path)
        self._refresh_warnings()
        self._refresh_segments()
        self._refresh_histidines()
        self._refresh_ss_bonds()
        self._refresh_hetero(path)

    def _refresh_hetero(self, path: str):
        for w in self.hetero_frame.winfo_children():
            w.destroy()
        self.hetero_rows.clear()

        heteros = find_hetero_residues(path)
        if not heteros:
            ctk.CTkLabel(self.hetero_frame, text="No hetero residues found",
                         text_color="gray").pack(anchor="w")
            return

        for het in heteros:
            row = ctk.CTkFrame(self.hetero_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            include_var = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(row, text=het.label(), variable=include_var,
                            width=300).pack(side="left")
            ctk.CTkLabel(row, text="segname:", text_color="gray").pack(side="left", padx=(6, 2))
            segname_var = tk.StringVar(value=het.default_segname())
            ctk.CTkEntry(row, textvariable=segname_var, width=70).pack(side="left")
            self.hetero_rows.append(
                {"hetero": het, "include_var": include_var, "segname_var": segname_var})

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

        if info.missing_residues:
            ctk.CTkLabel(
                self.warn_frame,
                text=f"⚠  {info.missing_residues} missing residue(s) (REMARK 465) — "
                     "guesscoord will build approximate coordinates",
                text_color="orange",
            ).pack(anchor="w", pady=2)

        if info.missing_atoms:
            ctk.CTkLabel(
                self.warn_frame,
                text=f"⚠  {info.missing_atoms} residue(s) with missing atoms (REMARK 470)",
                text_color="orange",
            ).pack(anchor="w", pady=2)

        if info.chain_gaps:
            shown = ", ".join(info.chain_gaps[:4]) + (" …" if len(info.chain_gaps) > 4 else "")
            ctk.CTkLabel(
                self.warn_frame,
                text=f"⚠  Chain numbering gaps: {shown}",
                text_color="orange",
            ).pack(anchor="w", pady=2)

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
            filetypes=[("CHARMM topology", "*.rtf *.top *.str"), ("All files", "*.*")],
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
        row.pack(fill="x", pady=2, before=self._add_patch_btn)   # keep button last
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
        # .str (CHARMM stream) files also carry RESI topology definitions
        return collect_files(TOPOLOGIES_DIR, (".rtf", ".top", ".str")) + self.ligand_topology_files

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

    def _collect_hetero_segments(self) -> list[HeteroSegment]:
        result = []
        for r in self.hetero_rows:
            if r["include_var"].get():
                het = r["hetero"]
                segname = r["segname_var"].get().strip() or het.default_segname()
                result.append(HeteroSegment(segname=segname, resname=het.resname,
                                            chain=het.chain))
        if self.keep_water_var.get():
            wname = self.water_segname_var.get().strip() or "XWAT"
            result.append(HeteroSegment(segname=wname, resname="HOH",
                                        chain="", selection="water"))
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

    # ------------------------------------------------------------------ #
    #  Summary & presets                                                   #
    # ------------------------------------------------------------------ #

    def _show_summary(self):
        if not self.pdb_info:
            messagebox.showinfo("Summary", "Load a PDB file first.")
            return
        info = self.pdb_info
        segs = self._collect_segments()
        het  = self._collect_hetero_segments()
        patches = self._collect_patches()
        lines = [
            f"PDB: {os.path.basename(self.pdb_var.get())}",
            f"Protein chains: {len(segs)}  ({', '.join(s.chain for s in segs)})",
            f"Histidines: {len(self.his_rows)}",
            f"Hetero segments to build: {len(het)}"
            + (f"  ({', '.join(h.segname for h in het)})" if het else ""),
            f"Patches (incl. SS): {len(patches)}",
            f"Missing residues: {info.missing_residues} · missing atoms: {info.missing_atoms}",
            f"Chain gaps: {len(info.chain_gaps)}",
            "",
            f"Box padding: {self.padding_var.get()} Å"
            + ("  + rotate" if self.rotate_var.get() else "")
            + ("  + recenter" if self.recenter_var.get() else ""),
        ]
        if self.ionize_var.get():
            sc = self.salt_var.get()
            lines.append(f"Ionize: neutralize"
                         + (f" + {sc} M {self.cation_var.get()}/{self.anion_var.get()}" if sc > 0 else "")
                         + f"  (cation {self.cation_var.get()}, anion {self.anion_var.get()})")
        else:
            lines.append("Ionize: off")
        messagebox.showinfo("System summary", "\n".join(lines))

    def _preset_dict(self) -> dict:
        return {
            "padding": self.padding_var.get(),
            "rotate": self.rotate_var.get(),
            "recenter": self.recenter_var.get(),
            "ionize": self.ionize_var.get(),
            "salt": self.salt_var.get(),
            "cation": self.cation_var.get(),
            "anion": self.anion_var.get(),
            "guesscoord": self.guesscoord_var.get(),
            "regen_angles": self.regen_angles_var.get(),
            "regen_dihedrals": self.regen_dihedrals_var.get(),
            "regen_resids": self.regen_resids_var.get(),
            "segments": {r["chain"]: {"first": r["first_var"].get(),
                                      "last": r["last_var"].get()}
                         for r in self.segment_rows},
            "histidines": {f'{r["his"].chain}:{r["his"].resid}': r["prot_var"].get()
                           for r in self.his_rows},
            "ss_disabled": [str(r["bond"]) for r in self.ss_rows
                            if not r["enabled_var"].get()],
            "patches": [{"name": p.name, "chain1": p.chain1, "resid1": p.resid1,
                         "chain2": p.chain2, "resid2": p.resid2}
                        for p in (row.to_patch() for row in self.patch_rows) if p],
            "hetero": {f'{r["hetero"].resname}:{r["hetero"].chain}':
                       {"include": r["include_var"].get(),
                        "segname": r["segname_var"].get()}
                       for r in self.hetero_rows},
            "ligand_topology_files": self.ligand_topology_files,
            "ligand_parameter_files": self.ligand_parameter_files,
        }

    def _save_preset(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Preset", "*.json"), ("All files", "*.*")])
        if not path:
            return
        with open(path, "w") as f:
            json.dump(self._preset_dict(), f, indent=2)
        messagebox.showinfo("Preset", f"Preset saved to:\n{path}")

    def _load_preset(self):
        path = filedialog.askopenfilename(
            filetypes=[("Preset", "*.json"), ("All files", "*.*")])
        if not path:
            return
        with open(path) as f:
            d = json.load(f)

        # scalars
        self.padding_var.set(d.get("padding", 10.0))
        self.rotate_var.set(d.get("rotate", False))
        self.recenter_var.set(d.get("recenter", False))
        self.ionize_var.set(d.get("ionize", True))
        self.salt_var.set(d.get("salt", 0.0))
        self.cation_var.set(d.get("cation", "Na+ (SOD)"))
        self.anion_var.set(d.get("anion", "Cl- (CLA)"))
        self.guesscoord_var.set(d.get("guesscoord", True))
        self.regen_angles_var.set(d.get("regen_angles", True))
        self.regen_dihedrals_var.set(d.get("regen_dihedrals", True))
        self.regen_resids_var.set(d.get("regen_resids", False))
        self._toggle_salt()

        # ligand files
        self.ligand_topology_files = list(d.get("ligand_topology_files", []))
        self.ligand_parameter_files = list(d.get("ligand_parameter_files", []))
        self.ligand_topo_label.configure(
            text=f"{len(self.ligand_topology_files)} file(s)" if self.ligand_topology_files else "None")
        self.ligand_param_label.configure(
            text=f"{len(self.ligand_parameter_files)} file(s)" if self.ligand_parameter_files else "None")

        # per-residue settings (only if a PDB with matching items is loaded)
        for r in self.segment_rows:
            s = d.get("segments", {}).get(r["chain"])
            if s:
                r["first_var"].set(s.get("first", "NTER"))
                r["last_var"].set(s.get("last", "CTER"))
        for r in self.his_rows:
            key = f'{r["his"].chain}:{r["his"].resid}'
            if key in d.get("histidines", {}):
                r["prot_var"].set(d["histidines"][key])
        ss_disabled = set(d.get("ss_disabled", []))
        for r in self.ss_rows:
            r["enabled_var"].set(str(r["bond"]) not in ss_disabled)
        for r in self.hetero_rows:
            key = f'{r["hetero"].resname}:{r["hetero"].chain}'
            h = d.get("hetero", {}).get(key)
            if h:
                r["include_var"].set(h.get("include", False))
                r["segname_var"].set(h.get("segname", r["segname_var"].get()))

        # custom patches
        for row in list(self.patch_rows):
            self._remove_patch_row(row)
        for p in d.get("patches", []):
            self._add_patch_row()
            row = self.patch_rows[-1]
            row.name_var.set(p.get("name", ""))
            row.chain1_var.set(p.get("chain1", ""))
            row.resid1_var.set(p.get("resid1", ""))
            row.chain2_var.set(p.get("chain2", ""))
            row.resid2_var.set(p.get("resid2", ""))

        messagebox.showinfo("Preset", "Preset loaded.\n"
                            "Load the matching PDB first for per-residue settings to apply.")

    def _log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self._scan_for_problems(text)

    # psfgen / solvate messages that indicate a problem worth surfacing
    _PROBLEM_PATTERNS = (
        "unknown residue", "failed to set coordinate", "poorly guessed",
        "failed to guess", "bad bond", "duplicate", "ERROR", "error:",
        "couldn't find", "warning: missing",
    )

    def _scan_for_problems(self, line: str):
        low = line.lower()
        for pat in self._PROBLEM_PATTERNS:
            if pat.lower() in low:
                self._problems.append(line.strip())
                break

    # ------------------------------------------------------------------ #
    #  Build                                                               #
    # ------------------------------------------------------------------ #

    def _build_script_or_none(self) -> str | None:
        """Validate inputs and write the build.tcl. Returns its path or None."""
        pdb    = self.pdb_var.get().strip()
        outdir = self.outdir_var.get().strip()

        if not pdb or not os.path.isfile(pdb):
            messagebox.showerror("Error", "Select a valid PDB file.")
            return None
        if not outdir:
            messagebox.showerror("Error", "Select an output directory.")
            return None

        topology_files = self._collect_topology_files()
        if not topology_files:
            messagebox.showerror("Error", "No topology files found in topologies/.")
            return None

        segments = self._collect_segments()
        if not segments:
            messagebox.showerror("Error", "No chains detected. Load a PDB file first.")
            return None

        # Validate hetero / water segment names (psfgen: ≤4 chars, unique)
        hetero_segments = self._collect_hetero_segments()
        seen_segids = {s.chain for s in segments}
        for h in hetero_segments:
            if not h.segname.isalnum() or len(h.segname) > 4:
                messagebox.showerror(
                    "Invalid segname",
                    f"Segment name '{h.segname}' must be 1–4 alphanumeric characters.")
                return None
            if h.segname in seen_segids:
                messagebox.showerror(
                    "Duplicate segname",
                    f"Segment name '{h.segname}' collides with another chain/segment.")
                return None
            seen_segids.add(h.segname)

        # Parameter coverage check — only for residues that are actually built
        # (included hetero segments). Standard protein residues are covered; any
        # hetero not selected here is simply left out by psfgen, so it's not a
        # problem. Crystal water (TIP3) is covered by the water topology.
        missing = uncovered_built_residues(
            [h.resname for h in hetero_segments if not h.selection], topology_files)
        if missing:
            shown = ", ".join(missing)
            if not messagebox.askyesno(
                    "Missing topology",
                    f"These hetero segments are set to be built but their residue is "
                    f"not defined in the loaded topologies:\n\n{shown}\n\n"
                    "psfgen will fail with 'unknown residue'. Load matching "
                    "topology/parameters, or untick them.\n\nContinue anyway?"):
                return None

        return write_build_script(
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
            cation=CATION_TYPES.get(self.cation_var.get(), "SOD"),
            anion=ANION_TYPES.get(self.anion_var.get(), "CLA"),
            hetero_segments=hetero_segments,
            guesscoord=self.guesscoord_var.get(),
            regenerate_angles=self.regen_angles_var.get(),
            regenerate_dihedrals=self.regen_dihedrals_var.get(),
            regenerate_resids=self.regen_resids_var.get(),
        )

    def _preview_script(self):
        script = self._build_script_or_none()
        if not script:
            return
        with open(script) as f:
            content = f.read()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", f"# Preview: {script}\n# (not executed)\n\n{content}")
        self.log_box.see("1.0")
        self.log_box.configure(state="disabled")

    def _run(self):
        vmd = self.config.get("vmd_path", "").strip()
        if not vmd or not os.path.isfile(vmd):
            messagebox.showerror("Error", "VMD binary not found. Check Settings.")
            return

        script = self._build_script_or_none()
        if not script:
            return

        self._problems = []
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._log(f"Running VMD: {script}")

        run_vmd(
            vmd_path=vmd,
            tcl_script=script,
            on_output=lambda line: self.after(0, self._log, line),
            on_done=lambda ok: self.after(0, self._on_done, ok),
            cwd=self.outdir_var.get().strip(),
        )

    def _on_done(self, success: bool):
        problems = getattr(self, "_problems", [])
        if not success:
            self._log("\nBuild failed. Check the log above.")
            messagebox.showerror("Failed", "VMD exited with an error.")
            return

        if problems:
            preview = "\n".join(f"  • {p}" for p in problems[:12])
            more = f"\n…and {len(problems) - 12} more" if len(problems) > 12 else ""
            self._log(f"\nBuild finished with {len(problems)} warning(s):\n{preview}{more}")
            messagebox.showwarning(
                "Build finished with warnings",
                f"{len(problems)} potential problem(s) detected in the psfgen log.\n"
                "Review the log — coordinates may have been guessed or residues skipped.",
            )
        else:
            self._log("\nBuild complete — no problems detected.")
            messagebox.showinfo("Done", "Structure built successfully.")
