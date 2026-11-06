/* The Summary block of a pain point: the session's model's summary when a review has one, else the rule-built one
   with a muted hint on how to ask for it. Pure: takes the pain point and dashboard.js's esc, returns HTML. */
(function () {
"use strict";
function summaryHtml(p,esc){
  if(p.summary)return '<p class="sum"><b>Summary.</b> '+esc(p.summary)+"</p>";
  if(!p.ruleSummary)return "";
  return '<p class="sum"><b>Summary.</b> '+esc(p.ruleSummary)+'</p><p class="mu hint">Ask your session for a summary: /symbiont review</p>';
}
window.SymbiontSummary={summaryHtml};
})();
