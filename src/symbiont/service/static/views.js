/* The Pain points tab's sub-views and the `?view=` link into them.
   Violation prevented: Silent Fallback. A renderer that has not shipped, or a snapshot key that is absent, shows a
   one-line "coming soon" instead of a blank pane or a crash; no `?view=` opens the Overview (view key `struggle`); an unknown one does too and warns once. */
(function () {
"use strict";
const M=window.SymbiontInboxModel;
const SUBVIEWS=[["struggle","Overview"],["inbox","Inbox"],["topics","Topics"],["trends","Is it getting better?"]];
const OTHER_STAGES={context:2,replay:3};
const SOON={topics:"Topics are coming soon.",trends:"The view of whether it is getting better is coming soon."};

function soon(pane,view){pane.innerHTML='<p class="soon" role="status">'+SOON[view]+"</p>";}

/* The page is drawn once; a later link with another `t` moves its selection instead of drawing again. */
let topicsPage=null;
function drawTopics(pane,data,project,route){
  const topics=window.SymbiontTopics;
  if(!topics||!data.topicView)return soon(pane,"topics");
  const incidents=data.incidents||{groups:[]};
  topicsPage=topics.render(pane,data.topicView,{compact:false,project,groups:incidents.groups,triage:data.triage,t:route.t})||null;
}
function drawTrends(pane,data,project){
  const trends=window.SymbiontTrends;
  if(!trends||!data.trends)return soon(pane,"trends");
  trends.render(pane,data.trends,project);
}
function drawInbox(pane,data,project){
  if(!data.incidents){pane.innerHTML='<p class="soon" role="status">Mine this repository again to fill the inbox.</p>';return;}
  window.SymbiontInbox.start(pane,data,project);
}

/* A triage click made on another page (the group page) leaves the drawn Inbox out of date; it redraws on next show. */
let inboxStale=false;
const dataChanged=()=>{inboxStale=true;};
function refreshInbox(){
  if(!inboxStale)return;
  inboxStale=false;
  if(window.SymbiontInbox.refresh)window.SymbiontInbox.refresh();
}

const DETAIL_VIEWS=["group","session"];
const DETAILS={};
let nav=null;
const tabOf=view=>["group","session","notfound"].includes(view)?"inbox":view;
const NOT_FOUND={group:"No such group.",session:"No such session."};

/* Tasks that own a detail page hand their renderer in here; until then the pane says it is not built. */
function registerDetail(view,render){
  if(!DETAIL_VIEWS.includes(view))throw new Error("symbiont: no detail view "+JSON.stringify(view));
  DETAILS[view]=render;
}
function setCrumb(text){
  const crumb=document.getElementById("crumb");
  crumb.textContent=text||"";crumb.hidden=!text;
}
function navigate(route){
  if(!nav)throw new Error("symbiont: navigate called before the dashboard was mounted");
  nav(route);
}
function drawNotFound(pane,route,project){
  const word=NOT_FOUND[route.what]||"Nothing here.";
  pane.innerHTML='<p class="soon" role="status">'+word+' <a data-route href="'+M.hrefFor(project,{view:"inbox"})+'">Back to the inbox</a></p>';
}
function drawDetail(pane,route,data,project){
  const render=DETAILS[route.view];
  if(!render){pane.innerHTML='<p class="soon" role="status">Not built yet.</p>';return;}
  render(pane,route,data,project);
}
const plainClick=e=>e.button===0&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey&&!e.defaultPrevented;
function followRouteLinks(go){
  document.addEventListener("click",e=>{
    const a=e.target.closest&&e.target.closest("a[data-route]");
    if(!a||!plainClick(e))return;
    const url=new URL(a.href,location.href);
    e.preventDefault();
    go(M.routeFrom(url.search,url.hash,console.warn));
  });
}

/* Returns the stage the link asks for (1 is Pain points) and a `show` that opens the remembered sub-view. */
function mount(data,project,s1,warn){
  const first=M.routeFrom(location.search,location.hash,warn);
  const subnav=s1.querySelector("#subnav"),drawn=new Set();
  const draw={
    inbox:()=>drawInbox(s1.querySelector("#vInbox"),data,project),
    topics:route=>drawTopics(s1.querySelector("#vTopics"),data,project,route),
    trends:()=>drawTrends(s1.querySelector("#vTrends"),data,project)
  };
  const paneOf={group:"#vGroup",session:"#vSession",notfound:"#vNotFound"};
  const overviewIfOtherStage=route=>route.view in OTHER_STAGES?{view:"struggle"}:route;
  let current=overviewIfOtherStage(first);
  subnav.insertAdjacentHTML("afterbegin",SUBVIEWS.map(([k,l])=>'<button data-view="'+k+'">'+l+"</button>").join(""));
  document.getElementById("meta").textContent=M.metaLine(data.stage.facts.length,(data.incidents||{groups:[]}).groups);
  const show=route=>{
    const view=route.view;current=route;s1.dataset.view=view;setCrumb("");
    document.getElementById("scope").hidden=!M.scopeVisible(view,1);
    subnav.querySelectorAll("button").forEach(b=>b.setAttribute("aria-current",String(b.dataset.view===tabOf(view))));
    if(view in draw&&!drawn.has(view)){drawn.add(view);draw[view](route);if(view==="inbox")inboxStale=false;}
    else if(view==="inbox")refreshInbox();
    else if(view==="topics"&&topicsPage&&route.t)topicsPage.select(route.t);
    if(view==="notfound")drawNotFound(s1.querySelector(paneOf.notfound),route,project);
    else if(DETAIL_VIEWS.includes(view))drawDetail(s1.querySelector(paneOf[view]),route,data,project);
  };
  nav=route=>{history.pushState(null,"",M.hrefFor(project,route));show(overviewIfOtherStage(route));};
  window.addEventListener("popstate",()=>show(overviewIfOtherStage(M.routeFrom(location.search,location.hash,warn))));
  followRouteLinks(route=>nav(route));
  subnav.onclick=e=>{
    const b=e.target.closest("button[data-view]");
    if(!b)return;
    show({view:b.dataset.view});
    history.replaceState(null,"",M.hrefFor(project,{view:b.dataset.view}));
    b.focus();
  };
  return {stage:OTHER_STAGES[first.view]||1,show:()=>show(current),syncScope:stage=>{document.getElementById("scope").hidden=!M.scopeVisible(current.view,stage);}};
}

window.SymbiontViews={mount,navigate,registerDetail,setCrumb,dataChanged};
})();
