/* The Ignored group at the bottom of the Add context list, and the calls behind Ignore and Restore.
   Violation prevented: Silent Fallback. An ignored pattern that simply disappears from the page cannot be found
   or undone; it stays listed here, collapsed by default, with a Restore button each. dashboard.js draws it with
   the same disclosure markup as the kind groups (painlist.js). */
(function () {
"use strict";
const KIND="ignored";
const storageKey=project=>"symbiont.ignored.open."+project;

/* Collapsed unless the developer opened it. An unreadable store must not break the page: warn naming the key. */
function readOpen(storage,project,warn){
  try{return storage.getItem(storageKey(project))==="1";}
  catch(err){warn("symbiont: could not read "+storageKey(project)+" ("+err.message+"); the Ignored list stays collapsed");return false;}
}
function writeOpen(storage,project,open,warn){
  try{storage.setItem(storageKey(project),open?"1":"0");}
  catch(err){warn("symbiont: could not save "+storageKey(project)+" ("+err.message+")");}
}

/* entries: [{label,signal,key}]. The label is text from the store, so it goes through esc. */
function itemsHtml(entries,esc){
  if(!entries.length)return '<p class="mu ign-none">Nothing is ignored.</p>';
  return entries.map((e,i)=>'<div class="ign" role="listitem"><span class="t">'+esc(e.label)+'</span>'
    +'<button type="button" data-restore="'+i+'" aria-label="Restore '+esc(e.label)+'">Restore</button></div>').join("");
}
function group(entries,esc){return {kind:KIND,label:"Ignored",count:entries.length,role:"list",itemsHtml:itemsHtml(entries,esc)};}

function post(url,body){
  return fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then(r=>{
    if(!r.ok)return r.text().then(t=>{throw new Error("symbiont could not do that (status "+r.status+"): "+t);});
    return r.json();
  });
}
const ignore=(project,lessonId)=>post("/lessons/"+encodeURIComponent(lessonId)+"/ignore",{project});
const restore=(project,entry)=>post("/ignored/restore",{project,signal:entry.signal,key:entry.key});

window.SymbiontIgnored={KIND,storageKey,readOpen,writeOpen,itemsHtml,group,ignore,restore};
})();
