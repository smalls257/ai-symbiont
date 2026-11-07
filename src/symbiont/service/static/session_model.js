/* What the session page decides from the snapshot: which group a step belongs to, who tops the picker, what a filter keeps.
   Violation prevented: Silent Fallback. A card without a step cannot be joined, so its steps read "Not in a group"
   only because the join says so out loud (joined/unjoined counts), never because a lookup quietly missed. */
(function () {
"use strict";
const PICKER_SIZE=40;
const joinKey=(sessionId,step)=>sessionId+"\u0000"+step;

/* (sessionId, step) -> the group that holds the card. Cards with no numeric step are left out, not guessed. */
function joinOf(groups){
  const table=new Map();
  (groups||[]).forEach(g=>(g.cards||[]).forEach(card=>{
    if(!card.sessionId||!Number.isInteger(card.step))return;
    const key=joinKey(card.sessionId,card.step);
    if(!table.has(key)||table.get(key).noise)table.set(key,{key:g.key,name:g.name,noise:!!g.noise,reason:g.noiseWords||""});
  }));
  return table;
}
/* "group", "noise" or "none" for one step of one session. */
function tagOf(table,sessionId,step){
  const hit=table.get(joinKey(sessionId,step));
  if(!hit)return {kind:"none"};
  return hit.noise?{kind:"noise",reason:hit.reason}:{kind:"group",key:hit.key,name:hit.name};
}
function groupedCardCount(groups){
  const per=new Map();
  (groups||[]).filter(g=>!g.noise).forEach(g=>(g.cards||[]).forEach(card=>{
    if(card.sessionId)per.set(card.sessionId,(per.get(card.sessionId)||0)+1);
  }));
  return per;
}
/* The summary the snapshot holds for one session: outcome, friction and goal, each null when unsummarized. */
function summaryOf(data,id){
  const found=describedSessions(data).get(id)||{};
  const pick=v=>(v===undefined||v===""?null:v);
  return {outcome:pick(found.outcome),friction:pick(found.friction),goal:pick(found.goal)};
}
function describedSessions(data){
  const known=new Map();
  const tv=data.topicView||{};
  const add=s=>known.set(s.id,{...known.get(s.id),...s});
  (tv.sessionsByDate||[]).forEach(add);
  (tv.topics||[]).forEach(t=>(t.sessionList||[]).forEach(add));
  return known;
}
/* The picker: the sessions with the most grouped trouble, at most 40, ties by newest then id. */
function pickerOf(data,current){
  const per=groupedCardCount((data.incidents||{}).groups),known=describedSessions(data);
  const rows=[...per.entries()].map(([id,hits])=>{
    const s=known.get(id)||{};
    return {id,hits,date:s.date||null,goal:s.goal||""};
  });
  rows.sort((a,b)=>b.hits-a.hits||String(b.date||"").localeCompare(String(a.date||""))||a.id.localeCompare(b.id));
  const top=rows.slice(0,PICKER_SIZE);
  return {rows:top,currentListed:top.some(r=>r.id===current)};
}
function capText(shown,total){
  if(shown>=total)return "";
  return "Showing "+shown.toLocaleString("en-US")+" of "+total.toLocaleString("en-US")+" steps, the stretch with the most trouble.";
}
function markClass(lane,tag){
  if(lane==="edit"||lane==="scratch")return lane;
  return tag.kind==="group"?lane+" grouped":tag.kind==="noise"?lane+" noise":lane+" ungrouped";
}
const MESSAGE_FILTERS=["all","group"],FAILED_FILTERS=["all","quiet"];
function keptMessages(messages,tagFor,filter){
  return filter==="group"?messages.filter(m=>tagFor(m.step).kind==="group"):messages;
}
function keptFailed(failed,tagFor,filter){
  return filter==="quiet"?failed.filter(f=>tagFor(f.step).kind!=="noise"):failed;
}
function noiseCount(failed,tagFor){return failed.filter(f=>tagFor(f.step).kind==="noise").length;}
/* Header facts: active time as "41 min", "2 h" past 90 minutes, null when the log has no clock. */
function activeTime(minutes){
  if(!Number.isFinite(minutes))return null;
  return minutes>=90?Math.round(minutes/60)+" h":minutes+" min";
}
window.SymbiontSessionModel={PICKER_SIZE,joinOf,tagOf,pickerOf,summaryOf,capText,markClass,MESSAGE_FILTERS,FAILED_FILTERS,keptMessages,keptFailed,noiseCount,activeTime};
})();
