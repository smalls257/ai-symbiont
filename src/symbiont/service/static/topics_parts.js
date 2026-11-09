/* The Topics page's pieces: what to show (sorting, joining groups to topics) and the markup of each panel.
   Every store string goes through esc; tooltips are HTML in a data attribute that topics.js reads through
   SymbiontTip.safe. window.SymbiontTopicParts is used by topics.js and tested under node. */
(function () {
"use strict";
const OUTCOMES=["done","partly","stuck","unclear"];
const MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const FULL_SESSIONS=12,HOT_SHARE=1.5,HOT_MIN=3,TOP_GROUPS=8,DAY_MS=864e5;
const GROUP_KINDS={correction:"message",failure:"time"};

const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const counted=(n,one,many)=>n.toLocaleString("en-US")+" "+(n===1?one:(many||one+"s"));
const dayLabel=d=>{if(!d)return "date unknown";const [,m,dd]=d.split("-");return esc(MONTHS[+m-1]+" "+(+dd));};
const dayLabelYear=d=>d?dayLabel(d)+", "+esc(d.slice(0,4)):"date unknown";
const tip=html=>' data-tip="'+esc(html)+'" tabindex="0"';
const href=(project,route)=>esc(window.SymbiontInboxModel.hrefFor(project,route));
const span=t=>t.first?dayLabel(t.first)+" – "+dayLabel(t.last):"dates unknown";
const doneShare=t=>t.sessions?Math.round(100*(t.outcomes.done||0)/t.sessions):0;
const notDone=t=>t.sessions?1-(t.outcomes.done||0)/t.sessions:0;

/* "Most sessions" or "Least often done" (the largest share of sessions that did not end done leads). */
const SORTS={
  sessions:(a,b)=>b.sessions-a.sessions,
  hard:(a,b)=>notDone(b)-notDone(a)||b.sessions-a.sessions
};
const SORT_WORDS=[["sessions","Most sessions"],["hard","Least often done"]];
function sorted(topics,sort){
  if(!(sort in SORTS))throw new Error("symbiont: unknown topic sort "+JSON.stringify(sort));
  return topics.slice().sort(SORTS[sort]);
}
/* A one-session topic is a footnote, not a row; when every topic is that small they all stay listed. */
function listed(topics){
  const recurring=topics.filter(t=>t.sessions>1);
  return recurring.length?recurring:topics;
}

/* The groups whose cards belong to the topic, by how many of its cards each holds. Cards name their topic. */
function groupsFor(groups,triage,key){
  const M=window.SymbiontInboxModel;
  const rows=[];
  (groups||[]).filter(g=>!g.noise).forEach(g=>{
    const n=(g.cards||[]).filter(c=>c.topic===key&&!c.noise).length;
    if(n)rows.push({key:g.key,name:M.displayName(triage,g),kind:g.kind,count:n});
  });
  return rows.sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name)).slice(0,TOP_GROUPS);
}

const total=o=>OUTCOMES.reduce((n,k)=>n+(o[k]||0),0);
const totals=topics=>topics.reduce((o,t)=>{OUTCOMES.forEach(k=>{o[k]=(o[k]||0)+(t.outcomes[k]||0);});return o;},{});
function outcomeBar(o,label,scale){
  const all=total(o);
  const parts=OUTCOMES.filter(k=>o[k]).map(k=>'<i class="o-'+k+'" style="flex:'+o[k]+'"'
    +tip("<b>"+counted(o[k],"session")+" "+k+"</b><br>"+Math.round(100*o[k]/all)+"% of "+counted(all,"session"))+"></i>").join("");
  const width=scale===undefined?"":' style="width:'+Math.max(8,Math.round(100*scale))+'%"';
  return '<div class="ob"'+width+' role="img" aria-label="'+esc(label+": "+OUTCOMES.map(k=>(o[k]||0)+" "+k).join(", "))+'">'+parts+"</div>";
}
const legend=o=>'<div class="lg">'+OUTCOMES.map(k=>'<span><i class="o-'+k+'"></i>'+k+" <b>"+counted(o[k]||0,"session")+"</b></span>").join("")+"</div>";
const chip=k=>k?'<span class="outc"><i class="o-'+k+'"></i>'+esc(k)+"</span>":"";

/* A topic's name edits in place; `key` is the model's name, which the service uses to find the topic. */
const nameButton=t=>'<button type="button" class="nm edit-name" data-rename="'+esc(t.key)+'" title="Click to rename" aria-label="Rename topic: '+esc(t.name)+'">'+esc(t.name)+"</button>";

function topicRow(t,state,max){
  const scale=state.sort==="sessions"?t.sessions/max:1;
  return '<button type="button" class="trow pick'+(t.key===state.topic?" on":"")+'" data-topic="'+esc(t.key)+'" aria-pressed="'+(t.key===state.topic)+'">'
    +'<span class="nm">'+esc(t.name)+'</span><span class="ct">'+t.sessions+"<small>"+(t.sessions===1?"session":"sessions")+"</small></span>"
    +'<div class="barw">'+outcomeBar(t.outcomes,t.name,scale)+'</div><span class="dt">'+doneShare(t)+"% done · "+span(t)+"</span></button>";
}
function leftColumn(tv,topics,state){
  const made=tv.requests?", made in "+counted(tv.requests,"request"):"";
  const sortButtons=SORT_WORDS.map(([k,l])=>'<button type="button" data-sort="'+k+'" aria-pressed="'+(state.sort===k)+'">'+l+"</button>").join("");
  const max=Math.max(1,...topics.map(t=>t.sessions));
  return '<section class="panel lcol" aria-label="Topics"><h2>Topics</h2><p class="sub">'+counted(topics.length,"topic")+" named by the model from "
    +counted(tv.sessions,"one-line session summary","one-line session summaries")+made+". Click one.</p>"
    +'<div class="sortrow"><span class="mu">Sort</span><div class="seg2">'+sortButtons+"</div></div>"+legend(totals(topics))
    +'<div style="margin-top:.3rem">'+sorted(topics,state.sort).map(t=>topicRow(t,state,max)).join("")+"</div></section>";
}

function sessionTable(project,list,all){
  const head="<thead><tr><th>Date</th><th>Goal (model summary)</th><th>Ended</th><th>Friction</th></tr></thead>";
  const rows=(all?list:list.slice(0,FULL_SESSIONS)).map(s=>'<tr><td class="d">'+dayLabelYear(s.date)+'</td><td><a data-route href="'+href(project,{view:"session",id:s.id})+'">'+esc(s.goal)+"</a></td><td>"+chip(s.outcome)
    +'</td><td class="f">'+esc(s.friction||"–")+"</td></tr>").join("");
  const more=list.length>FULL_SESSIONS?'<button type="button" class="btn" data-more>'+(all?"Show the latest "+FULL_SESSIONS:"Show all "+counted(list.length,"session"))+"</button>":"";
  return '<table class="sl">'+head+"<tbody>"+rows+"</tbody></table>"+more;
}
function wentWrong(project,rows){
  const body=rows.length
    ?rows.map(r=>'<a data-route href="'+href(project,{view:"group",key:r.key})+'"><span>'+esc(r.name)+"</span><b>"+counted(r.count,GROUP_KINDS[r.kind]||"time")+"</b></a>").join("")
    :'<p class="mu">No grouped failures or corrections in this topic.</p>';
  return '<div class="gin"><h3 style="margin-top:0">What went wrong here</h3>'+body+"</div>";
}
function detailPanel(t,state,extra){
  const shown=state.outcome==="all"?t.sessionList:t.sessionList.filter(s=>s.outcome===state.outcome);
  const filters=["all",...OUTCOMES].map(k=>'<button type="button" data-outcome="'+k+'" aria-pressed="'+(k===state.outcome)+'">'+(k==="all"?"All":k)
    +'<span class="c">'+(k==="all"?t.sessions:t.outcomes[k])+"</span></button>").join("");
  const goals=(t.examples||[]).map(x=>"<li>"+esc(x)+"</li>").join("");
  return "<h2>"+nameButton(t)+' <span class="n">'+counted(t.sessions,"session")+" · "+span(t)+"</span></h2><p class=\"sub\">"+esc(t.description)+"</p>"
    +'<div class="cols2"><div><h3 style="margin-top:0">How they ended</h3>'+outcomeBar(t.outcomes,t.name)+'<div style="margin-top:.5rem">'+legend(t.outcomes)+"</div>"
    +'<h3>Typical goals</h3><ul class="ex">'+goals+"</ul></div>"+wentWrong(extra.project,extra.groups)+"</div>"
    +'<h3>Sessions</h3><div class="seg2">'+filters+"</div>"+sessionTable(extra.project,shown,state.all);
}
function notFoundPanel(project,asked){
  return '<p class="soon" role="status">No such topic: “'+esc(asked)+'”. <a data-route href="'+href(project,{view:"topics"})+'">Show the topics</a></p>';
}

/* ISO week key to its Monday, as "Mar 9". */
function weekLabel(key){
  const [year,week]=key.split("-W").map(Number);
  const jan4=new Date(Date.UTC(year,0,4));
  const monday=new Date(jan4.getTime()-((jan4.getUTCDay()+6)%7)*DAY_MS+(week-1)*7*DAY_MS);
  return MONTHS[monday.getUTCMonth()]+" "+monday.getUTCDate();
}
function weekRow(label,counts,look,tv){
  const n=tv.weeks.length,W=300,H=30,bw=W/n;
  const fill={base:"#8c94ac",on:"#b28cff",off:"rgba(178,140,255,.55)"}[look.kind];
  const bars=counts.map((v,i)=>{
    const bh=v?Math.max(2,v/look.max*(H-3)):0;
    const rect=v?'<rect x="'+(i*bw+.8)+'" y="'+(H-bh)+'" width="'+(bw-1.6)+'" height="'+bh+'" rx="1" fill="'+fill+'"/>':"";
    const of=look.kind==="base"?"":" of "+tv.allPerWeek[i]+" that week";
    return rect+'<rect x="'+i*bw+'" y="0" width="'+bw+'" height="'+H+'" fill="transparent"'+tip("<b>"+esc(label)+"</b>, week of "+weekLabel(tv.weeks[i])+"<br>"+counted(v,"session")+of)+"/>";
  }).join("");
  const name=look.kind==="base"?'<span class="l base">'+esc(label)+"</span>":'<button type="button" class="l'+(look.kind==="on"?" on":"")+'" data-topic="'+esc(look.key)+'">'+esc(label)+"</button>";
  return name+'<svg viewBox="0 0 '+W+" "+H+'" preserveAspectRatio="none" role="img" aria-label="'+esc(label)+' sessions per week"><line x1="0" x2="'+W+'" y1="'+(H-.5)+'" y2="'+(H-.5)+'" stroke="var(--hair)"/>'+bars+'</svg><span class="n">'+look.total+"</span>";
}
function weeklyPanel(tv,topics,current){
  if(!tv.weeks||!tv.weeks.length)return '<section class="panel"><h2>Topics over time</h2><p class="sub">No session has a known date, so there is no timeline.</p></section>';
  const n=tv.weeks.length,at=i=>"<span>"+weekLabel(tv.weeks[Math.min(n-1,i)])+"</span>";
  const max=Math.max(1,...topics.flatMap(t=>t.perWeek));
  const axis='<span></span><div class="axis">'+[0,Math.round(n/3),Math.round(2*n/3),n-1].map(at).join("")+'</div><span class="n">sessions</span>';
  const base=weekRow("All sessions",tv.allPerWeek,{kind:"base",max:Math.max(1,...tv.allPerWeek),total:tv.sessions},tv);
  const rows=sorted(topics,"sessions").map(t=>weekRow(t.name,t.perWeek,{kind:t.key===current?"on":"off",max,total:t.sessions,key:t.key},tv)).join("");
  return '<section class="panel"><h2>Topics over time</h2><p class="sub">Sessions per week, every row on the same scale. The top row is all sessions, for context.</p><div class="sm-grid">'+axis+base+rows+"</div></section>";
}

const shade=s=>"color-mix(in srgb,var(--or) "+Math.round(100*(0.08+0.75*Math.min(1,s/0.5)))+"%,transparent)";
function frictionCell(t,f,tv){
  const v=t.frictions[f.name]||0,share=v/t.sessions,all=f.sessions/tv.sessions;
  const hot=v>=HOT_MIN&&share>=HOT_SHARE*all;
  return '<span class="c'+(v?"":" zero")+(hot?" hot":"")+'" style="background:'+(v?shade(share):"var(--faint)")+'"'
    +tip("<b>"+esc(t.name)+" · "+esc(f.name)+"</b><br>"+counted(v,"session")+" of "+t.sessions+" ("+Math.round(100*share)+"%)<br>across all topics: "+Math.round(100*all)+"%")+">"+v+"</span>";
}
function frictionBase(frictions,tv){
  return '<span class="l base">All topics <small>'+tv.sessions+"</small></span>"+frictions.map(f=>'<span class="c base" style="background:'+shade(f.sessions/tv.sessions)+'"'
    +tip("<b>"+esc(f.name)+"</b><br>"+counted(f.sessions,"session")+" of "+tv.sessions+" ("+Math.round(100*f.sessions/tv.sessions)+"%)")+">"+f.sessions+"</span>").join("");
}
function frictionPanel(tv,topics,current){
  const frictions=tv.frictions.slice().sort((a,b)=>b.sessions-a.sessions);
  const intro='<h2>Where each topic got stuck</h2>';
  if(!frictions.length)return '<section class="panel">'+intro+'<p class="sub">No friction categories were named yet.</p></section>';
  const head="<span></span>"+frictions.map(f=>'<span class="h"'+tip("<b>"+esc(f.name)+"</b><br>"+esc(f.description))+">"+esc(f.name)+"</span>").join("");
  const rows=sorted(topics,"sessions").map(t=>'<button type="button" class="l'+(t.key===current?" on":"")+'" data-topic="'+esc(t.key)+'">'+esc(t.name)+" <small>"+t.sessions+"</small></button>"
    +frictions.map(f=>frictionCell(t,f,tv)).join("")).join("");
  const key=[0,.12,.25,.38,.5].map(s=>'<i style="background:'+shade(s)+';border-radius:.15rem"></i>').join("");
  return '<section class="panel">'+intro+'<p class="sub">Sessions per friction category. Shade: share of the topic\'s sessions. Outlined: at least '+HOT_SHARE+" times the share across all topics, so the trouble is particular to that kind of work.</p>"
    +'<div class="fx" style="grid-template-columns:12rem repeat('+frictions.length+',minmax(4.5rem,1fr))">'+head+frictionBase(frictions,tv)+rows+"</div>"
    +'<div class="lg" style="margin-top:.6rem"><span>Cells count sessions.</span><span>share of the topic\'s sessions</span><span style="gap:2px">'+key+"</span><span>0% to 50% and up</span>"
    +'<span><i style="outline:2px solid var(--or);outline-offset:-2px"></i>'+HOT_SHARE+" times the all-topics share, "+HOT_MIN+"+ sessions</span></div></section>";
}

window.SymbiontTopicParts={OUTCOMES,esc,counted,tip,href,span,doneShare,sorted,listed,groupsFor,totals,outcomeBar,legend,chip,nameButton,leftColumn,detailPanel,notFoundPanel,weeklyPanel,frictionPanel,weekLabel,dayLabelYear};
})();
