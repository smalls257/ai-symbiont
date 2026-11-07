/* The Inbox's markup: one row per group, the folds, the tiles, the weekly bars.
   Violation prevented: Leaky Narrative. A row that shows a fingerprint or a score makes the developer reverse-engineer
   it; each row says what happened, what fixed it and the verdict in sentences, and every number carries its noun.
   Pure string builders (text from the store goes through esc), so node can test them. */
(function () {
"use strict";
const M=window.SymbiontInboxModel;
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const fd=d=>{if(!d)return "date unknown";const p=d.split("-");return MON[+p[1]-1]+" "+(+p[2]);};
const code=s=>esc(s).replace(/`([^`]+)`/g,"<code>$1</code>");
const day=d=>MON[d.getUTCMonth()]+" "+d.getUTCDate();

/* Weekly bars on one axis; a week with none is a faint tick so a gap reads as "none", not "missing". */
function sparkHtml(series,weeks,kind){
  const width=300,height=40,bar=width/series.length,peak=Math.max(1,...series);
  const noun=kind==="correction"?"message":"time";
  const cells=series.map((n,i)=>{
    const h=n?Math.max(3,n/peak*(height-4)):1.5;
    const tip="<b>Week of "+day(weeks[i].monday)+"</b><br>"+M.plural(n,noun);
    return '<rect'+(n?"":' class="z"')+' x="'+(i*bar+1).toFixed(1)+'" y="'+(height-h).toFixed(1)+'" width="'+Math.max(1,bar-2).toFixed(1)+'" height="'+h.toFixed(1)+'" rx="1"/>'
      +'<rect class="hit" x="'+(i*bar).toFixed(1)+'" y="0" width="'+bar.toFixed(1)+'" height="'+height+'" data-tip="'+esc(tip)+'"/>';
  }).join("");
  const label="Weekly occurrences of this group, "+M.plural(series.reduce((a,b)=>a+b,0),noun)+" in "+M.plural(series.length,"week");
  return '<svg class="spark'+(kind==="correction"?" cor":"")+'" viewBox="0 0 '+width+" "+(height+1)+'" preserveAspectRatio="none" role="img" aria-label="'+esc(label)+'">'
    +'<line class="ax" x1="0" x2="'+width+'" y1="'+height+'" y2="'+height+'"/>'+cells+"</svg>"
    +'<div class="sparkax"><span>'+day(weeks[0].monday)+"</span><span>"+day(weeks[weeks.length-1].monday)+"</span></div>";
}

const BADGES={regressed:'<span class="pill rising">Regressed</span> '};
const trendPill=g=>g.badge?'<span class="pill '+esc(g.badge)+'">'+esc(M.badgeLabel(g.badge))+"</span> ":"";
function stateNote(g,tri){
  if(tri.taught_on)return "Lesson added on "+fd(tri.taught_on)+".";
  return "";
}

function episodeRows(g){
  const newest=g.cards[0];
  if(g.kind!=="correction"||!newest.firstWrong)return "";
  const cost=newest.costSteps>0?"<dt>Cost</dt><dd>"+M.plural(newest.costSteps,"agent step")+" before you stepped in</dd>":"";
  return "<dt>Where it went wrong</dt><dd>"+code(newest.firstWrong)+"</dd>"+cost;
}

function actionsHtml(tab,openHref){
  const teach='<button class="btn primary" data-a="teach">Teach the agent</button>';
  const open='<a class="btn ghost" data-route href="'+esc(openHref)+'">Open</a>';
  if(tab==="review")return teach+'<button class="btn" data-a="reviewed">Mark reviewed</button><button class="btn" data-a="resolve">Resolve</button><button class="btn ghost" data-a="archive">Archive…</button>'+open;
  return '<button class="btn" data-a="reopen">Move to For review</button>'+(tab==="resolved"?"":teach)+open;
}

/* shown: {g, name, tab, tri, series, weeks, project}; one object so a row is built from one value. */
function rowHtml(shown){
  const {g,name,tab,tri,series,weeks,project}=shown;
  const openHref=M.hrefFor(project,{view:"group",key:g.key});
  const kind=g.kind==="failure"?"agent failure":"your correction";
  const stat=stateNote(g,tri);
  return '<article class="grp" tabindex="0" data-key="'+esc(g.key)+'" aria-label="'+esc(name)+'">'
    +'<span class="kmark '+esc(g.kind)+'" role="img" aria-label="'+kind+'" title="'+kind+'">'+(g.kind==="failure"?"!":"you")+"</span>"
    +'<div><button class="sn" data-a="rename" title="Click to rename" aria-label="Rename group: '+esc(name)+'">'+esc(name)+"</button>"
    +'<div class="ttl'+(g.kind==="failure"?" mono":"")+'">'+esc(g.title)+"</div>"
    +'<div class="why">'+(tri.regressed?BADGES.regressed:"")+trendPill(g)+(tab!=="review"?'<span class="pill '+tab+'">'+M.TAB_WORDS[tab]+"</span> ":"")+"Grouped because: "+esc(g.groupedBecause)+"</div></div>"
    +'<dl class="three"><dt>What happened</dt><dd>'+code(g.happened)+"</dd>"+episodeRows(g)
    +"<dt>What fixed it</dt><dd>"+(g.fixed?code(g.fixed):"Nothing fixed it in these sessions.")+"</dd><dt>Verdict</dt><dd><b>"+esc(M.verdictText(g))+"</b></dd></dl>"
    +'<div class="gacts">'+actionsHtml(tab,openHref)+"</div>"+(stat?'<div class="stnote">'+esc(stat)+"</div>":"")
    +'<div class="gstat"><div class="big">'+g.sessions.toLocaleString("en-US")+"<small>"+(g.sessions===1?"session":"sessions")+"</small></div>"
    +'<div class="sm"><b>'+M.plural(g.times,"time")+"</b> in all"+(g.undatedSessions?", "+M.plural(g.undatedSessions,"session")+" without a date":"")+"</div>"
    +(series.length?sparkHtml(series,weeks,g.kind):"")
    +'<div class="sm">first <b>'+fd(g.first)+"</b> · last <b>"+fd(g.last)+"</b></div></div></article>";
}

function tilesHtml(tiles){
  const hue=["var(--tx)","var(--rd)","var(--cy)","var(--or)","var(--vi)"];
  return tiles.map((t,i)=>'<div class="panel"><div class="num" style="color:'+hue[i]+'">'+t.value.toLocaleString("en-US")+'</div><div class="lbl">'+esc(t.label)+(t.sub?"<span>"+esc(t.sub)+"</span>":"")+"</div></div>").join("");
}

/* A fold is never silent: the summary says how many, and why when it is noise. */
function foldHtml(id,title,count,lead,body){
  return '<details class="fold" id="'+id+'"'+(body?" open":"")+"><summary><span class=\"chev\"></span><span>"+esc(title)+": "+count+"</span>"+(lead?' <span class="lead">'+lead+"</span>":"")+"</summary>"+body+"</details>";
}
function noiseLead(reasons){return reasons.map(r=>esc(r.reason)+" ("+M.plural(r.times,"time")+")").join(" · ");}

/* "Where sessions got stuck": one row per friction, its bar scaled to the biggest. */
function frictionHtml(rows){
  const head='<h2>Where sessions got stuck</h2><p class="sub">What slowed sessions down, named by your session model. Hover a bar for the share of all sessions.</p>';
  if(!rows.length)return head+'<p class="mu">No friction has been named yet.</p>';
  return head+rows.map(f=>'<div class="frow"><span class="nm">'+esc(f.name)+'</span><span class="ct">'+f.sessions.toLocaleString("en-US")+"<small>"+(f.sessions===1?"session":"sessions")+"</small></span>"
    +'<div class="tr"><i style="width:'+f.width.toFixed(1)+'%" tabindex="0" data-tip="'+esc("<b>"+esc(f.name)+"</b><br>"+f.tip)+'"></i></div><span class="ds">'+esc(f.description)+"</span></div>").join("");
}

window.SymbiontInboxRows={esc,fd,rowHtml,tilesHtml,foldHtml,noiseLead,frictionHtml};
})();
