/* The Pain points tab's sub-views and the `?view=` link into them.
   Violation prevented: Silent Fallback. A renderer that has not shipped, or a snapshot key that is absent, shows a
   one-line "coming soon" instead of a blank pane or a crash; an unknown `?view=` opens the inbox and warns once. */
(function () {
"use strict";
const M=window.SymbiontInboxModel;
const SUBVIEWS=[["inbox","Inbox"],["topics","Topics"],["trends","Is it getting better?"],["struggle","Struggle"]];
const OTHER_STAGES={context:2,replay:3};
const SOON={topics:"Topics are coming soon.",trends:"The view of whether it is getting better is coming soon."};

function soon(pane,view){pane.innerHTML='<p class="soon" role="status">'+SOON[view]+"</p>";}

function drawTopics(pane,data,project){
  const topics=window.SymbiontTopics;
  if(!topics||!data.topicView)return soon(pane,"topics");
  topics.render(pane,data.topicView,{compact:false,project});
}
function drawTrends(pane,data){
  const trends=window.SymbiontTrends;
  if(!trends||!data.trends)return soon(pane,"trends");
  trends.render(pane,data.trends);
}
function drawInbox(pane,data,project){
  if(!data.incidents){pane.innerHTML='<p class="soon" role="status">Mine this repository again to fill the inbox.</p>';return;}
  window.SymbiontInbox.start(pane,data,project);
}

/* Returns the stage the link asks for (1 is Pain points) and a `show` that opens the remembered sub-view. */
function mount(data,project,s1,warn){
  const asked=M.viewFrom(location.search,warn);
  const subnav=s1.querySelector("#subnav"),drawn=new Set();
  const draw={
    inbox:()=>drawInbox(s1.querySelector("#vInbox"),data,project),
    topics:()=>drawTopics(s1.querySelector("#vTopics"),data,project),
    trends:()=>drawTrends(s1.querySelector("#vTrends"),data)
  };
  let current=asked in OTHER_STAGES?"inbox":asked;
  subnav.innerHTML=SUBVIEWS.map(([k,l])=>'<button data-view="'+k+'">'+l+"</button>").join("");
  const show=view=>{
    current=view;s1.dataset.view=view;
    document.getElementById("scope").hidden=!M.scopeVisible(view,1);
    subnav.querySelectorAll("button").forEach(b=>b.setAttribute("aria-current",String(b.dataset.view===view)));
    if(view in draw&&!drawn.has(view)){drawn.add(view);draw[view]();}
  };
  subnav.onclick=e=>{
    const b=e.target.closest("button[data-view]");
    if(!b)return;
    show(b.dataset.view);
    const url=new URL(location.href);url.searchParams.set("view",b.dataset.view);history.replaceState(null,"",url);
    b.focus();
  };
  return {stage:OTHER_STAGES[asked]||1,show:()=>show(current),syncScope:stage=>{document.getElementById("scope").hidden=!M.scopeVisible(current,stage);}};
}

window.SymbiontViews={mount};
})();
