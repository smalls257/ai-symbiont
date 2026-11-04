/* The Mine stage on its own, for a repository whose mining is running, failed or found nothing.
   A dashboard opened before the lessons exist must show the job
   (or why it stopped), never an empty page. The server injects {mining:{project,progress}} as the
   page's one data object; this file polls GET /mining/<project>/progress. When the job is done with
   lessons it keeps the finished summary on screen (a Continue button, and an automatic move after
   SUMMARY_MS) and only then loads the address without ?mining, which the server renders as the
   pain-point view from the stored lessons. A short job would otherwise finish before the page
   painted and the developer would never see what was read. Every number shown is the service's:
   a burst of progress is painted as polled, nothing is interpolated. */
(function () {
"use strict";
const POLL_MS=700, RETRY_MS=2000, SUMMARY_MS=3500, CLEAR="#ff8c40";

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
    return {...base,percent:100,next:"summary",
      headline:"Read "+total+" sessions · found "+p.pain_points+" pain points · learned "+p.lessons+" lessons",
      lede:"Continue to see what it found, or wait a moment.",status:"done · "+p.lessons+" lessons ready to use"};
  }
  if(p.state==="done"){
    return {...base,percent:100,next:"stop",headline:"Read "+total+" sessions and found no pain points yet.",
      lede:"Nothing repeated enough to learn from. Mine again after more sessions.",status:"done · 0 lessons"};
  }
  return {...base,headline:"Reading "+total+" sessions",
    lede:"Looking for the same failure twice, files reworked, corrections and loops.",
    status:"session "+read+" of "+total+" · "+p.pain_points+" pain points so far"};
}

/* continueUrl is pure: the address the page moves to when the summary has been seen. */
function continueUrl(href){
  /* Edit the text, not URLSearchParams: it would re-encode a space as "+", which the server reads literally. */
  const [path,query=""]=href.split("?");
  const kept=query.split("&").filter(part=>part&&part.split("=")[0]!=="mining");
  return kept.length?path+"?"+kept.join("&"):path;
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
function offerContinue(){
  const go=()=>location.assign(continueUrl(location.href));
  const button=$("startBtn");
  button.textContent="Continue";button.style.display="";button.onclick=go;
  setTimeout(go,SUMMARY_MS);
}
async function run(shell){
  $("s0").classList.add("on");$("demotag").style.display="none";
  $("nav").style.display="none";$("startBtn").style.display="none";$("playdemo").style.display="none";
  $("repoName").textContent=shell.project;
  let progress=shell.progress;
  for(;;){
    const view=describe(progress);
    paint(view,progress.sessions_total);
    if(view.next==="summary"){offerContinue();return;}
    if(view.next==="stop")return;
    await new Promise(r=>setTimeout(r,POLL_MS));
    try{progress=await fetchProgress(shell.project);}
    catch(e){notice(String(e.message||e)+"; retrying");await new Promise(r=>setTimeout(r,RETRY_MS));}
  }
}
window.SymbiontMining={describe,continueUrl,run};
})();
