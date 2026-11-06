/* The Add context list: one collapsible section per kind of trouble. Pure functions, no DOM, so node can test them.
   Violation prevented: Paper Tiger. A long list that can only be scrolled shows every pain point and still does
   not let the developer work through one kind at a time. dashboard.js only draws what these functions decide. */
(function () {
"use strict";
const KEY_PREFIX="symbiont.plist.collapsed.";
const storageKey=project=>KEY_PREFIX+project;

/* The collapsed kind ids of one repository. Missing means all open. An unreadable value must not break the
   page: warn naming the key (a Silent Fallback would hide why the list forgot its state) and open everything. */
function readCollapsed(storage,project,warn){
  const key=storageKey(project);
  try{
    const raw=storage.getItem(key);
    if(raw===null||raw===undefined)return new Set();
    const ids=JSON.parse(raw);
    if(!Array.isArray(ids)||!ids.every(i=>typeof i==="string"))throw new Error("not a list of kind ids");
    return new Set(ids);
  }catch(err){
    warn("symbiont: could not read "+key+" ("+err.message+"); showing every section open");
    return new Set();
  }
}

function writeCollapsed(storage,project,collapsed,warn){
  const key=storageKey(project);
  try{storage.setItem(key,JSON.stringify([...collapsed]));}
  catch(err){warn("symbiont: could not save "+key+" ("+err.message+"); the sections will reopen on reload");}
}

/* groups: [{kind,label,count,itemsHtml}]. The heading is a disclosure button; the items sit in a list
   container it controls, hidden while collapsed. Labels go through esc like every other text from data. */
function groupsHtml(groups,collapsed,esc){
  return groups.map(g=>{
    const open=!collapsed.has(g.kind), id="plist-"+g.kind;
    return '<h3><button type="button" class="grp" data-kind="'+esc(g.kind)+'" aria-expanded="'+open+'" aria-controls="'+esc(id)+'">'
      +'<span class="chev" aria-hidden="true"></span><span class="gl">'+esc(g.label)+" · "+g.count+"</span></button></h3>"
      +'<div class="items" id="'+esc(id)+'" role="listbox"'+(open?"":" hidden")+">"+g.itemsHtml+"</div>";
  }).join("");
}

window.SymbiontPainList={storageKey,readCollapsed,writeCollapsed,groupsHtml};
})();
