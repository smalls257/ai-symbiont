/* The Inbox's noise rules: why each kind of item is folded away, when it would come back, and real examples.
   Violation prevented: Black Box (a fold that says "noise" with no reason is a rule nobody can check). Pure
   functions and string builders (store text goes through esc), so node can test them. */
(function () {
"use strict";
const M=window.SymbiontInboxModel;
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const EXAMPLES_SHOWN=12,EXAMPLE_CHARS=160,GROUPS_INLINE=3;

/* Copy per NoiseReason value, from the mockup; `kind` says which Kind filter lists the rule. */
const RULES={
  interrupt:{kind:"both",unit:"stop",why:"You stopped the agent or declined a tool call. The message after it is what counts.",returns:"Comes back if you stop the same kind of command in 3 sessions."},
  look_around:{kind:"failure",unit:"failure",why:"A search or listing that found nothing (exit 1). Finding nothing is an answer, not a mistake.",returns:"Comes back if a look-around fails in 5 sessions within a week and blocks an edit."},
  empty_correction:{kind:"correction",unit:"message",why:"“ok”, “please continue”, “1”, “/compact”: a nudge with nothing to learn from.",returns:"Never returns."},
  plain_retry:{kind:"failure",unit:"failure",why:"The same command passed when run again with no edit in between (network blips, rate limits, a race).",returns:"Comes back if a retry stops passing."},
  throwaway_script:{kind:"failure",unit:"failure",why:"An inline script the agent wrote and fixed itself. It never touched your code.",returns:"Comes back if a script inside the repo fails, not an inline one."},
  deliberate_repro:{kind:"failure",unit:"failure",why:"The agent ran a test or script it expected to fail, to prove the bug before fixing it.",returns:"Comes back if it is still failing after the fix."}
};
const cap=t=>t.length>EXAMPLE_CHARS?t.slice(0,EXAMPLE_CHARS-1)+"…":t;
const keepRule=(kind,rule)=>kind==="all"||rule.kind==="both"||rule.kind===kind;

/* Every card the miner called noise, grouped by its reason word; `value` is the NoiseReason the copy is keyed by. */
function noiseCards(groups){
  const by=new Map();
  groups.forEach(g=>g.cards.forEach(c=>{
    if(!c.noise)return;
    if(!RULES[c.noise])throw new Error("symbiont: no explanation for noise reason "+JSON.stringify(c.noise));
    const row=by.get(c.noiseWords)||{value:c.noise,cards:[]};
    row.cards.push(c);by.set(c.noiseWords,row);
  }));
  return by;
}

/* The noise groups behind a reason, so each stays reachable (its page holds its triage actions). */
const noiseGroupsOf=(groups,reason)=>groups.filter(g=>g.noise&&g.noiseWords===reason);

/* One rule per reason in incidents.noise.byReason, in its order: counts from byReason, examples from the cards. */
function rulesOf(byReason,groups,kind){
  const cards=noiseCards(groups);
  return byReason.map(r=>{
    const found=cards.get(r.reason),copy=found?RULES[found.value]:null,list=found?found.cards:[];
    return {reason:r.reason,count:r.count,copy,sessions:new Set(list.map(c=>c.sessionId)).size,
      examples:list,total:list.length,groups:noiseGroupsOf(groups,r.reason)};
  }).filter(r=>!r.copy||keepRule(kind,r.copy));
}

function exampleHtml(c,project){
  const href=M.hrefFor(project,{view:"session",id:c.sessionId,step:c.step});
  const date=c.date?M.shortDay(c.date):"date unknown";
  return '<li><a data-route href="'+esc(href)+'">'+esc(date)+"</a> <span>"+esc(cap(c.command||""))+"</span> · "+esc(cap(c.happened||""))+"</li>";
}

const exampleList=(list,project)=>"<ul>"+list.map(c=>exampleHtml(c,project)).join("")+"</ul>";

/* The first EXAMPLES_SHOWN examples, then a control that reveals every other one. */
function examplesHtml(r,project){
  if(!r.examples.length)return '<div class="w wide">No examples are in this snapshot.</div>';
  const head=r.examples.slice(0,EXAMPLES_SHOWN),rest=r.examples.slice(EXAMPLES_SHOWN);
  const all=rest.length?'<details class="nzall"><summary>Show all '+r.total.toLocaleString("en-US")+"</summary>"+exampleList(rest,project)+"</details>":"";
  const word=rest.length?head.length+" of "+r.total.toLocaleString("en-US"):String(r.total);
  return '<details class="nzex"><summary>Show '+word+" real "+(r.total===1?"example":"examples")+"</summary>"+exampleList(head,project)+all+"</details>";
}

function groupLinksHtml(r,project){
  if(!r.groups.length)return "";
  const links=r.groups.map(g=>'<li><a data-route href="'+esc(M.hrefFor(project,{view:"group",key:g.key}))+'">'+esc(g.name)+"</a> · "+esc(M.plural(g.times,"time"))+"</li>").join("");
  const list="<ul>"+links+"</ul>";
  if(r.groups.length<=GROUPS_INLINE)return '<div class="nzgroups">'+list+"</div>";
  return '<details class="nzgroups"><summary>'+M.plural(r.groups.length,"group")+"</summary>"+list+"</details>";
}

function ruleHtml(r,project){
  const unit=r.copy?r.copy.unit:"item";
  return '<div class="nz"><div class="r">'+esc(r.reason)+"</div>"
    +(r.copy?'<div class="w">'+esc(r.copy.why)+'</div><div class="ret">'+esc(r.copy.returns)+"</div>":"")
    +'<div class="ct"><b>'+r.count.toLocaleString("en-US")+"</b><span>"+(r.count===1?unit:unit+"s")+(r.sessions?" · "+M.plural(r.sessions,"session"):"")+"</span></div>"
    +groupLinksHtml(r,project)+examplesHtml(r,project)+"</div>";
}

/* The section's body: the rules and the Seen once line. */
function rulesHtml(rules,onceLine,project){
  const head='<h3>Folded as noise</h3><p class="mu intro">Never deleted: counted, viewable, and each rule says when it would bring an item back.</p>';
  const body=rules.length?rules.map(r=>ruleHtml(r,project)).join(""):'<div class="empty2">Nothing was folded as noise in this project.</div>';
  return head+body+(onceLine?'<div class="ungrouped">'+esc(onceLine)+"</div>":"");
}

window.SymbiontInboxNoise={rulesOf,rulesHtml};
})();
