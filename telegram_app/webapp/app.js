const tg = window.Telegram?.WebApp;
tg?.ready(); tg?.expand();
const headers = () => ({"Content-Type":"application/json", "X-Telegram-Init-Data": tg?.initData || ""});
const $ = (id) => document.getElementById(id);
async function request(path, options = {}) { const r = await fetch(path, {...options, headers:{...headers(), ...(options.headers||{})}}); const data = await r.json(); if (!r.ok) throw new Error(data.detail || "Помилка"); return data; }
async function refresh() { try { const s = await request('/api/state'); $('threshold').value = s.threshold; $('status').textContent = s.status; $('substatus').textContent = s.connected ? (s.running ? 'Моніторинг увімкнений' : 'Моніторинг зупинений') : 'Локальний агент не підключений'; $('dot').className = `dot ${s.connected ? 'ok' : ''}`; $('pair').hidden = s.paired; } catch(e) { $('status').textContent=e.message; } }
async function command(action) { try { await request('/api/command',{method:'POST',body:JSON.stringify({action,threshold:Number($('threshold').value)})}); await refresh(); } catch(e) { tg?.showAlert?.(e.message) || alert(e.message); } }
$('start').onclick=()=>command('start'); $('stop').onclick=()=>command('stop');
$('pair').onclick=async()=>{ try { const c=await request('/api/pair',{method:'POST'}); $('credentials').hidden=false; $('credentials').textContent=`Створи telegram_app/agent-config.json на своєму ПК:\n\n{\n  "server_ws_url": "${location.origin.replace('https','wss').replace('http','ws')}/ws/agent",\n  "agent_id": "${c.agent_id}",\n  "agent_token": "${c.agent_token}"\n}\n\nТокен показується лише один раз.`; $('pair').disabled=true; } catch(e) { alert(e.message); } };
refresh(); setInterval(refresh, 5000);
