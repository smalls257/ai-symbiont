/* Topics: what the developer was working on, named from batched session summaries.
   Empty topic sections and bars that do not add up look finished and tell
   nothing, so before topics exist the page says how to get them (and still lists the sessions by date), every
   count carries its noun, and one scale serves every row of "topics over time".
   window.SymbiontTopics.render(container, topicView, {compact}) draws the Inbox panel (compact) or the whole view.
   All text from the store goes through esc. Colors come from dashboard.css variables. */
(function () {
"use strict";
const INSTRUCTION="Summarize your sessions to see topics: /symbiont summarize";
const OUTCOMES=["done","partly","stuck","unclear"];
const MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const COMPACT_SESSIONS=8,FULL_SESSIONS=12,HOT_SHARE=1.5,HOT_MIN=3;
const CSS=`
.sbt{--o-done:#2fb36a;--o-partly:#f0b43c;--o-stuck:#f45454;--o-unclear:#6e7591;font-size:1rem}
.sbt h3{font-size:1.05rem;font-weight:650;margin:1rem 0 .5rem}
.sbt .sub{color:var(--mu);font-size:.95rem;margin:.15rem 0 .7rem}
.sbt .ob{display:flex;gap:2px;height:.7rem;border-radius:.3rem;overflow:hidden}
.sbt .ob i{display:block;height:100%}
.sbt .o-done{background:var(--o-done)}.sbt .o-partly{background:var(--o-partly)}
.sbt .o-stuck{background:var(--o-stuck)}.sbt .o-unclear{background:var(--o-unclear)}
.sbt .lg{display:flex;gap:1rem;flex-wrap:wrap;color:var(--mu);font-size:.88rem;align-items:center}
.sbt .lg span{display:inline-flex;align-items:center;gap:.35rem;white-space:nowrap}
.sbt .lg i{display:inline-block;width:.75rem;height:.75rem;border-radius:.2rem}
.sbt .lg b{color:var(--tx);font-weight:600}
.sbt .trow{display:grid;grid-template-columns:1fr auto;gap:.15rem .8rem;padding:.6rem .5rem;border-bottom:1px solid var(--line);border-radius:.4rem;text-align:left;width:100%;background:none;border-top:0;border-left:0;border-right:0}
.sbt .trow.pick{cursor:pointer}
.sbt .trow.pick:hover{background:rgba(255,255,255,.04)}
.sbt .trow.on{background:rgba(178,140,255,.12);box-shadow:inset .25rem 0 0 var(--vi)}
.sbt .trow .nm{font-weight:650;font-size:1.04rem}
.sbt .trow .ds{color:var(--mu);font-size:.9rem;grid-column:1/-1;line-height:1.3}
.sbt .trow .ct{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
.sbt .trow .ct small{font-weight:400;color:var(--mu);font-size:.82rem;margin-left:.2rem}
.sbt .trow .barw{grid-column:1/-1;margin-top:.3rem}
.sbt .trow .dt{grid-column:1/-1;color:var(--mu);font:.82rem var(--mono)}
.sbt .ins{color:var(--tx);padding:.6rem .8rem;border:1px dashed rgba(255,204,64,.5);border-radius:.6rem;font:500 .95rem var(--mono)}
.sbt .sl{width:100%;border-collapse:collapse;font-size:.95rem;margin-top:.5rem}
.sbt .sl th{text-align:left;color:var(--mu);font-weight:500;font-size:.85rem;padding:.35rem .5rem;border-bottom:1px solid var(--line)}
.sbt .sl td{padding:.45rem .5rem;border-bottom:1px solid var(--line);vertical-align:top}
.sbt .sl td.d{font:500 .85rem var(--mono);color:var(--mu);white-space:nowrap}
.sbt .sl td.f{color:var(--mu);font-size:.88rem}
.sbt .outc{display:inline-flex;align-items:center;gap:.3rem;font-size:.85rem;font-weight:600;white-space:nowrap}
.sbt .outc i{width:.6rem;height:.6rem;border-radius:.15rem;display:inline-block}
.sbt .btn{background:none;border:1px solid var(--line);color:var(--tx);border-radius:.55rem;padding:.33rem .85rem;font-weight:600;margin-top:.6rem}
.sbt .btn:hover{border-color:var(--mu)}
.sbt .tl{display:grid;grid-template-columns:11rem 1fr 6rem;gap:.15rem .8rem;align-items:center}
.sbt .tl .l,.sbt .fx .l{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer;background:none;border:0;text-align:left;padding:0}
.sbt .tl .l.on,.sbt .fx .l.on{color:var(--vi)}
.sbt .tl svg{width:100%;height:1.9rem;display:block}
.sbt .tl .n{text-align:right;font-variant-numeric:tabular-nums;color:var(--mu);font-size:.88rem}
.sbt .tl .axis{display:flex;justify-content:space-around;color:var(--mu);font-size:.78rem}
.sbt .fx{display:grid;gap:3px;align-items:stretch}
.sbt .fx .h{font-size:.82rem;color:var(--mu);line-height:1.15;padding:0 .2rem .3rem;align-self:end;text-align:center}
.sbt .fx .l small{color:var(--mu);font-weight:400}
.sbt .fx .c{display:grid;place-items:center;height:2.1rem;border-radius:.35rem;font-variant-numeric:tabular-nums}
.sbt .fx .c.hot{outline:2px solid var(--or);outline-offset:-2px}
.sbt .fx .c.zero{color:var(--mu);opacity:.6}
.sbt .cols2{display:grid;grid-template-columns:1fr 1fr;gap:1.2rem}
.sbt .undated{color:var(--mu);font-size:.88rem;margin-top:.5rem}
#sbt-tip{position:fixed;pointer-events:none;background:#0a0816;border:1px solid var(--vi);border-radius:.5rem;padding:.4rem .7rem;font-size:.92rem;max-width:26rem;display:none;z-index:20;line-height:1.35}
`;

const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const counted=(n,one,many)=>n.toLocaleString("en-US")+" "+(n===1?one:(many||one+"s"));
const dayLabel=d=>{if(!d)return "date unknown";const [,m,dd]=d.split("-");return MONTHS[+m-1]+" "+(+dd);};
const dayLabelYear=d=>d?dayLabel(d)+", "+d.slice(0,4):"date unknown";
const monthLabel=m=>{const [y,mo]=m.split("-");return MONTHS[+mo-1]+" "+y;};
const tip=html=>' data-tip="'+esc(html)+'" tabindex="0"';

function injectOnce(){
  if(document.getElementById("sbt-style"))return;
  const style=document.createElement("style");style.id="sbt-style";style.textContent=CSS;document.head.appendChild(style);
  const box=document.createElement("div");box.id="sbt-tip";box.setAttribute("role","tooltip");document.body.appendChild(box);
  const show=(el,x,y)=>{box.innerHTML=el.getAttribute("data-tip");box.style.display="block";
    const r=box.getBoundingClientRect();box.style.left=Math.max(4,Math.min(innerWidth-r.width-8,x+14))+"px";
    box.style.top=(y+18+r.height>innerHeight?y-r.height-10:y+18)+"px";};
  const target=e=>e.target.closest&&e.target.closest("[data-tip]");
  document.addEventListener("mousemove",e=>{const el=target(e);if(el&&el.closest(".sbt"))show(el,e.clientX,e.clientY);else box.style.display="none";});
  document.addEventListener("focusin",e=>{const el=target(e);if(el&&el.closest(".sbt")){const r=el.getBoundingClientRect();show(el,r.left,r.bottom-10);}});
  document.addEventListener("focusout",()=>{box.style.display="none";});
}

const total=o=>OUTCOMES.reduce((n,k)=>n+(o[k]||0),0);
function outcomeBar(o,label){
  const all=total(o);
  const parts=OUTCOMES.filter(k=>o[k]).map(k=>'<i class="o-'+k+'" style="flex:'+o[k]+'"'
    +tip("<b>"+counted(o[k],"session")+" "+k+"</b><br>"+Math.round(100*o[k]/all)+"% of "+counted(all,"session"))+"></i>").join("");
  return '<div class="ob" role="img" aria-label="'+esc(label+": "+OUTCOMES.map(k=>(o[k]||0)+" "+k).join(", "))+'">'+parts+"</div>";
}
const legend=o=>'<div class="lg">'+OUTCOMES.map(k=>'<span><i class="o-'+k+'"></i>'+k+" <b>"+counted(o[k]||0,"session")+"</b></span>").join("")+"</div>";
const chip=k=>'<span class="outc"><i class="o-'+k+'"></i>'+esc(k)+"</span>";
const span=t=>t.first?dayLabel(t.first)+" – "+dayLabel(t.last):"dates unknown";

function totals(topics){
  return topics.reduce((o,t)=>{OUTCOMES.forEach(k=>{o[k]=(o[k]||0)+t.outcomes[k];});return o;},{});
}

function sessionRows(list,limit){
  return list.slice(0,limit).map(s=>"<tr><td class=\"d\">"+dayLabelYear(s.date)+"</td><td>"+esc(s.goal)+"</td><td>"+chip(s.outcome)
    +'</td><td class="f">'+esc(s.friction||"none noted")+"</td></tr>").join("");
}
function sessionTable(list,limit,more){
  const head="<thead><tr><th>Date</th><th>Goal (from the session summary)</th><th>How it ended</th><th>What slowed it</th></tr></thead>";
  const button=list.length>limit||more?'<button type="button" class="btn" data-more>'+(more?"Show the latest "+FULL_SESSIONS:"Show all "+counted(list.length,"session"))+"</button>":"";
  return '<table class="sl">'+head+"<tbody>"+sessionRows(list,more?list.length:limit)+"</tbody></table>"+button;
}

/* Before topics exist: the one-line instruction and the sessions in date order, never empty sections. */
function emptyHtml(tv,compact){
  const list=(tv&&tv.sessionsByDate)||[];
  const limit=compact?COMPACT_SESSIONS:list.length;
  const rows=list.slice(0,limit).map(s=>'<div class="trow"><span class="nm">'+esc(s.goal)+'</span><span class="ct">'+chip(s.outcome)+'</span><span class="dt">'+dayLabelYear(s.date)+"</span></div>").join("");
  const rest=list.length>limit?'<p class="undated">and '+counted(list.length-limit,"more session")+"</p>":"";
  const need=tv&&tv.needed?'<p class="sub">'+counted(tv.needed,"more session summary","more session summaries")+" needed before topics can be named.</p>":"";
  return '<p class="ins">'+INSTRUCTION+"</p>"+need+(list.length?"<h3>Sessions by date</h3>"+rows+rest:"");
}

function compactHtml(tv){
  const rows=tv.topics.slice().sort((a,b)=>b.sessions-a.sessions).map(t=>'<div class="trow"><span class="nm">'+esc(t.name)+'</span><span class="ct">'+t.sessions+"<small>"+(t.sessions===1?"session":"sessions")+"</small></span>"
    +'<span class="ds">'+esc(t.description)+'</span><div class="barw">'+outcomeBar(t.outcomes,t.name)+'</div><span class="dt">'+span(t)+"</span></div>").join("");
  return '<p class="sub">'+counted(tv.topics.length,"topic")+" from "+counted(tv.sessions,"summarized session")+". The bar shows how each session ended.</p>"
    +legend(totals(tv.topics))+'<div style="margin-top:.4rem">'+rows+"</div>";
}

function listHtml(tv,state){
  const max=Math.max(...tv.topics.map(t=>t.sessions));
  return tv.topics.slice().sort((a,b)=>b.sessions-a.sessions).map(t=>'<button type="button" class="trow pick'+(t.name===state.topic?" on":"")+'" data-topic="'+esc(t.name)+'" aria-pressed="'+(t.name===state.topic)+'">'
    +'<span class="nm">'+esc(t.name)+'</span><span class="ct">'+t.sessions+"<small>"+(t.sessions===1?"session":"sessions")+"</small></span>"
    +'<div class="barw" style="width:'+Math.max(8,Math.round(100*t.sessions/max))+'%">'+outcomeBar(t.outcomes,t.name)+'</div><span class="dt">'+span(t)+"</span></button>").join("");
}

function detailHtml(tv,state){
  const t=tv.topics.find(x=>x.name===state.topic);
  const shown=state.outcome==="all"?t.sessionList:t.sessionList.filter(s=>s.outcome===state.outcome);
  const filters=["all",...OUTCOMES].map(k=>'<button type="button" class="btn" data-outcome="'+k+'" aria-pressed="'+(k===state.outcome)+'"'+(k===state.outcome?' style="border-color:var(--vi)"':"")+">"
    +(k==="all"?"All":k)+" "+(k==="all"?t.sessions:t.outcomes[k])+"</button>").join(" ");
  return "<h2>"+esc(t.name)+' <span class="mu">'+counted(t.sessions,"session")+" · "+span(t)+"</span></h2><p class=\"sub\">"+esc(t.description)+"</p>"
    +'<div class="cols2"><div><h3 style="margin-top:0">How the sessions ended</h3>'+outcomeBar(t.outcomes,t.name)+'<div style="margin-top:.5rem">'+legend(t.outcomes)+"</div></div>"
    +"<div><h3 style=\"margin-top:0\">What went wrong here</h3><p>"+counted(t.incidents,"failure card")+" from this topic's sessions.</p></div></div>"
    +"<h3>Sessions</h3><div>"+filters+"</div>"+sessionTable(shown,FULL_SESSIONS,state.all);
}

function timelineHtml(tv,state){
  const n=tv.months.length,max=Math.max(1,...tv.topics.flatMap(t=>t.perMonth));
  const W=300,H=30,bw=W/n;
  const row=t=>{
    const bars=t.perMonth.map((v,i)=>{
      const bh=v?Math.max(2,v/max*(H-3)):0;
      const rect=v?'<rect x="'+(i*bw+1)+'" y="'+(H-bh)+'" width="'+(bw-2)+'" height="'+bh+'" rx="1" fill="'+(t.name===state.topic?"var(--vi)":"rgba(178,140,255,.55)")+'"/>':"";
      return rect+'<rect x="'+i*bw+'" y="0" width="'+bw+'" height="'+H+'" fill="transparent"'+tip("<b>"+t.name+"</b>, "+monthLabel(tv.months[i])+"<br>"+counted(v,"session"))+"/>";
    }).join("");
    return '<button type="button" class="l'+(t.name===state.topic?" on":"")+'" data-topic="'+esc(t.name)+'">'+esc(t.name)+"</button>"
      +'<svg viewBox="0 0 '+W+" "+H+'" preserveAspectRatio="none" role="img" aria-label="'+esc(t.name)+' sessions per month"><line x1="0" x2="'+W+'" y1="'+(H-.5)+'" y2="'+(H-.5)+'" stroke="rgba(236,240,248,.15)"/>'+bars+"</svg>"
      +'<span class="n">'+counted(t.sessions,"session")+"</span>";
  };
  const axis='<span></span><div class="axis">'+tv.months.map(m=>"<span>"+monthLabel(m)+"</span>").join("")+"</div><span></span>";
  return '<div class="tl">'+axis+tv.topics.slice().sort((a,b)=>b.sessions-a.sessions).map(row).join("")+"</div>";
}

const shade=s=>"rgba(255,140,64,"+(0.08+0.75*Math.min(1,s/0.5)).toFixed(2)+")";
function frictionHtml(tv,state){
  if(!tv.frictions.length)return '<p class="sub">No friction categories were named yet.</p>';
  const cols="12rem repeat("+tv.frictions.length+",minmax(4.5rem,1fr))";
  const head="<span></span>"+tv.frictions.map(f=>'<span class="h"'+tip("<b>"+f.name+"</b><br>"+f.description)+">"+esc(f.name)+"</span>").join("");
  const cell=(t,f)=>{
    const v=t.frictions[f.name]||0,share=v/t.sessions,all=f.sessions/tv.sessions;
    const hot=v>=HOT_MIN&&share>=HOT_SHARE*all;
    return '<span class="c'+(v?"":" zero")+(hot?" hot":"")+'" style="background:'+(v?shade(share):"rgba(236,240,248,.04)")+'"'
      +tip("<b>"+t.name+" · "+f.name+"</b><br>"+counted(v,"session")+" of "+t.sessions+" ("+Math.round(100*share)+"%)<br>across all topics: "+Math.round(100*all)+"%")+">"+v+"</span>";
  };
  const rows=tv.topics.slice().sort((a,b)=>b.sessions-a.sessions).map(t=>'<button type="button" class="l'+(t.name===state.topic?" on":"")+'" data-topic="'+esc(t.name)+'">'+esc(t.name)+" <small>"+counted(t.sessions,"session")+"</small></button>"+tv.frictions.map(f=>cell(t,f)).join("")).join("");
  const key=[0,.12,.25,.38,.5].map(s=>'<i style="background:'+shade(s)+';border-radius:.15rem"></i>').join("");
  return '<div class="fx" style="grid-template-columns:'+cols+'">'+head+rows+"</div>"
    +'<div class="lg" style="margin-top:.6rem"><span>Cells count sessions.</span><span>Shade: share of the topic\'s sessions</span><span style="gap:2px">'+key+"</span><span>0% to 50% and up</span>"
    +'<span><i style="outline:2px solid var(--or);outline-offset:-2px"></i>at least '+HOT_SHARE+" times the all-topics share, "+HOT_MIN+"+ sessions</span></div>";
}

function fullHtml(tv,state){
  const undated=tv.undated?'<p class="undated">'+counted(tv.undated,"session")+" without a known date are left out of the timeline.</p>":"";
  return '<h2>Topics <span class="mu">'+counted(tv.topics.length,"topic")+" · "+counted(tv.sessions,"session")+"</span></h2>"
    +'<p class="sub">Named by your session model from one-line summaries. Click a topic.</p>'+legend(totals(tv.topics))
    +'<div style="margin-top:.4rem">'+listHtml(tv,state)+"</div>"
    +'<section class="det" style="margin-top:1.2rem">'+detailHtml(tv,state)+"</section>"
    +"<h3>Topics over time</h3><p class=\"sub\">Sessions per month, every row on the same scale (tallest bar: "+counted(Math.max(1,...tv.topics.flatMap(t=>t.perMonth)),"session")+"). Months with no sessions show as 0 on hover.</p>"+timelineHtml(tv,state)+undated
    +"<h3>Where each topic got stuck</h3><p class=\"sub\">Sessions per friction category; a session can sit in more than one.</p>"+frictionHtml(tv,state);
}

function render(container,tv,options){
  injectOnce();
  const compact=Boolean(options&&options.compact);
  container.classList.add("sbt");
  if(!tv||!tv.ready){container.innerHTML=emptyHtml(tv,compact);return;}
  if(compact){container.innerHTML=compactHtml(tv);return;}
  const top=tv.topics.slice().sort((a,b)=>b.sessions-a.sessions)[0];
  const state={topic:top.name,outcome:"all",all:false};
  const draw=()=>{container.innerHTML=fullHtml(tv,state);};
  container.onclick=e=>{
    const pick=e.target.closest("[data-topic]"),filter=e.target.closest("[data-outcome]"),more=e.target.closest("[data-more]");
    if(pick){state.topic=pick.dataset.topic;state.outcome="all";state.all=false;}
    else if(filter){state.outcome=filter.dataset.outcome;state.all=false;}
    else if(more){state.all=!state.all;}
    else return;
    draw();
  };
  draw();
}

window.SymbiontTopics={render};
})();
