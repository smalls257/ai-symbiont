/* The Inbox's small interactions: rename in place, the Archive return choice, the prefilled Teach the agent dialog.
   Violation prevented: Leaky Narrative. The developer never fills a form they had to read source to understand:
   Teach opens with When and What already written from the group, says what saving will do, and needs nothing typed. */
(function () {
"use strict";
const M=window.SymbiontInboxModel;

function toast(container,message){
  let node=container.querySelector(".toast2");
  if(!node){
    node=document.createElement("div");node.className="toast2";node.setAttribute("role","status");
    container.appendChild(node);
  }
  node.textContent=message;node.classList.add("on");
  clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.classList.remove("on"),4000);
}

/* Enter saves, Escape cancels; leaving the box cancels too, so nothing is written without an Enter. */
function renameInPlace(ui,g,button,save){
  const input=document.createElement("input");
  input.className="sn-edit";input.value=button.textContent;input.maxLength=M.MAX_NAME;
  input.setAttribute("aria-label","Group name (Enter saves, Escape cancels; empty restores the generated name)");
  let finished=false;
  const cancel=refocus=>{
    if(finished)return;
    finished=true;input.replaceWith(button);
    if(refocus)button.focus();
  };
  input.onkeydown=e=>{
    if(e.key==="Escape"){e.preventDefault();cancel(true);}
    if(e.key!=="Enter")return;
    e.preventDefault();finished=true;
    save(ui,g,input.value).catch(err=>{finished=false;toast(ui.container,"symbiont could not rename: "+err.message);});
  };
  input.onblur=()=>cancel(false);
  button.replaceWith(input);input.focus();input.select();
}

function archiveMenu(ui,g,button,pick){
  const old=ui.container.querySelector(".archmenu");
  if(old)old.remove();
  const menu=document.createElement("div");menu.className="archmenu";menu.setAttribute("role","menu");
  menu.innerHTML='<div class="h">Archive, and bring it back…</div>'+M.ARCHIVE_CHOICES.map((c,i)=>'<button role="menuitem" data-i="'+i+'">'+c.label+"<small>"+c.detail+"</small></button>").join("");
  const bar=button.parentElement;
  bar.appendChild(menu);
  menu.style.left=button.offsetLeft+"px";menu.style.top=(button.offsetTop+button.offsetHeight+4)+"px";
  const close=refocus=>{menu.remove();document.removeEventListener("click",outside);if(refocus)button.focus();};
  const outside=e=>{if(!menu.contains(e.target))close(false);};
  menu.onkeydown=e=>{if(e.key==="Escape"){e.preventDefault();close(true);}};
  menu.onclick=e=>{
    const item=e.target.closest("button[data-i]");
    if(!item)return;
    close(false);
    pick(M.ARCHIVE_CHOICES[+item.dataset.i]).catch(err=>toast(ui.container,"symbiont could not archive: "+err.message));
  };
  setTimeout(()=>document.addEventListener("click",outside),0);
  menu.querySelector("button").focus();
}

function teachHtml(){
  return '<form method="dialog" id="teachForm"><h2 id="teachTitle">Teach the agent</h2>'
    +'<p class="sub">This is what symbiont will teach, already filled in. Change anything, or save as it is.</p>'
    +'<label class="h" for="teachWhen">When</label><input id="teachWhen" placeholder="when the agent is about to…">'
    +'<label class="h" for="teachWhat">What the agent should know</label><textarea id="teachWhat" rows="5"></textarea>'
    +'<p class="mu" id="teachNote"></p><p class="mu" id="teachErr" role="alert"></p>'
    +'<div class="gacts"><button type="button" class="btn primary" id="teachSave">Save lesson</button>'
    +'<button type="button" class="btn ghost" id="teachCancel">Cancel</button></div></form>';
}

function teach(ui,g,button,done){
  const draft=M.teachDraft(g,M.displayName(ui.data.triage,g));
  const dialog=document.createElement("dialog");dialog.className="teach";dialog.setAttribute("aria-labelledby","teachTitle");
  dialog.innerHTML=teachHtml();
  const $=sel=>dialog.querySelector(sel);
  $("#teachWhen").value=draft.when;$("#teachWhat").value=draft.what;$("#teachNote").textContent=M.teachNote(draft);
  $("#teachCancel").onclick=()=>dialog.close();
  $("#teachSave").onclick=()=>{
    const request=M.lessonRequest(ui.project,g,$("#teachWhen").value,$("#teachWhat").value,draft.name);
    done(ui,g,request).then(()=>dialog.close()).catch(err=>{$("#teachErr").textContent="symbiont could not save the lesson: "+err.message;});
  };
  dialog.addEventListener("close",()=>{dialog.remove();const own=ui.container.querySelector('.grp[data-key="'+CSS.escape(g.key)+'"] button.btn');(own||button).focus();});
  ui.container.appendChild(dialog);dialog.showModal();$("#teachWhat").focus();
}

window.SymbiontInboxDialogs={toast,renameInPlace,archiveMenu,teach};
})();
