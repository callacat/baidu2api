import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from config import config

logger = logging.getLogger("baidu2api")

admin_router = APIRouter(prefix="/admin")


def _check_admin(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    key = auth[7:].strip()
    if key != config.admin_key:
        raise HTTPException(status_code=401, detail="Invalid admin key")


@admin_router.get("/config")
async def get_config(request: Request):
    _check_admin(request)
    return config.to_dict()


@admin_router.post("/config")
async def update_config(request: Request):
    _check_admin(request)
    data = await request.json()
    config.update(data)
    return {"status": "ok"}


@admin_router.get("/status")
async def get_status(request: Request):
    _check_admin(request)
    return {
        "status": "running",
        "uptime": time.time(),
        "toolcall_mode": config.toolcall_mode,
        "api_keys_count": len(config.api_keys),
    }


@admin_router.post("/api-keys")
async def add_api_key(request: Request):
    _check_admin(request)
    data = await request.json()
    key = data.get("key", "")
    if not key:
        raise HTTPException(status_code=400, detail="Key is required")
    if key not in config.api_keys:
        config.api_keys = config.api_keys + [key]
        config.save()
    return {"status": "ok"}


@admin_router.delete("/api-keys/{key}")
async def delete_api_key(request: Request, key: str):
    _check_admin(request)
    config.api_keys = [k for k in config.api_keys if k != key]
    config.save()
    return {"status": "ok"}


ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Baidu2API Admin</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
.container { max-width: 800px; margin: 0 auto; padding: 2rem; }
h1 { font-size: 1.5rem; margin-bottom: 1.5rem; color: #38bdf8; }
.card { background: #1e293b; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; }
.card h2 { font-size: 1.1rem; margin-bottom: 1rem; color: #94a3b8; }
input, select { width: 100%; padding: 0.5rem 0.75rem; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-size: 0.9rem; outline: none; }
input:focus, select:focus { border-color: #38bdf8; }
button { padding: 0.5rem 1rem; background: #38bdf8; color: #0f172a; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 0.9rem; }
button:hover { background: #7dd3fc; }
button.danger { background: #ef4444; color: white; }
button.danger:hover { background: #f87171; }
.key-list { list-style: none; }
.key-list li { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid #334155; }
.key-list li:last-child { border-bottom: none; }
.login-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.8); display: flex; align-items: center; justify-content: center; z-index: 100; }
.login-box { background: #1e293b; padding: 2rem; border-radius: 12px; width: 360px; }
.login-box h2 { margin-bottom: 1rem; color: #38bdf8; }
.login-box input { margin-bottom: 1rem; }
.row { display: flex; gap: 0.5rem; align-items: center; }
.row input { flex: 1; }
.status-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.status-item { text-align: center; }
.status-item .value { font-size: 1.5rem; font-weight: 700; color: #38bdf8; }
.status-item .label { font-size: 0.8rem; color: #64748b; margin-top: 0.25rem; }
</style>
</head>
<body>
<div id="loginOverlay" class="login-overlay">
  <div class="login-box">
    <h2>Baidu2API Admin</h2>
    <input type="password" id="loginKey" placeholder="Admin Key" onkeydown="if(event.key==='Enter')login()">
    <button onclick="login()" style="width:100%">Login</button>
  </div>
</div>
<div class="container" id="mainContent" style="display:none">
  <h1>Baidu2API Admin</h1>
  <div class="card">
    <h2>Status</h2>
    <div class="status-grid">
      <div class="status-item"><div class="value" id="statusMode">-</div><div class="label">Toolcall Mode</div></div>
      <div class="status-item"><div class="value" id="statusKeys">-</div><div class="label">API Keys</div></div>
    </div>
  </div>
  <div class="card">
    <h2>Configuration</h2>
    <div style="margin-bottom:1rem">
      <label style="display:block;margin-bottom:0.5rem;font-size:0.85rem;color:#94a3b8">Toolcall Mode</label>
      <select id="toolcallMode" onchange="updateConfig()">
        <option value="xml">XML (Toolify-style)</option>
        <option value="json">JSON (DS2API-style)</option>
      </select>
    </div>
  </div>
  <div class="card">
    <h2>API Keys</h2>
    <div class="row" style="margin-bottom:1rem">
      <input type="text" id="newKey" placeholder="New API Key">
      <button onclick="addKey()">Add</button>
    </div>
    <ul class="key-list" id="keyList"></ul>
  </div>
</div>
<script>
let adminKey = '';
async function api(method, path, body) {
  const opts = { method, headers: { 'Authorization': 'Bearer ' + adminKey, 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch('/admin' + path, opts);
  if (r.status === 401) { document.getElementById('loginOverlay').style.display = 'flex'; document.getElementById('mainContent').style.display = 'none'; return null; }
  return r.json();
}
function login() {
  adminKey = document.getElementById('loginKey').value;
  load();
  document.getElementById('loginOverlay').style.display = 'none';
  document.getElementById('mainContent').style.display = 'block';
}
async function load() {
  const status = await api('GET', '/status');
  if (!status) return;
  document.getElementById('statusMode').textContent = status.toolcall_mode;
  document.getElementById('statusKeys').textContent = status.api_keys_count;
  const cfg = await api('GET', '/config');
  if (!cfg) return;
  document.getElementById('toolcallMode').value = cfg.toolcall_mode || 'xml';
  renderKeys(cfg.api_keys || []);
}
function renderKeys(keys) {
  const ul = document.getElementById('keyList');
  ul.innerHTML = keys.map(k => '<li><code>' + k + '</code><button class="danger" onclick="delKey(\\''+k+'\\')">Delete</button></li>').join('');
}
async function addKey() {
  const key = document.getElementById('newKey').value.trim();
  if (!key) return;
  await api('POST', '/api-keys', { key });
  document.getElementById('newKey').value = '';
  load();
}
async function delKey(key) {
  await api('DELETE', '/api-keys/' + encodeURIComponent(key));
  load();
}
async function updateConfig() {
  await api('POST', '/config', { toolcall_mode: document.getElementById('toolcallMode').value });
  load();
}
</script>
</body>
</html>"""


@admin_router.get("/")
async def admin_page():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=ADMIN_HTML)
