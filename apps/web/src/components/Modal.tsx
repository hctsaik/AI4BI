import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';

/** Native modal semantics make the background inert and keep keyboard focus inside. */
export function Modal({title, children, onClose, busy=false, wide=false}: {
  title:string; children:ReactNode; onClose:()=>void; busy?:boolean; wide?:boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const composing = useRef(false);
  useEffect(()=>{
    const previous=document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const element=dialog.current;
    element?.showModal();
    return ()=>{element?.close();if(previous?.isConnected)previous.focus({preventScroll:true});};
  },[]);
  return <dialog ref={dialog} tabIndex={-1} aria-label={title} aria-busy={busy} className={`modal${wide?' wide':''}`}
    onCancel={event=>{event.preventDefault();if(!busy&&!composing.current)onClose();}}
    onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}}
    onKeyDown={event=>{
      if(event.key==='Escape'&&(event.nativeEvent.isComposing||composing.current))event.preventDefault();
      if(event.key!=='Tab')return;
      const items=Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button,input,select,textarea,a[href],[tabindex],summary,[contenteditable="true"]'))
        .filter(item=>item.tabIndex>=0&&!item.matches(':disabled')&&item.getClientRects().length>0);
      const first=items[0],last=items[items.length-1];
      if(!first){event.preventDefault();event.currentTarget.focus();}
      else if(event.shiftKey&&(document.activeElement===first||document.activeElement===event.currentTarget)){
        event.preventDefault();last.focus();
      }else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    }}>
    {children}
  </dialog>;
}
