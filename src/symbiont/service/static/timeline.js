/* Layout for "The same mistake, session after session". Pure functions, no DOM, so node can test them.
   Violation prevented: Leaky Narrative on the chart. Labels that ran across the plot and a dozen rows
   squeezed into a fixed height made the demo unreadable; the caps below keep the chart legible as the
   data grows to ~60 sessions over six weeks. dashboard.js only draws what these functions decide. */
(function () {
"use strict";
const MAX_ROWS=5, MAX_LABEL_LINES=2, MIN_TICK_PX=96, MAX_DOT_R=10, MIN_DOT_R=4;

/* Most repeated first, most recent first among equals. Rows beyond MAX_ROWS fold into one final row
   whose dots are the union of the folded rows' sessions. A mistake needs two sessions to count as repeated. */
function foldRows(points){
  const rec=points.filter(p=>p.s.length>=2).sort((a,b)=>b.s.length-a.s.length||b.s[b.s.length-1]-a.s[a.s.length-1]);
  const shown=rec.slice(0,MAX_ROWS).map(p=>({title:p.title,kind:p.kind,s:p.s,turns:p.turns,folded:0}));
  const rest=rec.slice(MAX_ROWS);
  if(!rest.length)return shown;
  const union=[...new Set(rest.flatMap(p=>p.s))].sort((a,b)=>a-b);
  return shown.concat([{title:"Other repeated mistakes ("+rest.length+" more)",kind:"other",s:union,turns:null,folded:rest.length}]);
}

/* Word-wrap into at most MAX_LABEL_LINES lines of maxChars; a word longer than a line (a file path)
   is cut, and whatever does not fit ends in an ellipsis. */
function labelLines(text,maxChars){
  const lines=[];
  let cur="";
  for(const word of text.split(/\s+/).filter(Boolean)){
    for(let w=word;w;w=w.slice(maxChars)){
      const piece=w.slice(0,maxChars), next=cur?cur+" "+piece:piece;
      if(next.length<=maxChars){cur=next;continue;}
      lines.push(cur);cur=piece;
    }
  }
  if(cur)lines.push(cur);
  if(lines.length<=MAX_LABEL_LINES)return lines.length?lines:[""];
  const kept=lines.slice(0,MAX_LABEL_LINES), last=kept[MAX_LABEL_LINES-1];
  kept[MAX_LABEL_LINES-1]=(last.length>=maxChars?last.slice(0,maxChars-1):last)+"…";
  return kept;
}

/* Every tickStep-th session gets a date, far enough apart that two dates never touch. */
const tickStep=(n,plotPx)=>n<2?1:Math.max(1,Math.ceil(MIN_TICK_PX/(plotPx/(n-1))));
/* Dots shrink so neighbors at the widest spacing still leave a gap. */
const dotRadius=(n,plotPx)=>n<2?MAX_DOT_R:Math.max(MIN_DOT_R,Math.min(MAX_DOT_R,plotPx/(n-1)*0.42));

window.SymbiontTimeline={foldRows,labelLines,tickStep,dotRadius};
})();
