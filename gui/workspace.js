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
let _activeSymposium = null; // symposium id
let _avatarPool = [];
let _expertAvatars = {};   // expert_id → avatarDef
let _expertAccents = {};   // expert_id → accent color class

const ACCENT_COLORS = ['gold', 'terracotta', 'olive', 'indigo', 'berry'];

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  _avatarPool = generateAvatarPool();
  showWorkspaceList();
});

// ── SSE stream helper ───────────────────────────────────────────────────────

async function streamSSE(url, options, onEvent) {
  const resp = await fetch(url, options);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    const lines = buffer.split('\n');
    buffer = '';
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        buffer = line + '\n';
      } else if (line.startsWith('data: ') && buffer) {
        const eventType = buffer.replace('event: ', '').trim();
        const dataStr = line.replace('data: ', '').trim();
        buffer = '';
        try { onEvent(eventType, JSON.parse(dataStr)); } catch(e) {}
      }
    }
  }
}

// ── Workspace List ───────────────────────────────────────────────────────────

async function showWorkspaceList() {
  _wsId = null; _activeExpert = null; _activeSymposium = null;
  document.getElementById('sidebar-panels').innerHTML = '';
  document.getElementById('sidebar-symposia').innerHTML = symposiaPlaceholder();
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
        <div><div class="ws-card-name">${esc(w.id)}</div>
        <div class="ws-card-meta">Updated ${w.updated_at || ''}</div></div>
        <span style="color:var(--text-dim);font-size:20px;">→</span></div>`;
    });
  } else {
    html += '<p style="color:var(--text-dim);padding:20px 0;">No workspaces yet.</p>';
  }
  html += '<button class="ws-create-btn" onclick="showNewWorkspaceModal()">+ New Workspace</button></div>';
  document.getElementById('main-content').innerHTML = html;
}

async function loadWorkspace(id) {
  _wsId = id;
  const resp = await fetch(`${API}/workspace/${id}`);
  _wsData = await resp.json();
  document.getElementById('sidebar-ws-name').textContent = `Workspace · ${id}`;
  assignExpertAttributes();
  renderSidebar();
  renderSymposiaList();
  showEmptyState();
}

// ── Expert attributes ────────────────────────────────────────────────────────

function assignExpertAttributes() {
  if (!_wsData?.panels) return;
  let colorIdx = 0;
  _wsData.panels.forEach(panel => {
    panel.experts.forEach(expert => {
      if (expert.id in _expertAvatars) {
        if (_avatarPool.find(a => a.id === _expertAvatars[expert.id].id)) return;
      }
      const avatar = randomAvatar(_avatarPool);
      _expertAvatars[expert.id] = {
        id: avatar.id, style: avatar.style, designIdx: avatar.designIdx,
        skinIdx: avatar.skinIdx, hairIdx: avatar.hairIdx,
        goldIdx: avatar.goldIdx || 0, robeIdx: avatar.robeIdx || 0,
        capIdx: avatar.capIdx || 0,
      };
      _expertAccents[expert.id] = ACCENT_COLORS[colorIdx % ACCENT_COLORS.length];
      colorIdx++;
    });
  });
}

// ── Sidebar ──────────────────────────────────────────────────────────────────

function renderSidebar() {
  if (!_wsData?.panels) return;
  let html = '';
  _wsData.panels.forEach(panel => {
    html += `<div class="panel-group">
      <div class="panel-group-header" onclick="togglePanelGroup(this)">
        <span class="collapse-icon">▼</span>${esc(panel.name || panel.id)}
        <span style="margin-left:auto;font-size:10px;color:var(--text-dim);cursor:pointer;" onclick="event.stopPropagation();conveneSymposium('${panel.id}')" title="Convene Symposium">⚡</span>
      </div>`;
    panel.experts.forEach(expert => {
      const activeCls = _activeExpert?.id === expert.id ? ' active' : '';
      html += `<div class="expert-item${activeCls}" onclick="selectExpert('${expert.id}')" data-expert-id="${expert.id}">
        <div class="avatar-wrap" id="av-sidebar-${expert.id}"></div>
        <div class="expert-info">
          <div class="expert-name">${esc(expert.name)}</div>
          <div class="expert-discipline">${esc(expert.discipline)}</div>
        </div>
        <div class="expert-accent-dot" style="background:var(--${_expertAccents[expert.id] || 'gold'})"></div>
      </div>`;
    });
    html += '</div>';
  });
  document.getElementById('sidebar-panels').innerHTML = html;
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
  wrap.innerHTML = '';
  wrap.appendChild(createAvatarElement(av, 36));
}

function togglePanelGroup(header) {
  const icon = header.querySelector('.collapse-icon');
  const items = header.parentElement.querySelectorAll('.expert-item');
  const collapsed = icon.textContent === '▶';
  icon.textContent = collapsed ? '▼' : '▶';
  items.forEach(el => { el.style.display = collapsed ? '' : 'none'; });
}

// ── Symposium sidebar ────────────────────────────────────────────────────────

function symposiaPlaceholder() {
  return '<span style="font-size:12px;color:var(--text-dim)">No symposia yet</span>';
}

function renderSymposiaList() {
  if (!_wsData?.symposia) return;
  const el = document.getElementById('sidebar-symposia');
  if (!_wsData.symposia.length) { el.innerHTML = symposiaPlaceholder(); return; }
  el.innerHTML = _wsData.symposia.map(s => `
    <div class="symposium-item" onclick="selectSymposium('${s.id}')">
      <span>⚡</span>
      <span>${esc(s.title || s.id)}</span>
      ${s.has_synthesis ? '<span style="margin-left:auto;font-size:10px;color:var(--olive);">✓</span>' : ''}
    </div>
  `).join('');
}

// ── Expert Selection ─────────────────────────────────────────────────────────

function selectExpert(expertId) {
  const expert = findExpert(expertId);
  if (!expert) return;
  _activeExpert = expert;
  _activeSymposium = null;
  renderSidebar();
  renderConversationHeader(expert);
  renderConversation(expert);
  document.getElementById('input-bar').style.display = 'flex';
  showContextPanel();
  renderContextPanel(expert);
}

function findExpert(expertId) {
  if (!_wsData?.panels) return null;
  for (const panel of _wsData.panels)
    for (const e of panel.experts)
      if (e.id === expertId) return e;
  return null;
}

// ── Conversation ─────────────────────────────────────────────────────────────

function renderConversationHeader(expert) {
  const av = _expertAvatars[expert.id];
  document.getElementById('main-content').innerHTML = `
    <div class="main-header">
      <div class="avatar-wrap">${av ? createAvatarElement(av, 44).outerHTML : ''}</div>
      <div class="header-info">
        <div class="header-name">${esc(expert.name)}</div>
        <div class="header-discipline">${esc(expert.discipline)} · ${esc(expert.bias || '')}</div>
      </div>
      <div class="main-header-actions">
        <button class="header-action-btn" onclick="showAddSourceModal()">+ Source</button>
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
      <p>Ask a question grounded in their discipline. They reason from their knowledge pool.</p>
    </div>`;
}

async function sendMessage() {
  const input = document.getElementById('msg-input');
  const msg = input.value.trim();
  if (!msg || !_activeExpert) return;
  input.value = ''; input.disabled = true;
  document.getElementById('send-btn').disabled = true;

  const conv = document.getElementById('conversation');
  const empty = conv.querySelector('.empty-state');
  if (empty) empty.remove();

  appendMessage('user', 'You', msg);
  const typing = appendTypingIndicator(_activeExpert.name);

  try {
    await streamSSE(
      `${API}/workspace/${_wsId}/experts/${_activeExpert.id}/message`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:msg}) },
      (eventType, data) => handleSSE(eventType, data, typing)
    );
  } catch(e) {
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
    appendMessage('agent', data.name, data.content, _expertAccents[_activeExpert?.id] || 'gold', data.turn);
  }
}

function appendMessage(role, name, content, accentClass, turn) {
  const conv = document.getElementById('conversation');
  if (!conv) return;
  const div = document.createElement('div');
  div.className = `message ${role}`;
  if (accentClass && role === 'agent') div.classList.add(`msg-accent-${accentClass}`);

  let avatarHtml = '';
  if (role === 'agent' && _activeExpert) {
    const av = _expertAvatars[_activeExpert.id];
    if (av) avatarHtml = `<div class="msg-avatar">${createAvatarElement(av, 34).outerHTML}</div>`;
  } else if (role === 'user') {
    avatarHtml = '<div class="msg-avatar" style="background:var(--gold-bg);display:flex;align-items:center;justify-content:center;">👤</div>';
  }

  const turnLabel = turn ? `Turn ${turn}` : '';
  const headerHtml = `<div class="msg-header"><strong>${esc(name)}</strong>${turnLabel ? ` <span style="font-size:10px;color:var(--text-dim)">${turnLabel}</span>` : ''}</div>`;
  const contentHtml = role === 'agent' ? preprocessMarkdown(content) : esc(content);

  div.innerHTML = `${avatarHtml}<div class="msg-body">${headerHtml}<div class="msg-bubble">${marked.parse(contentHtml)}</div></div>`;
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

function preprocessMarkdown(md) {
  return md.replace(/\*\*Keywords:\*\*\s*(.+?)(?:\n|$)/, (_, kw) => {
    const chips = kw.split(',').map(k => `<span class="keyword-chip">${esc(k.trim())}</span>`).join('');
    return `<div class="keyword-row">${chips}</div>`;
  });
}

// ── Knowledge Pool ───────────────────────────────────────────────────────────

function showAddSourceModal() {
  if (!_activeExpert) return;
  showModal(`
    <h3>Add Source</h3>
    <p>Add a URL, article, or document to <strong>${esc(_activeExpert.name)}</strong>'s knowledge pool.</p>
    <input id="modal-src-url" placeholder="URL (https://…)">
    <input id="modal-src-title" placeholder="Title">
    <textarea id="modal-src-snippet" placeholder="Snippet or key quote from the source…" rows="3" style="resize:vertical;"></textarea>
    <div class="modal-actions">
      <button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
      <button class="modal-btn primary" onclick="addSource()">Add to Pool</button>
    </div>
  `);
}

async function addSource() {
  const url = document.getElementById('modal-src-url').value.trim();
  const title = document.getElementById('modal-src-title').value.trim();
  const snippet = document.getElementById('modal-src-snippet').value.trim();
  if (!url && !snippet) { toast('Enter a URL or snippet', 'error'); return; }
  closeModal();
  toast('Adding source…', 'success');

  await fetch(`${API}/workspace/${_wsId}/experts/${_activeExpert.id}/sources`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({url, title, snippet, enrich: !!url}),
  });
  toast('Source added — full text fetched if available', 'success');
  renderContextPanel(_activeExpert, 'sources');
}

function showUploadModal() {
  if (!_activeExpert) return;
  showModal(`
    <h3>Upload File</h3>
    <p>Upload a PDF or text file to <strong>${esc(_activeExpert.name)}</strong>'s knowledge pool.</p>
    <p style="font-size:11px;color:var(--text-dim);">File upload is available via the API. Use the CLI for now:<br/><code>uv run python -m council.workspace.cli upload ${_wsId} ${_activeExpert.id} &lt;file&gt;</code></p>
    <div class="modal-actions">
      <button class="modal-btn secondary" onclick="closeModal()">Close</button>
    </div>
  `);
}

async function formOpinionForExpert() {
  if (!_activeExpert) return;
  toast('Forming opinion from verified sources…', 'success');
  try {
    await streamSSE(
      `${API}/workspace/${_wsId}/experts/${_activeExpert.id}/opinion`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message: _wsData?.query || ''}) },
      (eventType, data) => {
        if (eventType === 'opinion_ready') {
          toast('Opinion formed!', 'success');
          renderContextPanel(_activeExpert, 'sources');
        } else if (eventType === 'error') {
          toast(data.message, 'error');
        }
      }
    );
  } catch(e) {
    toast('Failed: ' + e.message, 'error');
  }
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
      let html = '<div style="display:flex;gap:8px;margin-bottom:12px;">';
      html += '<button class="sidebar-btn" style="flex:1;" onclick="showAddSourceModal()">+ Add URL</button>';
      html += '<button class="sidebar-btn" style="flex:1;" onclick="showUploadModal()">📄 Upload</button>';
      html += '<button class="sidebar-btn" style="flex:1;" onclick="formOpinionForExpert()">💡 Form Opinion</button>';
      html += '</div>';

      if (!pool?.sources?.length && !pool?.opinions?.length) {
        html += '<p style="font-size:12px;color:var(--text-dim)">No sources yet. Add a URL or upload a file.</p>';
      }

      if (pool?.sources?.length) {
        html += '<div style="font-size:11px;font-weight:600;color:var(--text-muted);margin-bottom:6px;">Sources</div>';
        html += pool.sources.map(s => `
          <div class="mini-claim-card">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <span style="font-weight:600;font-size:12px;">${esc(s.title || s.url || 'Untitled')}</span>
              ${statusBadge(s.verification_status)}
            </div>
            <div style="font-size:11px;color:var(--text-dim);margin-top:4px;">${esc((s.snippet || s.full_text_preview || '').substring(0, 180))}</div>
            ${s.url ? `<div style="font-size:10px;color:var(--gold);margin-top:4px;word-break:break-all;">→ ${esc(s.url)}</div>` : ''}
          </div>
        `).join('');
      }

      if (pool?.opinions?.length) {
        html += '<div style="font-size:11px;font-weight:600;color:var(--text-muted);margin:10px 0 6px;">Opinions</div>';
        html += pool.opinions.map(o => `
          <div class="mini-claim-card" style="border-left:3px solid var(--indigo);">
            <div style="font-size:12px;line-height:1.5;">${esc(o.text)}</div>
            <div style="font-size:10px;color:var(--text-dim);margin-top:4px;">Cites ${o.source_ids?.length || 0} sources</div>
          </div>
        `).join('');
      }

      content.innerHTML = html;
    } catch(e) {
      content.innerHTML = '<p style="font-size:12px;color:var(--text-dim)">Could not load pool.</p>';
    }
  } else if (tab === 'synthesis') {
    if (_activeSymposium) {
      try {
        const resp = await fetch(`${API}/workspace/${_wsId}`);
        const ws = await resp.json();
        const sym = (ws.symposia || []).find(s => s.id === _activeSymposium);
        if (sym?.has_synthesis) {
          content.innerHTML = '<p style="font-size:12px;color:var(--olive);">Synthesis available. Run a new symposium round or export.</p>';
        } else {
          content.innerHTML = '<p style="font-size:12px;color:var(--text-dim);">No synthesis yet. Synthesize after a debate round.</p>';
        }
      } catch(e) {
        content.innerHTML = '<p style="font-size:12px;color:var(--text-dim);">Could not load synthesis.</p>';
      }
    } else {
      content.innerHTML = '<p style="font-size:12px;color:var(--text-dim);">Select a symposium to see synthesis.</p>';
    }
  } else {
    content.innerHTML = '<p style="font-size:12px;color:var(--text-dim);">Evidence scorecard appears during symposia.</p>';
  }
}

function statusBadge(status) {
  if (!status) return '<span class="badge-mini unverifiable">pending</span>';
  const cls = {verified:'verified',misattributed:'misattributed',unverifiable:'unverifiable'}[status] || 'unverifiable';
  return `<span class="badge-mini ${cls}">${status}</span>`;
}

// ── Symposium ────────────────────────────────────────────────────────────────

function conveneSymposium(panelId) {
  if (!_wsId) return;
  const panel = _wsData.panels.find(p => p.id === panelId);
  if (!panel) return;
  showModal(`
    <h3>Convene Symposium</h3>
    <p>Start a structured debate with the experts from <strong>${esc(panel.name || panelId)}</strong>.</p>
    <p style="font-size:12px;color:var(--text-dim);">Format: Structured turn-based. Each expert speaks in turn, then the Rapporteur synthesizes.</p>
    <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">
      ${panel.experts.map(e => `<div>• ${esc(e.name)} (${esc(e.discipline)})</div>`).join('')}
    </div>
    <div class="modal-actions">
      <button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
      <button class="modal-btn primary" onclick="createAndStartSymposium('${panelId}')">Begin Symposium</button>
    </div>
  `);
}

async function createAndStartSymposium(panelId) {
  closeModal();
  toast('Creating symposium…', 'success');

  const resp = await fetch(`${API}/workspace/${_wsId}/symposia`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({title:`Debate: ${_wsData.query || ''}`, format:'structured', panel_id:panelId}),
  });
  const sym = await resp.json();
  _activeSymposium = sym.symposium_id;
  _activeExpert = null;
  await loadWorkspace(_wsId);

  // Show symposium view
  document.getElementById('input-bar').style.display = 'none';
  const convHeader = document.getElementById('main-content');
  convHeader.innerHTML = `
    <div class="main-header">
      <div style="font-size:24px;">⚡</div>
      <div class="header-info">
        <div class="header-name">Symposium</div>
        <div class="header-discipline">Structured debate · ${sym.participants?.length || 0} participants</div>
      </div>
      <div class="main-header-actions">
        <button class="header-action-btn" onclick="runSymposiumRound()" id="btn-run-round">▶ Run Round</button>
        <button class="header-action-btn" onclick="synthesizeSymposium()" id="btn-synthesize" style="display:none;">📋 Synthesize</button>
      </div>
    </div>
    <div id="conversation"><div class="empty-state"><div class="empty-icon">🏛️</div><h2>The Council convenes</h2><p>Click "Run Round" to begin the structured debate.</p></div></div>`;

  showContextPanel();
  document.getElementById('context-content').innerHTML = '<p style="font-size:12px;color:var(--text-dim);">Evidence will appear as experts speak.</p>';
}

function selectSymposium(symId) {
  _activeSymposium = symId;
  _activeExpert = null;
  const sym = _wsData.symposia.find(s => s.id === symId);
  if (!sym) return;
  renderSidebar();

  document.getElementById('input-bar').style.display = 'none';
  document.getElementById('main-content').innerHTML = `
    <div class="main-header">
      <div style="font-size:24px;">⚡</div>
      <div class="header-info">
        <div class="header-name">${esc(sym.title || sym.id)}</div>
        <div class="header-discipline">${sym.format} · ${sym.participant_ids?.length || 0} participants · ${sym.message_count || 0} messages</div>
      </div>
      <div class="main-header-actions">
        <button class="header-action-btn" onclick="runSymposiumRound()" id="btn-run-round">▶ Run Round</button>
        <button class="header-action-btn" onclick="synthesizeSymposium()" id="btn-synthesize" ${sym.has_synthesis ? '' : 'style="display:none;"'}>📋 Synthesize</button>
      </div>
    </div>
    <div id="conversation"><div class="empty-state"><div class="empty-icon">🏛️</div><h2>Symposium</h2><p>Run a round to see the debate.</p></div></div>`;

  showContextPanel();
  switchContextTab('synthesis', document.querySelector('.context-tab:last-child'));
}

async function runSymposiumRound() {
  if (!_activeSymposium) return;
  const btn = document.getElementById('btn-run-round');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Running…'; }

  const conv = document.getElementById('conversation');
  // Clear empty state
  const empty = conv?.querySelector('.empty-state');
  if (empty) empty.remove();

  // Clear previous messages for fresh round
  if (conv) conv.innerHTML = '';

  let currentTyping = null;

  try {
    await streamSSE(
      `${API}/workspace/${_wsId}/symposia/${_activeSymposium}/round`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' },
      (eventType, data) => {
        if (eventType === 'typing') {
          if (currentTyping) currentTyping.remove();
          currentTyping = appendTypingIndicator(data.name);
          // Flash sidebar avatar for active speaker
          highlightSidebarSpeaker(data.name);
        } else if (eventType === 'message') {
          if (currentTyping) currentTyping.remove();
          currentTyping = null;
          const accent = _expertAccents[findExpertIdByName(data.name)] || 'gold';
          appendMessage('agent', data.name, data.content, accent, data.turn);
        } else if (eventType === 'round_complete') {
          toast(`Round complete — ${data.turns} turns`, 'success');
          document.getElementById('btn-synthesize').style.display = '';
        }
      }
    );
  } catch(e) {
    if (currentTyping) currentTyping.remove();
    appendMessage('system', '', `Error: ${e.message}`);
  }

  if (btn) { btn.disabled = false; btn.textContent = '▶ Run Round'; }
  await loadWorkspace(_wsId);
  renderContextPanel(_activeExpert || {}, 'evidence');
}

function highlightSidebarSpeaker(name) {
  document.querySelectorAll('.expert-accent-dot').forEach(d => d.style.boxShadow = 'none');
  document.querySelectorAll('.expert-item').forEach(item => {
    const nameEl = item.querySelector('.expert-name');
    if (nameEl && nameEl.textContent === name) {
      item.style.background = 'var(--bg-card)';
      const dot = item.querySelector('.expert-accent-dot');
      if (dot) dot.style.boxShadow = '0 0 8px currentColor';
      setTimeout(() => { item.style.background = ''; if (dot) dot.style.boxShadow = 'none'; }, 1500);
    }
  });
}

function findExpertIdByName(name) {
  if (!_wsData?.panels) return null;
  for (const p of _wsData.panels)
    for (const e of p.experts)
      if (e.name === name) return e.id;
  return null;
}

async function synthesizeSymposium() {
  if (!_activeSymposium) return;
  toast('Rapporteur is synthesizing…', 'success');
  const btn = document.getElementById('btn-synthesize');
  if (btn) { btn.disabled = true; btn.textContent = '⏳…'; }

  try {
    await streamSSE(
      `${API}/workspace/${_wsId}/symposia/${_activeSymposium}/synthesize`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' },
      (eventType, data) => {
        if (eventType === 'message') {
          appendMessage('agent', 'Rapporteur', data.content, 'gold');
          toast('Synthesis complete!', 'success');
        }
      }
    );
  } catch(e) {
    toast('Failed: ' + e.message, 'error');
  }

  if (btn) { btn.disabled = false; btn.textContent = '📋 Synthesize'; }
  await loadWorkspace(_wsId);
  switchContextTab('synthesis', document.querySelector('.context-tab:last-child'));
}

// ── Modals ───────────────────────────────────────────────────────────────────

function showNewWorkspaceModal() {
  showModal(`<h3>New Workspace</h3><p>Create a new workspace to assemble your council of experts.</p>
    <input id="modal-ws-query" placeholder="Research question or topic (optional)…">
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="createWorkspace()">Create</button></div>`);
}

async function createWorkspace() {
  const query = document.getElementById('modal-ws-query').value.trim();
  closeModal();
  await fetch(`${API}/workspace`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query}) });
  toast('Workspace created', 'success');
  showWorkspaceList();
}

function showNewPanelModal() {
  if (!_wsId) { toast('Load a workspace first', 'error'); return; }
  showModal(`<h3>New Panel</h3><p>The Moderator will research and propose a panel of experts.</p>
    <input id="modal-panel-query" placeholder="Research question…">
    <div class="modal-actions"><button class="modal-btn secondary" onclick="closeModal()">Cancel</button>
    <button class="modal-btn primary" onclick="createPanel()">Propose Panel</button></div>`);
}

async function createPanel() {
  const query = document.getElementById('modal-panel-query').value.trim();
  if (!query) { toast('Enter a research question', 'error'); return; }
  closeModal();
  toast('Moderator is researching…', 'success');
  const resp = await fetch(`${API}/workspace/${_wsId}/panels`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query, max_experts:3}),
  });
  const data = await resp.json();
  await loadWorkspace(_wsId);
  toast(`Panel created with ${data.experts?.length || 0} experts`, 'success');
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
    <div class="empty-state"><div class="empty-icon">🏛️</div>
    <h2>Welcome to The Academy</h2>
    <p>Select an expert from the sidebar to begin, or click ⚡ on a panel to convene a symposium.</p></div>`;
}

function handleInputKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); }
}

function esc(str) {
  if (!str) return '';
  const div = document.createElement('div'); div.textContent = str; return div.innerHTML;
}

function toast(msg, type) {
  const container = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${type}`; el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}
