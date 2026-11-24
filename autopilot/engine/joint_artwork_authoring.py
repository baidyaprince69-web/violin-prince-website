"""Prepare source-aligned lower-body joint artwork for manual artist review.

The tool creates magnified source crops and an empty polygon-authoring template.
It never paints replacement pixels or edits the rig's original limb assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from full_body_performance_rig import _canvas_alpha_mask_for_layer


LOWER_BODY_JOINTS = (
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
)


def _nearest_parent_child_pixels(
    parent_mask: np.ndarray,
    child_mask: np.ndarray,
    *,
    offset_x: int,
    offset_y: int,
) -> tuple[float | None, list[int] | None, list[int] | None]:
    """Return exact nearest pixel coordinates for two local boolean masks."""
    parent_points = np.argwhere(np.asarray(parent_mask, dtype=bool))
    child_points = np.argwhere(np.asarray(child_mask, dtype=bool))
    if not len(parent_points) or not len(child_points):
        return None, None, None

    # The joint crops are small. Chunking keeps the exact pairwise distance
    # calculation bounded without adding a SciPy dependency to the rig tools.
    child_points_f = child_points.astype(np.float32)
    best_distance_sq = float("inf")
    best_parent: np.ndarray | None = None
    best_child: np.ndarray | None = None
    for start in range(0, len(parent_points), 256):
        parent_chunk = parent_points[start:start + 256].astype(np.float32)
        delta = parent_chunk[:, None, :] - child_points_f[None, :, :]
        distances_sq = np.einsum("ijk,ijk->ij", delta, delta)
        flat_index = int(np.argmin(distances_sq))
        row_index, child_index = np.unravel_index(flat_index, distances_sq.shape)
        distance_sq = float(distances_sq[row_index, child_index])
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best_parent = parent_points[start + row_index]
            best_child = child_points[child_index]

    assert best_parent is not None and best_child is not None
    parent_xy = [int(offset_x + best_parent[1]), int(offset_y + best_parent[0])]
    child_xy = [int(offset_x + best_child[1]), int(offset_y + best_child[0])]
    return round(float(np.sqrt(best_distance_sq)), 3), parent_xy, child_xy



def _build_offline_annotator_html(
    template: dict[str, Any],
    character: dict[str, Any],
    *,
    source_filename: str,
    crop_radius: int = 54,
) -> str:
    """Build an offline browser tool for tracing source-coordinate joint polygons."""
    template_json = json.dumps(template, ensure_ascii=False).replace("<", "\\u003c")
    character_json = json.dumps(character, ensure_ascii=False).replace("<", "\\u003c")
    html = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Violin Prince — Joint Artwork Annotator</title>
<style>
:root{color-scheme:dark;--bg:#0c121b;--panel:#141f2b;--line:#314354;--text:#edf3f5;--muted:#a5b7c2;--cyan:#30d9ee;--amber:#ffad45;--magenta:#ff4bdf;--yellow:#ffe26a;--green:#7ce3ae}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(ellipse at 50% -20%,#233b4b 0%,var(--bg) 62%);color:var(--text);font:15px/1.45 system-ui,Segoe UI,Arial,sans-serif}
header{padding:18px 22px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:16px}
h1{font-size:18px;margin:0 0 4px;font-weight:700;letter-spacing:.02em}
header p{margin:0;color:var(--muted);font-size:12px}
main{max-width:1500px;margin:0 auto;padding:16px;display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:16px}
.panel{background:rgba(20,31,43,.94);border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.22)}
.view-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;border-bottom:1px solid var(--line)}
.view-head strong{font-size:14px}
canvas{display:block;width:100%;max-height:76vh;object-fit:contain;background:#192330;cursor:crosshair;touch-action:none}
.controls{padding:14px;display:flex;flex-wrap:wrap;gap:8px;border-top:1px solid var(--line)}
button,select{font:inherit;color:var(--text);background:#203244;border:1px solid #496072;border-radius:9px;padding:9px 12px}
button{cursor:pointer}
button.primary{background:#1a5865;border-color:#2d9eb0}
button.approve{background:#244b3b;border-color:#3c8660}
button:disabled{opacity:.35;cursor:not-allowed}
aside{padding:14px}
.field{display:grid;gap:6px;margin-bottom:14px}
label{font-weight:650;font-size:12px;color:#c3d2dc}
select{width:100%}
.small{font-size:12px;color:var(--muted)}
.status{padding:10px 11px;border:1px solid #3b5264;background:#0d1722;border-radius:9px;font-size:12px;margin:10px 0 14px;white-space:pre-wrap}
.legend{display:grid;gap:7px;margin:12px 0 16px;font-size:12px;color:var(--muted)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px}
.cyan{background:var(--cyan)} .amber{background:var(--amber)} .magenta{background:var(--magenta)} .yellow{background:var(--yellow)} .red{background:#ff5058}
hr{border:0;border-top:1px solid var(--line);margin:15px 0}
.check{display:flex;align-items:flex-start;gap:9px;font-size:12px;color:#d6e2e8}
.check input{margin-top:3px;accent-color:#61cb92}
.notice{font-size:12px;line-height:1.5;padding:10px;background:#2b2519;border:1px solid #786039;border-radius:9px;color:#f3dfb5}
.metric{display:flex;justify-content:space-between;gap:10px;font-size:12px;margin:5px 0;color:var(--muted)}
.metric b{color:var(--text);font-variant-numeric:tabular-nums}
footer{padding:12px 18px;color:var(--muted);font-size:11px;text-align:center}
@media(max-width:900px){main{grid-template-columns:1fr}aside{order:-1}canvas{max-height:64vh}}
</style>
</head>
<body>
<header>
  <div><h1>VIOLIN PRINCE · JOINT ARTWORK ANNOTATOR</h1><p>Offline source-coordinate tracing · original pixels only · review before approval</p></div>
  <div class="small">441 × 755 source canvas</div>
</header>
<main>
  <section class="panel">
    <div class="view-head"><strong id="joint-title">Joint region</strong><span class="small" id="point-count">0 vertices</span></div>
    <canvas id="annotator-canvas"></canvas>
    <div class="controls">
      <button id="undo">Undo point</button>
      <button id="clear">Clear polygon</button>
      <button id="finish" class="primary">Close polygon</button>
      <button id="previous">Previous joint</button>
      <button id="next">Next joint</button>
    </div>
  </section>
  <aside class="panel">
    <div class="field"><label for="joint-select">JOINT REGION</label><select id="joint-select"></select></div>
    <div class="legend">
      <div><i class="dot cyan"></i>Parent layer source pixels</div>
      <div><i class="dot amber"></i>Child layer source pixels</div>
      <div><i class="dot magenta"></i>Shared-alpha overlap evidence only</div>
      <div><i class="dot yellow"></i>Nearest separate parent/child pixels</div>
      <div><i class="dot red"></i>Current mapped joint anchor</div>
      <div><i class="dot" style="background:var(--green)"></i>Your traced polygon</div>
    </div>
    <div id="metrics" class="status">Loading source artwork…</div>
    <div class="field"><label for="approval">ARTWORK REVIEW</label>
      <label class="check"><input type="checkbox" id="approval"><span>I have visually checked this polygon against the original clothing/shoe boundary and approve it for a production-rig test.</span></label>
    </div>
    <div class="notice">The magenta contour is only shared source-pixel overlap evidence. It is not a complete joint surface. Trace the full source-clothing or shoe region needed to bridge the two moving layers. Do not use capsules, circles or generic pads.</div>
    <hr>
    <div class="metric"><span>Polygon vertices</span><b id="metric-vertices">0</b></div>
    <div class="metric"><span>Closed polygon</span><b id="metric-closed">No</b></div>
    <div class="metric"><span>Approval state</span><b id="metric-approval">Draft</b></div>
    <div class="controls" style="padding:10px 0 0;border:0">
      <button id="save" class="approve">Export reviewed JSON</button>
    </div>
    <p class="small">Exported JSON does not change GitHub or the production rig. Review the file before supplying it to the isolated rig workflow.</p>
  </aside>
</main>
<footer>Nothing is uploaded. The source image and rig layers are loaded locally from the extracted review-pack folder.</footer>
<script type="application/json" id="template-data">__TEMPLATE_JSON__</script>
<script type="application/json" id="character-data">__CHARACTER_JSON__</script>
<script>
(function(){
"use strict";
const template=JSON.parse(document.getElementById("template-data").textContent);
const character=JSON.parse(document.getElementById("character-data").textContent);
const regions=template.joint_surfaces.regions;
const names=Object.keys(regions);
const layers=Object.fromEntries((character.layers||[]).map(layer=>[String(layer.role||""),layer]));
const canvas=document.getElementById("annotator-canvas");
const ctx=canvas.getContext("2d");
const select=document.getElementById("joint-select");
const imgCache={};
let activeName=names[0],editPoints=[],closed=false,approved=false;
let crop={x0:0,y0:0,width:1,height:1,scale:5};
const source=new Image();
source.src="../bundle/__SOURCE_FILENAME__";
function imageFor(src){
  if(!imgCache[src]){
    const img=new Image();
    img.src="../bundle/"+src;
    imgCache[src]=img;
  }
  return imgCache[src];
}
function ready(img){return new Promise((resolve,reject)=>{if(img.complete&&img.naturalWidth){resolve(img);return;}img.onload=()=>resolve(img);img.onerror=()=>reject(new Error("Could not load local image: "+img.src));});}
function roleImage(role){const layer=layers[role];if(!layer)throw new Error("Missing rig layer role: "+role);return {layer,image:imageFor(layer.src)};}
function linePolygon(points,color,width,close){
  if(!points||points.length<2)return;
  ctx.beginPath();
  points.forEach((point,index)=>{
    const x=(point[0]-crop.x0)*crop.scale;
    const y=(point[1]-crop.y0)*crop.scale;
    if(index===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
  });
  if(close)ctx.closePath();
  ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();
}
function drawLayerTint(layer,image,color){
  const temp=document.createElement("canvas");
  temp.width=canvas.width;temp.height=canvas.height;
  const t=temp.getContext("2d");
  const x=(Number(layer.x)-crop.x0)*crop.scale;
  const y=(Number(layer.y)-crop.y0)*crop.scale;
  t.drawImage(image,x,y,Number(layer.width)*crop.scale,Number(layer.height)*crop.scale);
  t.globalCompositeOperation="source-in";
  t.fillStyle=color;t.fillRect(0,0,temp.width,temp.height);
  ctx.save();ctx.globalAlpha=.24;ctx.drawImage(temp,0,0);ctx.restore();
}
function drawAnchor(region){
  const point=region.anchor_px||[0,0];
  const x=(point[0]-crop.x0)*crop.scale,y=(point[1]-crop.y0)*crop.scale;
  ctx.save();ctx.strokeStyle="#ff5058";ctx.lineWidth=2.5;
  ctx.beginPath();ctx.moveTo(x-18,y);ctx.lineTo(x+18,y);ctx.moveTo(x,y-18);ctx.lineTo(x,y+18);ctx.stroke();ctx.restore();
}
function drawPoints(){
  if(editPoints.length){
    linePolygon(editPoints,"#7ce3ae",3,closed);
    editPoints.forEach(point=>{
      const x=(point[0]-crop.x0)*crop.scale,y=(point[1]-crop.y0)*crop.scale;
      ctx.beginPath();ctx.arc(x,y,4.5,0,Math.PI*2);ctx.fillStyle="#7ce3ae";ctx.fill();
    });
  }
}
async function render(){
  const region=regions[activeName];
  const parent=roleImage(region.parent_role),child=roleImage(region.child_role);
  await Promise.all([ready(source),ready(parent.image),ready(child.image)]);
  const anchor=region.anchor_px||[source.naturalWidth/2,source.naturalHeight/2];
  const radius=54;
  crop.x0=Math.max(0,Math.round(anchor[0])-radius);
  crop.y0=Math.max(0,Math.round(anchor[1])-radius);
  const x1=Math.min(source.naturalWidth,Math.round(anchor[0])+radius);
  const y1=Math.min(source.naturalHeight,Math.round(anchor[1])+radius);
  crop.width=x1-crop.x0;crop.height=y1-crop.y0;crop.scale=5;
  canvas.width=crop.width*crop.scale;canvas.height=crop.height*crop.scale;
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.drawImage(source,crop.x0,crop.y0,crop.width,crop.height,0,0,canvas.width,canvas.height);
  drawLayerTint(parent.layer,parent.image,"#30d9ee");
  drawLayerTint(child.layer,child.image,"#ffad45");
  if(Array.isArray(region.candidate_source_polygon)&&region.candidate_source_polygon.length>2){
    linePolygon(region.candidate_source_polygon,"#ff4bdf",3,true);
  }
  drawAnchor(region);drawPoints();
  const gap=region.candidate_parent_child_gap_px;
  const details=[
    "Anchor: "+(anchor[0].toFixed(1))+", "+(anchor[1].toFixed(1))+" source px",
    "Layers: "+region.parent_role+" → "+region.child_role,
    "Shared overlap evidence: "+Number(region.candidate_source_pixels||0)+" source pixels",
    "Anchor-local edge gap: "+(gap===null||gap===undefined?"not measurable":gap+" px"),
    "Manual trace reason: "+(region.manual_trace_reason||"overlap evidence only; full surface still needs tracing")
  ].join("\n");
  document.getElementById("metrics").textContent=details;
  document.getElementById("joint-title").textContent=activeName.replaceAll("_"," ").toUpperCase();
  updateControls();
}
function updateControls(){
  document.getElementById("point-count").textContent=editPoints.length+" vertices";
  document.getElementById("metric-vertices").textContent=String(editPoints.length);
  document.getElementById("metric-closed").textContent=closed?"Yes":"No";
  document.getElementById("metric-approval").textContent=approved?"Approved by reviewer":"Draft";
  document.getElementById("approval").checked=approved;
  document.getElementById("undo").disabled=editPoints.length===0;
  document.getElementById("finish").disabled=editPoints.length<3||closed;
  document.getElementById("previous").disabled=names.indexOf(activeName)===0;
  document.getElementById("next").disabled=names.indexOf(activeName)===names.length-1;
}
function loadJoint(name){
  activeName=name;
  const region=regions[name];
  editPoints=Array.isArray(region.artist_source_polygon)?region.artist_source_polygon.map(p=>[Number(p[0]),Number(p[1])]):[];
  closed=editPoints.length>=3;
  approved=region.artwork_status==="artist_approved";
  select.value=name;
  render().catch(error=>{document.getElementById("metrics").textContent=error.message;});
}
function sourcePoint(event){
  const rect=canvas.getBoundingClientRect();
  const x=crop.x0+((event.clientX-rect.left)/rect.width)*canvas.width/crop.scale;
  const y=crop.y0+((event.clientY-rect.top)/rect.height)*canvas.height/crop.scale;
  return [Number(x.toFixed(3)),Number(y.toFixed(3))];
}
canvas.addEventListener("pointerdown",event=>{
  if(closed)return;
  const point=sourcePoint(event);
  editPoints.push(point);render();
});
document.getElementById("undo").addEventListener("click",()=>{editPoints.pop();closed=false;approved=false;render();});
document.getElementById("clear").addEventListener("click",()=>{editPoints=[];closed=false;approved=false;render();});
document.getElementById("finish").addEventListener("click",()=>{if(editPoints.length>=3){closed=true;approved=false;render();}});
document.getElementById("previous").addEventListener("click",()=>{const i=names.indexOf(activeName);if(i>0)loadJoint(names[i-1]);});
document.getElementById("next").addEventListener("click",()=>{const i=names.indexOf(activeName);if(i<names.length-1)loadJoint(names[i+1]);});
select.addEventListener("change",()=>loadJoint(select.value));
document.getElementById("approval").addEventListener("change",event=>{
  approved=Boolean(event.target.checked)&&closed&&editPoints.length>=3;
  render();
});
document.getElementById("save").addEventListener("click",()=>{
  const region=regions[activeName];
  region.artist_source_polygon=editPoints.map(point=>[Number(point[0]),Number(point[1])]);
  region.artwork_status=approved&&closed&&editPoints.length>=3?"artist_approved":"awaiting_artist_alignment";
  region.authoring_note="Source-coordinate polygon traced in offline review tool; verify original artwork before production extraction.";
  const blob=new Blob([JSON.stringify(template,null,2)+"\n"],{type:"application/json"});
  const url=URL.createObjectURL(blob);
  const link=document.createElement("a");
  link.href=url;link.download="joint-artwork-template-reviewed.json";
  document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
  document.getElementById("metrics").textContent="Exported JSON for "+activeName+". No files were uploaded or changed in GitHub.";
});
names.forEach(name=>{const option=document.createElement("option");option.value=name;option.textContent=name.replaceAll("_"," ");select.appendChild(option);});
loadJoint(activeName);
})();
</script>
</body>
</html>
"""
    return (
        html.replace("__TEMPLATE_JSON__", template_json)
        .replace("__CHARACTER_JSON__", character_json)
        .replace("__SOURCE_FILENAME__", source_filename)
    )


def build_joint_artwork_review_pack(
    source_path: str | Path,
    bundle_dir: str | Path,
    regions_path: str | Path,
    output_dir: str | Path,
    *,
    crop_radius: int = 54,
    scale: int = 4,
) -> dict[str, Any]:
    """Create a contact sheet and blank, source-coordinate polygon template."""
    source_path = Path(source_path).resolve(strict=True)
    bundle = Path(bundle_dir).resolve(strict=True)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    with Image.open(source_path) as opened:
        source = opened.convert("RGBA")
    source_pixels = np.asarray(source, dtype=np.uint8)
    canvas_width, canvas_height = source.size

    character_path = bundle / "character.json"
    if not character_path.is_file():
        raise FileNotFoundError("The rig bundle is missing character.json.")
    character = json.loads(character_path.read_text(encoding="utf-8"))
    if character.get("canvas") != {"width": canvas_width, "height": canvas_height}:
        raise ValueError("The source artwork and rig canvas dimensions do not match.")

    regions = json.loads(Path(regions_path).read_text(encoding="utf-8"))
    joint_regions = (regions.get("joint_surfaces") or {}).get("regions") or {}
    joints = character.get("joints") or {}
    layers = {
        str(layer.get("role") or ""): layer
        for layer in character.get("layers", [])
    }

    template: dict[str, Any] = {
        "schema_version": 1,
        "coordinate_space": "absolute_source_pixels_top_left",
        "canvas": {"width": canvas_width, "height": canvas_height},
        "source_artwork": {
            "filename": source_path.name,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        },
        "authoring_instructions": [
            "Trace the actual clothing or shoe silhouette and fold structure visible in the source crop.",
            "Use artist_source_polygon as absolute [x, y] source-canvas coordinates.",
            "Do not use circles, capsules, ellipses, rounded rectangles or generic joint pads.",
            "The polygon must overlap both named parent_role and child_role source masks.",
            "Mark artwork_status as artist_approved only after visual review of the traced source boundary.",
            "candidate_source_polygon outlines only the exact shared parent/child alpha pixels; it is overlap evidence, not a complete joint surface.",
            "Magenta contours in the contact sheet indicate shared-pixel evidence only; they are never production art.",
            "Yellow points and lines identify the nearest separate parent/child source pixels where no shared pixels exist.",
            "The extraction stage copies original source pixels only; it does not paint or invent texture.",
        ],
        "protected_scope": {
            "included": list(LOWER_BODY_JOINTS),
            "excluded": [
                "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                "wrists", "hands", "fingers", "bow", "violin",
            ],
            "reason": "Upper-body, arm, forearm, hand, finger and instrument assets are protected in this stage.",
        },
        "joint_surfaces": {
            "schema_version": 1,
            "coordinate_space": "absolute_source_pixels_top_left",
            "regions": {},
        },
    }

    cell_width = crop_radius * 2 * scale
    cell_height = crop_radius * 2 * scale
    label_height = 58
    columns = 3
    rows = (len(LOWER_BODY_JOINTS) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * cell_width, rows * (cell_height + label_height)),
        (15, 22, 32),
    )
    draw = ImageDraw.Draw(sheet)
    review_rows: list[dict[str, Any]] = []

    for index, joint_name in enumerate(LOWER_BODY_JOINTS):
        item = joint_regions.get(joint_name)
        if not isinstance(item, dict):
            raise ValueError(f"Performance-region manifest is missing {joint_name}.")
        anchor_name = str(item.get("anchor") or joint_name)
        anchor = joints.get(anchor_name)
        if not isinstance(anchor, dict):
            raise ValueError(f"Rig has no mapped joint anchor for {joint_name}.")
        center_x = float(anchor["x"]) * canvas_width
        center_y = float(anchor["y"]) * canvas_height
        parent_role = str(item.get("parent_role") or "")
        child_role = str(item.get("child_role") or "")
        if parent_role not in layers or child_role not in layers:
            raise ValueError(
                f"{joint_name} references missing body layers: {parent_role}/{child_role}."
            )

        parent_mask = _canvas_alpha_mask_for_layer(
            bundle, layers[parent_role],
            canvas_width=canvas_width, canvas_height=canvas_height,
        )
        child_mask = _canvas_alpha_mask_for_layer(
            bundle, layers[child_role],
            canvas_width=canvas_width, canvas_height=canvas_height,
        )
        cx, cy = int(round(center_x)), int(round(center_y))
        x0, y0 = max(0, cx - crop_radius), max(0, cy - crop_radius)
        x1, y1 = min(canvas_width, cx + crop_radius), min(canvas_height, cy + crop_radius)

        source_visible = source_pixels[:, :, 3] > 12
        shared_source = parent_mask & child_mask & source_visible
        shared_local = shared_source[y0:y1, x0:x1].astype(np.uint8)
        component_count, component_labels, component_stats, component_centroids = (
            cv2.connectedComponentsWithStats(shared_local, connectivity=8)
        )
        candidate_source_polygon: list[list[float]] = []
        candidate_source_pixels = 0
        candidate_status = "manual_seam_trace_required_no_shared_parent_child_pixels"
        if component_count > 1:
            candidate_labels = range(1, component_count)
            selected_label = max(
                candidate_labels,
                key=lambda label: int(component_stats[label, cv2.CC_STAT_AREA]),
            )
            selected = (component_labels == selected_label).astype(np.uint8)
            candidate_source_pixels = int(selected.sum())
            contours, _ = cv2.findContours(
                selected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if contours:
                contour = max(contours, key=cv2.contourArea)
                polygon = cv2.approxPolyDP(contour, 0.75, True).reshape(-1, 2)
                candidate_source_polygon = [
                    [round(float(point[0]) + x0, 3), round(float(point[1]) + y0, 3)]
                    for point in polygon
                ]
                if len(candidate_source_polygon) >= 3:
                    candidate_status = "shared_source_pixel_polygon_candidate_pending_artist_review"
                else:
                    candidate_source_polygon = []

        anchor_measure_radius_px = min(24, crop_radius)
        ax0, ay0 = max(0, cx - anchor_measure_radius_px), max(0, cy - anchor_measure_radius_px)
        ax1, ay1 = min(canvas_width, cx + anchor_measure_radius_px), min(canvas_height, cy + anchor_measure_radius_px)
        local_parent = parent_mask[ay0:ay1, ax0:ax1]
        local_child = child_mask[ay0:ay1, ax0:ax1]
        parent_pixels_near_anchor = int(local_parent.sum())
        child_pixels_near_anchor = int(local_child.sum())
        local_parent_child_gap_px, closest_parent_source_pixel, closest_child_source_pixel = (
            _nearest_parent_child_pixels(
                local_parent, local_child, offset_x=ax0, offset_y=ay0
            )
        )
        manual_trace_reason = None
        if not candidate_source_polygon:
            if not parent_pixels_near_anchor:
                manual_trace_reason = "parent_source_pixels_absent_near_anchor"
            elif not child_pixels_near_anchor:
                manual_trace_reason = "child_source_pixels_absent_near_anchor"
            else:
                manual_trace_reason = "source_layers_separated_near_anchor"
        if candidate_source_polygon:
            candidate_status = "source_alpha_overlap_evidence_only_not_full_joint_surface"
        crop = source.crop((x0, y0, x1, y1))
        matte = Image.new("RGBA", crop.size, (25, 31, 42, 255))
        matte.alpha_composite(crop)
        magnified = matte.resize(
            (crop.width * scale, crop.height * scale),
            Image.Resampling.NEAREST,
        )
        overlay = ImageDraw.Draw(magnified, "RGBA")

        if candidate_source_polygon:
            proposal_points = [
                (
                    int(round((point[0] - x0) * scale)),
                    int(round((point[1] - y0) * scale)),
                )
                for point in candidate_source_polygon
            ]
            if len(proposal_points) >= 3:
                overlay.line(
                    proposal_points + [proposal_points[0]],
                    fill=(255, 55, 225, 255),
                    width=3,
                )

        if (
            not candidate_source_polygon
            and closest_parent_source_pixel
            and closest_child_source_pixel
        ):
            parent_point = (
                int(round((closest_parent_source_pixel[0] - x0) * scale)),
                int(round((closest_parent_source_pixel[1] - y0) * scale)),
            )
            child_point = (
                int(round((closest_child_source_pixel[0] - x0) * scale)),
                int(round((closest_child_source_pixel[1] - y0) * scale)),
            )
            overlay.line(
                [parent_point, child_point],
                fill=(255, 220, 80, 255),
                width=2,
            )
            for point in (parent_point, child_point):
                overlay.ellipse(
                    (point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5),
                    fill=(255, 220, 80, 255),
                )

        for mask, color in (
            (parent_mask, (48, 220, 236, 255)),
            (child_mask, (255, 172, 63, 255)),
        ):
            # _canvas_alpha_mask_for_layer already returns a boolean mask.
            # Comparing booleans with 12 would erase every contour.
            local = mask[y0:y1, x0:x1].astype(np.uint8)
            contours, _ = cv2.findContours(
                local, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for contour in contours:
                if cv2.contourArea(contour) < 2:
                    continue
                points = [
                    (
                        int(round(float(point[0][0]) * scale)),
                        int(round(float(point[0][1]) * scale)),
                    )
                    for point in contour
                ]
                if len(points) > 1:
                    overlay.line(points + [points[0]], fill=color, width=2)

        anchor_x, anchor_y = (center_x - x0) * scale, (center_y - y0) * scale
        cross = 8 * scale
        overlay.line(
            (anchor_x - cross, anchor_y, anchor_x + cross, anchor_y),
            fill=(255, 70, 70, 255), width=3,
        )
        overlay.line(
            (anchor_x, anchor_y - cross, anchor_x, anchor_y + cross),
            fill=(255, 70, 70, 255), width=3,
        )

        canvas = Image.new("RGB", (cell_width, cell_height), (25, 31, 42))
        canvas.paste(magnified.convert("RGB"), (0, 0))
        column, row = index % columns, index // columns
        px, py = column * cell_width, row * (cell_height + label_height)
        sheet.paste(canvas, (px, py + label_height))
        draw.text(
            (px + 10, py + 5),
            f"{joint_name}  |  {parent_role} → {child_role}",
            fill=(241, 234, 219),
        )
        draw.text(
            (px + 10, py + 24),
            f"anchor ({center_x:.1f}, {center_y:.1f})  | cyan parent · amber child",
            fill=(170, 190, 204),
        )
        status_label = (
            f"shared pixels: {candidate_source_pixels} | magenta = overlap evidence only"
            if candidate_source_polygon
            else (
                f"0 shared | edge gap: {local_parent_child_gap_px}px | manual trace"
                if local_parent_child_gap_px is not None
                else f"0 shared | {manual_trace_reason.replace('_', ' ')}"
            )
        )
        draw.text(
            (px + 10, py + 41),
            status_label,
            fill=(255, 145, 225) if candidate_source_polygon else (255, 205, 125),
        )

        template["joint_surfaces"]["regions"][joint_name] = {
            "anchor": anchor_name,
            "anchor_px": [round(center_x, 3), round(center_y, 3)],
            "parent_role": parent_role,
            "child_role": child_role,
            "z_index": int(item.get("z_index", 20)),
            "minimum_pixels": int(item.get("minimum_pixels", 80)),
            "blend_axis_joints": list(item.get("blend_axis_joints") or []),
            "blend_axis_half_length_px": 18,
            "artist_source_polygon": [],
            "candidate_source_polygon": candidate_source_polygon,
            "candidate_source_pixels": candidate_source_pixels,
            "candidate_status": candidate_status,
            "candidate_parent_child_gap_px": local_parent_child_gap_px,
            "anchor_measure_radius_px": anchor_measure_radius_px,
            "parent_pixels_near_anchor": parent_pixels_near_anchor,
            "child_pixels_near_anchor": child_pixels_near_anchor,
            "manual_trace_reason": manual_trace_reason,
            "closest_parent_source_pixel": closest_parent_source_pixel,
            "closest_child_source_pixel": closest_child_source_pixel,
            "candidate_geometry_kind": "shared_alpha_overlap_evidence_only_not_full_joint_surface",
            "candidate_is_production_art": False,
            "artwork_status": "awaiting_artist_alignment",
        }
        review_rows.append({
            "joint": joint_name,
            "parent_role": parent_role,
            "child_role": child_role,
            "anchor_px": [round(center_x, 3), round(center_y, 3)],
            "crop_bounds": [x0, y0, x1, y1],
            "parent_source_pixels": int(parent_mask[y0:y1, x0:x1].sum()),
            "child_source_pixels": int(child_mask[y0:y1, x0:x1].sum()),
            "shared_source_pixels": candidate_source_pixels,
            "candidate_status": candidate_status,
            "candidate_source_polygon": candidate_source_polygon,
            "candidate_parent_child_gap_px": local_parent_child_gap_px,
            "anchor_measure_radius_px": anchor_measure_radius_px,
            "parent_pixels_near_anchor": parent_pixels_near_anchor,
            "child_pixels_near_anchor": child_pixels_near_anchor,
            "manual_trace_reason": manual_trace_reason,
            "closest_parent_source_pixel": closest_parent_source_pixel,
            "closest_child_source_pixel": closest_child_source_pixel,
            "candidate_geometry_kind": "shared_alpha_overlap_evidence_only_not_full_joint_surface",
            "candidate_is_production_art": False,
        })

    annotator_path = output / "joint-artwork-annotator.html"
    annotator_path.write_text(
        _build_offline_annotator_html(
            template, character, source_filename=source_path.name
        ),
        encoding="utf-8",
    )
    sheet_path = output / "joint-artwork-contact-sheet.jpg"
    sheet.save(sheet_path, format="JPEG", quality=95, optimize=True)
    template_path = output / "joint-artwork-template.json"
    template_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "status": "review_pack_created",
        "source_dimensions": [canvas_width, canvas_height],
        "source_sha256": template["source_artwork"]["sha256"],
        "joint_count": len(review_rows),
        "joint_names": list(LOWER_BODY_JOINTS),
        "contact_sheet": sheet_path.name,
        "template": template_path.name,
        "annotator": annotator_path.name,
        "production_art_assets_created": 0,
        "candidate_joint_polygons": sum(bool(row["candidate_source_polygon"]) for row in review_rows),
        "manual_seam_trace_required": sum(not bool(row["candidate_source_polygon"]) for row in review_rows),
        "candidate_geometry_source": "exact_parent_child_source_alpha_intersection_only",
        "candidate_geometry_kind": "shared_alpha_overlap_evidence_only_not_full_joint_surface",
        "candidate_polygons_artist_approved": 0,
        "rig_layers_modified": 0,
        "original_source_pixels_modified": 0,
        "upper_body_and_hand_assets_touched": False,
        "joints": review_rows,
        "limitation": (
            "Magenta outlines show exact shared parent/child source-alpha overlap only, not complete joint surfaces. "
            "They are draft tracing evidence, not approved artwork, and are never copied into artist_source_polygon automatically. "
            "Yellow markers show nearest separate parent/child source pixels where a manual seam trace is required. "
            "The rig must continue deferring joint surfaces until reviewed artist_source_polygon masks are supplied."
        ),
    }
    (output / "joint-artwork-review-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--regions", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    report = build_joint_artwork_review_pack(
        args.source, args.bundle, args.regions, args.out_dir
    )
    print(json.dumps({
        "status": report["status"],
        "joint_count": report["joint_count"],
        "production_art_assets_created": report["production_art_assets_created"],
        "candidate_joint_polygons": report["candidate_joint_polygons"],
        "manual_seam_trace_required": report["manual_seam_trace_required"],
        "candidate_polygons_artist_approved": report["candidate_polygons_artist_approved"],
        "contact_sheet": report["contact_sheet"],
        "template": report["template"],
        "annotator": report["annotator"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
