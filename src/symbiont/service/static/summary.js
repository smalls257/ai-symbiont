/* The story block of a pain point: Working on / What broke / How it ended from the rules, and Worth a look when the
   session's model wrote a summary (otherwise a muted hint on how to ask for one). Pure: takes the pain point and
   dashboard.js's esc, returns HTML. Everything goes through esc before the backtick pairs become <code>. */
(function () {
"use strict";
const LINES=[["Working on","workingOn"],["What broke","broke"],["How it ended","ended"]];
const code=(s,esc)=>esc(s).replace(/`([^`]+)`/g,"<code>$1</code>");
function summaryHtml(p,esc){
  const rows=LINES.filter(([,key])=>p[key]).map(([label,key])=>"<dt>"+label+"</dt><dd>"+code(p[key],esc)+"</dd>");
  if(p.summary)rows.push("<dt>Worth a look</dt><dd>"+esc(p.summary)+"</dd>");
  if(!rows.length)return "";
  const hint=p.summary?"":'<p class="mu hint">Ask your session for a summary: /symbiont review</p>';
  return '<dl class="three sum">'+rows.join("")+"</dl>"+hint;
}
window.SymbiontSummary={summaryHtml};
})();
