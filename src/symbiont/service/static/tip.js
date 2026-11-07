/* The one safe way a tooltip's markup reaches innerHTML.
   Violation prevented: Leaky Narrative at the page boundary. A lesson title or a repository path is the developer's
   text, and a `data-tip` that carries it must never become live HTML. Producers write a few formatting tags and escape
   their own text; this keeps those tags and turns every other `<` into text, so one forgotten esc() in any producer
   (dashboard.js, struggle.js, inbox_rows.js, topics.js, trends.js) cannot run script. */
(function () {
"use strict";
const ALLOWED=/^(?:<\/?b>|<br>|<span class="?m"?>|<\/span>)/;

function safe(html){
  let out="",rest=String(html);
  while(rest){
    const at=rest.indexOf("<");
    if(at<0)return out+rest;
    out+=rest.slice(0,at);rest=rest.slice(at);
    const tag=ALLOWED.exec(rest);
    if(tag){out+=tag[0];rest=rest.slice(tag[0].length);}
    else{out+="&lt;";rest=rest.slice(1);}
  }
  return out;
}

window.SymbiontTip={safe};
})();
