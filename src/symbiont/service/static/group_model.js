/* What the group page decides, with no DOM so node can test it.
   Violation prevented: Paper Tiger (a page of occurrences that cannot say which one to read first) and Leaky Narrative
   (a Teach preview in wording the agent never hears). Every sentence here is one the developer or the agent reads. */
(function () {
"use strict";
const M=window.SymbiontInboxModel;
const PER_PAGE=12,OTHER_GROUPS=5,DAY_MS=864e5;
const SHORT_COMMAND=90;
/* The wording and the cap are core/house_rules.py's LEAD and core/rule_relevance.py's rule_sentence, ported as is. */
const HOUSE_LEAD="[symbiont] House rules for this repo (from your corrections and PR reviews): ";
const REPO_LEAD="[symbiont] In this repo: ";
const MAX_NOTE_CHARS=600;
const BOUNDARY=/[.!?;:]\s|,\s/g;

const sessionsOf=(data)=>((data.topicView||{}).topics||[]).flatMap(t=>t.sessionList||[]);
const sessionById=(data,id)=>sessionsOf(data).find(s=>s.id===id)||null;
const noun=g=>g.kind==="correction"?"message":"time";

/* Oldest first; a card with no date sorts before every dated one. The list is stable for equal days. */
function chronological(g){
  return g.cards.map((card,i)=>({card,i})).sort((a,b)=>(a.card.date||"").localeCompare(b.card.date||"")||b.i-a.i).map(x=>x.card);
}

const fixed=c=>Boolean(c.fixed)&&c.outcome!=="never_fixed";
/* The clearest example: a real fix, a short command, and the latest of equals (the mockup's pickRecommended). */
function clearest(list){
  let best=0,score=-1;
  list.forEach((c,i)=>{
    const s=(fixed(c)?2:0)+((c.command||"").length<SHORT_COMMAND?1:0)+i/(list.length+1);
    if(s>score){score=s;best=i;}
  });
  return best;
}

const pagesOf=n=>Math.max(1,Math.ceil(n/PER_PAGE));
/* The page that shows the occurrence at chronological index `i` when pages run newest first. */
const pageOfIndex=(n,i)=>Math.floor((n-1-i)/PER_PAGE);
function pageSlice(list,page){
  const rows=list.map((card,index)=>({card,index})).reverse();
  return rows.slice(page*PER_PAGE,page*PER_PAGE+PER_PAGE);
}

/* Sessions per topic, from the topic the miner put on each card; a card without one is "Other". */
function topicShares(g,data){
  const seen=new Map();
  g.cards.forEach(c=>{const t=c.topic||"Other";if(!seen.has(t))seen.set(t,new Set());seen.get(t).add(c.sessionId);});
  const known=new Map(((data.topicView||{}).topics||[]).map(t=>[t.name,t.key]));
  return [...seen].map(([name,ids])=>({name,key:known.has(name)?known.get(name):null,sessions:ids.size}))
    .sort((a,b)=>b.sessions-a.sessions||a.name.localeCompare(b.name));
}

function otherGroups(groups,g,triage){
  return groups.filter(x=>x.key!==g.key&&x.kind===g.kind)
    .sort((a,b)=>b.sessions-a.sessions||b.times-a.times).slice(0,OTHER_GROUPS)
    .map(x=>({key:x.key,name:M.displayName(triage,x),sessions:x.sessions,last:x.last}));
}

const RETURN_WORDS={
  until_worse:"Comes back if it shows up clearly more often than before.",
  never:"Still counted; never comes back on its own."
};
function returnText(tri,fd){
  if(tri.return_rule==="after_sessions"&&tri.after_sessions)return "Comes back after "+M.plural(tri.after_sessions,"more session")+" show it.";
  if(tri.return_rule==="on_date"&&tri.until)return "Comes back on "+fd(tri.until)+".";
  return RETURN_WORDS[tri.return_rule]||"";
}

/* The pill: the tab the group is in, or why an untriaged group is not For review. */
function statusWord(g,tri){
  if(g.noise)return "Folded as noise";
  if(tri.regressed)return "Regressed";
  if(!tri.state&&!g.recurring)return "Seen once";
  return M.TAB_WORDS[M.tabOf({[g.key]:tri},g)];
}
const inReview=(g,tri)=>M.tabOf({[g.key]:tri},g)==="review";

/* One sentence under the facts, from what is stored; nothing when the store says nothing. */
function statusNote(g,tri,fd){
  if(tri.taught_on)return "Lesson added on "+fd(tri.taught_on)+"; any occurrence after that shows up as a regression.";
  if(g.noise)return "Folded as noise: "+g.noiseWords+".";
  if(tri.regressed)return "It happened again after you set it aside on "+fd(tri.changed_on)+".";
  if(tri.state&&tri.state!=="for_review"){
    return (M.TAB_WORDS[M.tabOf({[g.key]:tri},g)]+" by you on "+fd(tri.changed_on)+". "+returnText(tri,fd)).trim();
  }
  return g.recurring?"":"Seen in one session, not yet a pattern.";
}

/* Activity: only events the store recorded, in the order the page lists them. */
function activityRows(g,tri,lastGoal,fd){
  const rows=[{quiet:true,text:"Grouped from "+M.plural(g.sessions,"session"),when:g.first?"first seen "+fd(g.first):""}];
  if(tri.state&&tri.state!=="for_review"&&tri.changed_on&&!tri.regressed){
    rows.push({quiet:false,text:"Moved to "+M.TAB_WORDS[M.tabOf({[g.key]:tri},g)]+(returnText(tri,fd)?". "+returnText(tri,fd):""),when:fd(tri.changed_on)+" · you"});
  }
  if(tri.taught_on)rows.push({quiet:false,text:"Lesson added",when:fd(tri.taught_on)+" · you"});
  if(tri.regressed)rows.push({quiet:false,text:"It happened again after you set it aside",when:fd(tri.changed_on)+" · you"});
  if(g.last)rows.push({quiet:true,text:lastGoal?"Last seen in a session about “"+lastGoal+"”":"Last seen",when:fd(g.last)});
  return rows;
}

function cutAtBoundary(text){
  const head=text.slice(0,MAX_NOTE_CHARS+1);
  for(const strong of [true,false]){
    const ends=[...head.matchAll(BOUNDARY)].filter(m=>(m[0][0]!==",")===strong&&m.index+1<=MAX_NOTE_CHARS).map(m=>m.index+1);
    const end=ends[ends.length-1];
    if(end!==undefined&&end>=Math.floor(MAX_NOTE_CHARS/3))return head.slice(0,end).replace(/[ ,;:]+$/,"")+" ...";
  }
  return head.slice(0,MAX_NOTE_CHARS).replace(/\s+\S*$/,"").replace(/[ ,;:]+$/,"")+" ...";
}
const trimmed=text=>text.trim().replace(/[ .]+$/,"");

/* The note the agent receives for a taught lesson: a correction is said as a house rule, a mistake as a rule note. */
function noteText(kind,lesson){
  const text=trimmed(lesson);
  if(kind==="correction"&&HOUSE_LEAD.length+text.length+1<=MAX_NOTE_CHARS)return HOUSE_LEAD+text+".";
  return REPO_LEAD+(text.length>MAX_NOTE_CHARS?cutAtBoundary(text):text+".");
}

/* The week a day falls in on the shared axis: its index, or before/after when it is outside the axis. */
function weekPosition(axis,iso){
  const day=Date.parse(iso+"T00:00:00Z");
  if(!axis.length||Number.isNaN(day))return null;
  if(day<axis[0].monday.getTime())return {side:"before"};
  const i=axis.findIndex(w=>day<w.monday.getTime()+7*DAY_MS);
  return i<0?{side:"after"}:{index:i};
}
const niceMax=peak=>peak<=4?peak:Math.ceil(peak/2)*2;

/* Bars for the chart: one per axis week with this group's count and the project's sessions that week. */
function weekBars(g,axis,perWeek){
  const mine=new Map(g.weekly),sessions=new Map(perWeek||[]);
  const bars=axis.map(w=>({monday:w.monday,times:mine.get(w.key)||0,sessions:sessions.get(w.key)||0}));
  return {bars,top:niceMax(Math.max(1,...bars.map(b=>b.times)))};
}

window.SymbiontGroupModel={PER_PAGE,sessionById,noun,chronological,clearest,pagesOf,pageOfIndex,pageSlice,topicShares,otherGroups,statusWord,inReview,statusNote,activityRows,noteText,weekPosition,weekBars,fixed};
})();
