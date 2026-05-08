/**
 * gui/workspace.js — The Academy workspace
 *
 * Three-panel layout: sidebar (panels/experts/symposia),
 * main conversation area, context panel (evidence/sources/synthesis).
 */

// ── Global state ────────────────────────────────────────────────────────────

const API = '/api';
let _wsId = null;
let _wsData = null;        // full workspace JSON from GET
let _activeExpert = null;  // {id, name, discipline, ...}
let _avatarPool = [];
let _expertAvatars = {};   // expert_id → avatarDef
let _expertAccents = {};   // expert_id → accent color class

const ACCENT_COLORS = ['gold', 'terracotta', 'olive', 'indigo', 'berry'];

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  _avatarPool = generateAvatarPool();
  showWorkspaceList();
});

// ── Workspace List ───────────────────────────────────────────────────────────

async function showWorkspaceList() {
  _wsId = null;
  _activeExpert = null;
  document.getElementById('sidebar-panels').innerHTML = '';
  document.getElementById('sidebar-symposia').innerHTML =
    '<span style="font-size:12px;color:var(--text-dim)">No symposia yet</span>';
  document.getElementById('sidebar-ws-name').textContent = 'Select a workspace';
  document.getElementById('input-bar').style.display = 'none';
  hideContextPanel();

  const resp = await fetch(`${API}/workspace`);
  const list = await resp.json();

  let html = '<div class="ws-list"><h2>The Academy</h2>';
  html += '<p class="subtitle">Select a workspace or create a new one to assemble your council of experts.</p>';

  if (list && list.length) {
    list.forEach(w => {
      html += `<div class="ws-card" onclick="loadWorkspace('${w.id}')">
        <div>
          <div class="ws-card-name">${esc(w.id)}</div>
          <div class="ws-card-meta">Updated ${w.updated_at || ''}</div>
        </div>
        <span style="color:var(--text-dim);font-size:20px;">→</span>
      </div>`;
    });
  } else {
    html += '<p style="color:var(--text-dim);padding:20px 0;">No workspaces yet. Create your first one.</p>';
  }

  html += `<button class="ws-create-btn" onclick="showNewWorkspaceModal()">+ New Workspace</button></div>`;
  document.getElementById('main-content').innerHTML = html;
}

async function loadWorkspace(id) {
  _wsId = id;
  const resp = await fetch(`${API}/workspace/${id}`);
  _wsData = await resp.json();
  document.getElementById('sidebar-ws-name').textContent = `Workspace · ${id}`;
  assignExpertAttributes();
  renderSidebar();
  showEmptyState();
}

// ── Expert attributes (avatars + accents) ────────────────────────────────────

function assignExpertAttributes() {
  if (!_wsData || !_wsData.panels) return;
  let colorIdx = 0;
  _wsData.panels.forEach(panel => {
    panel.experts.forEach(expert => {
      if (expert.id in _expertAvatars) {
        const existing = _avatarPool.find(a => a.id === _expertAvatars[expert.id].id);
        if (existing) return; // already assigned + still in pool
      }
      const avatar = randomAvatar(_avatarPool);
      _expertAvatars[expert.id] = {
        id: avatar.id,
        style: avatar.style,
        designIdx: avatar.designIdx,
        skinIdx: avatar.skinIdx,
        hairIdx: avatar.hairIdx,
        goldIdx: avatar.goldIdx || 0,
        robeIdx: avatar.robeIdx || 0,
        capIdx: avatar.capIdx || 0,
      };
      _expertAccents[expert.id] = ACCENT_COLORS[colorIdx % ACCENT_COLORS.length];
      colorIdx++;
    });
  });
}

// ── Sidebar ──────────────────────────────────────────────────────────────────

function renderSidebar() {
  if (!_wsData || !_wsData.panels) return;

  let html = '';
  _wsData.panels.forEach(panel => {
    html += `<div class="panel-group">
      <div class="panel-group-header">
        <span class="collapse-icon">▼</span>${esc(panel.name || panel.id)}
      </div>`;
    panel.experts.forEach(expert => {
      const av = _expertAvatars[expert.id];
      const accent = _expertAccents[expert.id] || 'gold';
      const activeCls = _activeExpert && _activeExpert.id === expert.id ? ' active' : '';
      html += `<div class="expert-item${activeCls}" onclick="selectExpert('${expert.id}')" data-expert-id="${expert.id}">
        <div class="avatar-wrap" id="av-sidebar-${expert.id}"></div>
        <div class="expert-info">
          <div class="expert-name">${esc(expert.name)}</div>
          <div class="expert-discipline">${esc(expert.discipline)}</div>
        </div>
        <div class="expert-accent-dot" style="background:var(--${accent})"></div>
      </div>`;
    });
    html += '</div>';
  });

  document.getElementById('sidebar-panels').innerHTML = html;

  // Render avatars in sidebar
  _wsData.panels.forEach(panel => {
    panel.experts.forEach(expert => {
      setTimeout(() => renderSidebarAvatar(expert.id), 10);
    });
  });
}

function renderSidebarAvatar(expertId) {
  const wrap = document.getElementById(`av-sidebar-${expertId}`);
  if (!wrap) return;
  const av = _expertAvatars[expertId];
  if (!av) return;
  const canvas = createAvatarElement(av, 36);
  wrap.innerHTML = '';
  wrap.appendChild(canvas);
}

// ── Expert Selection ─────────────────────────────────────────────────────────

function selectExpert(expertId) {
  const expert = findExpert(expertId);
  if (!expert) return;
  _activeExpert = expert;
  renderSidebar();
  renderConversationHeader(expert);
  renderConversation(expert);
  document.getElementById('input-bar').style.display = 'flex';
  showContextPanel();
  renderContextPanel(expert);
}

function findExpert(expertId) {
  if (!_wsData || !_wsData.panels) return null;
  for (const panel of _wsData.panels) {
    for (const e of panel.experts) {
      if (e.id === expertId) return e;
    }
  }
  return null;
}

// ── Conversation ─────────────────────────────────────────────────────────────

function renderConversationHeader(expert) {
  const accent = _expertAccents[expert.id] || 'gold';
  const av = _expertAvatars[expert.id];
  let avatarHtml = '';
  if (av) {
    const canvas = createAvatarElement(av, 44);
    avatarHtml = canvas.outerHTML;
  }

  document.getElementById('main-content').innerHTML = `
    <div class="main-header">
      <div class="avatar-wrap">${avatarHtml}</div>
      <div class="header-info">
        <div class="header-name">${esc(expert.name)}</div>
        <div class="header-discipline">${esc(expert.discipline)} · ${esc(expert.bias || '')}</div>
      </div>
      <div class="main-header-actions">
        <button class="header-action-btn" onclick="showContextPanel()">☰ Context</button>
      </div>
    </div>
    <div id="conversation"></div>`;
}

function renderConversation(expert) {
  const conv = document.getElementById('conversation');
  if (!conv) return;
  conv.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">📜</div>
      <h2>${esc(expert.name)} awaits your inquiry</h2>
      <p>Ask a question grounded in their discipline. They will reason from their knowledge pool and present evidence-backed arguments.</p>
    </div>`;
}

async function sendMessage() {
  const input = document.getElementById('msg-input');
  const msg = input.value.trim();
  if (!msg || !_activeExpert) return;

  input.value = '';
  input.disabled = true;
  document.getElementById('send-btn').disabled = true;

  const conv = document.getElementById('conversation');
  // Remove empty state
  const empty = conv.querySelector('.empty-state');
  if (empty) empty.remove();

  // Add user message
  appendMessage('user', 'You', msg);

  // Add typing indicator
  const typing = appendTypingIndicator(_activeExpert.name);

  try {
    const resp = await fetch(`${API}/workspace/${_wsId}/experts/${_activeExpert.id}/message`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg}),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});

      // Parse SSE events from buffer
      const lines = buffer.split('\n');
      buffer = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          buffer = line + '\n';
        } else if (line.startsWith('data: ') && buffer) {
          const eventType = buffer.replace('event: ', '').trim();
          const dataStr = line.replace('data: ', '').trim();
          buffer = '';
          try {
            const data = JSON.parse(dataStr);
            handleSSE(eventType, data, typing);
          } catch(e) {}
        }
      }
    }
  } catch (e) {
    if (typing) typing.remove();
    appendMessage('system', '', `Error: ${e.message}`);
  }

  input.disabled = false;
  document.getElementById('send-btn').disabled = false;
  input.focus();
}

function handleSSE(eventType, data, typingEl) {
  if (eventType === 'message') {
    if (typingEl) typingEl.remove();
    const accent = _expertAccents[_activeExpert?.id] || 'gold';
    appendMessage('agent', data.name, data.content, accent, data.turn);
  } else if (eventType === 'typing') {
    // Typing indicator already shown
  }
}

function appendMessage(role, name, content, accentClass, turn) {
  const conv = document.getElementById('conversation');
  if (!conv) return;

  const div = document.createElement('div');
  div.className = `message ${role}`;
  if (accentClass && role === 'agent') {
    div.classList.add(`msg-accent-${accentClass}`);
  }

  let avatarHtml = '';
  if (role === 'agent' && _activeExpert) {
    const av = _expertAvatars[_activeExpert.id];
    if (av) {
      const canvas = createAvatarElement(av, 34);
      avatarHtml = `<div class="msg-avatar">${canvas.outerHTML}</div>`;
    }
  } else if (role === 'user') {
    avatarHtml = `<div class="msg-avatar" style="background:var(--gold-bg);display:flex;align-items:center;justify-content:center;font-size:16px;">👤</div>`;
  }

  const turnLabel = turn ? `Turn ${turn}` : '';
  const headerHtml = `<div class="msg-header">
    <strong>${esc(name)}</strong>
    ${turnLabel ? `<span style="font-size:10px;color:var(--text-dim)">${turnLabel}</span>` : ''}
  </div>`;

  const contentHtml = role === 'agent' ? preprocessMarkdown(content) : esc(content);

  div.innerHTML = `
    ${avatarHtml}
    <div class="msg-body">
      ${headerHtml}
      <div class="msg-bubble">${marked.parse(contentHtml)}</div>
    </div>`;

  conv.appendChild(div);
  conv.scrollTop = conv.scrollHeight;
}

function appendTypingIndicator(name) {
  const conv = document.getElementById('conversation');
  if (!conv) return null;
  const div = document.createElement('div');
  div.className = 'typing-indicator';
  div.innerHTML = `${esc(name)} is thinking <span class="typing-dots"><span></span><span></span><span></span></span>`;
  conv.appendChild(div);
  conv.scrollTop = conv.scrollHeight;
  return div;
}

// ── Markdown preprocessing ───────────────────────────────────────────────────

function preprocessMarkdown(md) {
  // Convert **Keywords:** chip1, chip2 → HTML chips
  return md.replace(/\*\*Keywords:\*\*\s*(.+?)(?:\n|$)/, (_, kw) => {
    const chips = kw.split(',').map(k =>
      `<span class="keyword-chip">${esc(k.trim())}</span>`
    ).join('');
    return `<div class="keyword-row">${chips}</div>`;
  });
}

// ── Context Panel ────────────────────────────────────────────────────────────

function showContextPanel() {
  document.getElementById('context-panel').classList.remove('collapsed');
}

function hideContextPanel() {
  document.getElementById('context-panel').classList.add('collapsed');
}

function switchContextTab(tab, btn) {
  document.querySelectorAll('.context-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  if (_activeExpert) renderContextPanel(_activeExpert, tab);
}

async function renderContextPanel(expert, tab = 'evidence') {
  const content = document.getElementById('context-content');
  if (!content) return;

  if (tab === 'sources') {
    try {
      const resp = await fetch(`${API}/workspace/${_wsId}/experts/${expert.id}/pool`);
      const pool = await resp.json();
      if (!pool || !pool.sources || !pool.sources.length) {
        content.innerHTML = '<p style="font-size:12px;color:var(--text-dim)">No sources in knowledge pool yet.</p>';
        return;
      }
      content.innerHTML = pool.sources.map(s => `
        <div class="mini-claim-card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-weight:600;font-size:12px;">${esc(s.title || s.url)}</span>
            ${s.verification_status ? `<span class="badge-mini ${s.verification_status}">${s.verification_status}</span>` : '<span class="badge-mini unverifiable">pending</span>'}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:4px;">${esc(s.snippet || s.full_text_preview || '')}</div>
          ${s.url ? `<div style="font-size:10px;color:var(--gold);margin-top:4px;">→ ${esc(s.url)}</div>` : ''}
        </div>
      `).join('');
    } catch(e) {
      content.innerHTML = '<p style="font-size:12px;color:var(--text-dim)">Could not load sources.</p>';
    }
  } else if (tab === 'synthesis') {
    content.innerHTML = '<p style="font-size:12px;color:var(--text-dim)">No synthesis yet. Convene a symposium to generate one.</p>';
  } else {
    content.innerHTML = '<p style="font-size:12px;color:var(--text-dim)">Evidence scorecard will appear here during symposia.</p>';
  }
}

// ── Modals ───────────────────────────────────────────────────────────────────

function showNewWorkspaceModal() {
  showModal(`
    <h3>New Workspace</h3>
    <p>Create a new workspace to assemble your council of experts.</p>
    <input id="modal-ws-query" placeholder="Research question or topic (optional)…">
    <div class="modal-actions">
      <button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
      <button class="modal-btn primary" onclick="createWorkspace()">Create</button>
    </div>
  `);
}

async function createWorkspace() {
  const query = document.getElementById('modal-ws-query').value.trim();
  closeModal();
  const resp = await fetch(`${API}/workspace`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({query}),
  });
  const data = await resp.json();
  toast('Workspace created', 'success');
  showWorkspaceList();
}

function showNewPanelModal() {
  if (!_wsId) { toast('Load a workspace first', 'error'); return; }
  showModal(`
    <h3>New Panel</h3>
    <p>The Moderator will research the topic and propose a panel of experts with distinct disciplinary perspectives.</p>
    <input id="modal-panel-query" placeholder="Research question…">
    <div class="modal-actions">
      <button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
      <button class="modal-btn primary" onclick="createPanel()">Propose Panel</button>
    </div>
  `);
}

async function createPanel() {
  const query = document.getElementById('modal-panel-query').value.trim();
  if (!query) { toast('Enter a research question', 'error'); return; }
  closeModal();
  toast('Moderator is researching and proposing experts…', 'success');

  try {
    const resp = await fetch(`${API}/workspace/${_wsId}/panels`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query, max_experts: 3}),
    });
    const data = await resp.json();
    // Reload workspace to get fresh data
    await loadWorkspace(_wsId);
    toast(`Panel created with ${data.experts?.length || 0} experts`, 'success');
  } catch(e) {
    toast('Failed to create panel: ' + e.message, 'error');
  }
}

function showModal(html) {
  const overlay = document.getElementById('modal-overlay');
  overlay.innerHTML = `<div class="modal">${html}</div>`;
  overlay.style.display = 'flex';
  overlay.onclick = (e) => { if (e.target === overlay) closeModal(); };
}

function closeModal() {
  document.getElementById('modal-overlay').style.display = 'none';
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function showEmptyState() {
  document.getElementById('main-content').innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">🏛️</div>
      <h2>Welcome to The Academy</h2>
      <p>Select an expert from the sidebar to begin a conversation, or create a panel to assemble your council.</p>
    </div>`;
}

function handleInputKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
}

function esc(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function toast(msg, type) {
  const container = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.remove(); }, 3500);
}
