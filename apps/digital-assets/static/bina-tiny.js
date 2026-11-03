/* @bina-tiny:start */
(function(){ if (window.binaTiny) return;
  var isTiny=function(w,h){return h<300||(w<560&&h<440);}; var said='';
  function say(m){ if(window.parent===window)return; var k=JSON.stringify(m||{}); if(k===said)return; said=k; try{window.parent.postMessage(Object.assign({type:'bina:widget'},m||{}),location.origin);}catch(e){} }
  function binaTiny(onChange){ var cur=null,root=document.documentElement; function check(){ var t=isTiny(innerWidth,innerHeight); if(t===cur)return; cur=t; if(t)root.setAttribute('data-tiny','');else root.removeAttribute('data-tiny'); if(onChange)try{onChange(t);}catch(e){} } addEventListener('resize',check); check(); return {get tiny(){return cur;},check:check}; }
  function onAction(fn){ addEventListener('message',function(e){ if(e.source!==window.parent||e.origin!==location.origin||!e.data||e.data.type!=='bina:widget-action')return; fn(e.data.id,e.data); }); }
  window.binaTiny=binaTiny; binaTiny.isTiny=isTiny; binaTiny.say=say; binaTiny.onAction=onAction; })();
/* @bina-tiny:end */
