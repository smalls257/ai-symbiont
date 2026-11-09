/* What a triage click does, for the Inbox and the group page alike: post, remember what changed, redraw, say so.
   Violation prevented: Distributed Monolith (two copies of the same click would drift apart), and Black Box (a
   click that fails without a word). The caller's `ui` carries `container`, `data`, `project`, and two hooks:
   `redraw(g, position)` shows the saved state and puts keyboard focus back; `positionOf(key)` says where the row was. */
(function () {
"use strict";
const M=window.SymbiontInboxModel;
const STATE_OF={reviewed:"reviewed",resolve:"resolved",reopen:"for_review"};
const DONE_WORDS={
  reviewed:"Marked reviewed. It stays in Reviewed.",
  resolve:"Resolved. It comes back as Regressed if it happens again.",
  reopen:"Back in For review."
};
const toast=(ui,message)=>window.SymbiontInboxDialogs.toast(ui.container,message);

async function post(path,body){
  const reply=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const text=await reply.text();
  if(!reply.ok)throw new Error(text||"status "+reply.status);
  return JSON.parse(text);
}

/* Keep only what the click changed: a rename must not turn a Regressed group (shown For review, saved Resolved)
   into a Resolved one on the page. */
function remember(ui,g,patch){
  ui.data.triage[g.key]={...M.triageOf(ui.data.triage,g),...patch};
  if(window.SymbiontViews&&window.SymbiontViews.dataChanged)window.SymbiontViews.dataChanged();
}

async function saveState(ui,g,fields,message){
  const position=ui.positionOf(g.key);
  const reply=await post("/triage",{project:ui.project,group_key:g.key,...fields});
  remember(ui,g,{state:reply.state,regressed:false});
  ui.redraw(g,position);
  toast(ui,message);
}

async function afterTaught(ui,g,request){
  const added=await post("/lessons/add",request);
  const reply=await post("/triage",M.taughtRequest(ui.project,g,added));
  remember(ui,g,{taught_on:reply.taught_on});
  ui.redraw(g,ui.positionOf(g.key));
  toast(ui,"Lesson saved. The agent hears it from the next session.");
}

/* `a` is one of reviewed, resolve, reopen, teach, archive; rename is the Inbox's own (it edits a row in place). */
async function perform(ui,g,a,button){
  const D=window.SymbiontInboxDialogs;
  if(a==="teach")return D.teach(ui,g,button,afterTaught);
  if(a==="archive")return D.archiveMenu(ui,g,button,choice=>saveState(ui,g,{state:"archived",...choice.body},"Archived. "+choice.detail));
  return saveState(ui,g,{state:STATE_OF[a]},DONE_WORDS[a]);
}
const runAction=(ui,g,button)=>perform(ui,g,button.dataset.a,button);

window.SymbiontTriageActions={post,remember,saveState,afterTaught,perform,runAction};
})();
