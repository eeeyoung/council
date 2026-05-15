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
let _session = null;        // full session JSON from GET /api/session
let _activeExpert = null;   // {id, name, discipline, ...}
let _activeSymposium = null;
let _activeContextTab = 'library';
let _avatarPool = [];
let _expertAvatars = {};    // expert_id → avatarDef
let _expertAccents = {};    // expert_id → accent color class
let _expertPanelMap = {};   // expert_id → panel_id
let _collapsedPanels = new Set();  // panel indices that are collapsed
let _panelEditMode = false;

// Restore collapse state from sessionStorage
try {
  const saved = sessionStorage.getItem('council_collapsed_panels');
  if (saved) _collapsedPanels = new Set(JSON.parse(saved));
} catch (_) {}
let _symposiumMessages = {}; // symposium_id → [{role, name, content, turn, accent}]
let _symposiumTyping = {};   // symposium_id → {name, discipline} — current speaker

// Load persisted symposium state from sessionStorage on init
try {
    const saved = sessionStorage.getItem('council_ws_sym_messages');
    if (saved) _symposiumMessages = JSON.parse(saved);
    const savedTyping = sessionStorage.getItem('council_ws_sym_typing');
    if (savedTyping) _symposiumTyping = JSON.parse(savedTyping);
} catch (_) {}

function _persistSymState() {
    try {
        sessionStorage.setItem('council_ws_sym_messages', JSON.stringify(_symposiumMessages));
        sessionStorage.setItem('council_ws_sym_typing', JSON.stringify(_symposiumTyping));
    } catch (_) {}
}

const ACCENT_COLORS = ['gold', 'terracotta', 'olive', 'indigo', 'berry'];

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  _avatarPool = generateAvatarPool();
  initApp().catch(e => {
    console.error('initApp failed:', e);
    document.getElementById('main-content').innerHTML =
      `<div class="empty-state"><div class="empty-icon">⚠️</div>
       <h2>Failed to load</h2><p style="color:var(--terracotta);">${esc(e.message)}</p></div>`;
  });
});

// ── Init ────────────────────────────────────────────────────────────────────

async function initApp() {
  _activeExpert = null;
  _activeSymposium = null;
  await refreshSessionData();
  assignExpertAttributes();
  hydrateSymposiumMessages();
  document.getElementById('sidebar-ws-name').textContent = 'COUNCIL Workspace';
  renderSidebar();
  renderSymposiaList();
  showEmptyState();
}

function hydrateSymposiumMessages() {
  if (!_session?.messages) return;
  for (const m of _session.messages) {
    if (!m.symposium_id) continue;
    if (!_symposiumMessages[m.symposium_id]) _symposiumMessages[m.symposium_id] = [];
    const expertId = findExpertIdByName(m.agent_name);
    _symposiumMessages[m.symposium_id].push({
      role: m.role,
      name: m.agent_name,
      content: m.content,
      accent: expertId ? (_expertAccents[expertId] || 'gold') : 'gold',
      turn: m.turn,
    });
  }
  _persistSymState();
}

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

async function refreshSessionData() {
  const resp = await fetch(`${API}/session`);
  if (!resp.ok) throw new Error(`Server returned ${resp.status}`);
  _session = await resp.json();
  if (!_session || !_session.panels) throw new Error('Session missing panels');
}

// ── Expert attributes ───────────────────────────────────────────────────────

function assignExpertAttributes() {
  if (!_session?.panels) return;
  _expertPanelMap = {};
  let ci = 0;
  for (const panel of _session.panels) {
    for (const expert of (panel.experts || [])) {
      _expertPanelMap[expert.id] = panel.id;
      if (expert.id in _expertAvatars) {
        if (_avatarPool.find(a => a.id === _expertAvatars[expert.id].id)) continue;
      }
      const av = randomAvatar(_avatarPool);
      _expertAvatars[expert.id] = {
        id: av.id, style: av.style, designIdx: av.designIdx,
        skinIdx: av.skinIdx, hairIdx: av.hairIdx,
        goldIdx: av.goldIdx || 0, robeIdx: av.robeIdx || 0, capIdx: av.capIdx || 0,
      };
      _expertAccents[expert.id] = ACCENT_COLORS[ci % ACCENT_COLORS.length];
      ci++;
    }
  }
}

// ── Sidebar ─────────────────────────────────────────────────────────────────

function renderSidebar() {
  if (!_session?.panels) return;
  let html = '';
  _session.panels.forEach((panel, pi) => {
    const collapsed = _collapsedPanels.has(pi);
    html += `<div class="panel-group">
      <div class="panel-group-header" onclick="togglePanel(${pi})" style="cursor:pointer;">
        <span class="collapse-icon">${collapsed ? '▶' : '▼'}</span>${esc(truncate(panel.name || 'Panel ' + (pi+1), 50))}
        <span style="margin-left:auto;font-size:10px;color:var(--text-dim);">${(panel.experts||[]).length} experts</span>
        ${_panelEditMode ? `<span onclick="event.stopPropagation();removePanel('${panel.id}')" style="cursor:pointer;margin-left:4px;color:var(--terracotta);font-size:12px;opacity:0.7;" title="Remove panel">✕</span>` : ''}
        <span onclick="event.stopPropagation();togglePanelEditMode()" style="cursor:pointer;margin-left:6px;font-size:12px;opacity:0.4;${_panelEditMode?'color:var(--terracotta);':''}" title="${_panelEditMode?'Done editing':'Edit panels'}">${_panelEditMode ? '✓' : '✎'}</span>
      </div>
      <div class="panel-experts" id="panel-${pi}-experts" style="${collapsed ? 'display:none' : ''}">`;
    (panel.experts || []).forEach(expert => {
      const active = _activeExpert?.id === expert.id ? ' active' : '';
      html += `<div class="expert-item${active}" onclick="event.stopPropagation();selectExpert('${expert.id}')">
        <div class="avatar-wrap" id="av-sidebar-${expert.id}"></div>
        <div class="expert-info">
          <div class="expert-name">${esc(expert.name)}</div>
          <div class="expert-discipline">${esc(expert.discipline)}</div>
        </div>
        <div class="expert-accent-dot" style="background:var(--${_expertAccents[expert.id] || 'gold'})"></div>
      </div>`;
    });
    html += '</div></div>';
  });
  document.getElementById('sidebar-panels').innerHTML = html;
  // Render avatars for all experts
  _session.panels.forEach(panel => (panel.experts || []).forEach(e => setTimeout(() => renderSidebarAvatar(e.id), 10)));
}

function togglePanel(pi) {
  const el = document.getElementById(`panel-${pi}-experts`);
  if (!el) return;
  const hidden = el.style.display === 'none';
  el.style.display = hidden ? '' : 'none';
  const header = el.parentElement.querySelector('.collapse-icon');
  if (header) header.textContent = hidden ? '▼' : '▶';
  // Persist collapse state
  if (hidden) {
    _collapsedPanels.delete(pi);
  } else {
    _collapsedPanels.add(pi);
  }
  try { sessionStorage.setItem('council_collapsed_panels', JSON.stringify([..._collapsedPanels])); } catch (_) {}
}

function togglePanelEditMode() {
  _panelEditMode = !_panelEditMode;
  renderSidebar();
}

async function removePanel(panelId) {
  const panel = _session.panels.find(p => p.id === panelId);
  if (!panel) return;
  if (!confirm(`Remove panel "${panel.name || panelId}" and all its experts?`)) return;

  // Clear expert mappings for this panel's experts
  for (const expert of (panel.experts || [])) {
    delete _expertAvatars[expert.id];
    delete _expertAccents[expert.id];
    delete _expertPanelMap[expert.id];
  }

  // Remove from local session state
  _session.panels = _session.panels.filter(p => p.id !== panelId);

  // Persist to server
  try {
    await fetch(`${API}/panels/${panelId}`, { method: 'DELETE' });
  } catch (_) {}

  // If the removed panel contained the active expert, clear it
  if (_activeExpert && !findExpert(_activeExpert.id)) {
    _activeExpert = null;
    showEmptyState();
  }
  renderSidebar();
  toast('Panel removed', 'success');
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
  let html = '';
  if (_session.symposia.length) {
    html += _session.symposia.map(s => `
      <div class="symposium-item" onclick="selectSymposium('${s.id}')">
        <span>⚡</span><span>${esc(truncate(s.title || s.id, 40))}</span>
        ${s.has_synthesis ? '<span style="margin-left:auto;font-size:10px;color:var(--olive);">✓</span>' : ''}
      </div>`).join('');
  } else {
    html += symposiaPlaceholder();
  }
  html += '<button class="sidebar-btn" onclick="conveneSymposium()" style="margin-top:8px;">⚡ Convene Symposium</button>';
  el.innerHTML = html;
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
  renderContextPanel(_activeContextTab);
}

function findExpert(expertId) {
  if (!_session?.panels) return null;
  for (const panel of _session.panels) {
    const e = (panel.experts || []).find(e => e.id === expertId);
    if (e) return e;
  }
  return null;
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
        <div class="header-discipline">${esc(expert.discipline)}</div>
      </div>
      <div class="main-header-actions">
        <button class="header-action-btn" onclick="showAddSourceModal()">+ Source</button>
        <button class="header-action-btn" onclick="showExpertProfileModal()">Profile</button>
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
      `${API}/panels/${_expertPanelMap[_activeExpert.id]}/experts/${_activeExpert.id}/message`,
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
  const bubbleContent = role === 'agent'
    ? _renderStructuredContent(content, name)
    : esc(content);

  // Avatar wrapper
  let avWrap;
  if (role === 'user') {
    avWrap = document.createElement('div');
    avWrap.className = 'msg-avatar';
    avWrap.style.cssText = 'background:var(--gold-bg);display:flex;align-items:center;justify-content:center;';
    avWrap.textContent = '👤';
  } else if (role === 'agent') {
    avWrap = _getExpertAvElement(name, 34);
  } else {
    avWrap = document.createElement('div');
    avWrap.className = 'msg-avatar';
  }

  // Message body
  const bodyDiv = document.createElement('div');
  bodyDiv.className = 'msg-body';
  bodyDiv.innerHTML = `${hdr}<div class="msg-bubble">${bubbleContent}</div>`;

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
  // Lightweight: only converts keywords for expert-chat messages
  return md.replace(/\*\*Keywords:\*\*\s*(.+?)(?:\n|$)/, (_, kw) =>
    '<div class="keyword-row">' + kw.split(',').map(k => `<span class="keyword-chip">${esc(k.trim())}</span>`).join('') + '</div>'
  );
}

// ── Structured message rendering (symposium debate responses) ──────────────

function _renderStructuredContent(md, expertName) {
  // Only apply special formatting if the message has structured sections
  if (!/## Position|### /.test(md)) {
    return marked.parse(md);
  }

  let html = '';
  let cursor = md;

  // ── ## Position → callout bar (always visible, never collapsed) ──
  const posMatch = cursor.match(/## Position\n([\s\S]*?)(?=\n\*\*Keywords:|\n##|\n###|$)/);
  if (posMatch) {
    html += '<div class="position-callout">' + marked.parse(posMatch[0]) + '</div>';
    cursor = cursor.slice(posMatch.index + posMatch[0].length);
  }

  // ── **Keywords:** → chip row ──
  const kwMatch = cursor.match(/\*\*Keywords:\*\*\s*(.+?)(?:\n|$)/);
  if (kwMatch) {
    const chips = kwMatch[1].split(',').map(k =>
      `<span class="keyword-chip">${esc(k.trim())}</span>`
    ).join('');
    html += '<div class="keyword-row">' + chips + '</div>';
    cursor = cursor.slice(kwMatch.index + kwMatch[0].length);
  }

  // ── Remaining ## sections → Notion-style toggle headings ──
  // Split on any ## heading (Evidence, Response to Peers, Opinion, etc.)
  const sections = cursor.split(/\n(?=## )/);
  for (const sec of sections) {
    const trimmed = sec.trim();
    if (!trimmed) continue;

    // Extract the ## heading title
    const headingMatch = trimmed.match(/^## (.+)/m);
    if (!headingMatch) {
      html += marked.parse(trimmed);
      continue;
    }
    const sectionTitle = headingMatch[1].trim();
    const body = trimmed.slice(headingMatch[0].length).trim();

    if (/^Evidence\b/i.test(sectionTitle)) {
      // ── ## Evidence: plain heading + collapsible ### Finding blocks ──
      html += marked.parse('## ' + sectionTitle);

      const findings = body.split(/\n(?=### )/);
      for (const f of findings) {
        const ftitleMatch = f.match(/### ([^\n]+)/);
        if (!ftitleMatch) {
          const t = f.trim();
          if (t) html += marked.parse(t);
          continue;
        }
        const ftitle = ftitleMatch[1].trim();
        const fbody = f.slice(ftitleMatch[0].length).trim();
        const pill = _lookupVerification(fbody, expertName);
        html += '<details class="evidence-item" open>';
        html += '<summary class="evidence-summary">';
        html += '<span class="evidence-title">' + esc(ftitle) + '</span>';
        if (pill) html += '<span class="verification-pill ' + pill.cls + '">' + pill.label + '</span>';
        html += '</summary>';
        html += '<div class="evidence-body">' + marked.parse(fbody) + '</div>';
        html += '</details>';
      }
    } else {
      // ── Other ## sections: collapsible, markdown body ──
      html += '<details class="section-toggle" open>';
      html += '<summary class="section-toggle-summary"><span class="section-toggle-chevron">▶</span>' + esc(sectionTitle) + '</summary>';
      html += '<div class="section-toggle-body">';
      html += marked.parse(body);
      html += '</div></details>';
    }
  }

  return html;
}

function _lookupVerification(sourceMd, expertName) {
  // Try to find a matching source in the expert's knowledge pool
  if (!_session?.experts) return null;
  const expert = findExpert(findExpertIdByName(expertName));
  if (!expert?.knowledge_pool?.sources?.length) return null;

  // Extract the source string from markdown
  const srcMatch = sourceMd.match(/\*\*Source:\*\*\s*(.+?)(?:\n|$)/);
  if (!srcMatch) return null;
  const needle = srcMatch[1].trim();

  const src = expert.knowledge_pool.sources.find(s =>
    (s.url && needle.includes(s.url)) || (s.title && needle.includes(s.title))
  );
  if (!src?.verification_status) return null;

  switch (src.verification_status) {
    case 'verified':      return {cls: 'verified', label: '✓ verified'};
    case 'misattributed': return {cls: 'misattributed', label: '✗ misattributed'};
    default:              return {cls: 'unverified', label: 'unverified'};
  }
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
  await fetch(`${API}/panels/${_expertPanelMap[_activeExpert.id]}/experts/${_activeExpert.id}/sources`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({url, title, snippet, enrich:!!url}),
  });
  toast('Source added', 'success');
  renderContextPanel('library');
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
    const resp = await fetch(`${API}/panels/${_expertPanelMap[_activeExpert.id]}/experts/${_activeExpert.id}/upload`, { method:'POST', body:fd });
    if (!resp.ok) { const e = await resp.json(); toast(e.detail||'Upload failed','error'); return; }
    const data = await resp.json();
    toast(`Uploaded — ${data.size} chars`, 'success');
    renderContextPanel('library');
  } catch(e) { toast('Upload failed: '+e.message, 'error'); }
}

async function formOpinionForExpert() {
  if (!_activeExpert) return;
  toast('Forming opinion…', 'success');
  await streamSSE(
    `${API}/panels/${_expertPanelMap[_activeExpert.id]}/experts/${_activeExpert.id}/opinion`,
    { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:_session?.query||''}) },
    (et, data) => {
      if (et === 'opinion_ready') { toast('Opinion formed!', 'success'); renderContextPanel('library'); }
      else if (et === 'error') toast(data.message, 'error');
    }
  );
}

let _researchAbortCtrl = null;

function startExpertResearch() {
  if (!_activeExpert) return;
  showModal(`<h3>Auto-Research</h3>
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:16px;">${esc(_activeExpert.name)} will search for sources. The Fact-Checker rejects unverified ones — only verified sources count toward the target.</p>
    <label style="font-size:12px;font-weight:600;">Target verified sources:</label>
    <input id="research-target" type="number" value="3" min="1" max="20" style="width:100%;padding:8px;margin:4px 0 12px;border:1px solid var(--border);border-radius:6px;font-family:var(--font-body);">
    <label style="font-size:12px;font-weight:600;">Time limit (seconds):</label>
    <input id="research-timeout" type="number" value="120" min="10" max="600" style="width:100%;padding:8px;margin:4px 0 12px;border:1px solid var(--border);border-radius:6px;font-family:var(--font-body);">
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="runExpertResearch()">Start</button></div>`);
}

async function runExpertResearch() {
  closeModal();
  const target = parseInt(document.getElementById('research-target')?.value) || 3;
  const timeout = parseInt(document.getElementById('research-timeout')?.value) || 120;
  if (!_activeExpert) return;

  if (_researchAbortCtrl) { _researchAbortCtrl.abort(); }
  _researchAbortCtrl = new AbortController();

  toast(`${_activeExpert.name} is researching…`, 'loading');

  // Render the library tab (if not already visible) so existing sources stay in view
  await renderContextPanel('library');

  // Append progress display at the bottom of the Discovered section
  const progressHtml = `<div id="research-progress" style="text-align:center;padding:14px 0 8px;border-top:1px solid var(--border-light);margin-top:8px;">
    <div class="spinner" style="margin:0 auto 10px;"></div>
    <p style="font-size:13px;color:var(--text-muted);">Searching for sources…</p>
    <p style="font-size:11px;color:var(--text-dim);" id="research-counter">Verified: 0 / ${target}</p>
    <p style="font-size:10px;color:var(--text-dim);" id="research-status"></p>
  </div>`;
  const discovered = document.getElementById('discovered-sources');
  if (discovered) {
    const existing = document.getElementById('research-progress');
    if (existing) existing.remove();
    discovered.insertAdjacentHTML('beforeend', progressHtml);
  }

  try {
    await streamSSE(
      `${API}/panels/${_expertPanelMap[_activeExpert.id]}/experts/${_activeExpert.id}/research`,
      { method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({target_sources:target, time_limit_seconds:timeout}),
        signal: _researchAbortCtrl.signal },
      (et, data) => {
        if (et === 'source_found') {
          const counter = document.getElementById('research-counter');
          const status = document.getElementById('research-status');
          if (counter) counter.textContent = `Verified: ${data.verified_count} / ${data.target} (${data.total_found} found, ${Math.round(data.elapsed)}s)`;
          if (status) {
            const icon = data.status === 'verified' ? '✓' : '✗';
            status.textContent = `${icon} ${data.title ? data.title.substring(0,80) : 'Source'} — ${data.status}`;
          }
          // Append source block to Discovered section in real time
          if (data.source_id) {
            const discoveredList = document.querySelector('#discovered-sources .source-list');
            if (discoveredList) {
              const placeholder = discoveredList.querySelector('p');
              if (placeholder) placeholder.remove();
              const block = _renderSourceBlock({
                id: data.source_id,
                title: data.title,
                url: data.url || '',
                snippet: data.snippet || '',
                source_type: 'url',
                origin: 'discovered',
                verification_status: data.status,
                full_text_preview: '',
              });
              // Avoid duplicates if the same event fires twice
              if (!discoveredList.querySelector(`[data-source-id="${data.source_id}"]`)) {
                discoveredList.insertAdjacentHTML('beforeend', block);
              }
            }
          }
        } else if (et === 'research_complete') {
          toast(`Research done — ${data.verified} verified, ${data.rejected || 0} rejected (${Math.round(data.elapsed)}s)`, 'success');
          if (_activeExpert) renderContextPanel('library');
        }
      }
    );
  } catch(e) {
    if (e.name !== 'AbortError') toast('Research failed: ' + e.message, 'error');
    if (_activeExpert) renderContextPanel('library');
  }
  _researchAbortCtrl = null;
  // Clean up progress bar if still present (e.g. after abort)
  var _rp = document.getElementById('research-progress');
  if (_rp) _rp.remove();
}

// ── Context Panel ───────────────────────────────────────────────────────────

function showContextPanel() { document.getElementById('context-panel').classList.remove('collapsed'); }
function hideContextPanel() { document.getElementById('context-panel').classList.add('collapsed'); }
function _renderContextTabs(tabs, active) {
  var h = '';
  tabs.forEach(function(t) {
    h += '<button class="context-tab' + (t.id === active ? ' active' : '') + '" onclick="switchContextTab(\'' + t.id + '\',this)">' + esc(t.label) + '</button>';
  });
  document.getElementById('context-tabs').innerHTML = h;
}

function switchContextTab(tab, btn) {
  _activeContextTab = tab;
  document.querySelectorAll('.context-tab').forEach(function(b) { return b.classList.remove('active'); });
  if (btn) btn.classList.add('active');
  renderContextPanel(tab);
}

async function renderContextPanel(tabOverride) {
  var content = document.getElementById('context-content');
  if (!content) return;
  var tab = tabOverride || _activeContextTab;

  if (_activeSymposium) {
    // ── Symposium context ──
    var sym = _session.symposia.find(function(s) { return s.id === _activeSymposium; });
    if (!sym) { content.innerHTML = '<p style="font-size:12px;color:var(--text-dim)">Symposium not found.</p>'; return; }

    var tabs = [{id:'evidence', label:'Evidence'}];
    if (sym.archive && sym.archive.length) tabs.push({id:'archive', label:'Archive'});
    if (tab !== 'evidence' && tab !== 'archive') tab = 'evidence';
    _renderContextTabs(tabs, tab);
    _activeContextTab = tab;

    if (tab === 'archive') {
      var ah = '<div style="padding:4px 0;">';
      sym.archive.slice().reverse().forEach(function(a) {
        var dt = a.created_at ? new Date(a.created_at).toLocaleDateString() : '';
        ah += '<details class="archive-round" style="margin-bottom:8px;border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden;">';
        ah += '<summary class="archive-round-summary" style="display:flex;align-items:center;gap:8px;padding:10px 12px;cursor:pointer;font-size:13px;list-style:none;">';
        ah += '<span class="archive-round-chevron" style="font-size:10px;width:12px;color:var(--text-dim);transition:transform 0.15s;">▶</span>';
        ah += '<span style="font-weight:600;">Round ' + a.round_number + '</span>';
        if (dt) ah += '<span style="font-size:10px;color:var(--text-dim);">' + dt + '</span>';
        ah += '<span style="font-size:10px;color:var(--text-dim);margin-left:auto;">' + (a.message_count || 0) + ' msgs</span>';
        ah += '</summary>';
        ah += '<div style="padding:0 12px 12px;">';
        if (a.synthesis) {
          ah += '<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-dim);margin-bottom:4px;">Synthesis</div>';
          ah += '<div style="font-size:12px;line-height:1.6;">' + marked.parse(a.synthesis.substring(0, 2000)) + '</div>';
        } else {
          ah += '<p style="font-size:11px;color:var(--text-dim);">No synthesis for this round.</p>';
        }
        ah += '</div></details>';
      });
      if (!sym.archive.length) ah += '<p style="font-size:11px;color:var(--text-dim);">No archived rounds yet.</p>';
      content.innerHTML = ah;
    } else {
      // ── Evidence tab: merged sources from all participating experts ──
      content.innerHTML = '<div style="text-align:center;padding:20px 0;"><div class="spinner" style="margin:0 auto;"></div></div>';
      var allCurated = [], allDiscovered = [];
      for (var i = 0; i < (sym.participant_ids || []).length; i++) {
        var pid = sym.participant_ids[i];
        var pnlId = _expertPanelMap[pid];
        if (!pnlId) continue;
        try {
          var resp = await fetch(API + '/panels/' + pnlId + '/experts/' + pid + '/pool');
          var pool = await resp.json();
          allCurated = allCurated.concat(pool.curated || []);
          allDiscovered = allDiscovered.concat(pool.discovered || []);
        } catch(e) {}
      }
      var eh = '';
      if (allCurated.length) eh += _renderSourceSection('curated', 'Curated', allCurated);
      if (allDiscovered.length) eh += _renderSourceSection('discovered', 'Discovered', allDiscovered);
      if (!allCurated.length && !allDiscovered.length) eh += '<p style="font-size:11px;color:var(--text-dim);">No sources across participants.</p>';
      content.innerHTML = eh;
    }
  } else if (_activeExpert) {
    // ── Expert context: Library only (no tabs) ──
    _renderContextTabs([], '');
    _activeContextTab = 'library';
    try {
      var resp = await fetch(API + '/panels/' + _expertPanelMap[_activeExpert.id] + '/experts/' + _activeExpert.id + '/pool');
      var pool = await resp.json();
      var html = '<div style="display:flex;gap:8px;margin-bottom:12px;">';
      html += '<button class="sidebar-btn" style="flex:1;" onclick="showAddSourceModal()">+ Add URL</button>';
      html += '<button class="sidebar-btn" style="flex:1;" onclick="showUploadModal()">📄 Upload</button>';
      html += '<button class="sidebar-btn" style="flex:1;" onclick="startExpertResearch()">🔍 Research</button></div>';

      var curated = pool?.curated || [];
      html += _renderSourceSection('curated', 'Curated', curated);

      var discovered = pool?.discovered || [];
      html += '<div id="discovered-sources">';
      html += _renderSourceSection('discovered', 'Discovered', discovered);
      html += '</div>';

      if (pool?.opinions?.length) {
        html += '<div style="font-size:11px;font-weight:600;color:var(--text-muted);margin:10px 0 6px;">Opinions</div>';
        html += pool.opinions.map(function(o) { return '<div class="mini-claim-card" style="border-left:3px solid var(--indigo);"><div style="font-size:12px;line-height:1.5;">' + esc(o.text) + '</div><div style="font-size:10px;color:var(--text-dim);margin-top:4px;">Cites ' + (o.source_ids?.length||0) + ' sources</div></div>'; }).join('');
      } else if (!curated.length && !discovered.length) {
        html += '<p style="font-size:12px;color:var(--text-dim)">Library is empty.</p>';
      }
      content.innerHTML = html;
      if (_researchAbortCtrl) {
        var _discovered = document.getElementById('discovered-sources');
        if (_discovered && !document.getElementById('research-progress')) {
          _discovered.insertAdjacentHTML('beforeend',
            '<div id="research-progress" style="text-align:center;padding:14px 0 8px;border-top:1px solid var(--border-light);margin-top:8px;">' +
            '<div class="spinner" style="margin:0 auto 10px;"></div>' +
            '<p style="font-size:13px;color:var(--text-muted);">Searching for sources…</p>' +
            '<p style="font-size:11px;color:var(--text-dim);" id="research-counter">Verified: … / …</p>' +
            '<p style="font-size:10px;color:var(--text-dim);" id="research-status"></p></div>');
        }
      }
    } catch(e) { content.innerHTML = '<p style="font-size:12px;color:var(--text-dim)">Could not load pool.</p>'; }
  } else {
    _renderContextTabs([], '');
    content.innerHTML = '<p style="font-size:12px;color:var(--text-dim)">Select an expert or symposium to see context.</p>';
  }
}

// ── Expert Profile Modal ──────────────────────────────────────────────────────

function showExpertProfileModal() {
  if (!_activeExpert) return;
  var e = _activeExpert;
  showModal(
    '<h3>Expert Profile</h3>' +
    '<div style="text-align:center;padding:8px 0 16px;">' +
    '<div style="font-family:var(--font-heading);font-size:17px;font-weight:600;">' + esc(e.name) + '</div>' +
    '<div style="font-size:12px;color:var(--text-dim);margin-top:2px;">' + esc(e.discipline) + '</div></div>' +
    '<div style="margin-bottom:8px;"><span style="font-size:10px;color:var(--text-dim);">Discipline</span>' +
    '<input id="profile-discipline" value="' + escAttr(e.discipline) + '" style="width:100%;padding:6px 8px;margin-top:2px;border:1px solid var(--border);border-radius:4px;font-size:12px;font-family:var(--font-body);"></div>' +
    '<div style="margin-bottom:8px;"><span style="font-size:10px;color:var(--text-dim);">Intellectual Bias</span>' +
    '<input id="profile-bias" value="' + escAttr(e.bias) + '" style="width:100%;padding:6px 8px;margin-top:2px;border:1px solid var(--border);border-radius:4px;font-size:12px;font-family:var(--font-body);"></div>' +
    '<div style="margin-bottom:8px;"><span style="font-size:10px;color:var(--text-dim);">Persona</span>' +
    '<textarea id="profile-persona" rows="3" style="width:100%;padding:6px 8px;margin-top:2px;border:1px solid var(--border);border-radius:4px;font-size:12px;font-family:var(--font-body);resize:vertical;">' + esc(e.persona_prompt||'') + '</textarea></div>' +
    '<div style="margin-bottom:8px;"><span style="font-size:10px;color:var(--text-dim);">Photo URL</span>' +
    '<input id="profile-photo" value="' + escAttr(e.photo_url||'') + '" placeholder="https://…" style="width:100%;padding:6px 8px;margin-top:2px;border:1px solid var(--border);border-radius:4px;font-size:12px;font-family:var(--font-body);"></div>' +
    '<div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>' +
    '<button class="modal-btn primary" onclick="saveExpertProfile(\'' + e.id + '\');closeModal();">💾 Save</button></div>'
  );
}

// ── Source block helpers ───────────────────────────────────────────────────────

function _renderSourceSection(origin, label, sources) {
  const count = sources.length;
  let html = `<div class="source-section">`;
  html += `<div class="panel-group-header" onclick="this.parentElement.classList.toggle('collapsed')">`;
  html += `<span class="collapse-icon">▼</span> ${esc(label)} (${count})`;
  html += `</div>`;
  html += `<div class="source-list">`;
  if (!count) {
    html += `<p style="font-size:11px;color:var(--text-dim);padding:8px;">No ${label.toLowerCase()} items yet.</p>`;
  } else {
    html += sources.map(s => _renderSourceBlock(s)).join('');
  }
  html += `</div></div>`;
  return html;
}

function _renderSourceBlock(s) {
  const icons = {url:'🌐', pdf:'📄', doc:'📄', txt:'📃'};
  const icon = icons[s.source_type] || '📎';
  const preview = (s.snippet || s.full_text_preview || '').substring(0, 120);
  const badge = s.origin === 'discovered' ? statusBadge(s.verification_status) : '';
  const onClick = s.source_type === 'url' && s.url
    ? `onclick="window.open('${escAttr(s.url)}','_blank','noopener')"`
    : `onclick="fetchFullSourceText('${escAttr(s.id)}')"`;

  return `<div class="source-block${s.origin==='discovered'?' discovered':''}" data-source-id="${escAttr(s.id)}" ${onClick}>
    <div class="source-block-header">
      <span class="source-icon">${icon}</span>
      <span class="source-title">${esc(s.title || s.url || 'Untitled')}</span>
      ${badge}
      <button class="source-delete-btn" onclick="event.stopPropagation();deleteSource('${escAttr(s.id)}')" title="Remove from library">✕</button>
    </div>
    ${s.url ? `<div class="source-url">→ ${esc(s.url)}</div>` : ''}
    <div class="source-preview">${esc(preview)}</div>
  </div>`;
}

async function deleteSource(sourceId) {
  if (!_activeExpert) return;
  const panelId = _expertPanelMap[_activeExpert.id];
  if (!panelId) return;
  try {
    const resp = await fetch(`${API}/panels/${panelId}/experts/${_activeExpert.id}/sources/${sourceId}`, { method:'DELETE' });
    if (!resp.ok) throw new Error('Failed');
    toast('Source removed', 'success');
    renderContextPanel('library');
  } catch(e) {
    toast('Could not remove source', 'error');
  }
}

async function fetchFullSourceText(sourceId) {
  if (!_activeExpert) return;
  const panelId = _expertPanelMap[_activeExpert.id];
  if (!panelId) return;
  try {
    const resp = await fetch(`${API}/panels/${panelId}/experts/${_activeExpert.id}/sources/${sourceId}/full`);
    if (!resp.ok) { toast('Full text not available for this source', 'error'); return; }
    const data = await resp.json();
    showModal(`<h3>${esc(data.title||'Source')}</h3>
      <div style="max-height:60vh;overflow-y:auto;font-size:13px;line-height:1.7;white-space:pre-wrap;font-family:var(--font-body);">
        ${esc((data.full_text||'').substring(0, 10000))}
      </div>`);
  } catch(e) {
    toast('Could not load source text', 'error');
  }
}

// ── Utility ──

function escAttr(s) { return (s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

async function saveExpertProfile(expertId) {
  const discipline = document.getElementById('profile-discipline')?.value?.trim() || '';
  const bias = document.getElementById('profile-bias')?.value?.trim() || '';
  const persona = document.getElementById('profile-persona')?.value?.trim() || '';
  const photo = document.getElementById('profile-photo')?.value?.trim() || '';

  const panelId = _expertPanelMap[expertId];
  if (!panelId) return;

  try {
    const resp = await fetch(`${API}/panels/${panelId}/experts/${expertId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ discipline, bias, persona_prompt: persona, photo_url: photo }),
    });
    if (!resp.ok) throw new Error('Failed');
    // Update local session state
    const expert = findExpert(expertId);
    if (expert) {
      expert.discipline = discipline;
      expert.bias = bias;
      expert.persona_prompt = persona;
      expert.photo_url = photo;
    }
    // Refresh the header if this expert is active
    if (_activeExpert?.id === expertId) {
      renderConversationHeader(expert || _activeExpert);
    }
    toast('Profile saved', 'success');
  } catch (e) {
    toast('Failed to save profile', 'error');
  }
}

function statusBadge(s) {
  if (!s) return '<span class="badge-mini unverifiable">pending</span>';
  const m = {verified:'verified',misattributed:'misattributed',unverifiable:'unverifiable'};
  return `<span class="badge-mini ${m[s]||'unverifiable'}">${s}</span>`;
}

// ── Symposium ───────────────────────────────────────────────────────────────

function conveneSymposium() {
  if (!_session?.panels) return;
  // Build panel options
  let panelOptions = _session.panels.map((p, i) =>
    `<option value="${p.id}">${esc(p.name || 'Panel ' + (i+1))} (${(p.experts||[]).length} experts)</option>`
  ).join('');
  // Build expert checkboxes (grouped by panel)
  let expertCBs = '';
  _session.panels.forEach((panel, pi) => {
    expertCBs += `<div style="font-size:11px;font-weight:600;color:var(--text-dim);margin:8px 0 4px;">${esc(truncate(panel.name || 'Panel ' + (pi+1), 60))}</div>`;
    (panel.experts || []).forEach(e => {
      expertCBs += `<label style="display:block;font-size:12px;margin:3px 0;cursor:pointer;">
        <input type="checkbox" class="sym-expert-cb" value="${e.id}" checked> ${esc(e.name)} (${esc(e.discipline)})
      </label>`;
    });
  });

  showModal(`<h3>Convene Symposium</h3>
    <div style="margin-bottom:14px;">
      <label style="font-size:12px;font-weight:600;">Mode:</label>
      <select id="sym-mode-select" onchange="toggleSymMode()" style="width:100%;padding:8px;margin-top:4px;border:1px solid var(--border);border-radius:6px;font-family:var(--font-body);">
        <option value="panel">From Panel (use panel's question + experts)</option>
        <option value="custom">Custom (pick experts + write question)</option>
      </select>
    </div>
    <div id="sym-panel-mode">
      <label style="font-size:12px;font-weight:600;">Panel:</label>
      <select id="sym-panel-select" style="width:100%;padding:8px;margin-top:4px;border:1px solid var(--border);border-radius:6px;font-family:var(--font-body);">${panelOptions}</select>
    </div>
    <div id="sym-custom-mode" style="display:none;">
      <label style="font-size:12px;font-weight:600;">Question:</label>
      <input id="sym-custom-query" placeholder="Enter symposium question…" style="width:100%;padding:8px;margin-top:4px;border:1px solid var(--border);border-radius:6px;font-family:var(--font-body);">
      <label style="font-size:12px;font-weight:600;margin-top:12px;display:block;">Experts:</label>
      <div style="max-height:180px;overflow-y:auto;margin-top:4px;">${expertCBs}</div>
    </div>
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="createAndStartSymposium()">Begin</button></div>`);
}

function toggleSymMode() {
  const mode = document.getElementById('sym-mode-select')?.value;
  const panelDiv = document.getElementById('sym-panel-mode');
  const customDiv = document.getElementById('sym-custom-mode');
  if (panelDiv) panelDiv.style.display = mode === 'panel' ? '' : 'none';
  if (customDiv) customDiv.style.display = mode === 'custom' ? '' : 'none';
}

async function createAndStartSymposium() {
  closeModal(); toast('Creating symposium…', 'success');
  const mode = document.getElementById('sym-mode-select')?.value || 'panel';
  let body;
  if (mode === 'panel') {
    const panelId = document.getElementById('sym-panel-select')?.value || '';
    body = JSON.stringify({panel_id: panelId, format:'structured'});
  } else {
    const cbs = document.querySelectorAll('.sym-expert-cb:checked');
    const expertIds = Array.from(cbs).map(cb => cb.value);
    const query = document.getElementById('sym-custom-query')?.value?.trim() || '';
    body = JSON.stringify({expert_ids: expertIds, query: query || 'Custom Symposium', format:'structured'});
  }
  const resp = await fetch(`${API}/symposia`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body,
  });
  const created = await resp.json();
  const symId = created.symposium_id;
  _activeSymposium = symId; _activeExpert = null;
  _symposiumMessages[symId] = [];
  _symposiumTyping[symId] = null;
  _persistSymState();
  await refreshSessionData();
  // Update the symposia list only — don't re-render the entire sidebar panels
  // (re-rendering sidebar-panels can cause focus/selection issues)
  renderSymposiaList();
  // Use the full symposium data from the refreshed session
  const sym = _session.symposia?.find(s => s.id === symId);
  document.getElementById('input-bar').style.display = 'none';
  _renderSymposiumView(sym || {id: symId, format: 'structured', participant_ids: created.participants || []});
  showContextPanel();
}

function selectSymposium(symId) {
  _activeSymposium = symId; _activeExpert = null;
  var sym = _session.symposia.find(function(s) { return s.id === symId; });
  if (!sym) return;
  renderSidebar();
  document.getElementById('input-bar').style.display = 'none';
  _renderSymposiumView(sym);
  showContextPanel();
  _activeContextTab = 'evidence';
  renderContextPanel('evidence');
}

function _renderSymposiumView(sym) {
  const symId = sym.id || sym.symposium_id;
  const msgs = _symposiumMessages[symId] || [];
  const typing = _symposiumTyping[symId] || null;
  const hasSynthesis = sym.has_synthesis;
  let convHTML = '<div id="conversation">';
  if (msgs.length) {
    msgs.forEach(m => {
      convHTML += _buildMessageHTML(m.role, m.name, m.content, m.accent, m.turn);
    });
  } else if (!typing) {
    convHTML += `<div class="empty-state"><div class="empty-icon">🏛️</div><h2>Symposium</h2><p>Run a round to see the debate.</p></div></div>`;
    document.getElementById('main-content').innerHTML = `
      <div class="main-header"><div style="font-size:24px;">⚡</div>
        <div class="header-info"><div class="header-name">${esc(truncate(sym.title||'Symposium', 120))}</div>
        <div class="header-discipline">${sym.format || 'structured'} · ${sym.participant_ids?.length||0} experts · ${msgs.length} msgs</div></div>
        <div class="main-header-actions">
          <button class="header-action-btn" onclick="runSymposiumRound()" id="btn-run-round">${hasSynthesis?'▶ Start New Round':'▶ Run Round'}</button>
          <button class="header-action-btn" onclick="synthesizeSymposium()" id="btn-synthesize" ${hasSynthesis?'style="display:none;"':''}>📋 Synthesize</button>
        </div></div>
      ${convHTML}`;
    return;
  }
  // Render typing indicator if an expert is currently speaking
  if (typing) {
    convHTML += `<div class="typing-indicator" id="typing-indicator">
      ${esc(typing.name)} is speaking <span class="typing-dots"><span></span><span></span><span></span></span>
    </div>`;
  }
  convHTML += '</div>';
  document.getElementById('main-content').innerHTML = `
    <div class="main-header"><div style="font-size:24px;">⚡</div>
      <div class="header-info"><div class="header-name">${esc(truncate(sym.title||'Symposium', 120))}</div>
      <div class="header-discipline">${sym.format || 'structured'} · ${sym.participant_ids?.length||0} experts · ${msgs.length} msgs</div></div>
      <div class="main-header-actions">
        <button class="header-action-btn" onclick="runSymposiumRound()" id="btn-run-round">▶ Run Round</button>
        <button class="header-action-btn" onclick="synthesizeSymposium()" id="btn-synthesize" ${hasSynthesis?'':'style="display:none;"'}>📋 Synthesize</button>
      </div></div>
    ${convHTML}`;
}

function _buildMessageHTML(role, name, content, accentClass, turn) {
  const turnLbl = turn ? ` <span style="font-size:10px;color:var(--text-dim)">Turn ${turn}</span>` : '';
  const hdr = `<div class="msg-header"><strong>${esc(name)}</strong>${turnLbl}</div>`;
  const bubbleContent = role === 'agent'
    ? _renderStructuredContent(content, name)
    : esc(content);
  const avWrap = role === 'user'
    ? '<div class="msg-avatar" style="background:var(--gold-bg);display:flex;align-items:center;justify-content:center;">👤</div>'
    : _getExpertAvatarHTML(name, 34);
  const side = role === 'user' ? 'message-right' : '';
  return `<div class="message ${role} ${side} msg-accent-${accentClass||'gold'}">
    ${role==='user' ? '' : avWrap}
    <div class="msg-body">${hdr}<div class="msg-bubble">${bubbleContent}</div></div>
    ${role==='user' ? avWrap : ''}
  </div>`;
}

async function runSymposiumRound() {
  if (!_activeSymposium) return;
  var symId = _activeSymposium;
  var sym = _session.symposia.find(function(s) { return s.id === symId; });
  var isNewRound = sym && sym.has_synthesis;

  // If starting a new round, archive the current one first
  if (isNewRound) {
    try {
      await fetch(API + '/symposia/' + symId + '/new-round', { method: 'POST', headers: {'Content-Type':'application/json'}, body:'{}' });
    } catch(e) { toast('Failed to archive round: ' + e.message, 'error'); return; }
    // Clear local message state
    _symposiumMessages[symId] = [];
    _symposiumTyping[symId] = null;
    _persistSymState();
    await refreshSessionData();
  }

  var btn = document.getElementById('btn-run-round');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Running…'; }
  var conv = document.getElementById('conversation');
  var empty = conv?.querySelector('.empty-state');
  if (empty) empty.remove();
  // Clear conversation DOM for new round
  if (isNewRound && conv) conv.innerHTML = '';
  var ct = null;
  var tid = toast('Symposium round starting…', 'loading');
  // Ensure message store exists for this symposium
  if (!_symposiumMessages[symId]) _symposiumMessages[symId] = [];
  try {
    await streamSSE(
      `${API}/symposia/${symId}/round`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' },
      (et, data) => {
        if (et === 'typing') {
          if (ct) ct.remove();
          ct = appendTypingIndicator(data.name);
          highlightSpeaker(data.name);
          // Store typing state so it persists across navigation
          _symposiumTyping[symId] = {name: data.name, discipline: data.discipline || ''};
          _persistSymState();
          updateToast(tid, `${data.name} is speaking…`, 'loading');
        } else if (et === 'message') {
          if (ct) ct.remove(); ct = null;
          // Clear typing state — message delivered
          _symposiumTyping[symId] = null;
          _persistSymState();
          const accent = _expertAccents[findExpertIdByName(data.name)] || 'gold';
          _symposiumMessages[symId].push({
            role: 'agent', name: data.name, content: data.content,
            accent: accent, turn: data.turn,
          });
          _persistSymState();
          // Also append to DOM if conversation is visible
          if (document.getElementById('conversation')) {
            appendMessage('agent', data.name, data.content, accent, data.turn);
          }
        } else if (et === 'round_complete') {
          dismissToast(tid);
          _symposiumTyping[symId] = null;
          _persistSymState();
          toast(`Round complete — ${data.turns} turns`, 'success');
          const sb = document.getElementById('btn-synthesize');
          if (sb) sb.style.display = '';
        }
      }
    );
  } catch(e) {
    if (ct) ct.remove(); dismissToast(tid);
    _symposiumTyping[symId] = null;
    const errMsg = {role:'system',name:'',content:`Error: ${e.message}`,accent:'gold',turn:null};
    _symposiumMessages[symId].push(errMsg);
    _persistSymState();
    if (document.getElementById('conversation')) {
      appendMessage('system', '', `Error: ${e.message}`);
    }
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
  if (!_session?.panels) return null;
  for (const panel of _session.panels) {
    const e = (panel.experts || []).find(e => e.name === name);
    if (e) return e.id;
  }
  return null;
}

function _getExpertAvatarHTML(name, size) {
  // Returns an HTML string for the expert's avatar (or a coloured initial circle)
  const expertId = findExpertIdByName(name);
  const av = expertId ? _expertAvatars[expertId] : null;
  const accent = (expertId ? _expertAccents[expertId] : null) || 'gold';
  if (av) {
    // We can't serialise a canvas to HTML easily, so render initials with accent
    const initial = (name || '?').replace(/^(Dr\.|Prof\.) /, '').charAt(0).toUpperCase();
    return `<div class="msg-avatar" style="background:var(--${accent}-bg);color:var(--${accent});display:flex;align-items:center;justify-content:center;font-size:${Math.round(size*0.45)}px;font-weight:700;width:${size}px;height:${size}px;border-radius:8px;flex-shrink:0;">${esc(initial)}</div>`;
  }
  // Fallback: lightning bolt for unrecognised names
  return `<div class="msg-avatar" style="background:var(--${accent}-bg);color:var(--${accent});display:flex;align-items:center;justify-content:center;font-size:${Math.round(size*0.5)}px;width:${size}px;height:${size}px;border-radius:8px;flex-shrink:0;">⚡</div>`;
}

function _getExpertAvElement(name, size) {
  // Returns a DOM element for the expert's avatar
  size = size || 34;
  const expertId = findExpertIdByName(name);
  const av = expertId ? _expertAvatars[expertId] : null;
  if (av) return createAvatarElement(av, size);
  // Fallback: coloured initial circle
  const div = document.createElement('div');
  div.className = 'msg-avatar';
  const accent = (expertId ? _expertAccents[expertId] : null) || 'gold';
  const initial = (name || '?').replace(/^(Dr\.|Prof\.) /, '').charAt(0).toUpperCase();
  div.style.cssText = `background:var(--${accent}-bg);color:var(--${accent});display:flex;align-items:center;justify-content:center;font-size:${Math.round(size*0.5)}px;font-weight:700;width:${size}px;height:${size}px;border-radius:8px;flex-shrink:0;`;
  div.textContent = initial;
  return div;
}

async function synthesizeSymposium() {
  if (!_activeSymposium) return;
  var tid = toast('Rapporteur is synthesizing…', 'loading');
  var btn = document.getElementById('btn-synthesize');
  if (btn) { btn.disabled = true; btn.textContent = '⏳…'; }

  // Show synthesis progress in context panel
  var ctx = document.getElementById('context-content');
  if (ctx) {
    ctx.innerHTML = '<div style="text-align:center;padding:20px 0;" id="synthesis-progress">' +
      '<div class="spinner" style="margin:0 auto 12px;"></div>' +
      '<p style="font-size:13px;color:var(--text-muted);">Rapporteur is drafting synthesis…</p>' +
      '<p style="font-size:10px;color:var(--text-dim);" id="synthesis-status">Reading debate transcript…</p></div>';
    _renderContextTabs([{id:'synthesis',label:'Synthesis'}], 'synthesis');
  }

  try {
    await streamSSE(
      API + '/symposia/' + _activeSymposium + '/synthesize',
      { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' },
      function(et, data) {
        if (et === 'typing') {
          var st = document.getElementById('synthesis-status');
          if (st) st.textContent = 'Drafting synthesis document…';
        } else if (et === 'message') {
          dismissToast(tid);
          appendMessage('agent','Rapporteur',data.content,'gold');
          toast('Synthesis complete!','success');
          // Update context panel with synthesis content
          if (ctx) {
            ctx.innerHTML = '<div style="padding:4px 0;">' +
              '<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-dim);margin-bottom:8px;">Synthesis</div>' +
              '<div style="font-size:12px;line-height:1.7;">' + marked.parse(data.content||'') + '</div></div>';
            _renderContextTabs([{id:'synthesis',label:'Synthesis'}], 'synthesis');
          }
        }
      }
    );
  } catch(e) { dismissToast(tid); toast('Failed: '+e.message,'error'); }
  if (btn) { btn.disabled=false; btn.textContent='📋 Synthesize'; }
  await refreshSessionData();
}

// ── Modals ──────────────────────────────────────────────────────────────────

function showNewPanelModal() {
  showAddExpertsModal();
}

function showAddExpertsModal() {
  showModal(`<h3>Add Experts</h3><p>The Moderator will research and propose experts.</p>
    <input id="modal-panel-query" placeholder="Research question…">
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="addExperts()">Propose Experts</button></div>`);
}

async function addExperts() {
  const query = document.getElementById('modal-panel-query').value.trim();
  if (!query) { toast('Enter a research question', 'error'); return; }
  closeModal(); toast('Moderator is researching…', 'success');
  const resp = await fetch(`${API}/panels`, {
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
function truncate(s, max) { if (!s) return ''; return s.length > max ? s.substring(0, max) + '…' : s; }

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
