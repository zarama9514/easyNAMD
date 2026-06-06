"""
Embedded 3D molecular viewer using VTK (via vedo) inside a tkinter frame.
Groups are rendered as:
  - Highlighted  → VDW spheres with CPK colours
  - Others       → small faded spheres (group colour, low opacity)
"""

import tkinter as tk
import numpy as np

try:
    import vtk
    from vtk.tk.vtkTkRenderWindowInteractor import vtkTkRenderWindowInteractor
    import vedo
    VTK_OK = True
except ImportError:
    VTK_OK = False

from core.molecule_groups import MolGroup

# Faded representation settings for non-highlighted groups
FADE_OPACITY   = 0.12
FADE_RADIUS    = 0.4   # Å — small dot
SPHERE_RES     = 8     # phi/theta resolution for VDW spheres
MAX_FADE_ATOMS = 8000  # skip rendering groups larger than this when faded


def _np_colors_01(cpk_list: list[tuple]) -> np.ndarray:
    """Convert list of (R,G,B) 0-255 tuples to Nx3 float array 0-1."""
    return np.array(cpk_list, dtype=np.float32) / 255.0


class MolViewer(tk.Frame):
    """A tkinter frame containing an interactive VTK 3-D viewer."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg='#15151e', **kwargs)

        if not VTK_OK:
            tk.Label(
                self,
                text="3D viewer requires vedo:\n  uv add vedo",
                bg='#15151e', fg='#888888', font=('', 12),
                justify='center',
            ).pack(expand=True)
            self._ready = False
            return

        self._ready = True
        self._actors: list = []
        self._setup_vtk()

    # ------------------------------------------------------------------ #
    #  VTK setup                                                           #
    # ------------------------------------------------------------------ #

    def _setup_vtk(self):
        self._vtkWidget = vtkTkRenderWindowInteractor(self, width=1, height=1)
        self._vtkWidget.pack(fill='both', expand=True)

        self._renderer = vtk.vtkRenderer()
        self._renderer.SetBackground(0.08, 0.08, 0.12)
        self._vtkWidget.GetRenderWindow().AddRenderer(self._renderer)

        style = vtk.vtkInteractorStyleTrackballCamera()
        self._vtkWidget.SetInteractorStyle(style)
        self._vtkWidget.Initialize()

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def show_groups(self, groups: list[MolGroup], highlighted_id: str | None):
        """Render all groups; highlight one in VDW, fade the rest."""
        if not self._ready:
            return

        self._renderer.RemoveAllViewProps()
        self._actors.clear()

        for group in groups:
            if not group.positions:
                continue

            positions = np.array(group.positions, dtype=np.float32)

            if group.group_id == highlighted_id:
                actor = self._make_vdw_actor(group, positions)
            else:
                if len(positions) > MAX_FADE_ATOMS:
                    continue   # skip huge water boxes when not focused
                actor = self._make_faded_actor(group, positions)

            if actor is not None:
                self._renderer.AddActor(actor)
                self._actors.append(actor)

        self._renderer.ResetCamera()
        self._vtkWidget.GetRenderWindow().Render()

    def clear(self):
        if not self._ready:
            return
        self._renderer.RemoveAllViewProps()
        self._actors.clear()
        self._vtkWidget.GetRenderWindow().Render()

    # ------------------------------------------------------------------ #
    #  Actor builders                                                      #
    # ------------------------------------------------------------------ #

    def _make_vdw_actor(self, group: MolGroup, positions: np.ndarray):
        """VDW spheres with per-atom CPK colours."""
        radii  = np.array(group.vdw_radii, dtype=np.float32)
        colors = _np_colors_01(group.cpk_colors)

        mesh = vedo.Spheres(positions, r=radii, c=colors, res=SPHERE_RES)
        mesh.alpha(1.0)
        return mesh.actor

    def _make_faded_actor(self, group: MolGroup, positions: np.ndarray):
        """Tiny uniform spheres in the group's theme colour, low opacity."""
        hex_color = group.color().lstrip('#')
        r, g, b = (int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4))

        radii = np.full(len(positions), FADE_RADIUS, dtype=np.float32)
        mesh  = vedo.Spheres(positions, r=radii, c=(r, g, b), res=4)
        mesh.alpha(FADE_OPACITY)
        return mesh.actor
