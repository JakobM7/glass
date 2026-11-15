/**
 * Client beacon (~1.4 KB gzipped). Inlined into each HTML page (no extra request, nothing for ad-block lists to match);
 * also served at /_al/s.js.
 * No cookies, no storage. Sends: pv on load/route change, engage on hide, custom events.
 *
 *   agentlens.track("signup", { plan: "pro" }, 49)
 *   <button data-al-event="cta_click">  → auto-tracked
 */
export const BEACON_JS = `(()=>{var s=document.currentScript,t=s&&s.dataset.t;if(!t||window.agentlens)return;
var n=navigator,w=window,E="/_al/e",G=[];
if(n.webdriver)G.push("webdriver");
["__playwright","__pwInitScripts","__puppeteer_evaluation_script__","callPhantom","_phantom","__nightmare","domAutomation","domAutomationController","_selenium","__selenium_unwrapped","__webdriver_evaluate","__driver_evaluate","__lastWatirAlert"].forEach(function(k){if(k in w)G.push("g:"+k)});
try{for(var k in w)if(/^\\$?cdc_/.test(k)){G.push("g:cdc");break}}catch(e){}
if(/HeadlessChrome/.test(n.userAgent))G.push("headless_ua");
if(w.outerWidth===0&&w.outerHeight===0)G.push("zero_outer");
if(n.languages&&n.languages.length===0)G.push("no_languages");
var q=new URLSearchParams(location.search),utm=q.get("utm_source")||"",med=q.get("utm_medium")||"",cmp=q.get("utm_campaign")||"",ref=document.referrer,P=location.pathname;
function send(k,d){var b=JSON.stringify(Object.assign({t:t,k:k,p:P,r:ref,u:utm,m:med,c:cmp,w:w.innerWidth,tp:n.maxTouchPoints||0,s:G},d));try{n.sendBeacon(E,b)||fetch(E,{method:"POST",body:b,keepalive:true})}catch(e){}}
var S;function reset(){S={t0:performance.now(),mv:0,sc:0,ky:0,ck:0,cnm:0,tc:0,ut:0,d:0,fx:-1,fy:-1,lx:-1,ly:-1,sent:0}}reset();
var o={passive:true,capture:true};
addEventListener("mousemove",function(e){if(!e.isTrusted){S.ut++;return}if(S.lx<0){S.fx=e.clientX;S.fy=e.clientY}else S.d+=Math.hypot(e.clientX-S.lx,e.clientY-S.ly);S.lx=e.clientX;S.ly=e.clientY;S.mv++},o);
addEventListener("scroll",function(){S.sc++},o);
addEventListener("touchstart",function(){S.tc++},o);
addEventListener("keydown",function(e){e.isTrusted?S.ky++:S.ut++},o);
addEventListener("click",function(e){if(!e.isTrusted){S.ut++;return}S.ck++;if(!S.mv&&!S.tc)S.cnm++;
var el=e.target&&e.target.closest&&e.target.closest("[data-al-event]");if(el)track(el.getAttribute("data-al-event"))},o);
function engage(){if(S.sent)return;S.sent=1;var disp=S.lx<0?0:Math.hypot(S.lx-S.fx,S.ly-S.fy);
send("engage",{d:Math.round(performance.now()-S.t0),mv:S.mv,sc:S.sc,ky:S.ky,ck:S.ck,cnm:S.cnm,tc:S.tc,ut:S.ut,st:S.d>0?+(disp/S.d).toFixed(3):0})}
function track(name,props,value){if(name)send("event",{n:String(name).slice(0,64),pr:props||null,v:+value||0})}
function nav(){if(location.pathname===P)return;engage();ref=location.origin+P;utm=med=cmp="";P=location.pathname;reset();send("pv")}
["pushState","replaceState"].forEach(function(m){var f=history[m];history[m]=function(){var r=f.apply(this,arguments);nav();return r}});
addEventListener("popstate",nav);
addEventListener("visibilitychange",function(){if(document.visibilityState==="hidden")engage()});
addEventListener("pagehide",engage);
var Q=w.agentlens_q||[];w.agentlens={track:track};Q.forEach(function(a){track.apply(null,a)});
send("pv")})();`;
