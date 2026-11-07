/* What the Inbox decides, with no DOM so node can test it.
   Violation prevented: Paper Tiger. An inbox that lists every group, or hides some without a count, meets "show the
   groups" and fails the need ("what is worth my time"). Only recurring groups are For review; the rest are folded,
   counted and still viewable. inbox.js draws what these functions decide. */
(function () {
"use strict";
const TAB_OF_STATE={for_review:"review",reviewed:"reviewed",resolved:"resolved",archived:"archived"};
const TABS=["review","reviewed","resolved","archived"];
const TAB_WORDS={review:"For review",reviewed:"Reviewed",resolved:"Resolved",archived:"Archived"};
const VIEWS=["inbox","topics","trends","struggle","context","replay"];
const MAX_NAME=80;
const DAY_MS=864e5;

const triageOf=(triage,g)=>(triage||{})[g.key]||{};
/* A group nobody triaged is For review. An unknown state is a contract break, not a silent For review. */
function tabOf(triage,g){
  const state=triageOf(triage,g).state||"for_review";
  if(!(state in TAB_OF_STATE))throw new Error("symbiont: unknown triage state "+JSON.stringify(state)+" for group "+g.key);
  return TAB_OF_STATE[state];
}
const displayName=(triage,g)=>triageOf(triage,g).name||g.name;

const SORTS={
  sessions:(a,b)=>b.sessions-a.sessions||b.times-a.times,
  last:(a,b)=>(b.last||"").localeCompare(a.last||""),
  first:(a,b)=>(b.first||"").localeCompare(a.first||"")
};
const KIND_FILTERS=["all","failure","correction"];
const keepKind=(kind,g)=>kind==="all"||g.kind===kind;

/* review: recurring groups only. once: not recurring, not yet triaged. noise: groups the miner called noise.
   A group the developer moved (Reviewed, Resolved, Archived) is listed in its tab whether or not it recurs. */
function sectionsOf(groups,triage,kind,sort){
  if(!(sort in SORTS))throw new Error("symbiont: unknown sort "+sort);
  const out={review:[],reviewed:[],resolved:[],archived:[],once:[],noise:[]};
  groups.filter(g=>keepKind(kind,g)).forEach(g=>{
    if(g.noise){out.noise.push(g);return;}
    const tab=tabOf(triage,g);
    if(tab!=="review")out[tab].push(g);
    else (g.recurring?out.review:out.once).push(g);
  });
  Object.keys(out).forEach(k=>out[k].sort(SORTS[sort]));
  return out;
}

/* Per reason: how many groups and how many times. Every count carries its noun at the call site. */
function noiseReasons(noiseGroups){
  const by=new Map();
  noiseGroups.forEach(g=>{
    const row=by.get(g.noiseWords)||{reason:g.noiseWords,groups:0,times:0,sessions:0};
    row.groups+=1;row.times+=g.times;row.sessions+=g.sessions;by.set(g.noiseWords,row);
  });
  return [...by.values()].sort((a,b)=>b.times-a.times);
}

const plural=(n,one,many)=>n.toLocaleString("en-US")+" "+(n===1?one:(many||one+"s"));
const sum=(list,pick)=>list.reduce((a,x)=>a+pick(x),0);

/* The five headline tiles: a big number, and a label that is its noun. Sessions read are all mined sessions
   (stage.facts), not only the ones with a lesson. */
const noun=(n,one,many)=>(n===1?one:many);
function tilesOf(data){
  const groups=data.incidents.groups,triage=data.triage;
  const failures=groups.filter(g=>g.kind==="failure"),corrections=groups.filter(g=>g.kind==="correction");
  const failed=sum(failures,g=>g.times),said=sum(corrections,g=>g.times);
  const folded=sum(failures.filter(g=>g.noise),g=>g.times);
  const review=sectionsOf(groups,triage,"all","sessions").review.length;
  const topics=data.incidents.topics.length,read=data.stage.facts.length;
  return [
    {value:read,label:noun(read,"session read","sessions read"),sub:""},
    {value:failed,label:noun(failed,"failed command","failed commands"),sub:plural(folded,"failed command")+" folded as noise"},
    {value:said,label:noun(said,"message from you","messages from you"),sub:plural(sum(corrections.filter(g=>!g.noise),g=>g.times),"message")+" in correction groups"},
    {value:review,label:noun(review,"group for review","groups for review"),sub:"of "+plural(groups.length,"group")+" found"},
    {value:topics,label:noun(topics,"topic","topics"),sub:""}
  ];
}

/* ISO weeks on one shared axis, so two groups' bars can be compared by eye. */
function isoMonday(key){
  const [year,week]=key.split("-W").map(Number);
  const jan4=new Date(Date.UTC(year,0,4));
  return new Date(jan4.getTime()-((jan4.getUTCDay()+6)%7)*DAY_MS+(week-1)*7*DAY_MS);
}
function isoKey(date){
  const thursday=new Date(date.getTime()+(3-((date.getUTCDay()+6)%7))*DAY_MS);
  const jan4=new Date(Date.UTC(thursday.getUTCFullYear(),0,4));
  const week=1+Math.round(((thursday-jan4)/DAY_MS-3+((jan4.getUTCDay()+6)%7))/7);
  return thursday.getUTCFullYear()+"-W"+String(week).padStart(2,"0");
}
function weekAxis(groups){
  const keys=groups.flatMap(g=>g.weekly.map(w=>w[0])).sort();
  if(!keys.length)return [];
  const axis=[],end=isoMonday(keys[keys.length-1]).getTime();
  for(let t=isoMonday(keys[0]).getTime();t<=end;t+=7*DAY_MS)axis.push({key:isoKey(new Date(t)),monday:new Date(t)});
  return axis;
}
const seriesOf=(g,axis)=>{const by=new Map(g.weekly);return axis.map(w=>by.get(w.key)||0);};

/* "Teach the agent" opens with what symbiont would teach, already filled in. Nothing is required: the text falls
   back to the group's name so the route (which needs some words) still gets a sentence. */
/* Only a card where something really fixed it has a fix to teach; "never fixed" and "passed when run again" teach nothing. */
const FIXES=["fixed_in_code","environment_fixed","corrected_command"];
function shownFix(g){
  const card=g.cards.find(c=>FIXES.includes(c.outcome));
  return card?card.fixed:"";
}
function teachDraft(g,name){
  const when=g.trigger?g.trigger.words:"";
  const first=g.kind==="correction"&&g.title?"You said: “"+g.title+"”. ":"";
  const fix=shownFix(g),trains=g.kind==="failure"&&Boolean(fix);
  return {when,what:(first+fix).trim(),trains,name,hasTrigger:Boolean(g.trigger)};
}
const capital=s=>s.charAt(0).toUpperCase()+s.slice(1);
function lessonRequest(project,g,when,what,name){
  const text=[when.trim()?capital(when.trim()):"",what.trim()].filter(Boolean).join(": ")||name;
  const lesson={text_in_plain_words:text,kind:g.kind==="correction"?"correction":"mistake",source_label:"From the inbox"};
  const applies=appliesTo(g.trigger);
  if(applies)lesson.applies_to=applies;
  return {project,lessons:[lesson]};
}
function appliesTo(trigger){
  if(!trigger)return null;
  const terms=trigger.program?[trigger.program]:[],areas=trigger.path?[trigger.path]:[];
  return terms.length||areas.length?{terms,areas}:null;
}
const TEACH_NOTES={
  trains:"This feeds nightly training (a failed command with a fix) and is delivered as a note.",
  noteOnly:"This is delivered as a note only; nightly training learns from failed commands that have a fix.",
  noSituation:"symbiont has not seen a shared situation yet; it will speak when this exact failure recurs."
};
const teachNote=draft=>[draft.hasTrigger?"":TEACH_NOTES.noSituation,draft.trains?TEACH_NOTES.trains:TEACH_NOTES.noteOnly].filter(Boolean).join(" ");

/* The ways back for an archived group; each maps to a rule POST /triage understands. */
const ARCHIVE_CHOICES=[
  {label:"Until it happens in 3 more sessions",detail:"Comes back after 3 more sessions show it.",body:{return_rule:"after_sessions",after_sessions:3}},
  {label:"The next time it shows up",detail:"Comes back in the next session that has it.",body:{return_rule:"new_session"}},
  {label:"Forever",detail:"Still counted; never comes back on its own.",body:{return_rule:"never"}}
];

/* ?view= picks the sub-view; an unknown value opens the inbox and says so once in the console. */
function viewFrom(search,warn){
  const asked=new URLSearchParams(search).get("view");
  if(asked===null||asked==="")return "inbox";
  if(VIEWS.includes(asked))return asked;
  warn("symbiont: unknown view "+JSON.stringify(asked)+"; showing the inbox. Known views: "+VIEWS.join(", "));
  return "inbox";
}
function cleanName(text){
  const name=text.trim();
  if(name.length>MAX_NAME)throw new Error("A name can have at most "+MAX_NAME+" characters; this one has "+name.length+".");
  return name;
}

window.SymbiontInboxModel={TABS,TAB_WORDS,KIND_FILTERS,SORTS,MAX_NAME,tabOf,displayName,sectionsOf,noiseReasons,tilesOf,weekAxis,seriesOf,teachDraft,teachNote,lessonRequest,ARCHIVE_CHOICES,viewFrom,cleanName,plural,triageOf};
})();
