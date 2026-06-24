from __future__ import annotations

import os
import subprocess
import tempfile

from core.molecule_groups import MolGroup


WATER_SELECTION = "water or resname HOH WAT TIP3 SOL H2O TIP"
CARBON_SELECTION = "element C"
CARBON_GREEN_COLOR_ID = 7


class VMDViewerController:
    """Owns one interactive VMD process and replaces its scene on demand."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._vmd_path: str | None = None
        self._tmp_dir: str | None = None
        self._command_path: str | None = None
        self._command_id_path: str | None = None
        self._command_counter = 0

    def show_groups(
        self,
        vmd_path: str,
        pdb_path: str,
        groups: list[MolGroup],
        selected_ids: set[str],
    ) -> subprocess.Popen:
        script = _group_view_script(pdb_path, groups, selected_ids)
        return self._send(vmd_path, script)

    def show_residue_focus(
        self,
        vmd_path: str,
        pdb_path: str,
        chain: str,
        resid: str,
        title: str | None = None,
    ) -> subprocess.Popen:
        script = _residue_focus_script(pdb_path, chain, resid, title or f"{chain}:{resid}")
        return self._send(vmd_path, script)

    def show_altloc_focus(
        self,
        vmd_path: str,
        focus_pdb_text: str,
        title: str,
        alt_codes: list[str] | None = None,
    ) -> subprocess.Popen:
        self._ensure_process(vmd_path)
        assert self._tmp_dir is not None
        pdb_path = os.path.join(self._tmp_dir, "altloc_focus.pdb")
        with open(pdb_path, "w") as f:
            f.write(focus_pdb_text)
        script = _altloc_focus_script(pdb_path, title, alt_codes)
        return self._send(vmd_path, script)

    def is_open(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _send(self, vmd_path: str, script: str) -> subprocess.Popen:
        self._ensure_process(vmd_path)
        assert self._process is not None
        assert self._command_path is not None
        assert self._command_id_path is not None

        self._command_counter += 1
        command_id = str(self._command_counter)
        _atomic_write(self._command_path, script)
        _atomic_write(self._command_id_path, command_id)
        return self._process

    def _ensure_process(self, vmd_path: str):
        if not vmd_path or not os.path.isfile(vmd_path):
            raise FileNotFoundError("VMD binary not found. Check Settings.")
        if (
            self._process is not None
            and self._process.poll() is None
            and self._vmd_path == vmd_path
        ):
            return

        self._tmp_dir = tempfile.mkdtemp(prefix="easynamd_vmd_")
        self._command_path = os.path.join(self._tmp_dir, "command.tcl")
        self._command_id_path = os.path.join(self._tmp_dir, "command.id")
        bootstrap_path = os.path.join(self._tmp_dir, "viewer_bootstrap.tcl")
        _atomic_write(self._command_path, "")
        _atomic_write(self._command_id_path, "")
        _atomic_write(bootstrap_path, _bootstrap_script(self._command_path, self._command_id_path))

        self._process = subprocess.Popen([vmd_path, "-e", bootstrap_path], cwd=self._tmp_dir)
        self._vmd_path = vmd_path
        self._command_counter = 0


def launch_group_view(
    vmd_path: str,
    pdb_path: str,
    groups: list[MolGroup],
    selected_ids: set[str],
) -> subprocess.Popen:
    return VMDViewerController().show_groups(vmd_path, pdb_path, groups, selected_ids)


def launch_residue_focus_view(
    vmd_path: str,
    pdb_path: str,
    chain: str,
    resid: str,
    title: str | None = None,
) -> subprocess.Popen:
    return VMDViewerController().show_residue_focus(vmd_path, pdb_path, chain, resid, title)


def launch_altloc_focus_view(
    vmd_path: str,
    focus_pdb_text: str,
    title: str,
    alt_codes: list[str] | None = None,
) -> subprocess.Popen:
    return VMDViewerController().show_altloc_focus(vmd_path, focus_pdb_text, title, alt_codes)


def _group_view_script(pdb_path: str, groups: list[MolGroup], selected_ids: set[str]) -> str:
    reps: list[str] = []
    reps.extend(_add_atom_reps("all", "Lines 0.45"))
    for group in groups:
        if group.group_id not in selected_ids:
            continue
        selection = _group_selection(group)
        if not selection:
            continue
        if group.group_type == "protein":
            reps.append(_add_rep(selection, "NewCartoon 0.35 10.0 4.1 0", "ColorID 0"))
        elif group.group_type == "water":
            reps.extend(_add_atom_reps(selection, "VDW 0.18 8.0"))
        elif group.group_type == "metal":
            reps.extend(_add_atom_reps(selection, "VDW 0.65 16.0"))
        else:
            reps.extend(_add_atom_reps(selection, "Licorice 0.22 12.0 12.0"))
    return _script_header(pdb_path, "easyNAMD group view") + "\n".join(reps) + _script_footer()


def _residue_focus_script(pdb_path: str, chain: str, resid: str, title: str) -> str:
    res_sel = _and_selection([_chain_selection(chain), f"resid {resid}"])
    env_sel = f"same residue as within 5 of ({res_sel})"
    reps = []
    reps.extend(_add_atom_reps("all", "Lines 0.35"))
    reps.extend(_add_atom_reps(env_sel, "Licorice 0.12 8.0 8.0"))
    reps.extend(_add_atom_reps(res_sel, "Licorice 0.28 16.0 16.0"))
    return (
        _script_header(pdb_path, f"easyNAMD {title}")
        + "\n".join(reps)
        + f"\nset sel [atomselect top {{{res_sel}}}]\n$sel frame 0\nmolinfo top set center [measure center $sel]\n$sel delete\n"
        + _script_footer()
    )


def _altloc_focus_script(pdb_path: str, title: str, alt_codes: list[str] | None = None) -> str:
    alt_codes = alt_codes or list("ABCDEFGHI")
    reps = []
    reps.extend(_add_atom_reps("all", "Lines 0.35"))
    reps.extend(_add_atom_reps("not chain 1 2 3 4 5 6 7 8 9", "Licorice 0.12 8.0 8.0"))
    for i, code in enumerate(alt_codes, start=1):
        selection = f"chain {i}"
        reps.append(_add_rep(_and_selection([selection, f"not ({CARBON_SELECTION})"]),
                             "Licorice 0.28 16.0 16.0", "Name"))
        reps.append(_add_rep(_and_selection([selection, CARBON_SELECTION]),
                             "Licorice 0.28 16.0 16.0", f"ColorID {_alt_color_id(code)}"))
    return _script_header(pdb_path, f"easyNAMD {title}") + "\n".join(reps) + _script_footer()


def _script_header(pdb_path: str, title: str) -> str:
    return f"""\
easyNAMD_clear_scene
display projection Orthographic
display depthcue off
axes location Off
color Display Background white
color Name C green
mol new [list {{{_tcl_text(pdb_path)}}}] type pdb waitfor all
mol delrep 0 top
catch {{wm title . {{{_tcl_text(title)}}}}}
"""


def _script_footer() -> str:
    return """
mol selection all
mol representation Lines
mol color Name
mol material Opaque
display resetview
"""


def _add_rep(selection: str, representation: str, color: str) -> str:
    return f"""\
mol selection {{{_tcl_text(selection)}}}
mol representation {representation}
mol color {color}
mol material Opaque
mol addrep top
"""


def _add_atom_reps(selection: str, representation: str) -> list[str]:
    noncarbon = _and_selection([selection, f"not ({CARBON_SELECTION})"])
    carbon = _and_selection([selection, CARBON_SELECTION])
    return [
        _add_rep(noncarbon, representation, "Name"),
        _add_rep(carbon, representation, f"ColorID {CARBON_GREEN_COLOR_ID}"),
    ]


def _group_selection(group: MolGroup) -> str:
    if group.group_type == "protein":
        return _and_selection(["protein", _chain_selection(group.chain)])
    if group.group_type == "water":
        return WATER_SELECTION
    resnames = " ".join(sorted(name for name in group.resnames if name))
    if not resnames:
        return ""
    return f"resname {resnames}"


def _chain_selection(chain: str) -> str:
    return f"chain {chain}" if chain else "chain \"\""


def _and_selection(parts: list[str]) -> str:
    return " and ".join(f"({part})" for part in parts if part)


def _alt_color_id(code: str) -> int:
    if code and code[0].isalpha():
        return ord(code[0].upper()) - ord("A")
    return 0


def _tcl_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _bootstrap_script(command_path: str, command_id_path: str) -> str:
    return f"""\
display projection Orthographic
display depthcue off
axes location Off
color Display Background white
catch {{wm title . {{easyNAMD VMD viewer}}}}

set ::easyNAMD_command_file {{{_tcl_text(command_path)}}}
set ::easyNAMD_command_id_file {{{_tcl_text(command_id_path)}}}
set ::easyNAMD_last_command_id {{}}

proc easyNAMD_clear_scene {{}} {{
    foreach molid [molinfo list] {{
        mol delete $molid
    }}
}}

proc easyNAMD_read_text {{path}} {{
    set fh [open $path r]
    set text [read $fh]
    close $fh
    return $text
}}

proc easyNAMD_poll {{}} {{
    if {{[file exists $::easyNAMD_command_id_file]}} {{
        set command_id [string trim [easyNAMD_read_text $::easyNAMD_command_id_file]]
        if {{$command_id ne "" && $command_id ne $::easyNAMD_last_command_id}} {{
            set ::easyNAMD_last_command_id $command_id
            if {{[file exists $::easyNAMD_command_file]}} {{
                set script [easyNAMD_read_text $::easyNAMD_command_file]
                if {{[string trim $script] ne ""}} {{
                    if {{[catch {{uplevel #0 $script}} err opts]}} {{
                        puts "easyNAMD viewer error: $err"
                        puts [dict get $opts -errorinfo]
                    }}
                }}
            }}
        }}
    }}
    after 250 easyNAMD_poll
}}

easyNAMD_poll
"""


def _atomic_write(path: str, text: str):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(text)
    os.replace(tmp_path, path)
