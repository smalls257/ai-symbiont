/* "Rules you've stated": things the developer told the agent more than once, above the failure groups in the Inbox.
   Violation prevented: Distributed Monolith (a second Teach and archive implementation would drift from the groups'),
   so Teach opens the shared dialog and posts through the shared triage actions; and Leaky Narrative (an unconfirmed
   rule says it was only grouped by shared words). No lesson exists until the Teach click. Every data string goes
   through esc. */
(function () {
"use strict";
const M=window.SymbiontInboxModel,R=window.SymbiontInboxRows,D=()=>window.SymbiontInboxDialogs,A=()=>window.SymbiontTriageActions;
const esc=R.esc;
const FOLD_AFTER=5;
const SUB="Things you told the agent more than once. Teach one and the agent hears it before it acts.";
const UNCONFIRMED="unconfirmed — grouped by shared words; run /symbiont summarize to confirm";
const EMPTY="No repeated rules were found yet.";
const ANYWHERE="anywhere in this repo";
const DISMISSED_WORDS="Dismissed. It stays counted but is never shown again.";

const stateOf=(triage,item)=>(triage||{})[item.key]||{};
const isDismissed=(triage,item)=>stateOf(triage,item).state==="archived";
const isTaught=(triage,item)=>item.state==="taught"||Boolean(stateOf(triage,item).taught_on);
const visibleItems=(rules,triage)=>((rules&&rules.items)||[]).filter(i=>!isDismissed(triage,i));

/* What the Teach dialog reads from a group: When is the rule's area (or anywhere in the repo), What is the rule. */
function teachable(item){
  const area=item.scope==="area"&&item.area?item.area:"";
  return {key:item.key,name:item.text,kind:"correction",title:"",happened:item.text,fixed:item.text,fixShown:true,trains:false,
    trigger:{words:area||ANYWHERE,path:area}};
}

const saidLine=item=>"said "+M.plural(item.times,"time")+" in "+M.plural(item.sessions,"session")+" · "+(item.last?"last "+R.fd(item.last):"last date unknown");

function exampleHtml(project,example){
  const href=M.hrefFor(project,{view:"session",id:example.sessionId,step:example.step});
  return '<li><a data-route href="'+esc(href)+'">“'+esc(example.text)+'”</a> <span class="mu">'+esc(R.fd(example.date))+"</span></li>";
}

function buttonsHtml(taught){
  const teach=taught?"":'<button class="btn primary" data-r="teach">Teach the agent</button>';
  return teach+'<button class="btn ghost" data-r="dismiss">Dismiss</button>';
}

function rowHtml(item,project,taught){
  const tag=item.confirmed?"":'<span class="pill review">'+esc(UNCONFIRMED)+"</span> ";
  const area=item.scope==="area"&&item.area?' <span class="mu">in '+esc(item.area)+"</span>":"";
  const note=taught?'<div class="stnote">Taught. The agent hears it from the next session.</div>':"";
  return '<article class="rrow" data-rule="'+esc(item.key)+'" aria-label="'+esc(item.text)+'">'
    +'<div class="rtext"><b>'+esc(item.text)+"</b>"+area+'<div class="why">'+tag+esc(saidLine(item))+"</div>"
    +'<ul class="rquotes">'+item.examples.map(e=>exampleHtml(project,e)).join("")+"</ul></div>"
    +'<div class="gacts">'+buttonsHtml(taught)+"</div>"+note+"</article>";
}

function sectionHtml(rules,project,triage,expanded){
  const shown=visibleItems(rules,triage);
  const page=expanded?shown:shown.slice(0,FOLD_AFTER);
  const head='<h2 id="inRulesTitle" tabindex="-1">Rules you’ve stated'+(shown.length?' <span class="n">'+esc(M.plural(shown.length,"rule"))+"</span>":"")+'</h2><p class="sub">'+esc(SUB)+"</p>";
  if(!shown.length)return head+'<div class="empty2">'+esc(EMPTY)+"</div>";
  const more=shown.length>page.length?'<button class="btn more" data-r="more">Show '+esc(M.plural(shown.length-page.length,"more rule"))+"</button>":"";
  return head+'<div class="glist">'+page.map(i=>rowHtml(i,project,isTaught(triage,i))).join("")+"</div>"+more;
}

function draw(ui){
  const rules=ui.data.rules;
  ui.$("#inRules").innerHTML=sectionHtml(rules,ui.project,ui.data.triage,ui.rulesOpen);
}

/* The shared actions call back with the group they were given; a rule has no list position, so focus goes to the
   section's first control, or its heading when no rule is left. */
function actionsUi(ui){
  return {container:ui.container,data:ui.data,project:ui.project,positionOf:()=>0,redraw:()=>{draw(ui);focusFirst(ui);}};
}

function focusFirst(ui){
  const target=ui.container.querySelector("#inRules button.btn")||ui.container.querySelector("#inRulesTitle");
  if(target)target.focus();
}

const itemOf=(ui,node)=>((ui.data.rules&&ui.data.rules.items)||[]).find(i=>i.key===node.closest(".rrow").dataset.rule);

async function onAction(ui,button){
  const kind=button.dataset.r;
  if(kind==="more"){ui.rulesOpen=true;draw(ui);return;}
  const item=itemOf(ui,button),g=teachable(item),rui=actionsUi(ui);
  if(kind==="teach")return D().teach(rui,g,button,A().afterTaught);
  return A().saveState(rui,g,{state:"archived",return_rule:"never"},DISMISSED_WORDS);
}

function mount(ui){
  ui.rulesOpen=false;
  draw(ui);
  ui.$("#inRules").addEventListener("click",e=>{
    const button=e.target.closest("button[data-r]");
    if(!button)return;
    onAction(ui,button).catch(err=>D().toast(ui.container,"symbiont could not do that: "+err.message));
  });
}

window.SymbiontInboxRules={mount,draw,sectionHtml,teachable,FOLD_AFTER,UNCONFIRMED,EMPTY};
})();
