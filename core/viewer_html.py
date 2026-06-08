"""
Build a single self-contained 3Dmol.js page used by the persistent pywebview
window. The page loads the PDB once and exposes global JS functions that the
parent GUI drives via evaluate_js:

  showGroups(selectedIds)          → group view (protein cartoon, het VDW)
  focusAltloc(chain, resi, codes)  → focus one residue: all altLoc conformers
                                     as licorice + 5 A shell as sticks

Selected group  → VDW spheres (CPK) / protein cartoon
Deselected group → faint grey lines / faint cartoon
"""

import json

from core.molecule_groups import AltLocResidue, MolGroup, build_focus_scene_pdb

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
  #panel {{ width: 300px; overflow-y: auto; padding: 10px;
            background: #1e1e28; border-left: 1px solid #333; }}
  #panel h3 {{ margin: 10px 0 8px; font-size: 14px; color: #fff; }}
  .row {{ display: flex; align-items: center; padding: 5px 4px; border-radius: 6px; }}
  .row:hover {{ background: #2a2a36; }}
  .row input {{ margin-right: 8px; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 3px; margin-right: 8px; flex: none; }}
  .label {{ flex: 1; font-size: 13px; }}
  .count {{ font-size: 11px; color: #888; }}
  button {{ background: #3a3a4a; color: #ddd; border: none; border-radius: 5px;
            padding: 4px 10px; cursor: pointer; font-size: 12px; }}
  button:hover {{ background: #4a4a5e; }}
  .focusbtn {{ margin-left: auto; }}
  #legend {{ position: absolute; top: 10px; left: 10px; z-index: 10;
             background: rgba(30,30,40,0.85); padding: 8px 12px; border-radius: 8px;
             font-size: 12px; display: none; }}
  .leg {{ display: flex; align-items: center; margin: 2px 0; }}
  .dot {{ width: 11px; height: 11px; border-radius: 50%; margin-right: 7px; }}
</style>
</head>
<body>
<div id="wrap">
  <div id="gl"><div id="legend"></div></div>
  <div id="panel">
    <button onclick="showGroups(currentSelection())" style="width:100%;margin-bottom:8px;">
      Show all groups
    </button>
    <h3>Molecular groups</h3>
    <div id="rows"></div>
    <h3>Alternative locations</h3>
    <div id="altrows"></div>
  </div>
</div>

<script id="pdbdata"   type="text/plain">{pdb_text}</script>
<script id="groupdata" type="application/json">{group_json}</script>
<script id="altdata"   type="application/json">{altloc_json}</script>

<script>
const pdb     = document.getElementById('pdbdata').textContent;
const GROUPS  = JSON.parse(document.getElementById('groupdata').textContent);
const ALTLOCS = JSON.parse(document.getElementById('altdata').textContent);

// 3Dmol carbon colour schemes: C atoms tinted, heteroatoms keep CPK colours
const ALT_SCHEMES = ['greenCarbon', 'orangeCarbon', 'purpleCarbon',
                     'yellowCarbon', 'cyanCarbon'];
const ALT_DISPLAY = ['#33dd66', '#ff8833', '#cc66ff', '#ffdd33', '#33ccff'];

const viewer = $3Dmol.createViewer(document.getElementById('gl'),
                                   {{ backgroundColor: '#15151e' }});
const mainModel = viewer.addModel(pdb, 'pdb');
let focusModel = null;

// ---- group styling (scoped to the main model) ------------------------ //
function applyGroupStyle(g, on) {{
  if (g.type === 'protein') {{
    mainModel.setStyle(g.sel, on
      ? {{ cartoon: {{ color: 'spectrum' }} }}
      : {{ cartoon: {{ color: 'gray', opacity: 0.3 }} }});
  }} else {{
    mainModel.setStyle(g.sel, on
      ? {{ sphere: {{}} }}
      : {{ line: {{ color: 'gray' }} }});
  }}
}}

function currentSelection() {{
  return GROUPS.filter(g => {{
    const cb = document.getElementById('cb_' + g.id);
    return cb ? cb.checked : g.selected;
  }}).map(g => g.id);
}}

function clearFocus() {{
  if (focusModel) {{ viewer.removeModel(focusModel); focusModel = null; }}
  document.getElementById('legend').style.display = 'none';
}}

// Group view: restyle the whole structure and exit any focus mode.
function showGroups(selectedIds) {{
  clearFocus();
  GROUPS.forEach(g => applyGroupStyle(g, selectedIds.indexOf(g.id) !== -1));
  viewer.zoomTo();
  viewer.render();
}}

// Focus one residue. The whole scene (residue conformers + 5 A environment)
// comes from one dedicated model (focusPdb) so 3Dmol re-derives all bonds by
// distance — peptide bonds to neighbours stay intact. Conformers sit on private
// chains ('0' = common/backbone, confChains[i] = each altLoc code); the
// environment keeps its original (letter) chains.
function focusAltloc(chain, resi, focusPdb, confChains, codes) {{
  // hide the main model entirely while focusing
  mainModel.setStyle({{}}, {{}});

  clearFocus();
  focusModel = viewer.addModel(focusPdb, 'pdb');

  // environment (everything) → thin grey sticks
  focusModel.setStyle({{}}, {{ stick: {{ radius: 0.08, colorscheme: 'grayCarbon' }} }});
  // residue common/backbone → medium grey
  focusModel.setStyle({{ chain: '0' }},
                      {{ stick: {{ radius: 0.18, colorscheme: 'grayCarbon' }} }});

  const legend = document.getElementById('legend');
  let html = '<div style="font-weight:600;margin-bottom:4px;">' +
             chain + ':' + resi + '</div>';
  codes.forEach((code, i) => {{
    focusModel.setStyle({{ chain: confChains[i] }},
                        {{ stick: {{ radius: 0.25, colorscheme: ALT_SCHEMES[i % ALT_SCHEMES.length] }} }});
    html += '<div class="leg"><span class="dot" style="background:' +
            ALT_DISPLAY[i % ALT_DISPLAY.length] + ';"></span>altLoc ' + code + '</div>';
  }});
  html += '<div class="leg"><span class="dot" style="background:#888;"></span>within 5 Å</div>';
  legend.innerHTML = html;
  legend.style.display = 'block';

  // zoom to the residue (its private chains)
  viewer.zoomTo({{ chain: ['0'].concat(confChains) }});
  viewer.render();
}}

function report() {{
  const ids = currentSelection();
  if (window.pywebview && window.pywebview.api) {{
    window.pywebview.api.set_selection(JSON.stringify(ids));
  }}
}}

// ---- build side panel ------------------------------------------------- //
const rows = document.getElementById('rows');
GROUPS.forEach(g => {{
  const row = document.createElement('label');
  row.className = 'row';
  row.innerHTML =
    '<input type="checkbox" id="cb_' + g.id + '"' + (g.selected ? ' checked' : '') + '>' +
    '<span class="swatch" style="background:' + g.color + ';"></span>' +
    '<span class="label">' + g.label + '</span>' +
    '<span class="count">' + g.count + '</span>';
  const cb = row.querySelector('input');
  cb.onchange = () => {{ showGroups(currentSelection()); report(); }};
  rows.appendChild(row);
}});

const altrows = document.getElementById('altrows');
if (ALTLOCS.length === 0) {{
  altrows.innerHTML = '<div class="count" style="padding:4px;">none</div>';
}}
ALTLOCS.forEach(a => {{
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = '<span class="label">' + a.label + '</span>';
  const btn = document.createElement('button');
  btn.className = 'focusbtn';
  btn.textContent = 'Focus';
  btn.onclick = () => focusAltloc(a.chain, a.resi, a.focuspdb, a.confchains, a.codes);
  row.appendChild(btn);
  altrows.appendChild(row);
}});

// initial render
showGroups(currentSelection());
</script>
</body>
</html>
"""


def build_viewer_html(
    pdb_file: str,
    groups: list[MolGroup],
    selected_ids: set[str],
    altlocs: list[AltLocResidue],
    output_html: str,
) -> str:
    """Write the persistent viewer page and return its path."""
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

    altloc_data = []
    for a in altlocs:
        focus_pdb, conf_map = build_focus_scene_pdb(pdb_file, a)
        altloc_data.append({
            'label':      a.label(),
            'chain':      a.chain,
            'resi':       int(a.resid),
            'codes':      a.codes,
            'focuspdb':   focus_pdb,
            'confchains': [chain for _code, chain in conf_map],
        })

    html = _TEMPLATE.format(
        pdb_text=pdb_text,
        group_json=json.dumps(group_data),
        altloc_json=json.dumps(altloc_data),
    )

    with open(output_html, 'w') as f:
        f.write(html)
    return output_html


# ------------------------------------------------------------------ #
#  Standalone residue focus (e.g. histidine environment)              #
# ------------------------------------------------------------------ #

_RESIDUE_FOCUS_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://3Dmol.org/build/3Dmol-min.js"></script>
<style>
  html, body {{ margin: 0; height: 100%; background: #15151e; }}
  #gl {{ width: 100vw; height: 100vh; position: relative; }}
  #legend {{ position: absolute; top: 10px; left: 10px; z-index: 10;
             background: rgba(30,30,40,0.85); padding: 8px 12px; border-radius: 8px;
             font-family: -apple-system, sans-serif; color: #ddd; font-size: 13px; }}
</style>
</head>
<body>
<div id="gl"></div>
<div id="legend">{title} — heavy atoms (licorice) + 5 Å environment (sticks)</div>

<script id="pdbdata" type="text/plain">{pdb_text}</script>
<script>
const pdb = document.getElementById('pdbdata').textContent;
const viewer = $3Dmol.createViewer(document.getElementById('gl'),
                                   {{ backgroundColor: '#15151e' }});
viewer.addModel(pdb, 'pdb');

const resSel = {res_sel};

// dim everything
viewer.setStyle({{}}, {{ line: {{ color: 'gray', opacity: 0.25 }} }});
// 5 A environment, whole residues, as thin sticks
viewer.setStyle({{ within: {{ distance: 5.0, sel: resSel }}, byres: true }},
                {{ stick: {{ radius: 0.1, colorscheme: 'grayCarbon' }} }});
// the residue itself as thick licorice
viewer.setStyle(resSel, {{ stick: {{ radius: 0.22, colorscheme: 'cyanCarbon' }} }});
// hide all hydrogens (show heavy atoms only)
viewer.setStyle({{ elem: 'H' }}, {{}});

viewer.zoomTo(resSel);
viewer.render();
</script>
</body>
</html>
"""


def build_residue_focus_html(
    pdb_file: str,
    chain: str,
    resid: str,
    output_html: str,
    title: str = "",
) -> str:
    """Standalone viewer focused on one residue: its heavy atoms as licorice and
    everything within 5 A (whole residues) as sticks. Used to inspect a residue's
    environment (e.g. choosing histidine protonation)."""
    with open(pdb_file) as f:
        pdb_text = f.read()

    res_sel = {'chain': chain, 'resi': int(resid)}
    html = _RESIDUE_FOCUS_TEMPLATE.format(
        title=title or f"{chain}:{resid}",
        pdb_text=pdb_text,
        res_sel=json.dumps(res_sel),
    )
    with open(output_html, 'w') as f:
        f.write(html)
    return output_html
