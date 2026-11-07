/* The group page's markup: header, weekly chart, three lines, teach panel, occurrences, side lists.
   Pure strings in, strings out. Everything from the store or the history goes through esc; tooltip markup is escaped
   once for its pieces and once for the attribute, and SymbiontTip.safe has the last word when it is shown. */
(function () {
"use strict";
const M=window.SymbiontInboxModel,R=window.SymbiontInboxRows,G=window.SymbiontGroupModel;
const esc=R.esc,fd=R.fd,code=s=>esc(s).replace(/`([^`]+)`/g,"<code>$1</code>");
const MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const dayOf=d=>MON[d.getUTCMonth()]+" "+d.getUTCDate();
const CAP_COMMAND=300;
const clip=text=>{const s=String(text==null?"":text);return s.length>CAP_COMMAND?s.slice(0,CAP_COMMAND)+"…":s;};
const unitOf=(g,n)=>M.plural(n,G.noun(g));

function factsHtml(g,topic,sessionsRead){
  const fact=(big,word)=>"<div><b>"+big+"</b>"+word+"</div>";
  const of=sessionsRead?" of "+sessionsRead.toLocaleString("en-US"):"";
  return '<div class="facts">'+fact(g.times.toLocaleString("en-US"),g.times===1?G.noun(g):G.noun(g)+"s")
    +fact(g.sessions.toLocaleString("en-US"),"session"+(g.sessions===1?"":"s")+of)
    +fact(esc(fd(g.first)),"first seen")+fact(esc(fd(g.last)),"last seen")
    +(topic?fact(esc(topic),"topic with most of it"):"")+"</div>";
}
function actionButtons(review){
  if(!review)return '<button class="btn" data-a="reopen">Move to For review</button>';
  return '<button class="btn primary" data-a="teach">Teach the agent</button><button class="btn" data-a="reviewed">Mark reviewed</button><button class="btn" data-a="resolve">Resolve</button>';
}
function archiveSelect(){
  const options=M.archiveChoices(new Date()).map((c,i)=>'<option value="'+i+'">'+esc(c.label)+"</option>").join("");
  return '<label class="mu archl">Archive, and bring it back<select class="sel" data-archive><option value="">choose…</option>'+options+"</select></label>";
}
/* shown: {g, name, tri, topic, sessionsRead}. A correction's words are shown whatever the history, as the Inbox shows them. */
function headHtml(shown){
  const {g,name,tri,topic,sessionsRead}=shown,cor=g.kind==="correction";
  const example='<div class="ex1'+(cor?"":" mono")+'">e.g. '+esc(g.title)+"</div>";
  const note=G.statusNote(g,tri,fd);
  return '<span class="kmark '+esc(g.kind)+'">'+(cor?"you":"!")+"</span>"
    +"<div><h1>"+esc(name)+"</h1>"+example+"</div>"
    +'<div class="acts"><span class="pill '+(tri.regressed?"rising":esc(M.tabOf({[g.key]:tri},g)))+'">'+esc(G.statusWord(g,tri))+"</span>"+actionButtons(G.inReview(g,tri))+archiveSelect()+"</div>"
    +'<div class="why">Grouped because: '+esc(g.groupedBecause)+"</div>"+factsHtml(g,topic,sessionsRead)
    +(note?'<div class="stn">'+esc(note)+"</div>":"");
}

function tipOf(bar,g){
  return "<b>Week of "+dayOf(bar.monday)+"</b><br>"+esc(unitOf(g,bar.times))+'<br><span class="m">'+esc(M.plural(bar.sessions,"session"))+" that week</span>";
}
function gridHtml(top){
  return [0,top/2,top].map(v=>{
    const y=150-(v/top)*140;
    return '<line class="ax" x1="34" x2="1040" y1="'+y+'" y2="'+y+'"'+(v?' stroke-dasharray="2 4"':"")+'/><text x="28" y="'+(y+4)+'" text-anchor="end">'+v+"</text>";
  }).join("");
}
function barHtml(bar,i,width,top,g){
  const x=40+i*width,h=bar.times?Math.max(3,(bar.times/top)*140):0;
  const rect=bar.times?'<rect class="wk" x="'+(x+2)+'" y="'+(150-h)+'" width="'+Math.max(1,width-4)+'" height="'+h+'" rx="3"/>':"";
  const hit='<rect class="hit" x="'+x+'" y="0" width="'+width+'" height="150" data-tip="'+esc(tipOf(bar,g))+'"'+(bar.times?' tabindex="0"':"")+"/>";
  const label=i%4===0?'<text x="'+(x+width/2)+'" y="168" text-anchor="middle">'+dayOf(bar.monday)+"</text>":"";
  return rect+hit+label;
}
function markerHtml(position,width,count,label){
  const right=position.side==="after",x=right?40+count*width-2:position.side==="before"?40:40+position.index*width;
  return '<line class="mark" x1="'+x+'" x2="'+x+'" y1="0" y2="150"/><text class="marktx" x="'+(right?x-6:x+6)+'" y="14" text-anchor="'+(right?"end":"start")+'">'+esc(label)+"</text>";
}
function legendHtml(g,marker){
  const first='<span><i class="'+esc(g.kind)+'"></i>'+(g.kind==="correction"?"your messages in this group":"failures in this group")+"</span>";
  return first+(marker?'<span><i class="lesson"></i>'+esc(marker.legend)+"</span>":"");
}
/* shown: {g, bars, top, marker: {position, label, legend}|null}; an empty axis says there is nothing dated. */
function timelineHtml(shown){
  const {g,bars,top,marker}=shown;
  if(!bars.length)return '<h2>When it happened</h2><p class="empty2">No session of this group has a date, so there is no timeline.</p>';
  const width=1000/bars.length;
  const svg='<svg viewBox="0 0 1040 176" role="img" aria-label="'+esc(G.noun(g))+'s per week">'+gridHtml(top)+bars.map((b,i)=>barHtml(b,i,width,top,g)).join("")
    +(marker?markerHtml(marker.position,width,bars.length,marker.label):"")+"</svg>";
  const sub=unitOf(g,g.times)+" in all, counted per week from "+dayOf(bars[0].monday)+" to "+dayOf(bars[bars.length-1].monday)+". Hover a week for the number of sessions that week: a busy week has more chances to go wrong.";
  return "<h2>When it happened</h2><p class=\"sub\">"+esc(sub)+'</p><div class="chart">'+svg+'</div><div class="legend2">'+legendHtml(g,marker)+"</div>";
}

function threeHtml(g){
  return "<h2>In three lines</h2><p class=\"sub\">Summarized from all "+esc(unitOf(g,g.times))+'.</p><dl class="three"><dt>What happened</dt><dd>'+code(g.happened)+"</dd><dt>What fixed it</dt><dd>"
    +(g.fixed?code(g.fixed):"Nothing fixed it in these sessions.")+'</dd><dt>Verdict</dt><dd class="v"><b>'+esc(M.verdictText(g))+"</b></dd></dl>";
}

function teachPanelHtml(draft,taught){
  return '<h2>Teach the agent</h2><p class="sub">'+esc(M.teachNote(draft))+"</p>"
    +'<div class="teachbox"><div><label class="h" for="gWhen">When</label><input id="gWhen" value="'+esc(draft.when)+'" placeholder="when the agent is about to…">'
    +'<label class="h" for="gWhat">What the agent should know</label><textarea id="gWhat" rows="4">'+esc(draft.what)+"</textarea>"
    +'<div class="row"><button class="btn primary" data-save id="gSave">'+(taught?"Update lesson":"Save lesson")+'</button><span class="mu">Suggested from what fixed it; edit freely.</span></div>'
    +'<p class="mu" id="gTeachErr" role="alert"></p></div>'
    +'<div class="agentbox"><div class="mu">What the agent receives</div><div class="notebox sm" id="gPreview"></div><div class="cap">Plain sentences only: no scores, counts or labels reach the agent.</div></div></div>';
}
const previewHtml=text=>'<span class="user">'+esc(text)+"</span>";

function outcomeChip(summary){
  return summary&&summary.outcome?' <span class="outc"><i class="o-'+esc(summary.outcome)+'"></i>'+esc(summary.outcome)+"</span>":"";
}
function whatHappenedHtml(card,cor){
  if(!cor)return '<span class="cmd">$ '+esc(clip(card.command))+'</span><span class="err">'+esc(clip(card.happened))+"</span>";
  const before=card.firstWrong?'<span class="ctx">Agent had just: '+code(clip(card.firstWrong))+"</span>":"";
  const said=card.command?'<span class="cmd you">You: “'+esc(clip(card.command))+"”</span>":'<span class="ctx">'+esc(clip(card.happened))+"</span>";
  return before+said;
}
function verdictHtml(card,cor){
  if(card.outcome==="never_fixed"&&!cor)return "<b>Unresolved here:</b> the session moved on without a fix.";
  return "<b>Same as the group:</b> "+(cor?"a correction worth teaching.":"a repeat with a known fix.");
}
/* shown: {card, summary, project, cor, clearest}. */
function occurrenceHtml(shown){
  const {card,summary,project,cor}=shown;
  const open=card.sessionId?'<a data-route href="'+esc(M.hrefFor(project,{view:"session",id:card.sessionId,step:card.step}))+'">open session →</a>':"";
  const goal=(summary&&summary.goal)||card.session||"(no summary)";
  return '<div class="occ2'+(shown.clearest?" rec":"")+'"><div class="d">'+esc(fd(card.date))+open+"</div><div>"
    +'<div class="g">'+esc(goal)+outcomeChip(summary)+(shown.clearest?' <span class="pill reviewed">clearest example</span>':"")+"</div>"
    +'<dl class="three"><dt>What happened</dt><dd>'+whatHappenedHtml(card,cor)+"</dd><dt>What fixed it</dt><dd>"
    +(card.fixed?code(card.fixed):"Nothing fixed it here.")+"</dd><dt>Verdict</dt><dd>"+verdictHtml(card,cor)+"</dd></dl></div></div>";
}
function pagerHtml(page,pages){
  const btn=(id,label,off)=>'<button class="btn" data-occ="'+id+'"'+(off?" disabled":"")+">"+label+"</button>";
  return '<button class="btn vi" data-occ="clearest">Clearest example</button>'+btn("first","First",false)+btn("latest","Latest",false)
    +'<span class="grow"></span>'+btn("newer","‹ Newer",page===0)+'<span class="mu">page '+(page+1)+" of "+pages+"</span>"+btn("older","Older ›",page>=pages-1);
}

function activityHtml(rows){
  return rows.map(r=>'<li><i class="'+(r.quiet?"g":"")+'"></i><span>'+esc(r.text)+(r.when?"<small>"+esc(r.when)+"</small>":"")+"</span></li>").join("");
}
function topicsHtml(rows,project){
  const peak=Math.max(1,...rows.map(r=>r.sessions));
  const name=r=>r.key?'<a data-route href="'+esc(M.hrefFor(project,{view:"topics",t:r.key}))+'">'+esc(r.name)+"</a>":"<span>"+esc(r.name)+"</span>";
  return rows.map(r=>'<div class="r">'+name(r)+"<b>"+r.sessions+'</b><div class="tr"><i style="width:'+(100*r.sessions/peak).toFixed(1)+'%" tabindex="0" data-tip="'+esc("<b>"+esc(r.name)+"</b><br>"+M.plural(r.sessions,"session")+" with this group")+'"></i></div></div>').join("")
    +'<p class="mu">Numbers are sessions.</p>';
}
function othersHtml(rows,project){
  if(!rows.length)return '<p class="mu">No other groups of this kind.</p>';
  return rows.map(x=>'<a data-route href="'+esc(M.hrefFor(project,{view:"group",key:x.key}))+'">'+esc(x.name)+"<small>"+esc(M.plural(x.sessions,"session"))+(x.last?" · last "+esc(fd(x.last)):"")+"</small></a>").join("");
}

window.SymbiontGroupParts={headHtml,timelineHtml,threeHtml,teachPanelHtml,previewHtml,occurrenceHtml,pagerHtml,activityHtml,topicsHtml,othersHtml};
})();
