/* The Mine stage on its own, for a repository whose mining is running, failed or found nothing.
   A dashboard opened before the lessons exist must show the job
   (or why it stopped), never an empty page. The server injects {mining:{project,progress}} as the
   page's one data object; this file polls GET /mining/<project>/progress and, when the job is
   done with lessons, reloads so the server renders the pain-point view from the stored lessons. */
(function () {
"use strict";
const POLL_MS=700, RETRY_MS=2000, RELOAD_MS=1400, CLEAR="#ff8c40";

/* describe is pure: progress in, what the page says out. */
function describe(p){
  const total=p.sessions_total, read=p.sessions_read;
  const counts=[read,p.pain_points,p.fixes_paired,p.lessons];
  const percent=total?Math.min(100,Math.round(read/total*100)):0;
  const base={counts,percent,feed:p.recent||[],failed:false,next:"poll"};
  if(p.state==="failed"){
    return {...base,failed:true,next:"stop",headline:"Mining stopped before it finished.",
      lede:p.error||"symbiont gave no reason; see the service log.",
      status:"failed after "+read+" of "+total+" sessions"};
  }
  if(p.state==="done"&&p.lessons>0){
    return {...base,percent:100,next:"reload",headline:"Found "+p.pain_points+" pain points in "+total+" sessions.",
      lede:"Opening what it found.",status:"done · "+p.lessons+" lessons ready to use"};
  }
  if(p.state==="done"){
    return {...base,percent:100,next:"stop",headline:"Read "+total+" sessions and found no pain points yet.",
      lede:"Nothing repeated enough to learn from. Mine again after more sessions.",status:"done · 0 lessons"};
  }
  return {...base,headline:"Reading "+total+" sessions",
    lede:"Looking for the same failure twice, files reworked, corrections and loops.",
    status:"session "+read+" of "+total+" · "+p.pain_points+" pain points so far"};
}

const $=id=>document.getElementById(id);
function tween(el,to){const from=+el.dataset.v||0;el.dataset.v=to;const t0=performance.now();(function f(t){const k=Math.min(1,(t-t0)/350);el.textContent=Math.round(from+(to-from)*k);if(k<1)requestAnimationFrame(f);})(t0);}
function feedItem(title){
  const li=document.createElement("li");li.className="fi";li.style.setProperty("--k",CLEAR);
  const k=document.createElement("span");k.className="k";k.textContent="Found";
  const t=document.createElement("span");t.className="t";t.textContent=title;
  li.append(k,t);return li;
}
function paint(view,total){
  $("h1").textContent=view.headline;$("lede").textContent=view.lede;$("status").textContent=view.status;
  $("bar").style.width=view.percent+"%";
  ["c0","c1","c2","c3"].forEach((id,i)=>tween($(id),view.counts[i]));
  const grid=$("sgrid");
  while(grid.children.length<total)grid.appendChild(document.createElement("i"));
  [...grid.children].forEach((c,i)=>{c.className=i<view.counts[0]?"read":"";});
  $("feed").replaceChildren(...view.feed.map(feedItem));
  $("status").style.color=view.failed?"#f45454":"";
}
function notice(text){$("status").textContent=text;$("status").style.color="#f45454";}

async function fetchProgress(project){
  const r=await fetch("/mining/"+encodeURIComponent(project)+"/progress");
  if(!r.ok)throw new Error("symbiont could not report progress (status "+r.status+")");
  return r.json();
}
async function run(shell){
  $("s0").classList.add("on");
  $("nav").style.display="none";$("startBtn").style.display="none";$("playdemo").style.display="none";
  $("repoName").textContent=shell.project;
  let progress=shell.progress;
  for(;;){
    const view=describe(progress);
    paint(view,progress.sessions_total);
    if(view.next==="reload"){setTimeout(()=>location.reload(),RELOAD_MS);return;}
    if(view.next==="stop")return;
    await new Promise(r=>setTimeout(r,POLL_MS));
    try{progress=await fetchProgress(shell.project);}
    catch(e){notice(String(e.message||e)+"; retrying");await new Promise(r=>setTimeout(r,RETRY_MS));}
  }
}
window.SymbiontMining={describe,run};
})();
