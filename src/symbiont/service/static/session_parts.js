/* The session page's markup: the step-by-step lanes and the two lists. Pure strings in, strings out.
   Every field that came from the log or the store goes through esc; tooltip text is escaped once for the markup it
   carries and once for the attribute, and SymbiontTip.safe has the last word when it is shown. */
(function () {
"use strict";
const SM=()=>window.SymbiontSessionModel;
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const LANE_Y={you:30,edit:80,scratch:80,failed:130},W=1500,H=170,X0=90,X1=W-12;
const LANE_WORD={you:"you wrote",edit:"edit in the codebase",scratch:"edit to a doc or scratch file",failed:"command failed"};

function tagHtml(tag,hrefOf){
  if(tag.kind==="group")return '<span class="tagl">In group: <a data-route href="'+esc(hrefOf({view:"group",key:tag.key}))+'">'+esc(tag.name)+" →</a></span>";
  if(tag.kind==="noise")return '<span class="tagl nz">Noise: '+esc(String(tag.reason).toLowerCase())+"</span>";
  return '<span class="tagl nz">Not in a group</span>';
}
function tipOf(step,lane,detail,tag){
  let html="<b>Step "+Number(step)+", "+LANE_WORD[lane]+"</b>";
  if(detail.label)html+="<br>"+esc(detail.label).slice(0,220);
  if(detail.error)html+='<br><span class="m">'+esc(detail.error).slice(0,160)+"</span>";
  if(tag.kind==="group")html+="<br><b>In a group: "+esc(tag.name)+"</b>";
  if(tag.kind==="noise")html+='<br><span class="m">noise: '+esc(tag.reason)+"</span>";
  return ' data-tip="'+esc(html)+'" data-step="'+Number(step)+'" tabindex="0"';
}
function markSvg(x,y,lane,tag,attrs){
  const cls=' class="mk '+SM().markClass(lane,tag)+'"';
  const r=tag.kind==="group"?8:6;
  if(lane==="you"){const s=tag.kind==="group"?14:10;return '<rect x="'+(x-s/2)+'" y="'+(y-s/2)+'" width="'+s+'" height="'+s+'" rx="3"'+cls+attrs+"/>";}
  return '<circle cx="'+x+'" cy="'+y+'" r="'+r+'"'+cls+attrs+"/>";
}
function stripSvg(steps,details,tagFor,focus){
  const nums=steps.map(s=>s[0]),lo=Math.min(...nums),hi=Math.max(...nums),span=Math.max(1,hi-lo);
  const xs=n=>Math.round(X0+((n-lo)/span)*(X1-X0));
  let h='<svg viewBox="0 0 '+W+" "+H+'" role="img" aria-label="Steps of this session: your messages, edits and failed commands">';
  [["you","you"],["edits","edit"],["failed","failed"]].forEach(([name,lane])=>{
    h+='<text x="'+(X0-14)+'" y="'+(LANE_Y[lane]+4)+'" text-anchor="end">'+name+'</text><line x1="'+X0+'" x2="'+X1+'" y1="'+LANE_Y[lane]+'" y2="'+LANE_Y[lane]+'" class="lane"/>';
  });
  steps.forEach(([n,lane,label])=>{
    h+=markSvg(xs(n),LANE_Y[lane],lane,tagFor(n),tipOf(n,lane,{label,error:(details[n]||{}).error},tagFor(n)));
  });
  if(focus!==null&&nums.includes(focus))h+='<line x1="'+xs(focus)+'" x2="'+xs(focus)+'" y1="10" y2="'+(H-18)+'" class="focus"/>';
  return h+'<text x="'+X0+'" y="'+(H-4)+'">step '+lo+'</text><text x="'+X1+'" y="'+(H-4)+'" text-anchor="end">step '+hi+"</text></svg>";
}
function filterButtons(prefix,options,current){
  return '<div class="seg2">'+options.map(([key,label])=>'<button data-filter="'+prefix+":"+key+'" aria-pressed="'+(key===current)+'">'+esc(label)+"</button>").join("")+"</div>";
}
function messageItem(m,tag,hrefOf){
  const before=m.before?'<div class="ctx">Before: <code>'+esc(m.before)+"</code></div>":"";
  const then=m.then?'<div class="next">'+esc(m.then)+"</div>":"";
  return '<div class="it" id="st-'+Number(m.step)+'"><span class="st">step '+Number(m.step)+"</span><div>"+before+'<div class="msg you">'+esc(m.text)+"</div>"+then+tagHtml(tag,hrefOf)+"</div></div>";
}
function failedItem(f,tag,hrefOf){
  return '<div class="it" id="st-'+Number(f.step)+'"><span class="st">step '+Number(f.step)+'</span><div><div class="cmd">$ '+esc(f.command)+'</div><div class="err">'+esc(f.error)+"</div>"+tagHtml(tag,hrefOf)+"</div></div>";
}
function itemsHtml(rows,emptyWord){
  return rows.length?rows.join(""):'<div class="empty2">'+emptyWord+"</div>";
}
window.SymbiontSessionParts={esc,tagHtml,stripSvg,filterButtons,messageItem,failedItem,itemsHtml};
})();
