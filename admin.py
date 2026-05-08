import json
import logging
import secrets
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


@admin_router.get("/init-status")
async def init_status():
    return {"initialized": bool(config.admin_key)}


@admin_router.post("/init")
async def init_admin(request: Request):
    if config.admin_key:
        raise HTTPException(status_code=400, detail="Already initialized")
    data = await request.json()
    key = data.get("admin_key", "")
    if not key or len(key) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    config.admin_key = key
    config.save()
    logger.info("Admin password initialized")
    return {"status": "ok"}


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


I18N = {
    "zh": {
        "title": "Baidu2API 管理后台",
        "initTitle": "初始化管理员密码",
        "initDesc": "首次使用，请设置管理员密码",
        "initPlaceholder": "请输入管理员密码（至少4位）",
        "initConfirm": "确认密码",
        "initBtn": "创建密码",
        "initMismatch": "两次输入的密码不一致",
        "loginTitle": "管理员登录",
        "loginPlaceholder": "请输入管理员密码",
        "loginBtn": "登录",
        "statusTitle": "服务状态",
        "toolcallMode": "工具调用模式",
        "apiKeysCount": "API 密钥数量",
        "configTitle": "配置管理",
        "toolcallModeLabel": "工具调用模式",
        "xmlMode": "XML 模式（Toolify 风格）",
        "jsonMode": "JSON 模式（DS2API 风格）",
        "apiKeysTitle": "API 密钥管理",
        "newKeyPlaceholder": "输入新的 API 密钥",
        "addBtn": "添加",
        "deleteBtn": "删除",
        "noKeys": "暂无 API 密钥",
        "langSwitch": "EN",
        "backHome": "返回首页",
        "saveSuccess": "保存成功",
        "saveFail": "保存失败",
    },
    "en": {
        "title": "Baidu2API Admin",
        "initTitle": "Initialize Admin Password",
        "initDesc": "First time setup, please create an admin password",
        "initPlaceholder": "Enter admin password (min 4 chars)",
        "initConfirm": "Confirm password",
        "initBtn": "Create Password",
        "initMismatch": "Passwords do not match",
        "loginTitle": "Admin Login",
        "loginPlaceholder": "Enter admin password",
        "loginBtn": "Login",
        "statusTitle": "Service Status",
        "toolcallMode": "Toolcall Mode",
        "apiKeysCount": "API Keys",
        "configTitle": "Configuration",
        "toolcallModeLabel": "Toolcall Mode",
        "xmlMode": "XML Mode (Toolify-style)",
        "jsonMode": "JSON Mode (DS2API-style)",
        "apiKeysTitle": "API Keys",
        "newKeyPlaceholder": "Enter new API key",
        "addBtn": "Add",
        "deleteBtn": "Delete",
        "noKeys": "No API keys",
        "langSwitch": "中文",
        "backHome": "Home",
        "saveSuccess": "Saved",
        "saveFail": "Save failed",
    },
}

ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Baidu2API Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f7fa;color:#1f2937;min-height:100vh}
.container{max-width:800px;margin:0 auto;padding:2rem}
h1{font-size:1.5rem;margin-bottom:1.5rem;color:#2563eb}
.card{background:#fff;border-radius:12px;padding:1.5rem;margin-bottom:1rem;box-shadow:0 1px 3px rgba(0,0,0,0.08)}
.card h2{font-size:1.1rem;margin-bottom:1rem;color:#6b7280;font-weight:600}
input,select{width:100%;padding:0.5rem 0.75rem;background:#fff;border:1px solid #d1d5db;border-radius:8px;color:#1f2937;font-size:0.9rem;outline:none;transition:border-color .2s}
input:focus,select:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,0.1)}
button{padding:0.5rem 1rem;background:#2563eb;color:#fff;border:none;border-radius:8px;font-weight:600;cursor:pointer;font-size:0.9rem;transition:background .2s}
button:hover{background:#1d4ed8}
button.danger{background:#dc2626;color:#fff}
button.danger:hover{background:#b91c1c}
button.secondary{background:#e5e7eb;color:#374151}
button.secondary:hover{background:#d1d5db}
.key-list{list-style:none}
.key-list li{display:flex;justify-content:space-between;align-items:center;padding:0.5rem 0;border-bottom:1px solid #f3f4f6}
.key-list li:last-child{border-bottom:none}
.overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.3);display:flex;align-items:center;justify-content:center;z-index:100}
.box{background:#fff;padding:2rem;border-radius:12px;width:380px;box-shadow:0 4px 20px rgba(0,0,0,0.15)}
.box h2{margin-bottom:0.5rem;color:#1f2937;font-size:1.2rem}
.box p{margin-bottom:1rem;color:#6b7280;font-size:0.85rem}
.box input{margin-bottom:0.75rem}
.row{display:flex;gap:0.5rem;align-items:center}
.row input{flex:1}
.status-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.status-item{text-align:center;padding:0.5rem}
.status-item .value{font-size:1.5rem;font-weight:700;color:#2563eb}
.status-item .label{font-size:0.8rem;color:#9ca3af;margin-top:0.25rem}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem}
.top-bar a{color:#2563eb;text-decoration:none;font-size:0.85rem}
.top-bar a:hover{text-decoration:underline}
.lang-btn{padding:0.25rem 0.75rem;background:#e5e7eb;color:#374151;border:none;border-radius:6px;font-size:0.8rem;cursor:pointer;font-weight:500}
.lang-btn:hover{background:#d1d5db}
.toast{position:fixed;top:1rem;right:1rem;padding:0.75rem 1.25rem;border-radius:8px;color:#fff;font-size:0.9rem;z-index:200;opacity:0;transition:opacity .3s}
.toast.show{opacity:1}
.toast.success{background:#16a34a}
.toast.error{background:#dc2626}
</style>
</head>
<body>
<div id="toast" class="toast"></div>
<div id="initOverlay" class="overlay" style="display:none">
  <div class="box">
    <h2 id="initTitle"></h2>
    <p id="initDesc"></p>
    <input type="password" id="initKey" autocomplete="new-password">
    <input type="password" id="initKeyConfirm" autocomplete="new-password">
    <button onclick="doInit()" style="width:100%" id="initBtn"></button>
  </div>
</div>
<div id="loginOverlay" class="overlay" style="display:none">
  <div class="box">
    <h2 id="loginTitle"></h2>
    <input type="password" id="loginKey" onkeydown="if(event.key==='Enter')login()">
    <button onclick="login()" style="width:100%" id="loginBtn"></button>
  </div>
</div>
<div class="container" id="mainContent" style="display:none">
  <div class="top-bar">
    <a href="/" id="backHome"></a>
    <button class="lang-btn" onclick="toggleLang()" id="langBtn"></button>
  </div>
  <h1 id="pageTitle"></h1>
  <div class="card">
    <h2 id="statusTitle"></h2>
    <div class="status-grid">
      <div class="status-item"><div class="value" id="statusMode">-</div><div class="label" id="statusModeLabel"></div></div>
      <div class="status-item"><div class="value" id="statusKeys">-</div><div class="label" id="statusKeysLabel"></div></div>
    </div>
  </div>
  <div class="card">
    <h2 id="configTitle"></h2>
    <div style="margin-bottom:1rem">
      <label style="display:block;margin-bottom:0.5rem;font-size:0.85rem;color:#6b7280" id="toolcallModeLabel"></label>
      <select id="toolcallMode" onchange="updateConfig()">
        <option value="xml" id="xmlOpt"></option>
        <option value="json" id="jsonOpt"></option>
      </select>
    </div>
  </div>
  <div class="card">
    <h2 id="apiKeysTitle"></h2>
    <div class="row" style="margin-bottom:1rem">
      <input type="text" id="newKey">
      <button onclick="addKey()" id="addBtn"></button>
    </div>
    <ul class="key-list" id="keyList"></ul>
  </div>
</div>
<script>
const I18N = """ + json.dumps(I18N, ensure_ascii=False) + """;
let lang = (navigator.language || navigator.userLanguage || '').startsWith('zh') ? 'zh' : 'en';
let adminKey = '';

function t(key) { return I18N[lang][key] || key; }

function applyLang() {
  document.title = t('title');
  document.getElementById('initTitle').textContent = t('initTitle');
  document.getElementById('initDesc').textContent = t('initDesc');
  document.getElementById('initKey').placeholder = t('initPlaceholder');
  document.getElementById('initKeyConfirm').placeholder = t('initConfirm');
  document.getElementById('initBtn').textContent = t('initBtn');
  document.getElementById('loginTitle').textContent = t('loginTitle');
  document.getElementById('loginKey').placeholder = t('loginPlaceholder');
  document.getElementById('loginBtn').textContent = t('loginBtn');
  document.getElementById('backHome').textContent = t('backHome');
  document.getElementById('langBtn').textContent = t('langSwitch');
  document.getElementById('pageTitle').textContent = t('title');
  document.getElementById('statusTitle').textContent = t('statusTitle');
  document.getElementById('statusModeLabel').textContent = t('toolcallMode');
  document.getElementById('statusKeysLabel').textContent = t('apiKeysCount');
  document.getElementById('configTitle').textContent = t('configTitle');
  document.getElementById('toolcallModeLabel').textContent = t('toolcallModeLabel');
  document.getElementById('xmlOpt').textContent = t('xmlMode');
  document.getElementById('jsonOpt').textContent = t('jsonMode');
  document.getElementById('apiKeysTitle').textContent = t('apiKeysTitle');
  document.getElementById('newKey').placeholder = t('newKeyPlaceholder');
  document.getElementById('addBtn').textContent = t('addBtn');
}

function toggleLang() {
  lang = lang === 'zh' ? 'en' : 'zh';
  applyLang();
  if (adminKey) load();
}

function showToast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast ' + type + ' show';
  setTimeout(() => { el.className = 'toast'; }, 2000);
}

async function api(method, path, body) {
  const opts = { method, headers: { 'Authorization': 'Bearer ' + adminKey, 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch('/admin' + path, opts);
  if (r.status === 401) {
    adminKey = '';
    showLogin();
    return null;
  }
  return r.json();
}

async function checkInit() {
  const r = await fetch('/admin/init-status');
  const data = await r.json();
  if (!data.initialized) {
    showInit();
  } else {
    showLogin();
  }
}

function showInit() {
  document.getElementById('initOverlay').style.display = 'flex';
  document.getElementById('loginOverlay').style.display = 'none';
  document.getElementById('mainContent').style.display = 'none';
}

function showLogin() {
  document.getElementById('initOverlay').style.display = 'none';
  document.getElementById('loginOverlay').style.display = 'flex';
  document.getElementById('mainContent').style.display = 'none';
}

function showMain() {
  document.getElementById('initOverlay').style.display = 'none';
  document.getElementById('loginOverlay').style.display = 'none';
  document.getElementById('mainContent').style.display = 'block';
}

async function doInit() {
  const key = document.getElementById('initKey').value;
  const confirm = document.getElementById('initKeyConfirm').value;
  if (key !== confirm) {
    showToast(t('initMismatch'), 'error');
    return;
  }
  if (key.length < 4) {
    showToast(t('initPlaceholder'), 'error');
    return;
  }
  const r = await fetch('/admin/init', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ admin_key: key })
  });
  if (r.ok) {
    adminKey = key;
    showMain();
    load();
  } else {
    const data = await r.json();
    showToast(data.detail || 'Error', 'error');
  }
}

function login() {
  adminKey = document.getElementById('loginKey').value;
  load();
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
  showMain();
}

function renderKeys(keys) {
  const ul = document.getElementById('keyList');
  if (!keys.length) {
    ul.innerHTML = '<li style="color:#9ca3af;font-size:0.85rem">' + t('noKeys') + '</li>';
    return;
  }
  ul.innerHTML = keys.map(k => '<li><code style="font-size:0.85rem">' + k + '</code><button class="danger" onclick="delKey(\\''+k+'\\')">' + t('deleteBtn') + '</button></li>').join('');
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
  const r = await api('POST', '/config', { toolcall_mode: document.getElementById('toolcallMode').value });
  if (r) showToast(t('saveSuccess'), 'success');
  else showToast(t('saveFail'), 'error');
  load();
}

applyLang();
checkInit();
</script>
</body>
</html>"""


@admin_router.get("/")
async def admin_page():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=ADMIN_HTML)
