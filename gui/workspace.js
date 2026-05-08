/**
 * gui/workspace.js — The Academy
 *
 * Three-panel layout: sidebar (experts/symposia),
 * main conversation area, context panel (evidence/sources/synthesis).
 *
 * A "session" is the top-level entity — one panel of experts, their
 * knowledge pools, symposia, and messages.
 */

// ── Global state ────────────────────────────────────────────────────────────

const API = '/api';
let _sessionId = null;
let _session = null;        // full session JSON from GET /api/sessions/{id}
let _activeExpert = null;   // {id, name, discipline, ...}
let _activeSymposium = null;
let _activeContextTab = 'evidence';
let _avatarPool = [];
let _expertAvatars = {};    // expert_id → avatarDef
let _expertAccents = {};    // expert_id → accent color class

const ACCENT_COLORS = ['gold', 'terracotta', 'olive', 'indigo', 'berry'];

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  _avatarPool = generateAvatarPool();
  showSessionList();
});

// ── SSE stream helper ───────────────────────────────────────────────────────

async function streamSSE(url, options, onEvent) {
  const resp = await fetch(url, options);
  if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buf += decoder.decode(value, {stream: true});
    const lines = buf.split('\n');
    buf = '';
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        buf = line + '\n';
      } else if (line.startsWith('data: ') && buf) {
        const et = buf.replace('event: ', '').trim();
        const ds = line.replace('data: ', '').trim();
        buf = '';
        try { onEvent(et, JSON.parse(ds)); } catch(e) {}
      }
    }
  }
}

// ── Session List ────────────────────────────────────────────────────────────

async function showSessionList() {
  _sessionId = null; _activeExpert = null; _activeSymposium = null;
  document.getElementById('sidebar-panels').innerHTML = '';
  document.getElementById('sidebar-symposia').innerHTML = symposiaPlaceholder();
  document.getElementById('sidebar-ws-name').textContent = 'Select a session';
  document.getElementById('input-bar').style.display = 'none';
  hideContextPanel();

  const resp = await fetch(`${API}/sessions`);
  const list = await resp.json();
  let html = '<div class="ws-list"><h2>The Academy</h2>';
  html += '<p class="subtitle">Select a session or create a new one.</p>';
  if (list && list.length) {
    list.forEach(s => {
      html += `<div class="ws-card" onclick="loadSession('${s.id}')">
        <div><div class="ws-card-name">${esc(s.id)}</div>
        <div class="ws-card-meta">Updated ${s.updated_at || ''}</div></div>
        <span style="color:var(--text-dim);font-size:20px;">→</span></div>`;
    });
  } else {
    html += '<p style="color:var(--text-dim);padding:20px 0;">No sessions yet.</p>';
  }
  html += '<button class="ws-create-btn" onclick="showNewSessionModal()">+ New Session</button></div>';
  document.getElementById('main-content').innerHTML = html;
}

async function loadSession(id) {
  _sessionId = id;
  await refreshSessionData();
  document.getElementById('sidebar-ws-name').textContent = `Session · ${id}`;
  assignExpertAttributes();
  renderSidebar();
  renderSymposiaList();
  showEmptyState();
}

async function refreshSessionData() {
  if (!_sessionId) return;
  const resp = await fetch(`${API}/sessions/${_sessionId}`);
  _session = await resp.json();
}

// ── Expert attributes ───────────────────────────────────────────────────────

function assignExpertAttributes() {
  if (!_session?.experts) return;
  let ci = 0;
  _session.experts.forEach(expert => {
    if (expert.id in _expertAvatars) {
      if (_avatarPool.find(a => a.id === _expertAvatars[expert.id].id)) return;
    }
    const av = randomAvatar(_avatarPool);
    _expertAvatars[expert.id] = {
      id: av.id, style: av.style, designIdx: av.designIdx,
      skinIdx: av.skinIdx, hairIdx: av.hairIdx,
      goldIdx: av.goldIdx || 0, robeIdx: av.robeIdx || 0, capIdx: av.capIdx || 0,
    };
    _expertAccents[expert.id] = ACCENT_COLORS[ci % ACCENT_COLORS.length];
    ci++;
  });
}

// ── Sidebar ─────────────────────────────────────────────────────────────────

function renderSidebar() {
  if (!_session?.experts) return;
  let html = `<div class="panel-group">
    <div class="panel-group-header">
      <span class="collapse-icon">▼</span>${esc(_session.name || _session.id)}
      <span style="margin-left:auto;font-size:10px;color:var(--text-dim);cursor:pointer;"
        onclick="conveneSymposium()" title="Convene Symposium">⚡</span>
    </div>`;
  _session.experts.forEach(expert => {
    const active = _activeExpert?.id === expert.id ? ' active' : '';
    html += `<div class="expert-item${active}" onclick="selectExpert('${expert.id}')">
      <div class="avatar-wrap" id="av-sidebar-${expert.id}"></div>
      <div class="expert-info">
        <div class="expert-name">${esc(expert.name)}</div>
        <div class="expert-discipline">${esc(expert.discipline)}</div>
      </div>
      <div class="expert-accent-dot" style="background:var(--${_expertAccents[expert.id] || 'gold'})"></div>
    </div>`;
  });
  html += '</div>';
  document.getElementById('sidebar-panels').innerHTML = html;
  _session.experts.forEach(e => setTimeout(() => renderSidebarAvatar(e.id), 10));
}

function renderSidebarAvatar(expertId) {
  const wrap = document.getElementById(`av-sidebar-${expertId}`);
  if (!wrap) return;
  const av = _expertAvatars[expertId];
  if (!av) return;
  wrap.innerHTML = '';
  wrap.appendChild(createAvatarElement(av, 36));
}

function symposiaPlaceholder() {
  return '<span style="font-size:12px;color:var(--text-dim)">No symposia yet</span>';
}

function renderSymposiaList() {
  if (!_session?.symposia) return;
  const el = document.getElementById('sidebar-symposia');
  if (!_session.symposia.length) { el.innerHTML = symposiaPlaceholder(); return; }
  el.innerHTML = _session.symposia.map(s => `
    <div class="symposium-item" onclick="selectSymposium('${s.id}')">
      <span>⚡</span><span>${esc(s.title || s.id)}</span>
      ${s.has_synthesis ? '<span style="margin-left:auto;font-size:10px;color:var(--olive);">✓</span>' : ''}
    </div>`).join('');
}

// ── Expert Selection ────────────────────────────────────────────────────────

function selectExpert(expertId) {
  const expert = findExpert(expertId);
  if (!expert) return;
  _activeExpert = expert; _activeSymposium = null;
  renderSidebar();
  renderConversationHeader(expert);
  renderConversation(expert);
  document.getElementById('input-bar').style.display = 'flex';
  showContextPanel();
  renderContextPanel(expert, _activeContextTab);
}

function findExpert(expertId) {
  if (!_session?.experts) return null;
  return _session.experts.find(e => e.id === expertId) || null;
}

// ── Conversation ────────────────────────────────────────────────────────────

function renderConversationHeader(expert) {
  const av = _expertAvatars[expert.id];
  const main = document.getElementById('main-content');
  main.innerHTML = `
    <div class="main-header">
      <div class="avatar-wrap" id="header-avatar-wrap"></div>
      <div class="header-info">
        <div class="header-name">${esc(expert.name)}</div>
        <div class="header-discipline">${esc(expert.discipline)} · ${esc(expert.bias || '')}</div>
      </div>
      <div class="main-header-actions">
        <button class="header-action-btn" onclick="showAddSourceModal()">+ Source</button>
        <button class="header-action-btn" onclick="showContextPanel()">☰ Context</button>
      </div>
    </div><div id="conversation"></div>`;
  if (av) {
    const wrap = document.getElementById('header-avatar-wrap');
    wrap.appendChild(createAvatarElement(av, 44));
  }
}

let _abortCtrl = null;  // AbortController for cancelling SSE streams

function renderConversation(expert) {
  const conv = document.getElementById('conversation');
  if (!conv) return;
  conv.innerHTML = '';

  // Load existing messages for this expert (direct conversations, not symposia)
  const msgs = (_session?.messages || []).filter(
    m => m.agent_id === expert.id && !m.symposium_id
  );
  if (msgs.length) {
    msgs.forEach(m => {
      const accent = _expertAccents[expert.id] || 'gold';
      appendMessage(m.role, m.role==='user'?'You':(m.agent_name||expert.name), m.content, accent, m.turn);
    });
  } else {
    conv.innerHTML = `<div class="empty-state"><div class="empty-icon">📜</div>
      <h2>${esc(expert.name)} awaits your inquiry</h2>
      <p>Ask a question grounded in their discipline.</p></div>`;
  }
}

async function sendMessage() {
  const input = document.getElementById('msg-input');
  const msg = input.value.trim();
  if (!msg || !_activeExpert) return;
  if (_abortCtrl) { _abortCtrl.abort(); _abortCtrl = null; }

  input.value = ''; input.disabled = true;
  const sendBtn = document.getElementById('send-btn');
  sendBtn.disabled = true;
  // Show stop button
  const stopBtn = document.getElementById('stop-btn');
  if (stopBtn) stopBtn.style.display = '';

  const conv = document.getElementById('conversation');
  const empty = conv.querySelector('.empty-state');
  if (empty) empty.remove();
  appendMessage('user', 'You', msg);
  const typing = appendTypingIndicator(_activeExpert.name);
  const tid = toast(`${_activeExpert.name} is thinking…`, 'loading');

  _abortCtrl = new AbortController();
  try {
    await streamSSE(
      `${API}/sessions/${_sessionId}/experts/${_activeExpert.id}/message`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:msg}), signal: _abortCtrl.signal },
      (et, data) => {
        if (et === 'message') {
          if (typing) typing.remove();
          dismissToast(tid);
          appendMessage('agent', data.name, data.content, _expertAccents[_activeExpert?.id] || 'gold', data.turn);
          toast(`${data.name} responded`, 'success');
        }
      }
    );
  } catch(e) {
    if (typing) typing.remove(); dismissToast(tid);
    if (e.name === 'AbortError') {
      toast('Generation stopped', 'info');
    } else {
      appendMessage('system', '', `Error: ${e.message}`);
      toast('Failed', 'error');
    }
  }
  _abortCtrl = null;
  input.disabled = false; sendBtn.disabled = false;
  if (stopBtn) stopBtn.style.display = 'none';
  input.focus();
  // Silently refresh session data (don't touch the UI)
  refreshSessionData();
}

function cancelGeneration() {
  if (_abortCtrl) { _abortCtrl.abort(); _abortCtrl = null; }
}

function appendMessage(role, name, content, accentClass, turn) {
  const conv = document.getElementById('conversation');
  if (!conv) return;
  const div = document.createElement('div');
  div.className = `message ${role}`;
  if (accentClass && role === 'agent') div.classList.add(`msg-accent-${accentClass}`);

  const turnLbl = turn ? ` <span style="font-size:10px;color:var(--text-dim)">Turn ${turn}</span>` : '';
  const hdr = `<div class="msg-header"><strong>${esc(name)}</strong>${turnLbl}</div>`;
  const body = role === 'agent' ? preprocessMarkdown(content) : esc(content);

  // Avatar wrapper
  let avWrap = document.createElement('div');
  avWrap.className = 'msg-avatar';
  if (role === 'agent' && _activeExpert) {
    const av = _expertAvatars[_activeExpert.id];
    if (av) avWrap.appendChild(createAvatarElement(av, 34));
  } else if (role === 'user') {
    avWrap.style.cssText = 'background:var(--gold-bg);display:flex;align-items:center;justify-content:center;';
    avWrap.textContent = '👤';
  }

  // Message body
  const bodyDiv = document.createElement('div');
  bodyDiv.className = 'msg-body';
  bodyDiv.innerHTML = `${hdr}<div class="msg-bubble">${marked.parse(body)}</div>`;

  // Assemble
  if (role === 'user') {
    div.appendChild(bodyDiv);
    div.appendChild(avWrap);
  } else {
    div.appendChild(avWrap);
    div.appendChild(bodyDiv);
  }
  conv.appendChild(div);
  conv.scrollTop = conv.scrollHeight;
}

function appendTypingIndicator(name) {
  const conv = document.getElementById('conversation');
  if (!conv) return null;
  const div = document.createElement('div');
  div.className = 'typing-indicator';
  div.innerHTML = `${esc(name)} is thinking <span class="typing-dots"><span></span><span></span><span></span></span>`;
  conv.appendChild(div); conv.scrollTop = conv.scrollHeight;
  return div;
}

function preprocessMarkdown(md) {
  return md.replace(/\*\*Keywords:\*\*\s*(.+?)(?:\n|$)/, (_, kw) =>
    '<div class="keyword-row">' + kw.split(',').map(k => `<span class="keyword-chip">${esc(k.trim())}</span>`).join('') + '</div>'
  );
}

// ── Knowledge Pool ──────────────────────────────────────────────────────────

function showAddSourceModal() {
  if (!_activeExpert) return;
  showModal(`<h3>Add Source</h3><p>Add a URL to <strong>${esc(_activeExpert.name)}</strong>'s pool.</p>
    <input id="modal-src-url" placeholder="URL (https://…)"><input id="modal-src-title" placeholder="Title">
    <textarea id="modal-src-snippet" placeholder="Snippet or key quote…" rows="3" style="resize:vertical;"></textarea>
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="addSource()">Add to Pool</button></div>`);
}

async function addSource() {
  const url = document.getElementById('modal-src-url').value.trim();
  const title = document.getElementById('modal-src-title').value.trim();
  const snippet = document.getElementById('modal-src-snippet').value.trim();
  if (!url && !snippet) { toast('Enter a URL or snippet', 'error'); return; }
  closeModal(); toast('Adding source…', 'success');
  await fetch(`${API}/sessions/${_sessionId}/experts/${_activeExpert.id}/sources`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({url, title, snippet, enrich:!!url}),
  });
  toast('Source added', 'success');
  renderContextPanel(_activeExpert, 'sources');
}

function showUploadModal() {
  if (!_activeExpert) return;
  showModal(`<h3>Upload File</h3><p>Upload a PDF or text file to <strong>${esc(_activeExpert.name)}</strong>'s pool.</p>
    <input type="file" id="modal-upload-file" accept=".pdf,.txt,.md,.csv,.html" style="margin-bottom:12px;">
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="uploadFile()">Upload</button></div>`);
}

async function uploadFile() {
  const fi = document.getElementById('modal-upload-file');
  const file = fi?.files?.[0];
  if (!file) { toast('Select a file', 'error'); return; }
  closeModal(); toast(`Uploading ${file.name}…`, 'success');
  const fd = new FormData(); fd.append('file', file);
  try {
    const resp = await fetch(`${API}/sessions/${_sessionId}/experts/${_activeExpert.id}/upload`, { method:'POST', body:fd });
    if (!resp.ok) { const e = await resp.json(); toast(e.detail||'Upload failed','error'); return; }
    const data = await resp.json();
    toast(`Uploaded — ${data.size} chars`, 'success');
    renderContextPanel(_activeExpert, 'sources');
  } catch(e) { toast('Upload failed: '+e.message, 'error'); }
}

async function formOpinionForExpert() {
  if (!_activeExpert) return;
  toast('Forming opinion…', 'success');
  await streamSSE(
    `${API}/sessions/${_sessionId}/experts/${_activeExpert.id}/opinion`,
    { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:_session?.query||''}) },
    (et, data) => {
      if (et === 'opinion_ready') { toast('Opinion formed!', 'success'); renderContextPanel(_activeExpert, 'sources'); }
      else if (et === 'error') toast(data.message, 'error');
    }
  );
}

// ── Context Panel ───────────────────────────────────────────────────────────

function showContextPanel() { document.getElementById('context-panel').classList.remove('collapsed'); }
function hideContextPanel() { document.getElementById('context-panel').classList.add('collapsed'); }
function switchContextTab(tab, btn) {
  _activeContextTab = tab;
  document.querySelectorAll('.context-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  if (_activeExpert) renderContextPanel(_activeExpert, tab);
}

async function renderContextPanel(expert, tab = 'evidence') {
  // Sync tab button highlights
  document.querySelectorAll('.context-tab').forEach(b => {
    b.classList.toggle('active', b.textContent.trim().toLowerCase().startsWith(tab));
  });

  const content = document.getElementById('context-content');
  if (!content) return;

  if (tab === 'sources') {
    try {
      const resp = await fetch(`${API}/sessions/${_sessionId}/experts/${expert.id}/pool`);
      const pool = await resp.json();
      let html = '<div style="display:flex;gap:8px;margin-bottom:12px;">';
      html += '<button class="sidebar-btn" style="flex:1;" onclick="showAddSourceModal()">+ Add URL</button>';
      html += '<button class="sidebar-btn" style="flex:1;" onclick="showUploadModal()">📄 Upload</button>';
      html += '<button class="sidebar-btn" style="flex:1;" onclick="formOpinionForExpert()">💡 Opinion</button></div>';
      if (!pool?.sources?.length && !pool?.opinions?.length)
        html += '<p style="font-size:12px;color:var(--text-dim)">No sources yet.</p>';
      if (pool?.sources?.length) {
        html += '<div style="font-size:11px;font-weight:600;color:var(--text-muted);margin-bottom:6px;">Sources</div>';
        html += pool.sources.map(s => `<div class="mini-claim-card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-weight:600;font-size:12px;">${esc(s.title||s.url||'Untitled')}</span>
            ${statusBadge(s.verification_status)}</div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:4px;">${esc((s.snippet||s.full_text_preview||'').substring(0,180))}</div>
          ${s.url?`<div style="font-size:10px;color:var(--gold);margin-top:4px;word-break:break-all;">→ ${esc(s.url)}</div>`:''}
        </div>`).join('');
      }
      if (pool?.opinions?.length) {
        html += '<div style="font-size:11px;font-weight:600;color:var(--text-muted);margin:10px 0 6px;">Opinions</div>';
        html += pool.opinions.map(o => `<div class="mini-claim-card" style="border-left:3px solid var(--indigo);">
          <div style="font-size:12px;line-height:1.5;">${esc(o.text)}</div>
          <div style="font-size:10px;color:var(--text-dim);margin-top:4px;">Cites ${o.source_ids?.length||0} sources</div></div>`).join('');
      }
      content.innerHTML = html;
    } catch(e) { content.innerHTML = '<p style="font-size:12px;color:var(--text-dim)">Could not load pool.</p>'; }
  } else if (tab === 'synthesis') {
    content.innerHTML = _activeSymposium
      ? '<p style="font-size:12px;color:var(--text-dim);">Run a debate round then synthesize.</p>'
      : '<p style="font-size:12px;color:var(--text-dim);">Select a symposium to see synthesis.</p>';
  } else {
    content.innerHTML = '<p style="font-size:12px;color:var(--text-dim);">Evidence appears during symposia.</p>';
  }
}

function statusBadge(s) {
  if (!s) return '<span class="badge-mini unverifiable">pending</span>';
  const m = {verified:'verified',misattributed:'misattributed',unverifiable:'unverifiable'};
  return `<span class="badge-mini ${m[s]||'unverifiable'}">${s}</span>`;
}

// ── Symposium ───────────────────────────────────────────────────────────────

function conveneSymposium() {
  if (!_sessionId || !_session?.experts) return;
  showModal(`<h3>Convene Symposium</h3><p>Structured debate with all experts.</p>
    <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">
    ${_session.experts.map(e => `<div>• ${esc(e.name)} (${esc(e.discipline)})</div>`).join('')}</div>
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="createAndStartSymposium()">Begin</button></div>`);
}

async function createAndStartSymposium() {
  closeModal(); toast('Creating symposium…', 'success');
  const resp = await fetch(`${API}/sessions/${_sessionId}/symposia`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({title:`Debate: ${_session.query||''}`, format:'structured'}),
  });
  const sym = await resp.json();
  _activeSymposium = sym.symposium_id; _activeExpert = null;
  await refreshSessionData();
  document.getElementById('input-bar').style.display = 'none';
  document.getElementById('main-content').innerHTML = `
    <div class="main-header"><div style="font-size:24px;">⚡</div>
      <div class="header-info"><div class="header-name">Symposium</div>
      <div class="header-discipline">Structured · ${sym.participants?.length||0} experts</div></div>
      <div class="main-header-actions">
        <button class="header-action-btn" onclick="runSymposiumRound()" id="btn-run-round">▶ Run Round</button>
        <button class="header-action-btn" onclick="synthesizeSymposium()" id="btn-synthesize" style="display:none;">📋 Synthesize</button>
      </div></div>
    <div id="conversation"><div class="empty-state"><div class="empty-icon">🏛️</div><h2>The Council convenes</h2>
    <p>Click "Run Round" to begin.</p></div></div>`;
  showContextPanel();
}

function selectSymposium(symId) {
  _activeSymposium = symId; _activeExpert = null;
  const sym = _session.symposia.find(s => s.id === symId);
  if (!sym) return;
  renderSidebar();
  document.getElementById('input-bar').style.display = 'none';
  document.getElementById('main-content').innerHTML = `
    <div class="main-header"><div style="font-size:24px;">⚡</div>
      <div class="header-info"><div class="header-name">${esc(sym.title||sym.id)}</div>
      <div class="header-discipline">${sym.format} · ${sym.participant_ids?.length||0} experts · ${sym.message_count||0} msgs</div></div>
      <div class="main-header-actions">
        <button class="header-action-btn" onclick="runSymposiumRound()" id="btn-run-round">▶ Run Round</button>
        <button class="header-action-btn" onclick="synthesizeSymposium()" id="btn-synthesize" ${sym.has_synthesis?'':'style="display:none;"'}>📋 Synthesize</button>
      </div></div>
    <div id="conversation"><div class="empty-state"><div class="empty-icon">🏛️</div><h2>Symposium</h2><p>Run a round to see the debate.</p></div></div>`;
  showContextPanel();
}

async function runSymposiumRound() {
  if (!_activeSymposium) return;
  const btn = document.getElementById('btn-run-round');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Running…'; }
  const conv = document.getElementById('conversation');
  const empty = conv?.querySelector('.empty-state');
  if (empty) empty.remove();
  if (conv) conv.innerHTML = '';
  let ct = null;
  let tid = toast('Symposium round starting…', 'loading');
  try {
    await streamSSE(
      `${API}/sessions/${_sessionId}/symposia/${_activeSymposium}/round`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' },
      (et, data) => {
        if (et === 'typing') {
          if (ct) ct.remove();
          ct = appendTypingIndicator(data.name);
          highlightSpeaker(data.name);
          updateToast(tid, `${data.name} is speaking…`, 'loading');
        } else if (et === 'message') {
          if (ct) ct.remove(); ct = null;
          appendMessage('agent', data.name, data.content, _expertAccents[findExpertIdByName(data.name)]||'gold', data.turn);
        } else if (et === 'round_complete') {
          dismissToast(tid);
          toast(`Round complete — ${data.turns} turns`, 'success');
          const sb = document.getElementById('btn-synthesize');
          if (sb) sb.style.display = '';
        }
      }
    );
  } catch(e) {
    if (ct) ct.remove(); dismissToast(tid);
    appendMessage('system', '', `Error: ${e.message}`);
    toast('Round failed', 'error');
  }
  if (btn) { btn.disabled = false; btn.textContent = '▶ Run Round'; }
  await refreshSessionData();
}

function highlightSpeaker(name) {
  document.querySelectorAll('.expert-item').forEach(el => {
    const nm = el.querySelector('.expert-name');
    if (nm && nm.textContent === name) { el.style.background = 'var(--bg-card)'; setTimeout(()=>el.style.background='',1500); }
  });
}

function findExpertIdByName(name) {
  if (!_session?.experts) return null;
  return _session.experts.find(e => e.name === name)?.id || null;
}

async function synthesizeSymposium() {
  if (!_activeSymposium) return;
  const tid = toast('Rapporteur is synthesizing…', 'loading');
  const btn = document.getElementById('btn-synthesize');
  if (btn) { btn.disabled = true; btn.textContent = '⏳…'; }
  try {
    await streamSSE(
      `${API}/sessions/${_sessionId}/symposia/${_activeSymposium}/synthesize`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' },
      (et, data) => {
        if (et==='message') {
          dismissToast(tid);
          appendMessage('agent','Rapporteur',data.content,'gold');
          toast('Synthesis complete!','success');
        }
      }
    );
  } catch(e) { dismissToast(tid); toast('Failed: '+e.message,'error'); }
  if (btn) { btn.disabled=false; btn.textContent='📋 Synthesize'; }
  await refreshSessionData();
}

// ── Modals ──────────────────────────────────────────────────────────────────

function showNewSessionModal() {
  showModal(`<h3>New Session</h3><p>Create a new research session.</p>
    <input id="modal-ws-query" placeholder="Research question or topic (optional)…">
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="createSession()">Create</button></div>`);
}

async function createSession() {
  const query = document.getElementById('modal-ws-query').value.trim();
  closeModal();
  await fetch(`${API}/sessions`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query}) });
  toast('Session created', 'success');
  showSessionList();
}

function showAddExpertsModal() {
  if (!_sessionId) { toast('Load a session first', 'error'); return; }
  showModal(`<h3>Add Experts</h3><p>The Moderator will research and propose experts.</p>
    <input id="modal-panel-query" placeholder="Research question…">
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="addExperts()">Propose Experts</button></div>`);
}

async function addExperts() {
  const query = document.getElementById('modal-panel-query').value.trim();
  if (!query) { toast('Enter a research question', 'error'); return; }
  closeModal(); toast('Moderator is researching…', 'success');
  const resp = await fetch(`${API}/sessions/${_sessionId}/panels`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query, max_experts:3}),
  });
  const data = await resp.json();
  await refreshSessionData();
  toast(`Experts added: ${data.experts?.length||0}`, 'success');
}

function showModal(html) {
  const o = document.getElementById('modal-overlay');
  o.innerHTML = `<div class="modal">${html}</div>`;
  o.style.display = 'flex';
  o.onclick = e => { if (e.target===o) closeModal(); };
}
function closeModal() { document.getElementById('modal-overlay').style.display = 'none'; }

// ── Helpers ─────────────────────────────────────────────────────────────────

function showEmptyState() {
  document.getElementById('main-content').innerHTML = `<div class="empty-state"><div class="empty-icon">🏛️</div>
    <h2>Welcome to The Academy</h2><p>Select an expert or add experts to begin.</p></div>`;
}

function handleInputKey(e) { if (e.key==='Enter'&&!e.shiftKey) { e.preventDefault(); sendMessage(); } }

function esc(s) { if (!s) return ''; const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

let _toastCounter = 0;

function toast(msg, type) {
  const id = `toast-${++_toastCounter}`;
  const c = document.getElementById('toasts');
  const el = document.createElement('div');
  el.id = id;
  el.className = `toast ${type}`;

  const icon = {loading:'⏳', success:'✓', error:'✗', info:'ℹ'}[type] || '';
  const spinner = type === 'loading' ? '<span class="toast-spinner"></span>' : '';

  el.innerHTML = `<span class="toast-icon">${spinner}${icon}</span>
    <span class="toast-msg">${esc(msg)}</span>
    <button class="toast-close" onclick="dismissToast('${id}')">×</button>`;

  c.appendChild(el);

  // Only auto-dismiss success after 5s; loading/info/error persist
  if (type === 'success') {
    setTimeout(() => { if (document.getElementById(id)) el.remove(); }, 5000);
  }

  return id;
}

function dismissToast(id) {
  const el = document.getElementById(id);
  if (el) { el.style.animation = 'toastOut 0.2s ease forwards'; setTimeout(() => el.remove(), 200); }
}

function updateToast(id, msg, type) {
  const el = document.getElementById(id);
  if (!el) return toast(msg, type);
  const icon = {loading:'⏳', success:'✓', error:'✗', info:'ℹ'}[type] || '';
  const spinner = type === 'loading' ? '<span class="toast-spinner"></span>' : '';
  el.className = `toast ${type}`;
  el.querySelector('.toast-icon').innerHTML = spinner + icon;
  el.querySelector('.toast-msg').textContent = msg;
  if (type === 'success') {
    setTimeout(() => { if (document.getElementById(id)) el.remove(); }, 5000);
  }
}
