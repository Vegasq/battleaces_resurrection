"""Self-contained dashboard assets, shipped without external scripts or fonts."""

PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Battle Aces · Server</title><link rel="stylesheet" href="/dashboard.css"><script src="/dashboard.js" defer></script></head>
<body><header><a class="brand" href="/">BA<span>BATTLE ACES</span></a><span class="header-label">SERVER OVERVIEW</span>
<span id="connection" class="connection" role="status">Connecting…</span></header>
<main><div class="intro"><div><p class="eyebrow">THE COMMUNITY, IN PLAY</p><h1>Your server. Live.</h1>
<p class="muted">Players, matches, and the stories behind the score.</p></div><div class="refresh"><span id="updated">Waiting for server</span><button id="refresh" type="button">Refresh ↻</button></div></div>
<p id="warning" class="warning" role="alert" hidden></p>
<section class="metrics" aria-label="Server totals"><article><span>Players online</span><strong id="online-count">—</strong><small>Connected right now</small></article>
<article><span>Active games</span><strong id="active-count">—</strong><small>Preparing, loading & playing</small></article>
<article><span>Completed matches</span><strong id="completed-count">—</strong><small>Within retained history</small></article>
<article><span>Server uptime</span><strong id="uptime">—</strong><small>Since dashboard started</small></article></section>
<div class="live-grid"><section class="panel"><div class="panel-heading"><h2>Online players</h2><span class="eyebrow">LIVE ROSTER</span></div><div id="players" class="list"><p class="empty">Loading players…</p></div></section>
<section class="panel"><div class="panel-heading"><h2>Active games</h2><span class="eyebrow">ON THE BATTLEFIELD</span></div><div id="games" class="list"><p class="empty">Loading games…</p></div></section></div>
<section class="panel history"><div class="panel-heading"><div><h2>Match history</h2><p class="muted" id="retention">Results are saved across server restarts.</p></div><span id="history-count" class="eyebrow"></span></div>
<div class="table-scroll"><table><thead><tr><th>Started</th><th>Match</th><th>Players</th><th>Game time</th><th>Outcome</th></tr></thead><tbody id="history"></tbody></table></div>
<p id="history-empty" class="empty" hidden>No matches yet. Completed and aborted games will appear here.</p>
<div class="pagination"><button id="previous" type="button" disabled>← Previous</button><span id="page">Page 1</span><button id="next" type="button" disabled>Next →</button></div></section>
<footer>Battle Aces Resurrection <span>Live view refreshes every 3 seconds · Read-only dashboard</span></footer></main></body></html>'''

STYLE = '''
:root{color-scheme:dark;--bg:#101512;--panel:#19201b;--line:#303a31;--ink:#eef2df;--dim:#a7b0a1;--accent:#d4ed83;--orange:#f1b878}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Segoe UI",Arial,sans-serif}
header{height:78px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:40px;padding:0 max(24px,calc((100% - 1240px)/2));background:#141b16}
.brand{display:flex;align-items:center;gap:13px;font-size:28px;font-weight:900;letter-spacing:-2px;color:var(--accent);text-decoration:none}.brand span{font-size:13px;letter-spacing:2px;color:var(--ink)}
.header-label,.eyebrow{font-size:11px;font-weight:600;letter-spacing:1.5px;color:var(--dim)}.connection{margin-left:auto;font-size:12px;white-space:nowrap;color:var(--orange)}.connection.live{color:var(--accent)}.connection:before{content:"●";margin-right:8px}
main{max-width:1288px;margin:auto;padding:42px 24px 24px}.intro{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:32px}.eyebrow{margin:0 0 8px}h1{font-size:clamp(32px,4vw,46px);font-weight:600;letter-spacing:-1.5px;margin:0 0 6px}h2{margin:0;font-size:19px;font-weight:600;letter-spacing:-.4px}.muted{color:var(--dim);margin:4px 0;font-size:13px}.refresh{display:flex;align-items:center;gap:15px;color:var(--dim);font-size:12px}
button{font:inherit;color:var(--ink);background:transparent;border:1px solid #58634e;padding:8px 13px;border-radius:6px;cursor:pointer}button:hover{background:#303a28}button:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:4px}button:disabled{opacity:.35;cursor:default}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}.metrics article{border:1px solid var(--line);border-radius:9px;padding:20px 24px;background:var(--panel)}.metrics article:first-child{border-top:2px solid var(--accent)}.metrics span{font-size:13px;color:var(--dim)}.metrics strong{display:block;font-size:38px;font-weight:500;letter-spacing:-1px;margin:8px 0}.metrics small{color:var(--dim);font-size:11px}
.live-grid{display:grid;grid-template-columns:1fr 1.4fr;gap:24px;margin-bottom:24px}.panel{border:1px solid var(--line);border-radius:9px;background:var(--panel);overflow:hidden}.panel-heading{padding:20px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:14px;align-items:center}.panel-heading .eyebrow{margin:0;font-size:10px}.list{padding:4px 24px;max-height:430px;overflow:auto;min-height:150px}.player{display:flex;align-items:center;gap:13px;padding:15px 0;border-bottom:1px solid var(--line)}.player:last-child{border:0}.avatar{height:36px;width:36px;flex-shrink:0;display:grid;place-items:center;border-radius:50%;background:#303d27;color:var(--accent);font-weight:600}.player-info{min-width:0;flex:1}.name{overflow-wrap:anywhere;font-weight:600}.identity{color:var(--dim);font-size:10px;overflow-wrap:anywhere}.badge{font-size:11px;padding:3px 8px;border:1px solid #48533d;border-radius:4px;color:var(--accent);white-space:nowrap}.badge.aborted,.badge.interrupted{color:var(--orange);border-color:#745438}
.game{padding:18px 0;border-bottom:1px solid var(--line)}.game:last-child{border:0}.game-top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:9px}.match-meta{font-size:12px;color:var(--dim)}.versus{display:flex;gap:12px;align-items:center;flex-wrap:wrap;overflow-wrap:anywhere}.vs{font-size:10px;color:var(--orange);letter-spacing:1px}.bot{font-size:10px;color:var(--dim)}
.empty{padding:34px 12px;text-align:center;color:var(--dim);font-size:13px}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;text-align:left;min-width:720px}th{font-size:10px;letter-spacing:1.1px;text-transform:uppercase;color:var(--dim);font-weight:500;padding:14px 24px;background:#151c17}td{padding:16px 24px;border-top:1px solid var(--line);font-size:12px;vertical-align:top}td .name{max-width:320px}.outcome{color:var(--accent);font-size:11px;margin-top:5px;overflow-wrap:anywhere}.pagination{display:flex;align-items:center;justify-content:flex-end;gap:20px;padding:16px 24px;border-top:1px solid var(--line);font-size:12px;color:var(--dim)}footer{display:flex;justify-content:space-between;gap:20px;padding:25px 0 0;color:var(--dim);font-size:11px}.warning{border:1px solid #85603c;background:#34291d;color:#f6cf9e;border-radius:6px;padding:12px 16px}.history .panel-heading{align-items:start}
@media(max-width:800px){header{padding:0 20px;gap:14px}.header-label{display:none}main{padding-top:26px}.intro{align-items:start;flex-direction:column}.metrics{grid-template-columns:repeat(2,1fr)}.live-grid{grid-template-columns:1fr}.panel-heading{padding:18px}.list{padding:4px 18px}footer{flex-direction:column;gap:5px}.metrics article{padding:17px}.brand span{font-size:11px}.panel-heading .eyebrow{font-size:9px}}
'''

SCRIPT = '''
'use strict';
const el=id=>document.getElementById(id);
let page=0,busy=false;
const mode=id=>({1:'1v1',2:'2v2',5:'2vAI'}[id]||'Match');
const title=s=>s.charAt(0).toUpperCase()+s.slice(1);
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function duration(s){s=Math.floor(s);return s>=3600?`${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`:`${Math.floor(s/60)}m ${s%60}s`;}
function roster(m){return m.players.map(p=>p.name+(p.bot?' [Bot]':'')).join(' · ');}
function outcome(m){if(m.state!=='completed')return m.state==='interrupted'?'Server stopped before a result was recorded':'No winner recorded';const winners=m.players.filter(p=>p.alliance===m.winning_alliance);return winners.length?winners.map(p=>p.name).join(' + ')+' won':'Match completed';}
function render(data){
 el('connection').textContent=data.closing?'Stopping':'Live';el('connection').className='connection live';
 el('updated').textContent='Updated '+new Date(data.utc).toLocaleTimeString();
 el('online-count').textContent=data.online.length;el('active-count').textContent=data.active.length;
 el('completed-count').textContent=data.completed;el('uptime').textContent=duration(data.uptime_seconds);
 el('warning').hidden=data.persistence_ok;el('warning').textContent='Match history could not be saved. Live information is still available; check server storage.';
 const players=el('players');players.replaceChildren();
 for(const p of data.online){const row=node('div',undefined,'player'),info=node('div',undefined,'player-info');info.append(node('div',p.name,'name'),node('div',p.id,'identity'));row.append(node('div',Array.from(p.name)[0]||'?','avatar'),info,node('span',p.status,'badge'));players.append(row);}
 if(!data.online.length)players.append(node('p','No players online. Ready when you are.','empty'));
 const games=el('games');games.replaceChildren();
 for(const m of data.active){const card=node('article',undefined,'game'),top=node('div',undefined,'game-top');top.append(node('span',`${m.kind} / ${mode(m.mode)} · ${duration(m.seconds)}`,'match-meta'),node('span',title(m.state),'badge'));card.append(top,node('div',roster(m),'name'),node('div',m.id,'identity'));games.append(card);}
 if(!data.active.length)games.append(node('p','The battlefield is quiet. New games will appear here.','empty'));
 const history=el('history');history.replaceChildren();
 for(const m of data.history){const row=node('tr');row.append(node('td',new Date(m.started_at||m.created_at).toLocaleString()));const match=node('td');match.append(node('div',`${m.kind} / ${mode(m.mode)}`),node('div',m.id.slice(0,12),'identity'));row.append(match,node('td',roster(m),'name'),node('td',duration(m.seconds)));const result=node('td');result.append(node('span',title(m.state),'badge '+m.state),node('div',outcome(m),'outcome'));row.append(result);history.append(row);}
 el('history-empty').hidden=data.history_total>0;el('history-count').textContent=data.history_total+' RECORDED';
 el('retention').textContent=`Latest ${data.history_limit.toLocaleString()} matches retained across restarts. Game time excludes loading.`;
 page=data.page;el('page').textContent=`Page ${page+1} of ${data.pages}`;
 el('previous').disabled=page===0;el('next').disabled=page+1>=data.pages;
}
async function refresh(){if(busy)return;busy=true;el('refresh').disabled=true;try{const response=await fetch('/api/status?page='+page,{cache:'no-store',signal:AbortSignal.timeout(5000)});if(!response.ok)throw new Error('unavailable');render(await response.json());}catch(e){el('connection').textContent='Disconnected';el('connection').className='connection';el('warning').hidden=false;el('warning').textContent='Server unavailable. Showing the last received information; reconnecting automatically.';}finally{busy=false;el('refresh').disabled=false;}}
el('refresh').addEventListener('click',refresh);
el('previous').addEventListener('click',()=>{if(busy)return;page=Math.max(0,page-1);refresh();});
el('next').addEventListener('click',()=>{if(busy)return;page++;refresh();});
refresh();setInterval(refresh,3000);
'''
