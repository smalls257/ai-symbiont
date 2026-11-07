/* The session page: one session's steps, your messages and failed commands, tagged by the group they belong to.
   Registered as the "session" detail view. The log is fetched once per open; a refused or failed fetch says so
   on the page, and an unknown id says "No such session" instead of opening another one. */
(function () {
"use strict";
const SM=window.SymbiontSessionModel,P=window.SymbiontSessionParts,esc=P.esc,M=window.SymbiontInboxModel;
const MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const UNREADABLE_WORD="this session's log is no longer readable";
const NOT_FOUND="No such session.",UNREADABLE="This session's log is no longer readable.";
let opened=0;

const dayWord=iso=>{const m=/^(\d{4})-(\d{2})-(\d{2})/.exec(iso||"");return m?MONTHS[Number(m[2])-1]+" "+Number(m[3])+", "+m[1]:null;};
const num=n=>Number(n).toLocaleString("en-US");

function backLink(project){
  return ' <a data-route href="'+esc(M.hrefFor(project,{view:"inbox"}))+'">Back to the inbox</a>';
}
function say(pane,text,project){pane.innerHTML='<p class="soon" role="status">'+esc(text)+backLink(project)+"</p>";}
function failure(pane,project,status,body){
  const word=body&&body.error;
  if(status===404&&word==="no such session")return say(pane,NOT_FOUND,project);
  if(status===404&&word===UNREADABLE_WORD)return say(pane,UNREADABLE,project);
  return say(pane,"Could not load this session: "+(word||("the service answered "+status)),project);
}
function topicOf(data,id){
  const found=((data.topicView||{}).topics||[]).find(t=>(t.sessionList||[]).some(s=>s.id===id));
  return found||null;
}
function pickerHtml(data,id){
  const {rows,currentListed}=SM.pickerOf(data,id);
  const options=rows.map(r=>'<option value="'+esc(r.id)+'"'+(r.id===id?" selected":"")+">"+esc((dayWord(r.date)||"undated")+" · "+(r.goal||"(no summary)").slice(0,46)+" ("+r.hits+")")+"</option>").join("");
  const extra=currentListed?"":'<option value="'+esc(id)+'" selected>this session</option>';
  return '<label class="mu pickl">Sessions with the most grouped trouble <select class="sel" data-pick>'+options+extra+"</select></label>";
}
function tilesHtml(body,noise){
  const c=body.counts||{},tile=(n,w)=>"<div><b>"+num(n)+"</b>"+w+"</div>";
  return '<div class="cnts">'+tile(body.total,"steps in all")+tile(c.failed,"failed commands ("+noise+" noise)")+tile(c.edits,"code edits")+tile(c.scratch,"doc or scratch edits")+tile(c.messages,"messages from you")+tile(c.passed,"passed commands, hidden")+"</div>";
}
function metaHtml(body,summary){
  const bits=["<span><b>"+esc(dayWord(body.date)||"undated")+"</b></span>"],wall=SM.wallClock(body.minutes);
  if(wall)bits.push("<span><b>"+wall+"</b> wall clock</span>");
  if(summary.outcome)bits.push('<span>ended <span class="pill">'+esc(summary.outcome)+"</span></span>");
  return '<div class="meta">'+bits.join("")+"</div>";
}
function headerHtml(ctx){
  const {body,data,id,project,noise}=ctx,topic=topicOf(data,id),summary=SM.summaryOf(data,id);
  const button=topic?'<a class="btn" data-route href="'+esc(M.hrefFor(project,{view:"topics",t:topic.key}))+'">Topic: '+esc(topic.name)+"</a>":"";
  return '<div class="shd"><h1>'+esc(body.goal||summary.goal||"(no summary)")+'</h1><div class="pick">'+pickerHtml(data,id)+button+"</div>"+metaHtml(body,summary)+
    (summary.friction?'<div class="fr">'+esc(summary.friction)+"</div>":"")+tilesHtml(body,noise)+"</div>";
}
function stripHtml(ctx){
  const {body,focus}=ctx,cap=SM.capText(body.shown,body.total);
  const details={};
  body.failed.forEach(f=>{details[f.step]={error:f.error};});
  const focusNote=focus!==null&&!body.steps.some(s=>s[0]===focus)?" Step "+focus+" is not among the steps shown.":"";
  return '<section class="panel full"><h2>Step by step</h2><p class="sub">'+esc(num(body.steps.length)+" marks over "+num(body.total)+" steps. Passed commands and the agent's own text are hidden. Click a mark to jump to it below. "+cap+focusNote)+"</p>"+
    '<div class="strip">'+(body.steps.length?P.stripSvg(body.steps,details,ctx.tagFor,focus):'<p class="empty2">This session has no steps to draw.</p>')+"</div>"+legendHtml()+"</section>";
}
function legendHtml(){
  const item=(cls,text)=>'<span><i class="'+cls+'"></i>'+text+"</span>";
  return '<div class="legend2">'+item("lg-group","failure or message in a group")+item("lg-ungrouped","not grouped")+item("lg-noise","folded as noise")+item("lg-edit","code edit")+item("lg-scratch","doc or scratch edit")+"</div>";
}
function listsHtml(ctx){
  const {body,tagFor,hrefOf,state}=ctx;
  const msgs=SM.keptMessages(body.messages,tagFor,state.messages),fails=SM.keptFailed(body.failed,tagFor,state.failed);
  const inGroup=body.messages.filter(m=>tagFor(m.step).kind==="group").length;
  return '<section class="panel"><h2>Your messages, in context</h2><p class="sub">What the agent had just done, what you said, and what it did next.</p>'+
    P.filterButtons("messages",[["all","All "+body.messages.length],["group","In a group "+inGroup]],state.messages)+
    '<div class="items">'+P.itemsHtml(msgs.map(m=>P.messageItem(m,tagFor(m.step),hrefOf)),"No messages from you in this filter.")+"</div></section>"+
    '<section class="panel"><h2>Failed commands</h2><p class="sub">Grouped ones link to their group; noise says why it was folded.</p>'+
    P.filterButtons("failed",[["all","All "+body.failed.length],["quiet","Hide noise "+(body.failed.length-ctx.noise)]],state.failed)+
    '<div class="items">'+P.itemsHtml(fails.map(f=>P.failedItem(f,tagFor(f.step),hrefOf)),"No failed commands in this filter.")+"</div></section>";
}
function draw(pane,ctx){
  pane.innerHTML='<div class="sess"><section class="panel full">'+headerHtml(ctx)+"</section>"+stripHtml(ctx)+listsHtml(ctx)+"</div>";
}
function jump(pane,step){
  const el=document.getElementById("st-"+step);
  if(!el)return;
  pane.querySelectorAll(".it.hl").forEach(x=>x.classList.remove("hl"));
  el.classList.add("hl");el.scrollIntoView({behavior:"smooth",block:"center"});
}
function wire(pane,ctx){
  pane.onclick=e=>{
    const button=e.target.closest&&e.target.closest("[data-filter]"),mark=e.target.closest&&e.target.closest("[data-step]");
    if(button){
      const [which,value]=button.dataset.filter.split(":");
      ctx.state[which]=value;draw(pane,ctx);
      const again=pane.querySelector('[data-filter="'+button.dataset.filter+'"]');
      if(again)again.focus();
    }else if(mark)jump(pane,Number(mark.dataset.step));
  };
  pane.onchange=e=>{
    if(e.target.matches&&e.target.matches("[data-pick]"))window.SymbiontViews.navigate({view:"session",id:e.target.value});
  };
}
function open(pane,body,route,data,project){
  const table=SM.joinOf((data.incidents||{}).groups);
  const tagFor=step=>SM.tagOf(table,route.id,step);
  const ctx={body,data,project,id:route.id,focus:Number.isInteger(route.step)?route.step:null,tagFor,
    hrefOf:r=>M.hrefFor(project,r),state:{messages:"all",failed:"all"}};
  ctx.noise=SM.noiseCount(body.failed,tagFor);
  window.SymbiontViews.setCrumb("Session "+(dayWord(body.date)||route.id));
  draw(pane,ctx);wire(pane,ctx);
  if(ctx.focus!==null)jump(pane,ctx.focus);
}
async function render(pane,route,data,project){
  const mine=++opened;
  pane.innerHTML='<p class="soon" role="status">Loading this session…</p>';
  const url="/dashboard/session?project="+encodeURIComponent(project)+"&id="+encodeURIComponent(route.id);
  try{
    const reply=await fetch(url);
    const body=await reply.json().catch(()=>null);
    if(mine!==opened)return;
    if(!reply.ok||!body)return failure(pane,project,reply.status,body);
    open(pane,body,route,data,project);
  }catch(err){
    if(mine===opened)say(pane,"Could not load this session: "+err.message,project);
  }
}
window.SymbiontSession={render};
if(window.SymbiontViews)window.SymbiontViews.registerDetail("session",render);
})();
