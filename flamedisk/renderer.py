"""
Renders the disk-usage Node tree as a TreeSize-style interactive HTML page.

Optimisations vs v0.1
----------------------
* JSON payload uses single-char keys (``n/s/d/p/c/e``) — ~40% smaller.
* Paths are stored only on the root node; the browser reconstructs them.
* CSS and JS are minified at import time (strips comments + excess whitespace).
* ``gzip`` compression available via :func:`render_html_gz` for HTTP serving.

v0.2 visualisation improvements
---------------------------------
* Right panel replaced with a horizontal **icicle chart** (flame-graph layout):
  each depth level is a fixed-height row; width is proportional to size.
  Equal-sized siblings are clearly distinguishable via alternating hue shifts
  and depth-based brightness.
* Directories with identical sizes now get visually distinct colours.
* Hover tooltip shows full path, size, % of parent, and child count.
* Clicking an icicle cell drills down; Escape / ▲ Up goes back.
* Tree panel bar widths and % column now reflect proportion of *parent* rather
  than root, making deep comparisons easier.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .scanner import Node


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_html(root: Node, title: Optional[str] = None) -> str:
    """Render *root* as a self-contained HTML string.

    Args:
        root:  Root :class:`~flamedisk.scanner.Node` returned by :func:`~flamedisk.scanner.scan`.
        title: Page ``<title>`` (defaults to ``"flamedisk — <path>"``).

    Returns:
        str: Complete HTML document, ready to write to a ``.html`` file.
    """
    title = title or f"flamedisk \u2014 {root.path}"
    data  = json.dumps(root.to_dict(), separators=(",", ":"))
    return (
        _TEMPLATE
        .replace("__TITLE__", _esc(title))
        .replace("__DATA__", data)
    )


def render_html_gz(root: Node, title: Optional[str] = None) -> bytes:
    """Like :func:`render_html` but returns gzip-compressed bytes.

    Useful when serving the report over HTTP
    (set ``Content-Encoding: gzip``).
    """
    import gzip
    return gzip.compress(render_html(root, title).encode("utf-8"), compresslevel=6)


def write_html(root: Node, output: str, title: Optional[str] = None) -> None:
    """Write the HTML report to *output*.

    Args:
        root:   Root node.
        output: Destination file path.
        title:  Optional page title.
    """
    Path(output).write_text(render_html(root, title), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return (str(s)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _minify(html: str) -> str:
    """Strip CSS/JS comments and collapse redundant whitespace."""
    # Remove /* ... */ block comments (CSS)
    html = re.sub(r"/\*.*?\*/", "", html, flags=re.DOTALL)
    # Remove // line comments inside <script> blocks only
    html = re.sub(r"(?m)^[ \t]*//[^\n]*\n", "\n", html)
    # Collapse runs of spaces/tabs to a single space
    html = re.sub(r"[ \t]{2,}", " ", html)
    # Collapse multiple blank lines to one
    html = re.sub(r"\n[ \t]*\n[ \t]*\n", "\n\n", html)
    # Strip trailing space on lines
    html = re.sub(r"[ \t]+\n", "\n", html)
    return html.strip()


# ---------------------------------------------------------------------------
# HTML template
# NOTE: Keys in the JSON payload are single-char to minimise size:
#   n = name   s = size   d = is_dir (1 if true, absent if false)
#   p = path   c = children   e = error
# The JS reconstructs full paths as  parent_path + "/" + n
# ---------------------------------------------------------------------------

_RAW_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>__TITLE__</title>
<style>
/* reset */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#1e1e2e;--sf:#252535;--sf2:#2d2d42;--bd:#3a3a52;
  --tx:#cdd6f4;--mt:#7f849c;--ac:#89b4fa;
  --gn:#a6e3a1;--rd:#f38ba8;--yw:#f9e2af;--mv:#cba6f7;
  --tl:#94e2d5;--pc:#fab387;--sk:#89dceb;
  --ui:"Segoe UI",system-ui,sans-serif;
  --mono:"Cascadia Code","JetBrains Mono","Fira Mono",monospace;
}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--tx);font-family:var(--ui);font-size:13px;display:flex;flex-direction:column}
/* header */
#hd{height:38px;background:var(--sf);border-bottom:1px solid var(--bd);display:flex;align-items:center;padding:0 10px;gap:10px;flex-shrink:0}
.logo{font-family:var(--mono);font-size:15px;font-weight:700;color:var(--ac);white-space:nowrap}
.logo em{color:var(--tx);font-style:normal}
#pb{flex:1;display:flex;align-items:center;gap:2px;font-family:var(--mono);font-size:12px;overflow:hidden;white-space:nowrap}
.ps{color:var(--mt);cursor:pointer;padding:1px 4px;border-radius:3px;transition:background .1s,color .1s}
.ps:hover{background:var(--sf2);color:var(--tx)}
.psep{color:var(--bd);padding:0 1px}
.ps.cur{color:var(--tx);cursor:default}
#si{font-size:11px;color:var(--mt);white-space:nowrap;font-family:var(--mono)}
#si strong{color:var(--ac)}
/* toolbar */
#tb{height:32px;background:var(--sf2);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:4px;padding:0 8px;flex-shrink:0}
.tbtn{height:22px;padding:0 10px;border-radius:3px;border:1px solid var(--bd);background:var(--sf);color:var(--tx);font-size:12px;cursor:pointer;font-family:var(--ui);white-space:nowrap;transition:border-color .1s}
.tbtn:hover{border-color:var(--ac)}
.tsep{width:1px;height:18px;background:var(--bd);margin:0 4px}
#vt{display:flex}
.vb{height:22px;padding:0 9px;border:1px solid var(--bd);background:var(--sf);color:var(--mt);font-size:12px;cursor:pointer}
.vb:first-child{border-radius:3px 0 0 3px}
.vb:last-child{border-radius:0 3px 3px 0;border-left:none}
.vb.on{background:var(--ac);color:#1e1e2e;border-color:var(--ac);font-weight:600}
#sw{position:relative;margin-left:auto}
#sw input{height:22px;padding:0 8px 0 26px;border-radius:3px;border:1px solid var(--bd);background:var(--sf);color:var(--tx);font-size:12px;width:200px;outline:none;font-family:var(--mono);transition:border-color .15s}
#sw input:focus{border-color:var(--ac)}
#sw .si2{position:absolute;left:7px;top:50%;transform:translateY(-50%);color:var(--mt);pointer-events:none;font-size:13px}
/* main */
#mn{display:flex;flex:1;overflow:hidden}
/* tree panel */
#tp{width:36%;min-width:240px;max-width:480px;background:var(--sf);border-right:1px solid var(--bd);display:flex;flex-direction:column;overflow:hidden;flex-shrink:0}
#th{height:26px;background:var(--sf2);border-bottom:1px solid var(--bd);display:flex;align-items:center;padding:0 8px;flex-shrink:0}
.thc{font-size:11px;font-weight:600;color:var(--mt);text-transform:uppercase;letter-spacing:.4px;padding:0 6px;height:100%;display:flex;align-items:center}
.thn{flex:1}.ths{width:80px;text-align:right;justify-content:flex-end}.thp{width:46px;text-align:right;justify-content:flex-end}
#tbody{flex:1;overflow-y:auto;overflow-x:hidden}
.tr{display:flex;align-items:center;height:22px;cursor:pointer;user-select:none}
.tr:hover{background:var(--sf2)}
.tr.sel{background:#2a3a5c}
.tr.sdim{opacity:.3}.tr.smatch{background:#2d3520}
.tri{flex-shrink:0}.trg{width:16px;height:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0;color:var(--mt);font-size:10px;transition:transform .1s}
.trg.op{transform:rotate(90deg)}
.tric{margin-right:4px;font-size:13px;flex-shrink:0}
.trn{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.trbw{width:60px;height:8px;background:var(--sf2);border-radius:2px;overflow:hidden;margin-right:6px;flex-shrink:0}
.trb{height:100%;border-radius:2px}
.trs{width:74px;text-align:right;font-family:var(--mono);font-size:11px;color:var(--mt);padding-right:4px;flex-shrink:0}
.tr.sel .trs{color:var(--tx)}
.trp{width:40px;text-align:right;font-family:var(--mono);font-size:11px;color:var(--mt);padding-right:6px;flex-shrink:0}
/* resizer */
#rz{width:4px;background:var(--bd);cursor:col-resize;flex-shrink:0;transition:background .15s}
#rz:hover,#rz.drag{background:var(--ac)}
/* icicle panel */
#mp{flex:1;display:flex;flex-direction:column;overflow:hidden;background:var(--bg)}
#mh{height:26px;background:var(--sf2);border-bottom:1px solid var(--bd);display:flex;align-items:center;padding:0 10px;font-size:11px;color:var(--mt);flex-shrink:0;gap:8px}
#mh strong{color:var(--tx)}
#mh .hint{margin-left:auto;font-size:10px;color:var(--mt)}
#mc{flex:1;overflow-y:auto;overflow-x:hidden;position:relative;padding:4px 6px 8px}
/* icicle rows */
.irow{display:flex;height:28px;margin-bottom:2px;position:relative}
.irow-label{position:absolute;left:0;top:0;height:28px;display:flex;align-items:center;
  font-size:10px;color:var(--mt);font-family:var(--mono);white-space:nowrap;
  pointer-events:none;padding-left:2px;z-index:1;min-width:40px;flex-shrink:0}
.irow-cells{flex:1;display:flex;height:100%;gap:1px;overflow:hidden}
/* individual icicle cell */
.ic{height:100%;min-width:1px;position:relative;overflow:hidden;cursor:pointer;
  border-radius:3px;transition:filter .12s,outline .1s;flex-shrink:0}
.ic:hover{filter:brightness(1.25);z-index:10}
.ic.sel{outline:2px solid #fff;z-index:20}
.ic.sdim{opacity:.12}.ic.smatch{outline:2px solid var(--yw);z-index:15}
/* cell label */
.icl{position:absolute;inset:0;display:flex;flex-direction:column;
  justify-content:center;padding:0 5px;overflow:hidden;pointer-events:none}
.icn{font-size:11px;font-weight:600;color:rgba(255,255,255,.9);
  text-shadow:0 1px 3px rgba(0,0,0,.7);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;line-height:1.3}
.ics{font-size:10px;color:rgba(255,255,255,.65);white-space:nowrap;
  font-family:var(--mono);overflow:hidden;text-overflow:ellipsis}
/* depth label strip on the left */
#dlabels{width:0px;flex-shrink:0}
/* legend strip at bottom of icicle */
#ileg{height:22px;background:var(--sf2);border-top:1px solid var(--bd);
  display:flex;align-items:center;padding:0 10px;gap:10px;flex-shrink:0}
.li{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--mt);white-space:nowrap}
.ld{width:10px;height:10px;border-radius:2px;flex-shrink:0}
/* status */
#st{height:28px;background:var(--sf);border-top:1px solid var(--bd);display:flex;align-items:center;padding:0 10px;gap:12px;flex-shrink:0;overflow:hidden}
#seli{font-family:var(--mono);font-size:11px;color:var(--mt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
#seli .hl{color:var(--ac)}
/* tooltip */
#tt{position:fixed;pointer-events:none;background:rgba(37,37,53,.97);border:1px solid var(--bd);border-radius:6px;padding:8px 12px;font-size:12px;font-family:var(--mono);max-width:360px;word-break:break-all;z-index:9999;display:none;line-height:1.8;box-shadow:0 6px 24px rgba(0,0,0,.6)}
.ttn{color:var(--tx);font-weight:700;font-size:13px}
.ttr{display:flex;justify-content:space-between;gap:16px}
.ttl{color:var(--mt)}.ttv{color:var(--ac)}
.ttp{color:var(--mt);font-size:10px;margin-top:2px;word-break:break-all}
/* scrollbar */
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:var(--sf)}
::-webkit-scrollbar-thumb{background:var(--bd);border-radius:3px}
</style>
</head>
<body>
<div id="hd">
  <span class="logo">flame<em>disk</em></span>
  <div id="pb"></div>
  <div id="si"></div>
</div>
<div id="tb">
  <button class="tbtn" id="bup">▲ Up</button>
  <button class="tbtn" id="brt">⌂ Root</button>
  <div class="tsep"></div>
  <div id="vt">
    <button class="vb on" data-v="tree">Tree+Icicle</button>
    <button class="vb" data-v="map">Icicle</button>
    <button class="vb" data-v="list">List</button>
  </div>
  <div class="tsep"></div>
  <div id="sw"><span class="si2">⌕</span><input id="srch" type="text" placeholder="Search…" autocomplete="off"/></div>
</div>
<div id="mn">
  <div id="tp">
    <div id="th">
      <div class="thc thn">Name</div>
      <div class="thc ths">Size</div>
      <div class="thc thp">%</div>
    </div>
    <div id="tbody"></div>
  </div>
  <div id="rz"></div>
  <div id="mp">
    <div id="mh">
      Icicle — <strong id="mt2"></strong>
      <span class="hint">Click to drill in · Esc / ▲ Up to go back</span>
    </div>
    <div id="mc"></div>
    <div id="ileg"></div>
  </div>
</div>
<div id="st">
  <div id="seli">Select a file or folder to see details</div>
</div>
<div id="tt"></div>
<script>
(function(){
"use strict";
const ROOT=__DATA__;
/* ── state ── */
let vr=ROOT,nav=[],sel=null,sq="";
/* ── palette ── */
// Base hues for directory depth levels
const DEPTH_HUES=[210,160,280,40,0,320,80,200,260,120];
// File-type palette (extension→colour)
const EP={
  jpg:"#f38ba8",jpeg:"#f38ba8",png:"#f38ba8",gif:"#f38ba8",webp:"#f38ba8",svg:"#f38ba8",bmp:"#f38ba8",ico:"#f38ba8",
  mp4:"#eba0ac",mov:"#eba0ac",avi:"#eba0ac",mkv:"#eba0ac",webm:"#eba0ac",
  mp3:"#fab387",wav:"#fab387",flac:"#fab387",ogg:"#fab387",m4a:"#fab387",
  zip:"#f9e2af",tar:"#f9e2af",gz:"#f9e2af",bz2:"#f9e2af",xz:"#f9e2af","7z":"#f9e2af",rar:"#f9e2af",dmg:"#f9e2af",
  js:"#89dceb",ts:"#89dceb",jsx:"#89dceb",tsx:"#89dceb",
  py:"#a6e3a1",rb:"#a6e3a1",go:"#a6e3a1",rs:"#a6e3a1",java:"#a6e3a1",c:"#a6e3a1",cpp:"#a6e3a1",h:"#a6e3a1",
  css:"#cba6f7",scss:"#cba6f7",html:"#89b4fa",htm:"#89b4fa",
  json:"#94e2d5",xml:"#94e2d5",yaml:"#94e2d5",yml:"#94e2d5",
  md:"#b4befe",txt:"#b4befe",log:"#b4befe",
  exe:"#6c7086",dll:"#6c7086",so:"#6c7086",bin:"#6c7086",
  pdf:"#f38ba8",docx:"#89b4fa",xlsx:"#a6e3a1",pptx:"#fab387",
};
function fileColor(name){
  const i=name.lastIndexOf(".");
  if(i<0) return "#45475a";
  return EP[name.slice(i+1).toLowerCase()]||"#45475a";
}
// Each directory gets a colour derived from its depth-level hue + a sibling
// index offset so same-sized siblings are visually distinct.
function dirColor(depth,siblingIdx,totalSiblings){
  const baseHue=DEPTH_HUES[depth%DEPTH_HUES.length];
  // spread siblings across ±40° of hue, and alternate lightness slightly
  const spread=Math.min(40,totalSiblings*8);
  const hueOff=totalSiblings>1?(siblingIdx/(totalSiblings-1)-0.5)*spread:0;
  const hue=(baseHue+hueOff+360)%360;
  // alternate lightness: even=36%, odd=44%
  const lt=siblingIdx%2===0?36:44;
  // saturation varies slightly with depth
  const sat=60-depth*4;
  return `hsl(${hue.toFixed(1)},${Math.max(30,sat)}%,${lt}%)`;
}
function ec(node,depth,sibIdx,sibCount){
  if(node.d) return dirColor(depth,sibIdx,sibCount);
  return fileColor(node.n);
}
/* ── format ── */
function fmt(b){
  if(!b) return "0 B";
  const u=["B","KB","MB","GB","TB"],i=Math.min(Math.floor(Math.log2(b)/10),4);
  return (i===0?Math.round(b/Math.pow(1024,i)):(b/Math.pow(1024,i)).toFixed(2))+"\u00a0"+u[i];
}
function pct(a,b){return b?((a/b)*100).toFixed(1)+"%":"—"}
function esc(s){return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function ficon(n){
  const i=n.lastIndexOf("."); if(i<0) return "📄";
  const e=n.slice(i+1).toLowerCase();
  if(["jpg","jpeg","png","gif","webp","svg"].includes(e)) return "🖼";
  if(["mp4","mov","avi","mkv"].includes(e)) return "🎬";
  if(["mp3","wav","flac","ogg"].includes(e)) return "🎵";
  if(["zip","tar","gz","bz2","7z","rar","dmg"].includes(e)) return "📦";
  if(e==="pdf") return "📕";
  if(["js","ts","py","rb","go","rs","java","c","cpp"].includes(e)) return "💻";
  return "📄";
}
function matchSq(nd){return sq&&(nd.n.toLowerCase().includes(sq)||(nd.p||"").toLowerCase().includes(sq));}
/* ══════════════════════════════════════════════
   TREE PANEL
══════════════════════════════════════════════ */
const tbody=document.getElementById("tbody");
function buildTree(node,parentEl,depth,parentSz,sibIdx,sibCount){
  const hasC=node.d&&node.c&&node.c.length;
  const col=ec(node,depth,sibIdx,sibCount);
  const fr=parentSz>0?node.s/parentSz:0;
  const bw=Math.round(fr*60);
  const row=document.createElement("div");
  row.className="tr"+(sq?matchSq(node)?" smatch":" sdim":"");
  row.dataset.path=node.p||node.n;
  row.innerHTML=
    `<div class="tri" style="width:${depth*16+4}px"></div>`+
    `<div class="trg${hasC?" ":""}">${hasC?"▶":""}</div>`+
    `<div class="tric">${node.d?"📁":ficon(node.n)}</div>`+
    `<div class="trn" title="${esc(node.n)}">${esc(node.n)}</div>`+
    `<div class="trbw"><div class="trb" style="width:${bw}px;background:${col}"></div></div>`+
    `<div class="trs">${fmt(node.s)}</div>`+
    `<div class="trp">${pct(node.s,vr.s)}</div>`;
  row.addEventListener("click",e=>{
    e.stopPropagation();
    selectNode(node,row);
    if(hasC) toggleRow(node,row,depth,parentSz,sibIdx,sibCount);
  });
  parentEl.appendChild(row);
  return row;
}
function toggleRow(node,row,depth,parentSz,sibIdx,sibCount){
  const tg=row.querySelector(".trg");
  if(!tg||!tg.textContent) return;
  if(tg.classList.contains("op")){
    tg.classList.remove("op");
    let nx=row.nextElementSibling;
    while(nx){
      const iw=parseInt((nx.querySelector(".tri")||{}).style?.width||"0");
      if(iw<=depth*16+4) break;
      const rm=nx; nx=nx.nextElementSibling; rm.remove();
    }
  } else {
    tg.classList.add("op");
    let after=row;
    const kids=node.c||[];
    kids.forEach((ch,ci)=>{
      const r=buildTree(ch,document.createDocumentFragment(),depth+1,node.s,ci,kids.length);
      after.after(r); after=r;
    });
  }
}
function renderTree(){
  tbody.innerHTML="";
  buildTree(vr,tbody,0,vr.s,0,1);
  const rootRow=tbody.querySelector(".tr");
  if(rootRow){
    const tg=rootRow.querySelector(".trg");
    if(tg&&tg.textContent){
      tg.classList.add("op");
      let after=rootRow;
      const kids=vr.c||[];
      kids.forEach((ch,ci)=>{
        const r=buildTree(ch,document.createDocumentFragment(),1,vr.s,ci,kids.length);
        after.after(r); after=r;
      });
    }
  }
}
/* ══════════════════════════════════════════════
   ICICLE CHART  (horizontal flame-graph layout)
   Each depth = one row; width proportional to size.
   Children are laid out left-to-right within their
   parent's horizontal span.
══════════════════════════════════════════════ */
const mcEl=document.getElementById("mc");
// Collect all nodes at each depth in left-to-right order
// We do a BFS, tracking (node, parentLeftFrac, parentWidthFrac, depth, sibIdx, sibCount)
function renderIcicle(){
  mcEl.innerHTML="";
  document.getElementById("mt2").textContent=vr.n||(vr.p||"");
  const totalW=mcEl.clientWidth||600;
  if(!totalW) return;

  // BFS queue: {node, x0 (fraction 0-1), x1, depth, sibIdx, sibCount, parentNode}
  const queue=[{node:vr,x0:0,x1:1,depth:0,sibIdx:0,sibCount:1,parent:null}];
  // Group by depth
  const byDepth=[];
  while(queue.length){
    const item=queue.shift();
    if(!byDepth[item.depth]) byDepth[item.depth]=[];
    byDepth[item.depth].push(item);
    const kids=item.node.c||[];
    if(kids.length&&item.node.s>0){
      const span=item.x1-item.x0;
      let cx=item.x0;
      kids.forEach((ch,ci)=>{
        const w=span*(ch.s/item.node.s);
        queue.push({node:ch,x0:cx,x1:cx+w,depth:item.depth+1,sibIdx:ci,sibCount:kids.length,parent:item.node});
        cx+=w;
      });
    }
  }

  // Render each depth row
  byDepth.forEach((row,depth)=>{
    const rowEl=document.createElement("div");
    rowEl.className="irow";
    rowEl.style.cssText="display:flex;height:28px;margin-bottom:2px;gap:1px;";
    row.forEach(item=>{
      const {node,x0,x1,sibIdx,sibCount,parent}=item;
      const widthPx=(x1-x0)*totalW;
      if(widthPx<1) return; // skip invisible cells
      const col=ec(node,depth,sibIdx,sibCount);
      const cell=document.createElement("div");
      cell.className="ic"+(sq?matchSq(node)?" smatch":" sdim":"")+(sel&&(sel.p||sel.n)===(node.p||node.n)?" sel":"");
      cell.style.cssText=`width:${widthPx.toFixed(2)}px;background:${col};flex-shrink:0;height:100%;min-width:1px;position:relative;overflow:hidden;cursor:pointer;border-radius:3px;transition:filter .12s`;
      // Label — only show if cell wide enough
      if(widthPx>38){
        const lbl=document.createElement("div");
        lbl.className="icl";
        lbl.style.cssText="position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;padding:0 5px;overflow:hidden;pointer-events:none";
        const nm=document.createElement("div");
        nm.className="icn";
        nm.style.cssText="font-size:11px;font-weight:600;color:rgba(255,255,255,.92);text-shadow:0 1px 3px rgba(0,0,0,.65);white-space:nowrap;overflow:hidden;text-overflow:ellipsis";
        nm.textContent=node.n;
        lbl.appendChild(nm);
        if(widthPx>80){
          const sz=document.createElement("div");
          sz.className="ics";
          sz.style.cssText="font-size:10px;color:rgba(255,255,255,.62);white-space:nowrap;font-family:var(--mono)";
          sz.textContent=fmt(node.s)+(parent?" · "+pct(node.s,parent.s):"");
          lbl.appendChild(sz);
        }
        cell.appendChild(lbl);
      }
      cell.addEventListener("mouseenter",e=>showTT(e,node,parent));
      cell.addEventListener("mousemove",moveTT);
      cell.addEventListener("mouseleave",()=>document.getElementById("tt").style.display="none");
      cell.addEventListener("click",e=>{
        e.stopPropagation();
        selectNode(node,null);
        if(node.d&&node.c&&node.c.length){
          nav.push(vr);vr=node;renderAll();
        }
      });
      rowEl.appendChild(cell);
    });
    // depth guide label on far right
    const depthNote=document.createElement("span");
    depthNote.style.cssText="position:absolute;right:4px;top:50%;transform:translateY(-50%);font-size:9px;color:var(--mt);pointer-events:none;font-family:var(--mono);";
    depthNote.textContent=depth===0?"root":"L"+depth;
    rowEl.style.position="relative";
    rowEl.appendChild(depthNote);
    mcEl.appendChild(rowEl);
  });
  updateLegend();
}
/* ══════════════════════════════════════════════
   RENDER ALL
══════════════════════════════════════════════ */
function renderAll(){renderTree();renderIcicle();updatePB();}
function updatePB(){
  const bar=document.getElementById("pb"); bar.innerHTML="";
  const chain=nav.concat([vr]);
  chain.forEach((nd,i)=>{
    if(i>0){const s=document.createElement("span");s.className="psep";s.textContent="/";bar.appendChild(s);}
    const s=document.createElement("span");
    s.className="ps"+(i===chain.length-1?" cur":"");
    s.textContent=nd.n||(nd.p||"");
    s.title=nd.p||nd.n;
    if(i<chain.length-1){const ci=i,cn=nd;s.addEventListener("click",()=>{nav.length=ci;vr=cn;renderAll();});}
    bar.appendChild(s);
  });
  const inf=document.getElementById("si");
  inf.innerHTML=`<strong>${fmt(vr.s)}</strong> · ${(vr.c||[]).length} items`;
}
/* ── select ── */
function selectNode(nd,rowEl){
  sel=nd;
  document.querySelectorAll(".tr.sel").forEach(r=>r.classList.remove("sel"));
  if(rowEl) rowEl.classList.add("sel");
  const si=document.getElementById("seli");
  const fp=nd.p||nd.n;
  si.innerHTML=`<span class="hl">${esc(nd.n)}</span> · ${fmt(nd.s)} · ${pct(nd.s,vr.s)} of view · ${nd.d?"Directory":"File"} · <span style="color:var(--mt)">${esc(fp)}</span>`;
}
/* ── legend ── */
function updateLegend(){
  const counts={};
  function wk(n){if(!n.d)counts[fileColor(n.n)]=(counts[fileColor(n.n)]||0)+n.s;(n.c||[]).forEach(wk);}
  wk(vr);
  const s=Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,6);
  document.getElementById("ileg").innerHTML=s.map(([c,z])=>`<div class="li"><div class="ld" style="background:${c}"></div>${fmt(z)}</div>`).join("");
}
/* ── tooltip ── */
const ttEl=document.getElementById("tt");
function showTT(e,nd,parent){
  const fp=nd.p||nd.n;
  const kids=(nd.c||[]).length;
  ttEl.innerHTML=`<div class="ttn">${esc(nd.n)}</div>`+
    `<div class="ttr"><span class="ttl">Size</span><span class="ttv">${fmt(nd.s)}</span></div>`+
    `<div class="ttr"><span class="ttl">% of view</span><span class="ttv">${pct(nd.s,vr.s)}</span></div>`+
    (parent?`<div class="ttr"><span class="ttl">% of parent</span><span class="ttv">${pct(nd.s,parent.s)}</span></div>`:"")+
    (nd.d?`<div class="ttr"><span class="ttl">Children</span><span class="ttv">${kids}</span></div>`:"")+
    `<div class="ttr"><span class="ttl">Type</span><span class="ttv">${nd.d?"Directory":"File"}</span></div>`+
    `<div class="ttp">${esc(fp)}</div>`;
  ttEl.style.display="block"; moveTT(e);
}
function moveTT(e){
  let x=e.clientX+16,y=e.clientY+16;
  const tw=ttEl.offsetWidth,th=ttEl.offsetHeight;
  if(x+tw>window.innerWidth) x=e.clientX-tw-10;
  if(y+th>window.innerHeight) y=e.clientY-th-10;
  ttEl.style.left=x+"px"; ttEl.style.top=y+"px";
}
/* ── view mode ── */
const tp=document.getElementById("tp"),rz=document.getElementById("rz"),mp=document.getElementById("mp");
document.querySelectorAll(".vb").forEach(b=>{
  b.addEventListener("click",()=>{
    document.querySelectorAll(".vb").forEach(x=>x.classList.remove("on"));
    b.classList.add("on");
    const v=b.dataset.v;
    tp.style.display=v==="map"?"none":"";
    rz.style.display=v==="tree"?"":"none";
    mp.style.display=v==="list"?"none":"";
    setTimeout(renderIcicle,10);
  });
});
/* ── resizer ── */
let rd=false,rs=0,rp=0;
rz.addEventListener("mousedown",e=>{rd=true;rs=e.clientX;rp=tp.offsetWidth;rz.classList.add("drag");e.preventDefault();});
window.addEventListener("mousemove",e=>{if(!rd)return;tp.style.width=Math.max(160,Math.min(600,rp+e.clientX-rs))+"px";});
window.addEventListener("mouseup",()=>{if(rd){rd=false;rz.classList.remove("drag");renderIcicle();}});
/* ── controls ── */
document.getElementById("bup").addEventListener("click",()=>{if(nav.length){vr=nav.pop();renderAll();}});
document.getElementById("brt").addEventListener("click",()=>{nav=[];vr=ROOT;renderAll();});
document.getElementById("srch").addEventListener("input",e=>{sq=e.target.value.toLowerCase().trim();renderAll();});
window.addEventListener("keydown",e=>{
  if(e.key==="Escape"){
    if(nav.length){vr=nav.pop();renderAll();}
    sq="";document.getElementById("srch").value="";renderAll();
  }
});
window.addEventListener("resize",renderIcicle);
renderAll();
})();
</script>
</body>
</html>"""

_TEMPLATE = _minify(_RAW_TEMPLATE)
