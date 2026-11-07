/* Topics: what the developer was working on, named from batched session summaries.
   window.SymbiontTopics.render(container, topicView, options) draws the Inbox panel (options.compact) or the whole
   page, and returns {select(key)} for the page so a link can change the topic without a redraw of the pane.
   options: project, groups and triage (the Inbox's, to list what went wrong per topic), t (the topic key asked for).
   Before topics exist it draws the one-line instruction and the sessions by date instead of empty sections.
   Hover tips are HTML in a data attribute and are read back only through SymbiontTip.safe. */
(function () {
"use strict";
const P=window.SymbiontTopicParts;
const {esc,counted}=P;
const INSTRUCTION="Summarize your sessions to see topics: /symbiont summarize";
const COMPACT_SESSIONS=8;

function injectOnce(){
  if(document.getElementById("sbt-tip"))return;
  const box=document.createElement("div");box.id="sbt-tip";box.setAttribute("role","tooltip");document.body.appendChild(box);
  const show=(el,x,y)=>{box.innerHTML=window.SymbiontTip.safe(el.getAttribute("data-tip"));box.style.display="block";
    const r=box.getBoundingClientRect();box.style.left=Math.max(4,Math.min(innerWidth-r.width-8,x+14))+"px";
    box.style.top=(y+18+r.height>innerHeight?y-r.height-10:y+18)+"px";};
  const target=e=>e.target.closest&&e.target.closest("[data-tip]");
  document.addEventListener("mousemove",e=>{const el=target(e);if(el&&el.closest(".sbt"))show(el,e.clientX,e.clientY);else box.style.display="none";});
  document.addEventListener("focusin",e=>{const el=target(e);if(el&&el.closest(".sbt")){const r=el.getBoundingClientRect();show(el,r.left,r.bottom-10);}});
  document.addEventListener("focusout",()=>{box.style.display="none";});
}

/* Dataset history (swe-chat, openhands) is never shown to a session model, so asking the developer to run
   /symbiont summarize would send them to a dead end: say why there are no topics instead. */
function whyNoTopics(tv){
  const readers=(tv&&tv.datasetReaders)||[];
  if(!readers.length)return '<p class="ins">'+INSTRUCTION+"</p>";
  return '<p class="ins">No topics for this repository: its history comes from the '+esc(readers.join(" and "))
    +" dataset, and dataset sessions are never shown to a session model, so they cannot be summarized.</p>";
}

/* Before topics exist: why, and the sessions in date order from the session facts, never empty sections. */
function emptyHtml(tv,compact){
  const list=(tv&&tv.sessionsByDate)||[];
  const limit=compact?COMPACT_SESSIONS:list.length;
  const rows=list.slice(0,limit).map(s=>'<div class="trow"><span class="nm">'+esc(s.goal)+'</span><span class="ct">'+P.chip(s.outcome)+'</span><span class="dt">'+P.dayLabelYear(s.date)+"</span></div>").join("");
  const rest=list.length>limit?'<p class="undated">and '+counted(list.length-limit,"more session")+"</p>":"";
  const readers=(tv&&tv.datasetReaders)||[];
  const need=tv&&tv.needed&&!readers.length?'<p class="sub">'+counted(tv.needed,"more session summary","more session summaries")+" needed before topics can be named.</p>":"";
  return whyNoTopics(tv)+need+(list.length?"<h3>Sessions by date</h3>"+rows+rest:"");
}

/* The Inbox panel: topics with more than one session fold open to three goals and a link to the page. */
function compactRow(t,open,project,max){
  const on=t.key===open;
  const goals=(t.examples||[]).map(x=>"<li>"+esc(x)+"</li>").join("");
  const more='<li class="more"><a data-route href="'+P.href(project,{view:"topics",t:t.key})+'">All '+t.sessions+" sessions, outcomes and friction →</a></li>";
  return '<div class="trow fold'+(on?" on":"")+'" tabindex="0" role="button" aria-expanded="'+on+'" data-fold="'+esc(t.key)+'">'+P.nameButton(t)
    +'<span class="ct">'+t.sessions+"<small>"+(t.sessions===1?"session":"sessions")+"</small></span>"
    +'<span class="ds">'+esc(t.description)+'</span><div class="barw">'+P.outcomeBar(t.outcomes,t.name,t.sessions/max)+'</div>'
    +'<span class="dt">'+P.span(t)+" · "+P.doneShare(t)+"% done</span><ul class=\"exs\">"+goals+more+"</ul></div>";
}
function smallTopicsLine(tv,small){
  const parts=small.map(t=>esc(t.name)+": "+counted(t.sessions,"session"));
  if(tv.noiseSessions)parts.push(counted(tv.noiseSessions,"session")+" with no real task (noise)");
  return parts.length?'<p class="undated">'+parts.join(" · ")+"</p>":"";
}
function compactHtml(tv,open,project){
  const big=tv.topics.filter(t=>t.sessions>1),small=tv.topics.filter(t=>t.sessions<=1);
  const max=Math.max(1,...tv.topics.map(t=>t.sessions));
  const made=tv.requests?" ("+counted(tv.requests,"model request")+")":"";
  const rows=P.sorted(big,"sessions").map(t=>compactRow(t,open,project,max)).join("");
  return '<div class="head"><h2>What was being worked on</h2><a data-route href="'+P.href(project,{view:"topics"})+'">Topics in detail →</a></div>'
    +'<p class="sub">'+counted(tv.topics.length,"topic")+" from one-line summaries of all "+counted(tv.sessions,"session")+made+". The bar shows how each session ended.</p>"
    +P.legend(P.totals(tv.topics))+'<div style="margin-top:.4rem">'+rows+"</div>"+smallTopicsLine(tv,small);
}

function fullHtml(tv,state,options){
  const found=tv.topics.find(t=>t.key===state.topic);
  const extra={project:options.project,groups:found?P.groupsFor(options.groups,options.triage,found.key):[]};
  const detail=found?P.detailPanel(found,state,extra):P.notFoundPanel(options.project,state.topic);
  const topics=P.listed(tv.topics);
  return '<div class="tpage">'+P.leftColumn(tv,topics,state)+'<div class="mcol"><section class="panel det">'+detail+"</section>"
    +P.weeklyPanel(tv,topics,state.topic)+P.frictionPanel(tv,topics,state.topic)+"</div></div>";
}

async function postRename(project,topic,text){
  const name=window.SymbiontRename.clean(text);
  const reply=await fetch("/topics/rename",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({project,topic:topic.key,name})});
  const body=await reply.text();
  if(!reply.ok)throw new Error(body||"status "+reply.status);
  return JSON.parse(body).name||topic.key;
}

/* Rename in place. After a save the page redraws from the same data with the new name; a refusal says why. */
function wireRename(container,tv,options,redraw){
  container.addEventListener("click",e=>{
    const button=e.target.closest("[data-rename]");
    if(!button||!options||!options.project)return;
    e.stopPropagation();
    const topic=tv.topics.find(t=>t.key===button.dataset.rename);
    const say=message=>{container.insertAdjacentHTML("afterbegin",'<p class="undated" role="alert">'+esc(message)+"</p>");};
    window.SymbiontRename.inPlace(button,async text=>{
      topic.name=await postRename(options.project,topic,text);
      redraw();
    },say);
  },true);
}

function renderCompact(container,tv,options){
  let open=null;
  const draw=()=>{container.innerHTML=compactHtml(tv,open,options.project);};
  const toggle=e=>{
    const row=e.target.closest("[data-fold]");
    if(!row||e.target.closest("a")||e.target.closest("[data-rename]"))return;
    open=open===row.dataset.fold?null:row.dataset.fold;
    draw();
    const again=container.querySelector('[data-fold="'+CSS.escape(row.dataset.fold)+'"]');
    if(again)again.focus();
  };
  container.onclick=toggle;
  container.onkeydown=e=>{if((e.key==="Enter"||e.key===" ")&&e.target.dataset&&e.target.dataset.fold){e.preventDefault();toggle(e);}};
  draw();wireRename(container,tv,options,draw);
}

function renderPage(container,tv,options){
  const top=P.sorted(P.listed(tv.topics),"sessions")[0];
  const state={topic:options.t||top.key,sort:"sessions",outcome:"all",all:false};
  const draw=()=>{container.innerHTML=fullHtml(tv,state,options);};
  const pick=key=>{Object.assign(state,{topic:key,outcome:"all",all:false});};
  const written=key=>history.replaceState(null,"",window.SymbiontInboxModel.hrefFor(options.project,{view:"topics",t:key}));
  const refocus=selector=>{const el=container.querySelector(selector);if(el)el.focus();};
  const choose=(el,apply,focus)=>{apply(el);draw();refocus(focus(el));};
  container.onclick=e=>{
    const topic=e.target.closest("[data-topic]"),sort=e.target.closest("[data-sort]"),outcome=e.target.closest("[data-outcome]"),more=e.target.closest("[data-more]");
    if(topic)choose(topic,el=>{pick(el.dataset.topic);written(el.dataset.topic);},el=>'.lcol [data-topic="'+CSS.escape(el.dataset.topic)+'"]');
    else if(sort)choose(sort,el=>{state.sort=el.dataset.sort;},el=>'[data-sort="'+el.dataset.sort+'"]');
    else if(outcome)choose(outcome,el=>{state.outcome=el.dataset.outcome;state.all=false;},el=>'[data-outcome="'+el.dataset.outcome+'"]');
    else if(more)choose(more,()=>{state.all=!state.all;},()=>"[data-more]");
  };
  wireRename(container,tv,options,draw);
  draw();
  return {select(key){pick(key);draw();}};
}

function render(container,tv,options){
  injectOnce();
  const compact=Boolean(options&&options.compact);
  container.classList.add("sbt");
  if(!tv||!tv.ready){container.innerHTML=emptyHtml(tv,compact);return undefined;}
  if(compact){renderCompact(container,tv,options||{});return undefined;}
  return renderPage(container,tv,options||{});
}

window.SymbiontTopics={render};
})();
