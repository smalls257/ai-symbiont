/* Click a name to edit it where it stands: Enter saves, Escape cancels, an empty name restores the generated one.
   Violation prevented: Silent Fallback. Leaving the box cancels, so nothing is written without an Enter, and a refused
   save keeps the box open and says why. Used for group names (inbox_dialogs.js) and topic names (topics.js). */
(function () {
"use strict";
const MAX_NAME=80;

function inPlace(button,save,report){
  const input=document.createElement("input");
  input.className="sn-edit";input.value=button.textContent;input.maxLength=MAX_NAME;
  input.setAttribute("aria-label","Name (Enter saves, Escape cancels; empty restores the generated name)");
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
    save(input.value).catch(err=>{finished=false;report("symbiont could not rename: "+err.message);});
  };
  input.onblur=()=>cancel(false);
  button.replaceWith(input);input.focus();input.select();
}

/* The trimmed name; longer than MAX_NAME is refused here too, before any request. */
function clean(text){
  const name=text.trim();
  if(name.length>MAX_NAME)throw new Error("A name can have at most "+MAX_NAME+" characters; this one has "+name.length+".");
  return name;
}

window.SymbiontRename={MAX_NAME,clean,inPlace};
})();
