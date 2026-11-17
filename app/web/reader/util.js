export const $=id=>document.getElementById(id);
export function el(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
export function button(text,fn,cls){const b=el('button',text,cls);b.type='button';b.addEventListener('click',fn);return b;}
export async function api(url,options={}){const r=await fetch(url,options);let d;try{d=await r.json();}catch{throw new Error('服务暂时不可用，请稍后重试。');}if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:'输入不符合要求，请检查后重试。');return d;}
export const send=(url,data,method='POST')=>api(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
let timer;
export function toast(text,action){const box=$('reader-toast');box.replaceChildren(el('span',text));if(action)box.append(button(action.label,action.fn));box.hidden=false;clearTimeout(timer);timer=setTimeout(()=>box.hidden=true,7000);}
export function uid(){return crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+Math.random().toString(36).slice(2);}
export function time(value){if(!value)return '';return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',month:'2-digit',day:'2-digit',hour12:false}).format(new Date(value.replace(' ','T')+'Z'));}
