const tg = window.Telegram?.WebApp;
tg?.ready(); tg?.expand();
const headers = () => ({"Content-Type":"application/json", "X-Telegram-Init-Data": tg?.initData || ""});
const $ = (id) => document.getElementById(id);
let thresholdDirty = false;
$("threshold").addEventListener("input", () => { thresholdDirty = true; });
async function request(path, options = {}) { const r = await fetch(path, {...options, headers:{...headers(), ...(options.headers||{})}}); const data = await r.json(); if (!r.ok) throw new Error(data.detail || "Помилка"); return data; }
async function refresh() { try { const s = await request('/api/state'); if (!thresholdDirty && document.activeElement !== $('threshold')) $('threshold').value = s.threshold; $('status').textContent = s.status; $('substatus').textContent = s.connected ? (s.running ? 'Моніторинг увімкнений' : 'Моніторинг зупинений') : 'Локальний агент не підключений'; $('dot').className = `dot ${s.connected ? 'ok' : ''}`; $('pair').hidden = s.connected; $('pair').textContent = s.paired ? 'Створити новий код підключення' : 'Підключити цей комп’ютер'; $('disconnect').hidden = !s.paired; } catch(e) { $('status').textContent=e.message; } }
async function command(action) { try { await request('/api/command',{method:'POST',body:JSON.stringify({action,threshold:Number($('threshold').value)})}); thresholdDirty = false; await refresh(); } catch(e) { tg?.showAlert?.(e.message) || alert(e.message); } }
$('login').onclick=()=>command('open_login'); $('start').onclick=()=>command('start'); $('stop').onclick=()=>command('stop');
$('disconnect').onclick=()=>{ if(confirm('Відключити цей ПК від Telegram-бота? Моніторинг буде зупинено.')) command('disconnect'); };
$('pair').onclick=async()=>{ try { const c=await request('/api/pair',{method:'POST'}); const config={server_ws_url:location.origin.replace('https','wss').replace('http','ws')+'/ws/agent',agent_id:c.agent_id,agent_token:c.agent_token}; $('credentials').hidden=false; $('credentials').textContent='Завантаж файл і поклади його в папку telegram_app на своєму ПК. Токен показується лише один раз.'; const blob=new Blob([JSON.stringify(config,null,2)],{type:'application/json'}); const link=$('download'); link.href=URL.createObjectURL(blob); link.hidden=false; $('pair').disabled=true; } catch(e) { alert(e.message); } };
refresh(); setInterval(refresh, 5000);
