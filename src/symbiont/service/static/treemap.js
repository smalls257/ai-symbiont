/* Layout for "Where in the repo". Pure functions, no DOM, so node can test them.
   Violation prevented: Silent Fallback on the chart. A tile too small for its label, or a file with no
   path, drew a blank or half-labeled rectangle that looked like missing data. Here a tile either fits
   its file name AND its turns, or it is folded into one labeled "Other files (N)" tile BEFORE the
   layout, so the area stays proportional to turns. dashboard.js only draws what these functions decide. */
(function () {
"use strict";
const MIN_W=90, MIN_H=44, NO_FILE="Not tied to a file", FAILED_COMMANDS="Failed commands", PAD=8, CHAR_EM=0.62, MAX_TITLE_FILES=8, MIN_FONT=10;

/* The name a tile shows. Trouble not tied to one file (a failing command) has an empty path; it gets a
   name instead of the blank label that hid the biggest tile. */
function fileName(path){
  const base=String(path||"").split("/").filter(Boolean).pop();
  return base||NO_FILE;
}

/* Name cut to the characters that fit widthPx at fontPx (monospace), ending in an ellipsis when cut. */
function fitName(name,widthPx,fontPx){
  const cap=Math.max(1,Math.floor((widthPx-2*PAD)/(fontPx*CHAR_EM)));
  return name.length<=cap?name:name.slice(0,Math.max(1,cap-1))+"…";
}

/* The Other tile's name carries the file count, so it shrinks the font (never below MIN_FONT) instead of
   losing the count to an ellipsis. */
function fitFont(name,widthPx,fontPx){
  const room=Math.floor((widthPx-2*PAD)/(name.length*CHAR_EM));
  return Math.max(MIN_FONT,Math.min(fontPx,room));
}

function squarify(items,x,y,w,h){
  const total=items.reduce((a,b)=>a+b.v,0), sc=w*h/total;
  const sized=items.map(i=>({...i,a:i.v*sc}));
  const out=[]; let rect={x,y,w,h}, row=[];
  const sumA=r=>r.reduce((a,b)=>a+b.a,0);
  const worst=(r,s)=>{const t=sumA(r);return Math.max(s*s*Math.max(...r.map(q=>q.a))/(t*t),t*t/(s*s*Math.min(...r.map(q=>q.a))));};
  const place=r=>{const t=sumA(r);
    if(rect.w>=rect.h){const rw=t/rect.h;let yy=rect.y;r.forEach(q=>{const hh=q.a/rw;out.push({...q,x:rect.x,y:yy,w:rw,h:hh});yy+=hh;});rect={x:rect.x+rw,y:rect.y,w:rect.w-rw,h:rect.h};}
    else{const rh=t/rect.w;let xx=rect.x;r.forEach(q=>{const ww=q.a/rh;out.push({...q,x:xx,y:rect.y,w:ww,h:rh});xx+=ww;});rect={x:rect.x,y:rect.y+rh,w:rect.w,h:rect.h-rh};}};
  for(const it of sized){const s=Math.min(rect.w,rect.h);if(row.length&&worst(row.concat(it),s)>worst(row,s)){place(row);row=[];}row.push(it);}
  if(row.length)place(row);
  return out;
}

const fits=t=>t.w>=MIN_W&&t.h>=MIN_H;

function otherTile(rest){
  const shown=rest.slice(0,MAX_TITLE_FILES).map(r=>r.label||r.f||NO_FILE).join(", ");
  const more=rest.length>MAX_TITLE_FILES?" and "+(rest.length-MAX_TITLE_FILES)+" more":"";
  return {f:null,v:rest.reduce((a,r)=>a+r.v,0),name:"Other files ("+rest.length+")",title:shown+more,folded:rest.map(r=>r.f)};
}

/* The name of the tile for trouble with no file: "Failed commands" when every such pain point is a failed
   command (the usual case), else the neutral "Not tied to a file", so the label never claims more than it holds. */
function noFileLabel(points){
  const loose=points.filter(p=>!p.file);
  return loose.length&&loose.every(p=>p.command)?FAILED_COMMANDS:NO_FILE;
}

/* items: [{f: path, v: turns, label?: name for the no-file tile}]. Returns tiles {f,v,x,y,w,h,name,title,folded} in a width x height box.
   The smallest files fold one at a time into the Other tile and the layout is redone until every tile,
   Other included, is at least MIN_W x MIN_H; folding precedes layout so area stays proportional. */
function plan(items,width,height){
  const sorted=items.filter(i=>i.v>0).sort((a,b)=>b.v-a.v);
  if(!sorted.length)return [];
  for(let keep=sorted.length;keep>=0;keep--){
    const rest=sorted.slice(keep);
    const parts=sorted.slice(0,keep).map(i=>({...i,name:i.label||fileName(i.f),title:i.label||i.f||NO_FILE,folded:null}));
    const all=rest.length?parts.concat([otherTile(rest)]):parts;
    all.sort((a,b)=>b.v-a.v);
    const tiles=squarify(all,0,0,width,height);
    if(keep===0||tiles.every(fits))return tiles;
  }
  return [];
}

window.SymbiontTreemap={plan,fileName,fitName,fitFont,noFileLabel,MIN_W,MIN_H,NO_FILE,FAILED_COMMANDS};
})();
