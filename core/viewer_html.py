"""
Build a self-contained 3Dmol.js HTML page for previewing/selecting PDB groups.

Selected group  → VDW spheres (CPK element colours)
Deselected group → faint grey lines

Toggling a checkbox in the page updates the WebGL view live and reports the
current selection back to Python via pywebview's js_api.
"""

import json
import os

from core.molecule_groups import AltLocResidue, MolGroup

_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://3Dmol.org/build/3Dmol-min.js"></script>
<style>
  html, body {{ margin: 0; height: 100%; background: #15151e;
                font-family: -apple-system, sans-serif; color: #ddd; }}
  #wrap {{ display: flex; height: 100vh; }}
  #gl {{ flex: 1; position: relative; }}
  #panel {{ width: 280px; overflow-y: auto; padding: 10px;
            background: #1e1e28; border-left: 1px solid #333; }}
  #panel h3 {{ margin: 6px 0 12px; font-size: 14px; color: #fff; }}
  .row {{ display: flex; align-items: center; padding: 6px 4px;
          border-radius: 6px; }}
  .row:hover {{ background: #2a2a36; }}
  .row input {{ margin-right: 8px; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 3px;
             margin-right: 8px; flex: none; }}
  .label {{ flex: 1; font-size: 13px; }}
  .count {{ font-size: 11px; color: #888; }}
</style>
</head>
<body>
<div id="wrap">
  <div id="gl"></div>
  <div id="panel">
    <h3>Molecular groups</h3>
    <div id="rows"></div>
  </div>
</div>

<script id="pdbdata" type="text/plain">{pdb_text}</script>
<script id="groupdata" type="application/json">{group_json}</script>

<script>
const pdb    = document.getElementById('pdbdata').textContent;
const groups = JSON.parse(document.getElementById('groupdata').textContent);

const viewer = $3Dmol.createViewer(document.getElementById('gl'),
                                   {{ backgroundColor: '#15151e' }});
viewer.addModel(pdb, 'pdb');

function applyStyle(g, on) {{
  if (g.type === 'protein') {{
    if (on) {{
      viewer.setStyle(g.sel, {{ cartoon: {{ color: 'spectrum' }} }});
    }} else {{
      viewer.setStyle(g.sel, {{ cartoon: {{ color: 'gray', opacity: 0.3 }} }});
    }}
  }} else {{
    if (on) {{
      viewer.setStyle(g.sel, {{ sphere: {{}} }});         // VDW, CPK colours
    }} else {{
      viewer.setStyle(g.sel, {{ line: {{ color: 'gray' }} }});
    }}
  }}
}}

function report() {{
  const ids = groups.filter(g => document.getElementById('cb_' + g.id).checked)
                    .map(g => g.id);
  if (window.pywebview && window.pywebview.api) {{
    window.pywebview.api.set_selection(JSON.stringify(ids));
  }}
}}

const rows = document.getElementById('rows');
groups.forEach(g => {{
  const row = document.createElement('label');
  row.className = 'row';

  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.id = 'cb_' + g.id;
  cb.checked = g.selected;
  cb.onchange = () => {{ applyStyle(g, cb.checked); viewer.render(); report(); }};

  const sw = document.createElement('span');
  sw.className = 'swatch';
  sw.style.background = g.color;

  const lab = document.createElement('span');
  lab.className = 'label';
  lab.textContent = g.label;

  const cnt = document.createElement('span');
  cnt.className = 'count';
  cnt.textContent = g.count + ' atoms';

  row.appendChild(cb);
  row.appendChild(sw);
  row.appendChild(lab);
  row.appendChild(cnt);
  rows.appendChild(row);

  applyStyle(g, g.selected);
}});

viewer.zoomTo();
viewer.render();
</script>
</body>
</html>
"""


def build_html(
    pdb_file: str,
    groups: list[MolGroup],
    selected_ids: set[str],
    output_html: str,
) -> str:
    """Write the viewer HTML and return its path."""
    with open(pdb_file) as f:
        pdb_text = f.read()

    group_data = [
        {
            'id':       g.group_id,
            'label':    g.label,
            'type':     g.group_type,
            'color':    g.color(),
            'count':    g.atom_count(),
            'sel':      g.selection(),
            'selected': g.group_id in selected_ids,
        }
        for g in groups
    ]

    html = _TEMPLATE.format(
        pdb_text=pdb_text,
        group_json=json.dumps(group_data),
    )

    with open(output_html, 'w') as f:
        f.write(html)
    return output_html


# ------------------------------------------------------------------ #
#  AltLoc focused view                                                 #
# ------------------------------------------------------------------ #

# Distinct colours for altLoc conformers (A, B, C, …)
_ALTLOC_COLORS = ['#33dd66', '#ff8833', '#cc66ff', '#ffdd33', '#33ccff']

_ALTLOC_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://3Dmol.org/build/3Dmol-min.js"></script>
<style>
  html, body {{ margin: 0; height: 100%; background: #15151e;
                font-family: -apple-system, sans-serif; color: #ddd; }}
  #gl {{ width: 100vw; height: 100vh; position: relative; }}
  #legend {{ position: absolute; top: 10px; left: 10px; z-index: 10;
             background: rgba(30,30,40,0.85); padding: 10px 14px;
             border-radius: 8px; font-size: 13px; }}
  .leg {{ display: flex; align-items: center; margin: 3px 0; }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }}
</style>
</head>
<body>
<div id="gl"></div>
<div id="legend">
  <div style="font-weight:600; margin-bottom:6px;">{title}</div>
  {legend_rows}
  <div class="leg" style="margin-top:6px;">
    <span class="dot" style="background:#888;"></span>within 5 Å (sticks)
  </div>
</div>

<script id="pdbdata" type="text/plain">{pdb_text}</script>

<script>
const pdb = document.getElementById('pdbdata').textContent;
const viewer = $3Dmol.createViewer(document.getElementById('gl'),
                                   {{ backgroundColor: '#15151e' }});
viewer.addModel(pdb, 'pdb');

const resSel = {res_sel};
const altColors = {alt_colors};

// Everything within 5 Å of the residue → thin sticks
viewer.setStyle({{ within: {{ distance: 5.0, sel: resSel }} }},
                {{ stick: {{ radius: 0.08, colorscheme: 'grayCarbon' }} }});

// Each altLoc conformer → licorice in its own colour
for (const code in altColors) {{
  const sel = Object.assign({{}}, resSel, {{ altloc: code }});
  viewer.setStyle(sel, {{ stick: {{ radius: 0.2, color: altColors[code] }} }});
}}

viewer.zoomTo(resSel);
viewer.render();
</script>
</body>
</html>
"""


def build_altloc_html(
    pdb_file: str,
    residue: AltLocResidue,
    output_html: str,
) -> str:
    """Write a focused viewer: altLoc conformers as licorice, 5 Å shell as sticks."""
    with open(pdb_file) as f:
        pdb_text = f.read()

    res_sel = {'chain': residue.chain, 'resi': int(residue.resid)}

    alt_colors = {
        code: _ALTLOC_COLORS[i % len(_ALTLOC_COLORS)]
        for i, code in enumerate(residue.codes)
    }

    legend_rows = "\n".join(
        f'<div class="leg"><span class="dot" style="background:{alt_colors[c]};"></span>altLoc {c}</div>'
        for c in residue.codes
    )

    html = _ALTLOC_TEMPLATE.format(
        title=residue.label(),
        legend_rows=legend_rows,
        pdb_text=pdb_text,
        res_sel=json.dumps(res_sel),
        alt_colors=json.dumps(alt_colors),
    )

    with open(output_html, 'w') as f:
        f.write(html)
    return output_html
