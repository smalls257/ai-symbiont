/* "What reviewers flagged" below the failure groups: comments reviewers made that a later edit answered, grouped by
   what they said. Groups that came up twice or more are listed first; single comments wait in a collapsed fold,
   paged, so hundreds of them cost one line. Violation prevented: Paper Tiger (a wall of near-identical rows) and
   Distributed Monolith (Dismiss is the shared triage action on the group key, not a second path). Every string from
   the history is put in the page with textContent, never as markup. */
(function () {
"use strict";
const M=window.SymbiontInboxModel,R=window.SymbiontInboxRows,A=()=>window.SymbiontTriageActions,D=()=>window.SymbiontInboxDialogs;
const TITLE="What reviewers flagged";
const SUB="Comments from reviewers that a later edit answered. Groups that came up again are first.";
const ONCE_ID="inReviewsOnce";
const MORE_KEY="reviews:more";
const DISMISSED_WORDS="Dismissed. It stays counted but is never shown again.";
const MAX_QUOTE=160;

const allGroups=data=>(data.reviews&&data.reviews.groups)||[];
const isDismissed=(triage,group)=>((triage||{})[group.key]||{}).state==="archived";
const shown=data=>allGroups(data).filter(g=>!isDismissed(data.triage,g));
const dismissedCount=data=>((data.reviews&&data.reviews.dismissed)||0)+allGroups(data).filter(g=>isDismissed(data.triage,g)).length;

function el(tag,cls,text){
  const node=document.createElement(tag);
  if(cls)node.className=cls;
  if(text!==undefined)node.textContent=text;
  return node;
}
const quoted=text=>"“"+(text.length>MAX_QUOTE?text.slice(0,MAX_QUOTE-1)+"…":text)+"”";
const list=(names,more)=>names.join(", ")+(more>0?" and "+more+" more":"");

function whyLine(group){
  const times=group.count>1?"came up "+M.plural(group.count,"time")+" in "+M.plural(group.sessions,"session"):"flagged once";
  const parts=[times,group.reviewers.join(", ")];
  if(group.files.length)parts.push(list(group.files,0));
  return parts.join(" · ");
}

function stepLink(project,example){
  const link=el("a","",[example.file,R.fd(example.date)].filter(Boolean).join(" · ")+" — "+quoted(example.gist));
  link.setAttribute("data-route","");
  link.setAttribute("href",M.hrefFor(project,{view:"session",id:example.sessionId,step:example.step}));
  return link;
}

function textBlock(group,project,withExamples){
  const box=el("div","rtext"),lead=el("b","rgist",quoted(group.gist));
  box.appendChild(lead);
  box.appendChild(el("div","why",whyLine(group)));
  if(group.fixedBy.length)box.appendChild(el("div","why","fixed by editing "+group.fixedBy.join(", ")));
  const examples=withExamples?group.examples:group.examples.slice(0,1);
  const links=el("ul","rquotes");
  for(const example of examples){
    const item=el("li");
    item.appendChild(stepLink(project,example));
    links.appendChild(item);
  }
  box.appendChild(links);
  return box;
}

function row(group,project){
  const article=el("article","rrow vrow");
  article.setAttribute("data-review",group.key);
  article.setAttribute("aria-label",group.gist);
  article.appendChild(textBlock(group,project,group.count>1));
  const acts=el("div","gacts"),dismiss=el("button","btn ghost","Dismiss");
  dismiss.setAttribute("data-v","dismiss");
  acts.appendChild(dismiss);
  article.appendChild(acts);
  return article;
}

function rowsOf(groups,project){
  const box=el("div","glist");
  for(const group of groups)box.appendChild(row(group,project));
  return box;
}

function onceFold(singles,ui){
  const fold=el("details","fold"),open=ui.open.has(ONCE_ID);
  fold.id=ONCE_ID;
  fold.open=open;
  const summary=el("summary");
  summary.appendChild(el("span","chev"));
  summary.appendChild(el("span","","Flagged once ("+singles.length.toLocaleString("en-US")+")"));
  fold.appendChild(summary);
  if(!open)return fold;
  const page=M.pageOf(singles,ui.open.has(MORE_KEY));
  fold.appendChild(rowsOf(page.rows,ui.project));
  if(page.more){
    const more=el("button","btn more","Show "+M.plural(page.more,"more comment"));
    more.setAttribute("data-v","more");
    fold.appendChild(more);
  }
  return fold;
}

function head(groups,data){
  const title=el("h2","",TITLE+" ");
  title.id="inReviewsTitle";
  title.setAttribute("tabindex","-1");
  title.appendChild(el("span","n",M.plural(groups.length,"group")));
  const gone=dismissedCount(data);
  if(gone){title.appendChild(document.createTextNode(" "));title.appendChild(el("span","mu",gone+" dismissed"));}
  return [title,el("p","sub",SUB)];
}

function draw(ui){
  const section=ui.$("#inReviews"),groups=shown(ui.data);
  section.hidden=!groups.length;
  const nodes=[];
  if(groups.length){
    const repeated=groups.filter(g=>g.count>=2),singles=groups.filter(g=>g.count<2);
    nodes.push(...head(groups,ui.data));
    if(repeated.length)nodes.push(rowsOf(repeated,ui.project));
    if(singles.length)nodes.push(onceFold(singles,ui));
  }
  section.replaceChildren(...nodes);
}

function focusFirst(ui){
  const target=ui.container.querySelector("#inReviews button.btn")||ui.container.querySelector('#inTabs button[aria-pressed="true"]');
  if(target)target.focus();
}

function actionsUi(ui){
  return {container:ui.container,data:ui.data,project:ui.project,positionOf:()=>0,redraw:()=>{draw(ui);focusFirst(ui);}};
}

async function onClick(ui,button){
  if(button.dataset.v==="more"){ui.open.add(MORE_KEY);draw(ui);return;}
  const key=button.closest("[data-review]").dataset.review;
  const group=allGroups(ui.data).find(g=>g.key===key);
  return A().saveState(actionsUi(ui),{key:group.key,name:group.gist},{state:"archived",return_rule:"never"},DISMISSED_WORDS);
}

function mount(ui){
  ui.reviewsMounted=true;
  ui.$("#inReviews").addEventListener("click",e=>{
    const button=e.target.closest("button[data-v]");
    if(!button)return;
    onClick(ui,button).catch(err=>D().toast(ui.container,"symbiont could not do that: "+err.message));
  });
  draw(ui);
}

window.SymbiontInboxReviews={mount,draw,TITLE,ONCE_ID};
})();
