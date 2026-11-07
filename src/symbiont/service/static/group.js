/* The group page: one pain point in full. Registered as the "group" detail view.
   Violation prevented: Silent Fallback. An unknown key says "No such group" with a way back and never opens another
   group; a failed triage click or lesson save says why on the page. The triage clicks are the Inbox's own
   (triage_actions.js); what is decided lives in group_model.js, markup in group_parts.js. */
(function () {
"use strict";
const M=window.SymbiontInboxModel,R=window.SymbiontInboxRows,G=window.SymbiontGroupModel,P=window.SymbiontGroupParts;
const esc=R.esc,fd=R.fd;
const KIND_WORDS={failure:"Agent failure",correction:"Your correction"};

function skeleton(){
  return '<div class="gp"><section class="hd panel" id="gHead" data-part="head"></section><div class="gmain">'
    +'<section class="panel" id="gTimeline"></section><section class="panel" id="gThree"></section><section class="panel" id="gTeach"></section>'
    +'<section class="panel" id="gOccs"><h2>Every occurrence <span class="n" id="gOccN"></span></h2>'
    +'<p class="sub">Each one in the same three lines, with the session it came from. The highlighted one is the clearest example: a real fix, a short command, the latest of equals.</p>'
    +'<div class="occnav" id="gNav"></div><div id="gList"></div></section></div>'
    +'<aside class="side"><section class="panel act"><h2>Activity</h2><ul id="gAct"></ul></section>'
    +'<section class="panel tdist"><h2>In which topics</h2><p class="sub">Sessions with this group, by what was being worked on.</p><div id="gTopics"></div></section>'
    +'<section class="panel sim"><h2>Other groups</h2><div id="gOthers"></div></section></aside></div>';
}

function notFound(pane,route,project){
  pane.innerHTML='<p class="soon" role="status">No such group: '+esc(route.key)+'. <a data-route href="'+esc(M.hrefFor(project,{view:"inbox"}))+'">Back to the inbox</a></p>';
}

function context(pane,route,data,project,g){
  const incidents=data.incidents,list=G.chronological(g);
  const ui={container:pane,data,project,positionOf:()=>0,redraw:()=>{}};
  const ctx={pane,data,project,g,ui,list,page:0,rec:G.clearest(list),ownHistory:incidents.ownHistory===true,$:sel=>pane.querySelector(sel)};
  ctx.name=()=>M.displayName(data.triage,g);
  ctx.tri=()=>M.triageOf(data.triage,g);
  ctx.draft=M.teachDraft(g,ctx.name(),ctx.ownHistory);
  return ctx;
}

function drawHead(ctx){
  const {g,data}=ctx,shares=G.topicShares(g,data),facts=(data.stage||{}).facts;
  ctx.$("#gHead").innerHTML=P.headHtml({g,name:ctx.name(),tri:ctx.tri(),topic:shares.length?shares[0].name:"",sessionsRead:facts?facts.length:0});
}
function markerOf(ctx,axis){
  const taught=ctx.tri().taught_on,position=taught&&G.weekPosition(axis,taught);
  if(!position)return null;
  const label="lesson added "+fd(taught);
  return {position,label,legend:position.side?label+" (outside the mined weeks; the after-period starts here)":label};
}
function drawTimeline(ctx){
  const {g,data}=ctx,incidents=data.incidents,axis=M.weekAxis(incidents.groups);
  const {bars,top}=G.weekBars(g,axis,incidents.sessionsPerWeek);
  ctx.$("#gTimeline").innerHTML=P.timelineHtml({g,bars,top,marker:markerOf(ctx,axis)});
}
function drawActivity(ctx){
  const last=G.chronological(ctx.g).filter(c=>c.date).pop(),summary=last&&G.sessionById(ctx.data,last.sessionId);
  ctx.$("#gAct").innerHTML=P.activityHtml(G.activityRows(ctx.g,ctx.tri(),summary?summary.goal:"",fd));
}
function drawTeach(ctx){
  ctx.$("#gTeach").innerHTML=P.teachPanelHtml(ctx.draft,Boolean(ctx.tri().taught_on));
  drawPreview(ctx);
}
const lessonOf=ctx=>M.lessonRequest(ctx.project,ctx.g,ctx.$("#gWhen").value,ctx.$("#gWhat").value,ctx.draft.name);
function drawPreview(ctx){
  const lesson=lessonOf(ctx).lessons[0];
  ctx.$("#gPreview").innerHTML=P.previewHtml(G.noteParts(G.noteText(lesson.kind==="correction"?"correction":"mistake",lesson.text_in_plain_words)));
}
function drawOccurrences(ctx){
  const {list,g,data,project}=ctx,pages=G.pagesOf(list.length);
  ctx.$("#gOccN").textContent=M.plural(list.length,"occurrence");
  ctx.$("#gNav").innerHTML=P.pagerHtml(ctx.page,pages);
  ctx.$("#gList").innerHTML=G.pageSlice(list,ctx.page).map(({card,index})=>P.occurrenceHtml({
    card,summary:G.sessionById(data,card.sessionId),project,cor:g.kind==="correction",clearest:index===ctx.rec})).join("");
}
function drawSide(ctx){
  const {g,data,project}=ctx;
  ctx.$("#gTopics").innerHTML=P.topicsHtml(G.topicShares(g,data),project);
  ctx.$("#gOthers").innerHTML=P.othersHtml(G.otherGroups(data.incidents.groups,g,data.triage),project);
}
/* After a saved click the status-dependent parts redraw; the teach inputs keep what was typed. */
function redraw(ctx){
  drawHead(ctx);drawTimeline(ctx);drawActivity(ctx);
  const save=ctx.$("#gSave");
  if(save)save.textContent=ctx.tri().taught_on?"Update lesson":"Save lesson";
  const first=ctx.$("#gHead button");
  if(first)first.focus();
}

function focusTeach(ctx,flash){
  const box=ctx.$("#gTeach");
  if(box.scrollIntoView)box.scrollIntoView({behavior:"smooth"});
  if(flash)box.classList.add("spot");
  ctx.$("#gWhat").focus();
}
function jump(ctx,index){
  ctx.page=G.pageOfIndex(ctx.list.length,index);
  drawOccurrences(ctx);
  const el=ctx.pane.querySelectorAll(".occ2")[(ctx.list.length-1-index)%G.PER_PAGE];
  if(el&&el.scrollIntoView)el.scrollIntoView({behavior:"smooth",block:"center"});
}
function turn(ctx,id){
  const pages=G.pagesOf(ctx.list.length);
  if(id==="newer")ctx.page=Math.max(0,ctx.page-1);
  else if(id==="older")ctx.page=Math.min(pages-1,ctx.page+1);
  else return jump(ctx,{clearest:ctx.rec,first:0,latest:ctx.list.length-1}[id]);
  drawOccurrences(ctx);
  const again=ctx.$('[data-occ="'+id+'"]');
  if(again&&!again.disabled)again.focus();
}

function say(ctx,message){window.SymbiontInboxDialogs.toast(ctx.pane,message);}
const failed=ctx=>err=>say(ctx,"symbiont could not do that: "+err.message);
async function save(ctx){
  const err=ctx.$("#gTeachErr");
  err.textContent="";
  try{await window.SymbiontTriageActions.afterTaught(ctx.ui,ctx.g,lessonOf(ctx));}
  catch(e){err.textContent="symbiont could not save the lesson: "+e.message;}
}
function wire(ctx){
  const A=window.SymbiontTriageActions;
  ctx.ui.redraw=()=>redraw(ctx);
  ctx.pane.onclick=e=>{
    const act=e.target.closest("button[data-a]"),occ=e.target.closest("[data-occ]");
    if(e.target.closest("[data-save]"))save(ctx);
    else if(occ)turn(ctx,occ.dataset.occ);
    else if(act&&act.dataset.a==="teach")focusTeach(ctx,false);
    else if(act)A.perform(ctx.ui,ctx.g,act.dataset.a,act).catch(failed(ctx));
  };
  ctx.pane.onchange=e=>{
    if(!e.target.matches||!e.target.matches("[data-archive]")||e.target.value==="")return;
    const choice=M.archiveChoices(new Date())[Number(e.target.value)];
    A.saveState(ctx.ui,ctx.g,{state:"archived",...choice.body},"Archived. "+choice.detail).catch(failed(ctx));
  };
  ctx.pane.oninput=e=>{if(e.target.matches&&e.target.matches("#gWhen,#gWhat"))drawPreview(ctx);};
}

function render(pane,route,data,project){
  const g=((data.incidents||{}).groups||[]).find(x=>x.key===route.key);
  if(!g)return notFound(pane,route,project);
  const ctx=context(pane,route,data,project,g);
  window.SymbiontViews.setCrumb(KIND_WORDS[g.kind]+": "+ctx.name());
  pane.innerHTML=skeleton();
  drawHead(ctx);drawTimeline(ctx);
  ctx.$("#gThree").innerHTML=P.threeHtml(g);
  drawTeach(ctx);drawOccurrences(ctx);drawActivity(ctx);drawSide(ctx);
  wire(ctx);
  if(route.hash==="teach")focusTeach(ctx,true);
}
window.SymbiontGroup={render};
if(window.SymbiontViews)window.SymbiontViews.registerDetail("group",render);
})();
