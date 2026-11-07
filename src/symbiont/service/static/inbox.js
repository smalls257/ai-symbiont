/* The Inbox: what keeps going wrong, for review. The default view of the Pain points tab.
   Violation prevented: Black Box (a triage click that changes nothing visible, or fails without a word) and Paper Tiger
   (a list nobody can work through). Every click posts to the service and shows its answer or its error; the list
   redraws from the saved state and keyboard focus lands on the next thing to do. Rules live in inbox_model.js,
   markup in inbox_rows.js, dialogs in inbox_dialogs.js. */
(function () {
"use strict";
const M=window.SymbiontInboxModel,R=window.SymbiontInboxRows,N=window.SymbiontInboxNoise;
const SORT_WORDS=M.SORT_WORDS;
const KIND_WORDS={all:"All",failure:"Agent failures",correction:"Your corrections"};
const STATE_OF={reviewed:"reviewed",resolve:"resolved",reopen:"for_review"};
const DONE_WORDS={
  reviewed:"Marked reviewed. It stays in Reviewed.",
  resolve:"Resolved. It comes back as Regressed if it happens again.",
  reopen:"Back in For review."
};

function skeleton(){
  return '<div class="sumline" id="inSum"></div>'
    +'<section class="panel" id="inMain" aria-label="Pain points inbox"><h2 id="inTitle" tabindex="-1">What keeps going wrong <span class="n" id="inCount"></span></h2>'
    +'<p class="sub">Agent failures and your corrections that came back across sessions, grouped by what they share. Each one says what happened, what fixed it, and whether it is worth your time.</p>'
    +'<div class="tbar"><div class="seg2" role="group" aria-label="Status" id="inTabs"></div><span class="sp"></span>'
    +'<div class="seg2" role="group" aria-label="Kind" id="inKinds"></div>'
    +'<label class="mu sortl">Sort <select class="sel" id="inSort">'+Object.keys(SORT_WORDS).map(k=>'<option value="'+k+'">'+SORT_WORDS[k]+"</option>").join("")+"</select></label></div>"
    +'<div class="glist" id="inList"></div><div id="inFolds"></div></section>'
    +'<aside class="side"><section class="panel" id="inTopics" aria-label="What was being worked on"></section>'
    +'<section class="panel" id="inFriction" aria-label="Where sessions got stuck"></section></aside>';
}

function start(container,data,project){
  const ui={container,data,project,tab:"review",kind:"all",sort:M.DEFAULT_SORT,open:new Set()};
  container.innerHTML=skeleton();
  const $=sel=>container.querySelector(sel);
  ui.$=$;
  $("#inSort").onchange=e=>{ui.sort=e.target.value;draw(ui);};
  container.addEventListener("click",e=>onClick(ui,e));
  container.addEventListener("keydown",e=>onKey(ui,e));
  container.addEventListener("toggle",e=>onToggle(ui,e),true);
  drawTopics(ui);
  drawFriction(ui);
  draw(ui);
}

function sections(ui){return M.sectionsOf(ui.data.incidents.groups,ui.data.triage,ui.kind,ui.sort);}

function draw(ui){
  const found=sections(ui);
  ui.$("#inSum").innerHTML=R.tilesHtml(M.tilesOf(ui.data));
  drawTabs(ui,found);
  const list=found[ui.tab],axis=M.weekAxis(ui.data.incidents.groups);
  ui.$("#inCount").textContent=list.length?M.plural(list.length,"group"):"";
  const page=ui.tab==="review"?M.pageOf(list,ui.open.has("review:more")):{rows:list,more:0};
  ui.$("#inList").innerHTML=(list.length?page.rows.map(g=>R.rowHtml(shownOf(ui,g,axis))).join(""):emptyHtml(ui,found))+moreHtml(page.more);
  ui.$("#inFolds").innerHTML=foldsHtml(ui,found,axis);
}

const moreHtml=n=>n?'<button class="btn more" data-more="review">Show '+M.plural(n,"more group","more groups")+"</button>":"";

function shownOf(ui,g,axis){
  const tri=M.triageOf(ui.data.triage,g);
  return {g,project:ui.project,name:M.displayName(ui.data.triage,g),tab:M.tabOf(ui.data.triage,g),tri,series:M.seriesOf(g,axis),weeks:axis};
}

function emptyHtml(ui,found){
  const word=M.TAB_WORDS[ui.tab];
  const more=ui.tab==="review"&&(found.once.length||found.noise.length)?" The folded groups below were seen once or are noise.":"";
  return '<div class="empty2">No groups in '+word+"."+more+"</div>";
}

function drawTabs(ui,found){
  ui.$("#inTabs").innerHTML=M.TABS.map(k=>'<button aria-pressed="'+(ui.tab===k)+'" data-tab="'+k+'">'+M.TAB_WORDS[k]+'<span class="c">'+found[k].length.toLocaleString("en-US")+" "+(found[k].length===1?"group":"groups")+"</span></button>").join("");
  ui.$("#inKinds").innerHTML=M.KIND_FILTERS.map(k=>'<button aria-pressed="'+(ui.kind===k)+'" data-kind="'+k+'">'+KIND_WORDS[k]+"</button>").join("");
}

/* A fold is drawn closed and empty until opened: a project can have hundreds of seen-once groups, and building
   their rows up front would make every redraw slow. Opened folds stay open across redraws. */
function foldsHtml(ui,found,axis){
  const rows=list=>'<div class="glist">'+list.map(g=>R.rowHtml(shownOf(ui,g,axis))).join("")+"</div>";
  const body=(id,list)=>ui.open.has(id)?rows(list):"";
  const count=list=>M.plural(list.length,"group");
  const once=found.once.length?R.foldHtml("inOnce","Seen once",count(found.once),"each happened in one session",body("inOnce",found.once)):"";
  return once+noiseHtml(ui,found);
}

/* The rules say why items are folded; the Archived tab shows them open, the other tabs behind the fold. */
function noiseHtml(ui,found){
  const incidents=ui.data.incidents,rules=N.rulesOf(incidents.noise.byReason,incidents.groups,ui.kind);
  const body=N.rulesHtml(rules,M.seenOnceLine(found.once),ui.project);
  if(ui.tab==="archived")return '<div class="rules">'+body+"</div>";
  if(!incidents.noise.total)return "";
  const lead=rules.map(r=>R.esc(r.reason)+" ("+M.plural(r.count,"item")+")").join(" · ");
  return R.foldHtml("inNoise","Folded as noise",M.plural(incidents.noise.total,"item"),lead,ui.open.has("inNoise")?body:"");
}

function onToggle(ui,e){
  const fold=e.target.closest&&e.target.closest("details.fold");
  if(!fold||fold.open===ui.open.has(fold.id))return;
  if(fold.open)ui.open.add(fold.id);else ui.open.delete(fold.id);
  draw(ui);
  ui.$("#"+fold.id+" summary").focus();
}

function drawTopics(ui){
  const panel=ui.$("#inTopics"),topics=window.SymbiontTopics,view=ui.data.topicView;
  if(topics&&view){panel.innerHTML='<div id="inTopicsBody"></div>';topics.render(panel.firstChild,view,{compact:true,project:ui.project});return;}
  panel.innerHTML='<h2>What was being worked on</h2><p class="sub">Topics are coming soon.</p>';
}

function drawFriction(ui){
  const view=ui.data.topicView,panel=ui.$("#inFriction");
  if(!view){panel.hidden=true;return;}
  panel.innerHTML=R.frictionHtml(M.frictionRows(view));
}

/* Redrawing replaces the clicked button, so focus goes to the same row's next button, the row now at that place,
   or the status tab, never to the page body. */
function focusAfter(ui,key,position){
  const rows=[...ui.container.querySelectorAll("#inList .grp")];
  const same=ui.container.querySelector('#inList .grp[data-key="'+CSS.escape(key)+'"] button.btn');
  const target=same||(rows.length?rows[Math.min(position,rows.length-1)].querySelector("button.btn"):null)||ui.$('#inTabs button[aria-pressed="true"]');
  if(target)target.focus();
}
const positionOf=(ui,key)=>[...ui.container.querySelectorAll("#inList .grp")].findIndex(r=>r.dataset.key===key);

const INNER_CONTROL="button,a,select,input,summary,.archmenu";
const groupOf=(ui,row)=>ui.data.incidents.groups.find(x=>x.key===row.dataset.key);
function openGroup(ui,row){
  window.SymbiontViews.navigate({view:"group",key:groupOf(ui,row).key});
}
/* Enter on the row itself opens the group; Enter on a button or link inside keeps that control's own action. */
function onKey(ui,e){
  if(e.key!=="Enter"||!e.target.classList||!e.target.classList.contains("grp"))return;
  openGroup(ui,e.target);
}

function onClick(ui,e){
  const clicked=e.target.closest(".grp");
  if(clicked&&!e.target.closest(INNER_CONTROL)){openGroup(ui,clicked);return;}
  const tab=e.target.closest("[data-tab]"),kind=e.target.closest("[data-kind]"),act=e.target.closest("button[data-a]");
  if(tab){ui.tab=tab.dataset.tab;draw(ui);ui.$('#inTabs button[aria-pressed="true"]').focus();return;}
  if(kind){ui.kind=kind.dataset.kind;draw(ui);ui.$('#inKinds button[aria-pressed="true"]').focus();return;}
  if(e.target.closest("[data-more]")){
    const first=M.focusAfterExpand(M.REVIEW_PAGE);
    ui.open.add("review:more");draw(ui);
    const row=ui.container.querySelectorAll("#inList .grp")[first],control=row&&row.querySelector("button.btn");
    if(control)control.focus();
    return;
  }
  if(!act)return;
  const row=act.closest(".grp"),g=ui.data.incidents.groups.find(x=>x.key===row.dataset.key);
  runAction(ui,g,act).catch(err=>window.SymbiontInboxDialogs.toast(ui.container,"symbiont could not do that: "+err.message));
}

async function runAction(ui,g,button){
  const a=button.dataset.a,D=window.SymbiontInboxDialogs;
  if(a==="rename")return D.renameInPlace(ui,g,button,saveName);
  if(a==="teach")return D.teach(ui,g,button,afterTaught);
  if(a==="archive")return D.archiveMenu(ui,g,button,choice=>saveState(ui,g,{state:"archived",...choice.body},"Archived. "+choice.detail));
  return saveState(ui,g,{state:STATE_OF[a]},DONE_WORDS[a]);
}

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
}

async function saveState(ui,g,fields,message){
  const position=positionOf(ui,g.key);
  const reply=await post("/triage",{project:ui.project,group_key:g.key,...fields});
  remember(ui,g,{state:reply.state,regressed:false});
  draw(ui);focusAfter(ui,g.key,position);
  window.SymbiontInboxDialogs.toast(ui.container,message);
}

async function saveName(ui,g,text){
  const name=M.cleanName(text);
  const reply=await post("/triage",{project:ui.project,group_key:g.key,name});
  remember(ui,g,{name:reply.name});
  draw(ui);
  const own=ui.container.querySelector('.grp[data-key="'+CSS.escape(g.key)+'"] .sn');
  if(own)own.focus();
  window.SymbiontInboxDialogs.toast(ui.container,name?"Renamed.":"Name restored to the generated one.");
}

async function afterTaught(ui,g,request){
  await post("/lessons/add",request);
  const reply=await post("/triage",{project:ui.project,group_key:g.key,taught:true});
  remember(ui,g,{taught_on:reply.taught_on});
  draw(ui);focusAfter(ui,g.key,positionOf(ui,g.key));
  window.SymbiontInboxDialogs.toast(ui.container,"Lesson saved. The agent hears it from the next session.");
}

window.SymbiontInbox={start};
})();
