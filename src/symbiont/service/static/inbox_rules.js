/* "Rules you've stated" above the failure groups, and a fold of "Possible rules" below them.
   The top section holds only rules the developer's session model confirmed; groups found by shared words alone wait
   in the fold, shown as quotes, with a line saying how to confirm them. Teach opens the shared dialog and posts
   through the shared triage actions (one implementation for groups and rules); no lesson exists until the Teach
   click. Every data string goes through esc. */
(function () {
"use strict";
const M=window.SymbiontInboxModel,R=window.SymbiontInboxRows,D=()=>window.SymbiontInboxDialogs,A=()=>window.SymbiontTriageActions;
const esc=R.esc;
const FOLD_AFTER=5;
const MAX_QUOTE=140;
const SUB="Things you told the agent more than once. Teach one and the agent hears it before it acts.";
const POSSIBLE_TITLE="Possible rules — not confirmed yet";
const CONFIRM_LINE="Run /symbiont summarize to confirm which of these are rules.";
const ANYWHERE="anywhere in this repo";
const DISMISSED_WORDS="Dismissed. It stays counted but is never shown again.";

const stateOf=(triage,item)=>(triage||{})[item.key]||{};
const isDismissed=(triage,item)=>stateOf(triage,item).state==="archived";
const isTaught=(triage,item)=>item.state==="taught"||Boolean(stateOf(triage,item).taught_on);
const allItems=data=>(data.rules&&data.rules.items)||[];
/* Dismissed on this page since the snapshot was built, plus what the snapshot already left out. */
function dismissedCount(data,confirmed){
  const server=data.rules?(confirmed?data.rules.dismissed:data.rules.dismissedPossible)||0:0;
  return server+allItems(data).filter(i=>i.confirmed===confirmed&&isDismissed(data.triage,i)).length;
}
const itemsOf=(data,confirmed)=>allItems(data).filter(i=>i.confirmed===confirmed&&!isDismissed(data.triage,i));
const dismissedNote=n=>n?' <span class="mu">'+esc(n+" dismissed")+"</span>":"";

/* What the Teach dialog reads from a group: When is the rule's area (or anywhere in the repo), What is the rule. */
function teachable(item){
  const area=item.scope==="area"&&item.area?item.area:"";
  return {key:item.key,name:item.text,kind:"correction",title:"",happened:item.text,fixed:item.text,fixShown:true,trains:false,
    trigger:{words:area||ANYWHERE,path:area}};
}

const saidLine=item=>"said "+M.plural(item.times,"time")+" in "+M.plural(item.sessions,"session")+" · "+(item.last?"last "+R.fd(item.last):"last date unknown");
const quoted=text=>"“"+(text.length>MAX_QUOTE?text.slice(0,MAX_QUOTE-1)+"…":text)+"”";

function exampleHtml(project,example){
  const href=M.hrefFor(project,{view:"session",id:example.sessionId,step:example.step});
  return '<li><a data-route href="'+esc(href)+'">'+esc(quoted(example.text))+'</a> <span class="mu">'+esc(R.fd(example.date))+"</span></li>";
}

function buttonsHtml(taught){
  const teach=taught?"":'<button class="btn primary" data-r="teach">Teach the agent</button>';
  return teach+'<button class="btn ghost" data-r="dismiss">Dismiss</button>';
}

function rowHtml(item,project,taught){
  const area=item.scope==="area"&&item.area?' <span class="mu">in '+esc(item.area)+"</span>":"";
  const lead=item.confirmed?"<b>"+esc(item.text)+"</b>"+area:'<b class="said">You said: '+esc(quoted(item.text))+"</b>";
  const seen=item.examples.filter(e=>item.confirmed||e.text!==item.text);
  const note=taught?'<div class="stnote">Taught. The agent hears it from the next session.</div>':"";
  return '<article class="rrow" data-rule="'+esc(item.key)+'" aria-label="'+esc(item.text)+'">'
    +'<div class="rtext">'+lead+'<div class="why">'+esc(saidLine(item))+"</div>"
    +'<ul class="rquotes">'+seen.map(e=>exampleHtml(project,e)).join("")+"</ul></div>"
    +'<div class="gacts">'+buttonsHtml(taught)+"</div>"+note+"</article>";
}

function listHtml(items,ui,expanded){
  const page=expanded?items:items.slice(0,FOLD_AFTER);
  const more=items.length>page.length?'<button class="btn more" data-r="more">Show '+esc(M.plural(items.length-page.length,"more rule"))+"</button>":"";
  return '<div class="glist">'+page.map(i=>rowHtml(i,ui.project,isTaught(ui.data.triage,i))).join("")+"</div>"+more;
}

/* No confirmed rule, no section: an empty header would only push the failures down. */
function confirmedHtml(ui){
  const items=itemsOf(ui.data,true);
  if(!items.length)return "";
  const head='<h2 id="inRulesTitle" tabindex="-1">Rules you’ve stated <span class="n">'+esc(M.plural(items.length,"rule"))+"</span>"
    +dismissedNote(dismissedCount(ui.data,true))+'</h2><p class="sub">'+esc(SUB)+"</p>";
  return head+listHtml(items,ui,ui.rulesOpen);
}

function possibleHtml(ui){
  const items=itemsOf(ui.data,false);
  if(!items.length)return "";
  const open=ui.open.has("inPossible");
  const title=esc(POSSIBLE_TITLE+" ("+items.length.toLocaleString("en-US")+")");
  const body=open?'<p class="sub">'+esc(CONFIRM_LINE)+"</p>"+listHtml(items,ui,ui.possibleOpen):"";
  return '<details class="fold" id="inPossible"'+(open?" open":"")+'><summary><span class="chev"></span><span>'+title+"</span>"
    +dismissedNote(dismissedCount(ui.data,false))+"</summary>"+body+"</details>";
}

function draw(ui){
  const top=confirmedHtml(ui);
  ui.$("#inRules").innerHTML=top;
  ui.$("#inRules").hidden=!top;
  ui.$("#inPossibleBox").innerHTML=possibleHtml(ui);
}

/* The shared actions call back with the group they were given; a rule has no list position, so focus goes to the
   first control of the section it was in, or the page's tab when none is left. */
function actionsUi(ui,home){
  return {container:ui.container,data:ui.data,project:ui.project,positionOf:()=>0,redraw:()=>{draw(ui);focusFirst(ui,home);}};
}

function focusFirst(ui,home){
  const target=ui.container.querySelector(home+" button.btn")||ui.container.querySelector('#inTabs button[aria-pressed="true"]');
  if(target)target.focus();
}

const itemOf=(ui,node)=>allItems(ui.data).find(i=>i.key===node.closest(".rrow").dataset.rule);

async function onAction(ui,button){
  const kind=button.dataset.r,home=button.closest("#inPossibleBox")?"#inPossibleBox":"#inRules";
  if(kind==="more"){
    if(home==="#inRules")ui.rulesOpen=true;else ui.possibleOpen=true;
    draw(ui);
    return;
  }
  const item=itemOf(ui,button),g=teachable(item),rui=actionsUi(ui,home);
  if(kind==="teach")return D().teach(rui,g,button,A().afterTaught);
  return A().saveState(rui,g,{state:"archived",return_rule:"never"},DISMISSED_WORDS);
}

function mount(ui){
  ui.rulesOpen=false;
  ui.possibleOpen=false;
  const onClick=e=>{
    const button=e.target.closest("button[data-r]");
    if(!button)return;
    onAction(ui,button).catch(err=>D().toast(ui.container,"symbiont could not do that: "+err.message));
  };
  ui.$("#inRules").addEventListener("click",onClick);
  ui.$("#inPossibleBox").addEventListener("click",onClick);
  draw(ui);
}

window.SymbiontInboxRules={mount,draw,FOLD_AFTER,POSSIBLE_TITLE,CONFIRM_LINE};
})();
