/* The Held back list on the Pain points stage, and the one plural rule the page shares.
   Violation prevented: Paper Tiger. Mining counts the failures it would not teach and the dashboard used to compute
   them and draw nothing, so "held back 81" was a number with nowhere to look. Each entry is text from a record
   (what happened), so everything goes through esc. struggle.js draws it with painlist.js's disclosure markup. */
(function () {
"use strict";
const KIND="heldback";
const counted=(n,noun)=>n+" "+noun+(n===1?"":"s");

/* A backtick pair marks a command, the same notation the notes use. */
const fmt=(text,esc)=>String(text).split("`").map((x,i)=>i%2?'<span class="cmd">'+esc(x)+"</span>":esc(x)).join("");

/* entries: [{what,reason,sessions,occurrences,minutes}], costliest first (dashboard_view decides the order). */
function itemsHtml(entries,esc){
  return entries.map(e=>'<div class="hb" role="listitem"><span class="t">'+fmt(e.what,esc)+'</span><span class="m">'
    +esc(counted(e.sessions,"session"))+" · "+esc(counted(e.occurrences,"time"))+" · about "+esc(e.minutes)+" min · "+esc(e.reason)+"</span></div>").join("");
}
function group(entries,esc){return {kind:KIND,label:"Failures held back, costliest first",count:entries.length,role:"list",itemsHtml:itemsHtml(entries,esc)};}

window.SymbiontHeldBack={KIND,counted,fmt,itemsHtml,group};
})();
