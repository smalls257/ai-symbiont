(function () {
"use strict";
const KINDS={
  repeat:{label:"Repeated failure",color:"#f45454"},
  rework:{label:"File reworked",color:"#ff8c40"},
  correction:{label:"You corrected the agent",color:"#5cc8ff"},
  loop:{label:"Stuck in a loop",color:"#e879c8"},
  tdd:{label:"Planned red test",color:"#8c94ac"},
  rule:{label:"A rule you keep",color:"#54de7c"},
  friction:{label:"Friction",color:"#ffcc40"}
};
const DEMO=new URLSearchParams(location.search).get("demo")==="1";
const DATA=window.SYMBIONT_DATA||JSON.parse(document.getElementById("symbiont-data").textContent);
if(DATA.mining){window.SymbiontMining.run(DATA.mining);return;}

const MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const N=DATA.sessions.length;
const dayOf=i=>DATA.sessions[i].day;
const dateOf=d=>{const x=new Date(DATA.sessions[0].date+"T00:00:00Z");x.setUTCDate(x.getUTCDate()+d);return MONTHS[x.getUTCMonth()]+" "+x.getUTCDate();};
const WINDOW_START=DATA.replay.windowStartDay;
const LAST_DAY=Math.round((new Date(DATA.repo.today)-new Date(DATA.sessions[0].date))/864e5);
const isMistake=p=>p.kind!=="tdd";
const cost=p=>isMistake(p)?p.turns*p.s.length:0;
const minutes=p=>isMistake(p)?p.min*p.s.length:0;
const detectAt=p=>p.s[Math.min(1,p.s.length-1)];
const LESSON=Object.fromEntries(DATA.lessons.map(l=>[l.id,l]));
/* internal view of a pain point: the schema joined with its lesson */
const P=DATA.painPoints.map(d=>{const l=LESSON[d.lessonId];return {id:d.id,kind:d.kind,title:d.title,file:d.file,cmd:d.command||"",s:d.sessions,turns:d.turnsPerOccurrence,min:d.minutesPerOccurrence,what:d.failure,fix:d.fix||"",note:l.note,ex:l.exampleContext,srcLabel:l.sourceLabel||"",srcUrl:l.sourceUrl||"",lesson:l.confirmed,lessonId:l.id,conflict:l.reviewConflict||null};});
const byId=id=>P.find(p=>p.id===id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const $=id=>document.getElementById(id);
const totals={turns:P.reduce((a,p)=>a+cost(p),0),mins:P.reduce((a,p)=>a+minutes(p),0),mistakes:P.filter(isMistake).length,tdd:P.filter(p=>!isMistake(p)).length,lessons:P.filter(p=>p.lesson).length};

/* ===== User edits. ST is the local copy; saveContext is the ONE place a user action leaves the UI. =====
   The local service stores it (POST /lessons/<id>/context).
   payload keys (any subset): context:string, intentional:boolean, priority:"low"|"normal"|"high". */
const ST={};
const csv=a=>(a||[]).join(", ");
const uncsv=t=>(t||"").split(",").map(x=>x.trim()).filter(Boolean);
function initState(){DATA.painPoints.forEach(d=>{const l=LESSON[d.lessonId];ST[d.id]={ctx:l.context,intent:l.intentional,prio:l.priority,terms:csv((l.appliesTo||{}).terms),areas:csv((l.appliesTo||{}).areas),saved:false};});}
initState();
function saveContext(lessonId,payload){
  const l=LESSON[lessonId];if(!l)throw new Error("Unknown lesson "+lessonId);
  const st=ST[l.painPointId];
  if("context" in payload){st.ctx=payload.context;st.saved=true;}
  if("intentional" in payload)st.intent=payload.intentional;
  if("priority" in payload)st.prio=payload.priority;
  if("terms" in payload)st.terms=payload.terms;
  if("areas" in payload)st.areas=payload.areas;
  const body={...("override" in payload?{review_override:payload.override}:{}),text:st.ctx,intentional:st.intent,priority:st.prio,applies_to:{terms:uncsv(st.terms),areas:uncsv(st.areas)}};
  return fetch("/lessons/"+encodeURIComponent(lessonId)+"/context",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then(r=>{
    if(!r.ok)throw new Error("symbiont could not save (status "+r.status+")");
    return {lessonId,saved:true};
  }).catch(e=>{const t=$("toast");t.textContent=String(e.message);t.classList.add("on");});
}
const saveFor=(p,payload)=>saveContext(p.lessonId,payload);

/* note prose: sentences only, never scores or thresholds (project rule 2) */
function fmt(s){return s.split("`").map((x,i)=>i%2?'<span class="cmd">'+esc(x)+"</span>":esc(x)).join("");}
function noteHTML(p,reveal){
  const st=ST[p.id];
  if(st.intent||!p.note)return null;
  const lead=st.prio==="high"?"Worth checking before you go on. ":"";
  const base=(lead+p.note).slice(0,(reveal??null)===null?1e9:reveal);
  const done=(reveal??null)===null||reveal>=(lead+p.note).length;
  const user=done&&st.ctx.trim()?' <span class="user">Your rule for this repo: '+esc(st.ctx.trim())+"</span>":"";
  return '<span class="tag">[symbiont]</span> '+fmt(base)+user;
}

/* ===== tooltip (delegated, any [data-tip]) ===== */
const tip=$("tip");
document.addEventListener("mousemove",e=>{
  const t=e.target.closest&&e.target.closest("[data-tip]");
  if(!t){tip.style.display="none";return;}
  tip.innerHTML=t.dataset.tip;tip.style.display="block";
  tip.style.left=Math.min(e.clientX+16,innerWidth-tip.offsetWidth-8)+"px";tip.style.top=Math.min(e.clientY+16,innerHeight-tip.offsetHeight-8)+"px";
});

/* ===== flow control ===== */
let token=0;const CANCEL=Symbol("cancel");
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function pause(t,ms){await wait(ms);if(t!==token)throw CANCEL;}
const STAGES=["Mine","Pain points","Add context","30-day replay"];
let mined=false;
function go(n){
  document.querySelectorAll(".stage").forEach((s,i)=>s.classList.toggle("on",i===n));
  [...$("nav").children].forEach((b,i)=>{b.setAttribute("aria-current",i===n);b.classList.toggle("done",i<n);});
  if(n===0&&!mined)resetMining();
  if(n===0&&mined)finishMiningUI();
  if(n===3&&!replayRunning)renderReplay(1e9);
}
const nav=$("nav");
STAGES.forEach((s,i)=>{const b=document.createElement("button");b.innerHTML="<b>"+(i+1)+"</b>"+s;b.onclick=()=>{token++;setDemo(false);go(i);};nav.appendChild(b);});
function caption(txt){$("caption").textContent=txt;}
function setDemo(on){document.body.classList.toggle("demo",on);if(!on)caption("");}

/* ===== stage 0: live mining ===== */
function tween(el,to,ms){const from=+el.dataset.v||0;el.dataset.v=to;const t0=performance.now();(function f(t){const k=Math.min(1,(t-t0)/(ms||350));el.textContent=Math.round(from+(to-from)*k);if(k<1)requestAnimationFrame(f);})(t0);}
const sg=$("sgrid");for(let i=0;i<N;i++){const c=document.createElement("i");sg.appendChild(c);}
const occAt=i=>P.flatMap(p=>p.s.includes(i)?[p]:[]);
function countsAt(i){
  let fail=0,fix=0;
  P.forEach(p=>p.s.forEach(s=>{if(s<=i){if(p.kind==="repeat"||p.kind==="loop"||p.kind==="tdd")fail++;if((p.kind==="repeat"||p.kind==="loop")&&p.fix)fix++;}}));
  const les=P.filter(p=>p.lesson&&p.s.filter(s=>s<=i).length>=2).length;
  return {fail,fix,les};
}
function resetMining(){
  ["c0","c1","c2","c3"].forEach(id=>{$(id).textContent="0";$(id).dataset.v=0;});
  $("feed").innerHTML="";$("bar").style.width="0";$("status").textContent="";
  [...sg.children].forEach(c=>c.className="");
  $("h1").textContent="Turn symbiont on and it reads your past sessions.";
  $("lede").textContent="Everything stays on this machine. Nothing is uploaded.";
  $("startBtn").style.display="";$("startBtn").textContent="Turn on symbiont";$("startBtn").className="cta";
}
function feedItem(p){
  const li=document.createElement("li");li.className="fi";li.id="fi"+p.id;li.style.setProperty("--k",KINDS[p.kind].color);
  li.innerHTML='<span class="k">'+KINDS[p.kind].label+'</span><span class="t">'+esc(p.title)+'</span><span class="f">'+esc(p.file)+'</span><span class="n"><span class="cnt">1</span><small>sessions</small></span>';
  $("feed").prepend(li);
  while($("feed").children.length>9)$("feed").lastChild.remove();
}
function mineStep(i){
  const cells=sg.children;
  [...cells].forEach(c=>c.classList.remove("cur"));
  cells[i].className="read cur";
  const here=occAt(i).filter(isMistake);
  if(here.length){cells[i].style.background="";cells[i].style.setProperty("background",KINDS[here[0].kind].color);}
  const c=countsAt(i);
  tween($("c0"),i+1);tween($("c1"),c.fail);tween($("c2"),c.fix);tween($("c3"),c.les);
  $("bar").style.width=((i+1)/N*100)+"%";
  const ev=occAt(i)[0];
  $("status").textContent="session "+(i+1)+" of "+N+" · "+dateOf(dayOf(i))+(ev?" · "+(ev.cmd||ev.file)+(ev.kind==="tdd"?" (planned red)":""):" · nothing to learn");
  P.forEach(p=>{
    if(detectAt(p)===i&&isMistake(p)&&p.s.length>1)feedItem(p);
    const el=$("fi"+p.id);if(el)el.querySelector(".cnt").textContent=p.s.filter(s=>s<=i).length;
  });
}
function finishMiningUI(){
  $("h1").textContent="Found "+P.length+" pain points in "+N+" sessions.";
  $("lede").textContent=totals.mistakes+" are mistakes. "+totals.tdd+" are planned red tests, so symbiont leaves them alone.";
  $("startBtn").style.display="";$("startBtn").textContent="See what went wrong";$("startBtn").className="cta";
  $("status").textContent="done · "+totals.lessons+" lessons ready to use";
}
async function mine(t,ms){
  resetMining();mined=false;$("startBtn").style.display="none";
  $("h1").textContent="Reading "+N+" sessions of "+DATA.repo.name;
  $("lede").textContent="Looking for the same failure twice, files reworked, corrections and loops.";
  for(let i=0;i<N;i++){mineStep(i);await pause(t,ms/N);}
  [...sg.children].forEach(c=>c.classList.remove("cur"));
  mined=true;await pause(t,500);
  tween($("c3"),totals.lessons);finishMiningUI();
}
$("startBtn").onclick=async()=>{
  if(mined){go(1);return;}
  const t=++token;try{await mine(t,13000);}catch(e){if(e!==CANCEL)throw e;}
};

/* ===== stage 1: pain-point dashboard ===== */
function renderDashboard(){
  const hrs=(totals.mins/60).toFixed(1);
  $("kpis").innerHTML=[
   [P.length,"pain points found",'<span>'+totals.mistakes+' mistakes, '+totals.tdd+' planned</span>',"var(--tx)"],
   [totals.turns,"agent turns lost",'<span>to the same trouble recurring</span>',"var(--rd)"],
   ["~"+hrs+" h","of working time lost",'<span>across '+N+' sessions, estimated</span>',"var(--or)"],
   [totals.lessons,"lessons ready",'<span>a fix is known for each</span>',"var(--vi)"]
  ].map(k=>'<div class="panel kpi"><div class="num" style="color:'+k[3]+'">'+k[0]+'</div><div class="lbl">'+k[1]+" "+k[2]+"</div></div>").join("");
  // by kind
  const kinds=["repeat","rework","correction","loop"];
  const sum=k=>P.filter(p=>p.kind===k).reduce((a,p)=>a+cost(p),0);
  const mx=Math.max(...kinds.map(sum));
  let h=kinds.map(k=>{const n=P.filter(p=>p.kind===k).length;
    return '<div class="kb" style="--k:'+KINDS[k].color+'" data-tip="'+KINDS[k].label+": "+n+" pain points, "+sum(k)+' turns lost"><div class="nm">'+KINDS[k].label+"<small>"+n+' points</small></div><div class="v">'+sum(k)+"<small>turns</small></div><div class=\"tr\"><i data-w=\""+(sum(k)/mx*100)+'"></i></div></div>';}).join("");
  h+='<div class="kdiv">Not mistakes</div><div class="kb tdd" style="--k:#8c94ac" data-tip="Tests written red on purpose. symbiont never warns about these."><div class="nm">Planned red tests<small>'+totals.tdd+' points</small></div><div class="v">0<small>turns</small></div><div class="tr"><i data-w="100"></i></div></div>';
  $("kbars").innerHTML=h;
  renderTreemap();
  // lessons
  const les=P.filter(p=>p.lesson).sort((a,b)=>cost(b)-cost(a)).slice(0,3);
  $("les").innerHTML=les.map(p=>'<li><button data-pick="'+p.id+'"><span class="t">'+esc(short(p.title))+'</span><span class="big">'+cost(p)+"<small>turns</small></span><span class=\"m\">"+p.s.length+" sessions, about "+p.turns+" turns each time</span></button></li>").join("");
  $("les").querySelectorAll("button").forEach(b=>b.onclick=()=>{token++;setDemo(false);openPain(+b.dataset.pick);});
  renderTimeline(P.filter(isMistake));
}
function mix(a,b,k){const h=s=>[1,3,5].map(i=>parseInt(s.slice(i,i+2),16));const A=h(a),B=h(b);return "#"+A.map((v,i)=>Math.round(v+(B[i]-v)*k).toString(16).padStart(2,"0")).join("");}
/* "Where in the repo": every tile carries its file name and its turns, or is folded into "Other files (N)"
   (treemap.js decides, in rendered pixels, so nothing is cut by scaling). */
let tmSize="";
function renderTreemap(){
  const svg=$("tm"),box=svg.getBoundingClientRect(),W=Math.round(box.width)||478,H=Math.round(box.height)||245;
  tmSize=W+"x"+H;
  const files={};P.filter(isMistake).forEach(p=>{files[p.file]=(files[p.file]||0)+cost(p);});
  const loose=window.SymbiontTreemap.noFileLabel(P.filter(isMistake));
  const items=Object.entries(files).map(([f,v])=>(f?{f,v}:{f,v,label:loose}));
  const lay=window.SymbiontTreemap.plan(items,W,H);if(!lay.length){svg.innerHTML="";return;}
  const vmax=Math.max(...lay.map(r=>r.v));
  svg.setAttribute("viewBox","0 0 "+W+" "+H);
  svg.innerHTML=lay.map(r=>{
    const k=r.v/vmax,col=r.folded?"#5a4f78":mix("#4a3470","#ff8c40",Math.pow(k,.7)),dark=!r.folded&&k>.45,ink=dark?"#1a1020":"#ecf0f8";
    const TM=window.SymbiontTreemap,big=r.w>=200&&r.h>=80,fs=r.folded?TM.fitFont(r.name,r.w,13):big?20:13,ts=big?16:12;
    const top=r.folded?null:P.filter(p=>p.file===r.f&&isMistake(p)).sort((a,b)=>cost(b)-cost(a))[0];
    const tip=esc(r.title)+": "+r.v+" turns lost";
    return '<g tabindex="0"'+(top?' data-pick="'+top.id+'"':' class="folded"')+' data-tip="'+tip+'"><title>'+tip+'</title><rect x="'+r.x+'" y="'+r.y+'" width="'+r.w+'" height="'+r.h+'" rx="6" fill="'+col+'"/>'
      +'<text x="'+(r.x+9)+'" y="'+(r.y+fs+6)+'" font-family="ui-monospace,Menlo,monospace" font-size="'+fs+'" font-weight="700" fill="'+ink+'">'+esc(TM.fitName(r.name,r.w,fs))+"</text>"
      +'<text x="'+(r.x+9)+'" y="'+(r.y+fs+ts+10)+'" font-size="'+ts+'" font-weight="600" fill="'+ink+'">'+r.v+" turns</text></g>";}).join("");
  svg.querySelectorAll("g[data-pick]").forEach(g=>{g.onclick=()=>{token++;setDemo(false);openPain(+g.dataset.pick);};g.onkeydown=e=>{if(e.key==="Enter")g.onclick();};});
}
if(window.ResizeObserver)new ResizeObserver(()=>{const b=$("tm").getBoundingClientRect();if(b.width&&Math.round(b.width)+"x"+Math.round(b.height)!==tmSize)renderTreemap();}).observe($("tm"));
function renderTimeline(points){
  const TL=window.SymbiontTimeline, rows=TL.foldRows(points);
  const X0=480,X1=1760,LBL_X=X0-30,LBL_CHARS=40,RH=54,Y0=34,xs=i=>X0+i/Math.max(1,N-1)*(X1-X0);
  const rad=TL.dotRadius(N,X1-X0), step=TL.tickStep(N,X1-X0), ay=Y0+RH*rows.length+22, H=ay+16;
  let s='';
  s+='<line x1="'+xs(WIN_I-.5)+'" x2="'+xs(WIN_I-.5)+'" y1="8" y2="'+(Y0+RH*rows.length)+'" stroke="#b28cff" stroke-dasharray="6 6" stroke-width="2"/><text x="'+(xs(WIN_I-.5)+10)+'" y="18" font-size="17" fill="#b28cff">last 30 days</text>';
  rows.forEach((p,r)=>{
    const y=Y0+r*RH+RH/2,c=p.folded?"#8c94ac":KINDS[p.kind].color,lines=TL.labelLines(p.title,LBL_CHARS);
    const y0=y+6-(lines.length-1)*11;
    s+='<text text-anchor="end" font-size="18" fill="#ecf0f8" font-weight="600">'+lines.map((l,k)=>'<tspan x="'+LBL_X+'" y="'+(y0+k*22)+'">'+esc(l)+"</tspan>").join("")+"<title>"+esc(p.title)+"</title></text>";
    s+='<line x1="'+X0+'" x2="'+X1+'" y1="'+y+'" y2="'+y+'" stroke="rgba(236,240,248,.1)" stroke-width="2"/>';
    s+='<line x1="'+xs(p.s[0])+'" x2="'+xs(p.s[p.s.length-1])+'" y1="'+y+'" y2="'+y+'" stroke="'+c+'" stroke-opacity=".55" stroke-width="2"/>';
    p.s.forEach((i,k)=>{const tip=p.folded?esc(p.title)+"<br>"+dateOf(dayOf(i))+", session with a repeated mistake":esc(p.title)+"<br>"+dateOf(dayOf(i))+", time "+(k+1)+" of "+p.s.length+", "+p.turns+" turns lost";
      s+='<circle cx="'+xs(i)+'" cy="'+y+'" r="'+rad+'" fill="'+c+'" stroke="#16112a" stroke-width="2" tabindex="0" data-tip="'+tip+'"/>';});
  });
  for(let i=0;i<N;i+=step)s+='<text x="'+xs(i)+'" y="'+ay+'" text-anchor="middle" font-size="16" fill="#8c94ac">'+dateOf(dayOf(i))+"</text>";
  $("tlsvg").setAttribute("viewBox","0 0 1800 "+H);
  $("tlsvg").innerHTML=s;
}
const WIN_I=DATA.sessions.findIndex(s=>s.day>=WINDOW_START);
const short=t=>t.length>46?t.slice(0,44)+"…":t;
function growBars(){requestAnimationFrame(()=>document.querySelectorAll("#kbars i").forEach(i=>i.style.width=i.dataset.w+"%"));}
function resetBars(){document.querySelectorAll("#kbars i").forEach(i=>i.style.width="0");}

/* ===== stage 2: add context ===== */
let sel=1,reveal=null,revealTimer=0;
const PL=window.SymbiontPainList, PROJECT=DATA.repo.name;
const collapsed=PL.readCollapsed(window.localStorage,PROJECT,console.warn);
function setGroupOpen(kind,open){
  if(collapsed.has(kind)===!open)return;
  if(open)collapsed.delete(kind);else collapsed.add(kind);
  PL.writeCollapsed(window.localStorage,PROJECT,collapsed,console.warn);
}
function itemHtml(p){
  const st=ST[p.id];
  return '<button role="option" aria-selected="'+(p.id===sel)+'" data-id="'+p.id+'" style="--k:'+KINDS[p.kind].color+'"><i></i><span class="t'+(st.intent&&p.kind!=="tdd"?" q":"")+'">'+esc(short(p.title))+'</span><span class="c">'+(st.saved?"✓ ":"")+"×"+p.s.length+"</span></button>";
}
function renderList(){
  const groups=Object.keys(KINDS).map(k=>{
    const ps=P.filter(p=>p.kind===k).sort((a,b)=>cost(b)-cost(a));
    return {kind:k,label:KINDS[k].label+(k==="tdd"?" (not mistakes)":""),count:ps.length,itemsHtml:ps.map(itemHtml).join("")};
  });
  const L=$("plist"),keep=L.scrollTop;L.innerHTML=PL.groupsHtml(groups,collapsed,esc);L.scrollTop=keep;
  L.querySelectorAll("button.grp").forEach(b=>b.onclick=()=>{setGroupOpen(b.dataset.kind,b.getAttribute("aria-expanded")!=="true");renderList();});
  L.querySelectorAll("button[data-id]").forEach(b=>b.onclick=()=>{token++;setDemo(false);selectPain(+b.dataset.id);});
}
function sourceChip(p){
  if(!p.srcLabel&&!p.srcUrl)return "";
  const label=esc(p.srcLabel||"source");
  return /^https:\/\//.test(p.srcUrl)?'<a class="chip src" href="'+esc(p.srcUrl)+'" target="_blank" rel="noopener noreferrer">'+label+"</a>":'<span class="chip src">'+label+"</span>";
}
function openPain(id){go(2);selectPain(id);const b=$("plist").querySelector('[data-id="'+id+'"]');if(b)b.scrollIntoView({block:"center"});}
function selectPain(id){setGroupOpen(byId(id).kind,true);showPain(id);}
/* showPain does not expand: page load shows the first pain point and must keep the sections the developer closed. */
function showPain(id){
  sel=id;const p=byId(id),st=ST[id];
  renderList();
  $("edit").style.setProperty("--k",KINDS[p.kind].color);
  $("edit").innerHTML='<div class="chips"><span class="chip kind">'+KINDS[p.kind].label+'</span><span class="chip">'+esc(p.file)+'</span>'+sourceChip(p)+'<span class="chip">seen '+p.s.length+(p.s.length===1?" time":" times")+"</span></div>"
   +"<h2>"+esc(p.title)+"</h2>"
   +'<div class="occ" aria-label="Sessions where it happened">'+p.s.map(i=>'<i style="background:'+KINDS[p.kind].color+'" data-tip="'+dateOf(dayOf(i))+'"></i>').join("")+'<span class="mu">'+p.s.map(i=>dateOf(dayOf(i))).slice(-3).join(", ")+(p.s.length>3?" and earlier":"")+"</span></div>"
   +"<p><span class=\"mu\">What happened.</span> "+fmt(p.what)+"</p>"+(p.fix?"<p><b>How it was fixed.</b> "+fmt(p.fix)+"</p>":"")
   +(p.conflict&&!st.intent&&!st.kept?'<div class="conflict" id="conflict" role="note">The reviewer thinks this is '+esc(p.conflict)+', but you added your own words, so it stays active. <button id="keepit">Keep</button> <button id="dismissit">Dismiss</button></div>':"")
   +'<div><label class="h" for="ctx">Add context in your own words</label><textarea id="ctx" placeholder="Tell the agent what it cannot see in the code." aria-label="Context for the agent">'+esc(st.ctx)+'</textarea>'
   +(p.ex?'<div class="ex"><button id="exb">Use: “'+esc(p.ex)+'”</button></div>':"")+"</div>"
   +'<div class="tags"><label class="h" for="terms">Applies to: words and codes, comma separated</label><input id="terms" value="'+esc(st.terms)+'" placeholder="currency, BHD, refund">'
   +'<label class="h" for="areas">Paths it applies to, comma separated</label><input id="areas" value="'+esc(st.areas)+'" placeholder="ledger/"></div>'
   +'<div class="ctl"><button class="sw" id="sw" aria-pressed="'+st.intent+'"><i></i>Intentional, not a mistake</button>'
   +'<div class="seg" role="group" aria-label="Priority">'+["low","normal","high"].map(x=>'<button data-p="'+x+'" aria-pressed="'+(st.prio===x)+'">'+x[0].toUpperCase()+x.slice(1)+" priority</button>").join("")+'</div><button class="save" id="save">Save context</button></div>';
  $("ctx").oninput=e=>{st.ctx=e.target.value;st.saved=false;renderNote();};
  if($("exb"))$("exb").onclick=()=>{st.ctx=p.ex;$("ctx").value=p.ex;renderNote();};
  $("terms").oninput=e=>{st.terms=e.target.value;st.saved=false;};
  $("areas").oninput=e=>{st.areas=e.target.value;st.saved=false;};
  $("sw").onclick=()=>setIntent(!st.intent);
  if($("keepit")){$("keepit").onclick=()=>{st.kept=true;saveFor(byId(sel),{override:"keep"});selectPain(sel);};$("dismissit").onclick=()=>{st.intent=true;saveFor(byId(sel),{intentional:true,override:"dismiss"});selectPain(sel);};}
  $("edit").querySelectorAll(".seg button").forEach(b=>b.onclick=()=>setPrio(b.dataset.p));
  $("save").onclick=save;
  startReveal();
}
function setIntent(v){saveFor(byId(sel),{intentional:v});$("sw").setAttribute("aria-pressed",v);renderNote();renderList();}
function setPrio(x){saveFor(byId(sel),{priority:x});$("edit").querySelectorAll(".seg button").forEach(b=>b.setAttribute("aria-pressed",b.dataset.p===x));renderNote();}
function save(){saveFor(byId(sel),{context:ST[sel].ctx,intentional:ST[sel].intent,priority:ST[sel].prio,terms:ST[sel].terms,areas:ST[sel].areas});renderList();const t=$("toast");t.classList.add("on");setTimeout(()=>t.classList.remove("on"),2200);}
function startReveal(){
  clearInterval(revealTimer);const p=byId(sel);const total=(ST[sel].prio==="high"?39:0)+p.note.length;reveal=0;
  revealTimer=setInterval(()=>{reveal+=4;if(reveal>=total){reveal=null;clearInterval(revealTimer);}renderNote();},22);
  renderNote();
}
function renderNote(){
  const p=byId(sel),st=ST[sel],box=$("note");
  $("run").innerHTML=p.cmd?'<span class="cmd">'+esc(p.cmd)+"</span>":'<span class="mu">'+esc(trigger(p))+"</span>";
  const h=noteHTML(p,reveal);
  if(h===null){box.className="notebox quiet";box.innerHTML=st.intent?"Nothing will be shown. symbiont stays quiet about this one.":"No note for this one yet.";
    $("cap").innerHTML="Marked <b>intentional</b>, so the agent is never interrupted for it.";return;}
  box.className="notebox";
  box.innerHTML=h+((reveal??null)!==null||document.activeElement===$("ctx")?'<span class="caret"></span>':"")+(st.ctx.trim()?"":'<div class="mu" style="margin-top:.8rem;font-size:1rem">Your context appears here as you type.</div>');
  $("cap").innerHTML=({high:"<b>Shown first</b>, right before the agent repeats this.",normal:"Shown <b>right before</b> the agent repeats this.",low:"Shown <b>only if</b> the agent has already tried once."})[st.prio]+" Plain sentences, nothing else.";
}
function trigger(p){return p.kind==="rework"?"before editing "+p.file.split("/").pop()+" again":p.kind==="correction"?"before the agent picks an approach":"before the next retry";}

/* ===== stage 3: 30-day replay ===== */
const EVENTS=DATA.replay.items.map(r=>{const p=byId(r.painPointId);return {p,k:p.s.indexOf(r.sessionIndex),day:r.day,saved:r.turnsSaved,mins:r.minutesSaved};});
const RX=d=>40+(d-WINDOW_START)/(LAST_DAY-WINDOW_START)*1720;
let replayRunning=false;
function drawStrip(upto){
  let s='<line x1="40" x2="1760" y1="130" y2="130" stroke="rgba(236,240,248,.2)" stroke-width="2"/>';
  for(let d=WINDOW_START;d<=LAST_DAY;d+=5)s+='<text x="'+RX(d)+'" y="172" text-anchor="middle" font-size="17" fill="#8c94ac">'+dateOf(d)+"</text>";
  const slot={};
  EVENTS.forEach((e,i)=>{slot[e.day]=(slot[e.day]||0);const y=112-slot[e.day]*26;slot[e.day]++;
    if(i<upto)s+='<circle cx="'+RX(e.day)+'" cy="'+y+'" r="11" fill="#b28cff" stroke="#16112a" stroke-width="2" data-tip="'+dateOf(e.day)+": "+esc(e.p.title)+'"/>';});
  if(upto<EVENTS.length&&upto>0){const d=EVENTS[upto-1].day;s+='<line x1="'+RX(d)+'" x2="'+RX(d)+'" y1="10" y2="136" stroke="#ff8c40" stroke-width="3"/>';}
  $("rsvg").innerHTML=s;
}
function showEvent(i){
  const e=EVENTS[i];if(!e){$("fire").innerHTML='<h2>The note that would have fired</h2><p class="sub">Press Replay, or pick a dot.</p>';return;}
  const p=e.p;
  $("fire").innerHTML='<h2>'+esc(p.title)+'</h2><div class="when">'+dateOf(e.day)+" · it would have spoken "+esc(trigger(p))+"</div>"
   +(p.cmd?'<div class="run" style="margin-bottom:.7rem"><span class="cmd">'+esc(p.cmd)+"</span></div>":"")
   +'<div class="notebox">'+(noteHTML(p,null)||"")+'</div><div class="sv">~'+e.saved+" turns, ~"+e.mins+' min <small>estimate</small></div>';
}
function tallies(n){
  const sv=EVENTS.slice(0,n).reduce((a,e)=>a+e.saved,0),mn=EVENTS.slice(0,n).reduce((a,e)=>a+e.mins,0);
  tween($("r0"),n);tween($("r1"),sv);$("r2").textContent=(mn/60).toFixed(1);
}
function listTo(n){$("evl").innerHTML=EVENTS.slice(0,n).reverse().map(e=>'<li><span class="d">'+dateOf(e.day)+'</span><span class="t">'+esc(e.p.title)+'</span><span class="s">−'+e.saved+"</span></li>").join("");}
function renderReplay(upto){const n=Math.min(upto,EVENTS.length);drawStrip(n);tallies(n);listTo(n);showEvent(n-1);}
async function playReplay(t,ms){
  replayRunning=true;
  try{
    renderReplay(0);let prev=WINDOW_START;
    for(let i=0;i<EVENTS.length;i++){
      const dt=(EVENTS[i].day-prev)/(LAST_DAY-WINDOW_START)*ms*0.9+ms*0.1/EVENTS.length;prev=EVENTS[i].day;
      await pause(t,Math.max(60,dt));renderReplay(i+1);
    }
  }finally{replayRunning=false;}
}
$("replayBtn").onclick=async()=>{const t=++token;setDemo(false);try{await playReplay(t,10000);}catch(e){if(e!==CANCEL)throw e;}};
$("rsvg").addEventListener("click",()=>{});

/* ===== demo mode: hands-free, about 80 seconds ===== */
async function typeInto(t,text,ms){const ta=$("ctx"),st=ST[sel];ta.focus();for(let i=1;i<=text.length;i++){ta.value=text.slice(0,i);st.ctx=ta.value;st.saved=false;renderNote();await pause(t,ms);}}
async function spotlight(t,id,txt,ms){caption(txt);const el=$(id);el.classList.remove("spot");void el.offsetWidth;el.classList.add("spot");await pause(t,ms);}
async function demo(){
  const t=++token;setDemo(true);
  initState();mined=false;sel=1;
  try{
    go(0);caption("symbiont reads every past session, locally");await pause(t,1200);
    caption("It pairs each failure with the fix that worked");await mine(t,15000);
    await pause(t,1800);
    go(1);resetBars();growBars();
    await spotlight(t,"kpis",totals.turns+" turns lost to trouble that kept coming back",3200);
    await spotlight(t,"pKinds","Repeated failures cost the most. Planned red tests are not mistakes.",3600);
    await spotlight(t,"pTree","Three files carry most of the pain",3200);
    await spotlight(t,"pTl","The same mistake, session after session",3600);
    caption("Open the costliest one and tell it what only you know");await pause(t,1500);
    go(2);selectPain(1);caption("This is what the agent will see before it repeats the mistake");await pause(t,3400);
    caption("Add context in your own words");await typeInto(t,"Money must stay integer cents, round half-up.",55);
    await pause(t,1200);
    caption("Set the priority");setPrio("high");await pause(t,2000);
    save();caption("Saved. It is used from the next session");await pause(t,1800);
    caption("Or mark a pain point intentional and it goes quiet");selectPain(7);await pause(t,2200);setIntent(true);await pause(t,2600);
    go(3);caption("Replay of the last 30 days, estimated");
    await playReplay(t,12000);await pause(t,2200);
    await pause(t,6000);
    caption("");setDemo(false);
  }catch(e){if(e!==CANCEL)throw e;}
}
$("playdemo").onclick=demo;
document.addEventListener("keydown",e=>{if(e.key==="d"&&!/TEXTAREA|INPUT/.test(e.target.tagName))demo();});

/* ===== boot ===== */
$("repoName").textContent=DATA.repo.name;if(DATA.nightly){var nl=DATA.nightly,lc=nl.last_checked;$("nightly").textContent="Nightly training: "+nl.sentence+(lc?" \u00b7 last checked note: \u201c"+lc.note+"\u201d. "+lc.sentence:"");$("nightly").dataset.state=nl.state}$("ofN").textContent="of "+N;$("demotag").style.display=DEMO?"":"none";$("playdemo").style.display=DEMO?"":"none";
$("rtitle").textContent=dateOf(WINDOW_START)+" to "+dateOf(LAST_DAY)+": each dot is a repeat the note would have come before";
renderDashboard();renderList();showPain(1);
mined=true;[...sg.children].forEach((c,i)=>mineStep(i));finishMiningUI();
go(1);
window.__symbiont={go,mine:()=>$("startBtn").click(),selectPain,setPrio,setIntent,ST,P,EVENTS,renderReplay,finishAll:()=>{mined=true;[...sg.children].forEach((c,i)=>mineStep(i));finishMiningUI();}};
const obs=new MutationObserver(()=>{if($("s1").classList.contains("on"))growBars();});obs.observe($("s1"),{attributes:true,attributeFilter:["class"]});
})();
