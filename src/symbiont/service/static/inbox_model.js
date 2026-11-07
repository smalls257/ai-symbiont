/* What the Inbox decides, with no DOM so node can test it.
   Violation prevented: Paper Tiger. An inbox that lists every group, or hides some without a count, meets "show the
   groups" and fails the need ("what is worth my time"). Only recurring groups are For review; the rest are folded,
   counted and still viewable. inbox.js draws what these functions decide. */
(function () {
"use strict";
const TAB_OF_STATE={for_review:"review",reviewed:"reviewed",resolved:"resolved",archived:"archived"};
const TABS=["review","reviewed","resolved","archived"];
const TAB_WORDS={review:"For review",reviewed:"Reviewed",resolved:"Resolved",archived:"Archived"};
const VIEWS=["inbox","topics","trends","struggle","context","replay","group","session"];
const DAY_MS=864e5;

const triageOf=(triage,g)=>(triage||{})[g.key]||{};
/* A group nobody triaged is For review. An unknown state is a contract break, not a silent For review. */
function tabOf(triage,g){
  const state=triageOf(triage,g).state||"for_review";
  if(!(state in TAB_OF_STATE))throw new Error("symbiont: unknown triage state "+JSON.stringify(state)+" for group "+g.key);
  return TAB_OF_STATE[state];
}
const displayName=(triage,g)=>triageOf(triage,g).name||g.name;

/* worth: a group with a fix the page shows leads, then the one in more sessions, then the one that happened more. */
const SORTS={
  worth:(a,b)=>(+!!b.fixShown-+!!a.fixShown)||b.sessions-a.sessions||b.times-a.times,
  sessions:(a,b)=>b.sessions-a.sessions||b.times-a.times,
  last:(a,b)=>(b.last||"").localeCompare(a.last||""),
  first:(a,b)=>(b.first||"").localeCompare(a.first||"")
};
/* Twenty rows of equal weight is a wall; the first fifteen are what to read, the rest are one click away. */
const REVIEW_PAGE=15;
const pageOf=(list,expanded)=>expanded?{rows:list,more:0}:{rows:list.slice(0,REVIEW_PAGE),more:Math.max(0,list.length-REVIEW_PAGE)};
/* The "click a theme" hint describes the Overview page's selection; on other views it points at nothing. */
const scopeVisible=(view,stage)=>stage===1&&view==="struggle";
/* Show more redraws the list; the first row that was not there before is where keyboard focus continues. */
const focusAfterExpand=shownBefore=>shownBefore;
const SORT_WORDS={worth:"Worth a look",sessions:"most sessions",last:"last seen",first:"newest group"};
const DEFAULT_SORT="worth";
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
    {value:read,label:noun(read,"session read","sessions read"),sub:rangeText(groups)},
    {value:failed,label:noun(failed,"failed command","failed commands"),sub:plural(folded,"failed command")+" folded as noise"},
    {value:said,label:noun(said,"message from you","messages from you"),sub:plural(sum(corrections.filter(g=>!g.noise),g=>g.times),"message")+" in correction groups"},
    {value:review,label:noun(review,"group for review","groups for review"),sub:"of "+plural(groups.length,"group")+" found"},
    {value:topics,label:noun(topics,"topic","topics"),sub:requestsText(data.topicView)}
  ];
}

/* First and last day any group was seen, "Feb 11 – Aug 31"; empty when no group has a date. */
const shortDay=d=>{const p=d.split("-");return MONTH_NAMES[+p[1]-1]+" "+(+p[2]);};
function rangeText(groups){
  const firsts=groups.map(g=>g.first).filter(Boolean).sort(),lasts=groups.map(g=>g.last).filter(Boolean).sort();
  return firsts.length&&lasts.length?shortDay(firsts[0])+" – "+shortDay(lasts[lasts.length-1]):"";
}
/* The request count is omitted, not guessed, when the snapshot does not know it. */
const requestsText=view=>view&&view.requests?"from "+plural(view.requests,"summarizer request"):"";

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

/* "Teach the agent" opens with what symbiont would teach, already filled in. Nothing is required: an empty What
   falls back to the group's "What happened" sentence, so a saved lesson is never only a trigger.
   g.fixed is the server's one answer; it is taught only when the verdict says something really fixed it.
   g.trains is the server's: the mined lesson behind the group is one nightly training reads.
   A correction's text is quoted as "You said" only when the history is the developer's own (ownHistory). */
function teachDraft(g,name,ownHistory){
  const when=g.trigger?g.trigger.words:"";
  const first=g.kind==="correction"&&g.title&&ownHistory?"You said: “"+g.title+"”. ":"";
  const fix=g.fixShown?g.fixed:"";
  return {when,what:(first+fix).trim(),trains:Boolean(g.trains),name,hasTrigger:Boolean(g.trigger)};
}
const capital=s=>s.charAt(0).toUpperCase()+s.slice(1);
function lessonRequest(project,g,when,what,name){
  const body=what.trim()||g.happened||"";
  const text=[when.trim()?capital(when.trim()):"",body].filter(Boolean).join(": ")||name;
  const lesson={text_in_plain_words:text,kind:g.kind==="correction"?"correction":"mistake",source_label:"From the inbox"};
  const applies=appliesTo(g.trigger);
  if(applies)lesson.applies_to=applies;
  return {project,lessons:[lesson]};
}
/* The body that records the day a lesson was taught, with the id /lessons/add gave it. */
function taughtRequest(project,g,added){
  return {project,group_key:g.key,taught:true,lesson_id:added.ids[0]};
}
function appliesTo(trigger){
  if(!trigger)return null;
  const terms=trigger.program?[trigger.program]:[],areas=trigger.path?[trigger.path]:[];
  return terms.length||areas.length?{terms,areas}:null;
}
const TEACH_NOTES={
  trains:"The mined lesson behind this group feeds nightly training; your note is delivered to the agent.",
  noteOnly:"Delivered to the agent as a note; it does not feed nightly training.",
  noSituation:"symbiont has not seen a shared situation yet; it will speak when this exact failure recurs."
};
const teachNote=draft=>[draft.hasTrigger?"":TEACH_NOTES.noSituation,draft.trains?TEACH_NOTES.trains:TEACH_NOTES.noteOnly].filter(Boolean).join(" ");

/* The ways back for an archived group, the mockup's four in its order; each body is a rule POST /triage
   understands. "For 30 days" says its day only once `archiveChoices(today)` knows today. */
const ARCHIVE_DAYS=30;
const ARCHIVE_CHOICES=[
  {label:"Until it happens in 3 more sessions",detail:"Comes back after 3 more sessions show it.",body:{return_rule:"after_sessions",after_sessions:3}},
  {label:"Until it gets worse",detail:"Comes back if it shows up clearly more often than before.",body:{return_rule:"until_worse"}},
  {label:"For 30 days",detail:"Comes back 30 days from now.",body:{return_rule:"on_date"}},
  {label:"Forever",detail:"Still counted; never comes back on its own.",body:{return_rule:"never"}}
];
const MONTH_NAMES=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function archiveChoices(today){
  const back=new Date(today.getFullYear(),today.getMonth(),today.getDate()+ARCHIVE_DAYS);
  const day=MONTH_NAMES[back.getMonth()]+" "+back.getDate();
  return ARCHIVE_CHOICES.map(c=>c.body.return_rule==="on_date"?{...c,detail:"Comes back on "+day+"."}:c);
}

/* ?view= picks the sub-view; no value, or an unknown one, opens the Overview (key `struggle`); an unknown one says so once in the console. */
function viewFrom(search,warn){
  const asked=new URLSearchParams(search).get("view");
  if(asked===null||asked==="")return "struggle";
  if(VIEWS.includes(asked))return asked;
  warn("symbiont: unknown view "+JSON.stringify(asked)+"; showing the overview. Known views: "+VIEWS.join(", "));
  return "struggle";
}
/* Detail views need what names them; without it the page says what is missing instead of opening another item. */
const ROUTE_PARTS=["key","id","step","t"];
const NEEDS={group:"key",session:"id"};
const enc=encodeURIComponent;
function hrefFor(project,route){
  let out="?project="+enc(project)+"&view="+enc(route.view);
  for(const part of ROUTE_PARTS)if(route[part]!==undefined&&route[part]!==null&&route[part]!=="")out+="&"+part+"="+enc(route[part]);
  return route.hash?out+"#"+enc(route.hash):out;
}
/* A hash that is not valid percent-encoding was typed by hand; it stays as typed. */
function hashFrom(hash){
  const raw=String(hash||"").replace(/^#/,"");
  try{return decodeURIComponent(raw);}catch(_){return raw;}
}
function routeFrom(search,hash,warn){
  const view=viewFrom(search,warn||console.warn),q=new URLSearchParams(search);
  const route={view};
  for(const part of ROUTE_PARTS){const v=q.get(part);if(v)route[part]=v;}
  if(route.step!==undefined&&!/^\d+$/.test(route.step))delete route.step;
  else if(route.step!==undefined)route.step=Number(route.step);
  const missing=NEEDS[view];
  if(missing&&!route[missing])return {view:"notfound",what:view};
  const h=hashFrom(hash);
  if(h)route.hash=h;
  return route;
}

const MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const dayWord=iso=>{const m=/^(\d{4})-(\d{2})-(\d{2})/.exec(iso||"");return m?MONTHS[Number(m[2])-1]+" "+Number(m[3])+", "+m[1]:null;};
/* The header's one line of scale: how many sessions, over which days, and that nothing left the machine. */
function metaLine(sessions,groups){
  const firsts=groups.map(g=>g.first).filter(Boolean).sort(),lasts=groups.map(g=>g.last).filter(Boolean).sort();
  const first=dayWord(firsts[0]),last=dayWord(lasts[lasts.length-1]);
  const span=first&&last?" \u00b7 "+first+" \u2013 "+last:"";
  return sessions+(sessions===1?" session":" sessions")+span+" \u00b7 local only";
}
const cleanName=text=>window.SymbiontRename.clean(text);

/* A group's trend pill word and its verdict line. A badge value this page does not know is a bug upstream. */
const BADGE_WORDS={new:"New this month",rising:"Rising"};
function badgeLabel(badge){
  if(!badge)return "";
  if(!(badge in BADGE_WORDS))throw new Error("symbiont: unknown group badge "+JSON.stringify(badge));
  return BADGE_WORDS[badge];
}
/* The Seen once fold's one-line promise: nothing here is lost, it just is not a pattern yet. */
function seenOnceLine(once){
  if(!once.length)return "";
  const failed=sum(once.filter(g=>g.kind==="failure"),g=>g.times);
  return "Seen once: "+plural(once.length,"group")+" ("+plural(failed,"failed command")+") — counted, not yet a pattern. They still count in topic outcomes.";
}
const verdictText=g=>g.verdictSentence||g.verdict;

/* The story lines of a group or card: Working on / What broke / How it ended, then Worth a look when the
   session model wrote one. A correction has no failed command: it reads What you said / What the agent did next.
   A line the miner could not say is left out, never filled with a placeholder. */
const STORY_LABELS={failure:["Working on","What broke","How it ended"],correction:["Working on","What you said","What the agent did next"]};
function storyRows(s){
  const label=STORY_LABELS[s.kind==="correction"?"correction":"failure"];
  const rows=[[label[0],s.workingOn,false],[label[1],s.broke,true],[label[2],s.ended,true],["Worth a look",s.verdictSentence,false]];
  return rows.filter(row=>row[1]).map(([name,text,code])=>({name,text,code}));
}
/* esc and code come from the caller; the verdict word is a small pill on the ending only when no Worth a look line exists. */
function storyHtml(s,esc,code){
  const pill=!s.verdictSentence&&s.verdict?' <span class="pill vpill">'+esc(s.verdict)+"</span>":"";
  return storyRows(s).map(row=>"<dt>"+row.name+"</dt><dd>"+(row.code?code(row.text):esc(row.text))+(row.name===STORY_LABELS.failure[2]||row.name===STORY_LABELS.correction[2]?pill:"")+"</dd>").join("");
}

/* "Where sessions got stuck": biggest first, bar scaled to the biggest, share of all sessions in the tooltip. */
function frictionRows(view){
  const all=view.sessions,list=(view.frictions||[]).slice().sort((a,b)=>b.sessions-a.sessions);
  const peak=Math.max(1,...list.map(f=>f.sessions));
  return list.map(f=>({name:f.name,description:f.description,sessions:f.sessions,width:100*f.sessions/peak,
    tip:plural(f.sessions,"session")+" of "+all.toLocaleString("en-US")+" ("+(all?Math.round(100*f.sessions/all):0)+"%)"}));
}

window.SymbiontInboxModel={badgeLabel,verdictText,storyRows,storyHtml,frictionRows,rangeText,seenOnceLine,shortDay,TABS,TAB_WORDS,KIND_FILTERS,SORTS,REVIEW_PAGE,pageOf,scopeVisible,focusAfterExpand,SORT_WORDS,DEFAULT_SORT,tabOf,displayName,sectionsOf,tilesOf,weekAxis,seriesOf,teachDraft,teachNote,lessonRequest,ARCHIVE_CHOICES,archiveChoices,viewFrom,hrefFor,routeFrom,metaLine,cleanName,plural,triageOf,taughtRequest};
})();
