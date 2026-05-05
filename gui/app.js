// gui/app.js

// ─── Global state ─────────────────────────────────────────────────────────────
let currentSession    = null;  // manifest object from /api/sessions/{id}
let currentAnimationId = 0;

// Live-mode data stores (populated by SSE events)
let _liveResearch = {};        // {expert_id: {name, discipline, status:'researching'|'done', summary}}
let _liveDebateMessages = [];  // [{name, discipline, round, content, turn}]
let _liveCurrentRound  = 0;
let _liveDossier = '';         // accumulated dossier text during streaming
let _liveSSE = null;           // active EventSource, if any
let _reconnectAttempts = 0;    // SSE reconnection counter
let _reconnectTimer = null;    // reconnection timeout ID

// When the GUI is served by council.server (port 8000) this is ''.
// Override to 'http://localhost:8000' if you serve the GUI from a different origin.
const API_BASE = '';

// ─── Index-based color system ─────────────────────────────────────────────────
// Experts are assigned a color by their position in the panel, not by name.
const EXPERT_COLOR_CLASSES = ['expert-cyan', 'expert-magenta', 'expert-green', 'expert-default'];
const CLAIM_COLOR_CLASSES  = ['claim-cyan',  'claim-magenta',  'claim-green',  'claim-default'];

function _expertEntry(name) {
    return currentSession?.experts?.find(e => e.name === name) ?? null;
}
function expertColorClass(name) {
    const idx = _expertEntry(name)?.color_index ?? 3;
    return EXPERT_COLOR_CLASSES[Math.min(idx, 3)];
}
function claimColorMeta(name) {
    const e = _expertEntry(name);
    return {
        cls:   CLAIM_COLOR_CLASSES[Math.min(e?.color_index ?? 3, 3)],
        label: e?.name ?? name,
    };
}
function auditColorClass(marker) {
    return marker === '[RAPPORTEUR]' ? 'rapporteur' : 'discussant';
}

// ─── URL helpers ──────────────────────────────────────────────────────────────
function outputUrl(filename) {
    return `${API_BASE}/outputs/${filename}`;
}

async function fetchText(url) {
    const res = await fetch(url + '?t=' + Date.now());
    if (!res.ok) throw new Error(`Could not load: ${url}`);
    return (await res.text()).replace(/\r\n/g, '\n');
}

// ─── Marked.js config ─────────────────────────────────────────────────────────
marked.setOptions({
    highlight(code, lang) {
        const language = hljs.getLanguage(lang) ? lang : 'plaintext';
        return hljs.highlight(code, { language }).value;
    },
    gfm: true,
    breaks: true,
});

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const contentBody = document.getElementById('content-body');
const phaseTitle  = document.getElementById('phase-title');

const phaseTitles = {
    panel:     'The Expert Panel',
    research:  'Research Library',
    debate:    'The Live Symposium',
    scorecard: 'Evidence Scorecard',
    dossier:   'Final Dossier',
};

// ─── HTML escape ──────────────────────────────────────────────────────────────
function _esc(str) {
    return (str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─── Phase switching ──────────────────────────────────────────────────────────
async function switchPhase(phaseId) {
    // In live mode, allow panel phase without a loaded session (new session wizard)
    if (!currentSession && !(window.SERVER_MODE === 'live' && phaseId === 'panel')) {
        await renderSessionPicker();
        return;
    }

    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.phase === phaseId);
    });

    phaseTitle.innerText = phaseTitles[phaseId] ?? phaseId;
    contentBody.innerHTML = '<div class="loading-spinner"></div>';
    currentAnimationId++;

    try {
        switch (phaseId) {
            case 'panel':     await renderPanelPhase();     break;
            case 'research':  await renderResearchPhase();  break;
            case 'debate':    await renderDebatePhase();    break;
            case 'scorecard': await renderScorecardPhase(); break;
            case 'dossier':   await renderDossierPhase();   break;
        }
    } catch (e) {
        contentBody.innerHTML = `<div class="markdown-content"><p style="color:#ef4444;">${_esc(e.message)}</p></div>`;
    }
}

// ─── Session picker ───────────────────────────────────────────────────────────
async function renderSessionPicker() {
    phaseTitle.innerText = 'Select Session';
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
    contentBody.innerHTML = '<div class="loading-spinner"></div>';

    let sessions = [];
    try {
        const res = await fetch(`${API_BASE}/api/sessions`);
        if (res.ok) sessions = await res.json();
    } catch (_) { /* server not reachable */ }

    if (!sessions.length) {
        contentBody.innerHTML = `
            <div class="panel-editor" style="max-width:600px;margin:0 auto;padding:48px 0;">
                <h2 style="margin-bottom:14px;">No sessions found</h2>
                <p style="color:var(--text-muted);line-height:1.7;">
                    Run the COUNCIL pipeline to produce output files, then start the server:
                </p>
                <pre style="background:rgba(255,255,255,0.04);border:1px solid var(--border-glass);border-radius:8px;
                            padding:14px;margin-top:16px;font-size:13px;color:var(--accent-cyan);">uv run python -m council.server</pre>
                <p style="color:var(--text-muted);margin-top:16px;font-size:13px;">
                    Then open <strong>http://localhost:8000</strong> in your browser.
                </p>
            </div>`;
        return;
    }

    const PHASE_LABELS = { A: 'Panel', B: 'Research', C: 'Debate', D: 'Audit', E: 'Dossier' };

    const cards = sessions.map(s => {
        const phases = (s.phases_complete || [])
            .map(p => `<span class="phase-badge phase-badge-${p.toLowerCase()}">${PHASE_LABELS[p] || p}</span>`)
            .join('');
        const statusCls = s.status === 'done' ? 'status-done' : 'status-partial';
        const q = s.query ? s.query : '';
        const qText = q
            ? `<p class="session-card-query">"${_esc(q.length > 110 ? q.slice(0, 110) + '…' : q)}"</p>`
            : '';
        return `
            <div class="session-card" onclick="loadSession('${s.session_id}')">
                <div class="session-card-header">
                    <span class="session-id-badge">${s.session_id}</span>
                    <span class="session-status ${statusCls}">${s.status}</span>
                </div>
                ${qText}
                <div class="session-phases">${phases}</div>
            </div>`;
    }).join('');

    contentBody.innerHTML = `
        <div style="padding:8px 0;">
            <p style="color:var(--text-muted);font-size:13px;margin-bottom:24px;">
                Select a completed session. All data loads from output files — no tokens used.
            </p>
            <div class="session-grid">${cards}</div>
        </div>`;
}

async function loadSession(sessionId) {
    contentBody.innerHTML = '<div class="loading-spinner"></div>';
    try {
        const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`);
        if (!res.ok) throw new Error(`Session ${sessionId} not found`);
        currentSession = await res.json();

        // Reset panel wizard so it re-populates from the new session
        panelWizardState.experts = [];
        panelWizardState.dirty   = false;
        panelWizardState.step    = 1;
        panelWizardState.visited = new Set([1]);

        const badge = document.getElementById('session-badge-text');
        if (badge) badge.textContent = `Session: ${sessionId}`;

        await switchPhase('panel');
    } catch (e) {
        contentBody.innerHTML = `<div class="markdown-content"><p style="color:#ef4444;">${_esc(e.message)}</p></div>`;
    }
}

function startNewSession() {
    // Warn if a live session is actively running
    if (_liveSSE) {
        if (!confirm('A session pipeline is currently running. Starting a new session will abandon it. Continue?')) {
            return;
        }
        _liveSSE.close();
        _liveSSE = null;
    }

    currentSession = null;
    _liveResearch = {};
    _liveDebateMessages = [];
    _liveCurrentRound = 0;
    _liveDossier = '';
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    _reconnectAttempts = 0;

    if (window.SERVER_MODE === 'live') {
        panelWizardState.query = '';
        panelWizardState.experts = [];
        panelWizardState.sessionId = null;
        panelWizardState.step = 1;
        panelWizardState.dirty = false;
        panelWizardState.visited = new Set([1]);
        const badge = document.getElementById('session-badge-text');
        if (badge) badge.textContent = 'No session loaded';
        switchPhase('panel');
        return;
    }

    const badge = document.getElementById('session-badge-text');
    if (badge) badge.textContent = 'No session loaded';
    renderSessionPicker();
}

// ─── Phase A: Expert Panel ────────────────────────────────────────────────────

const panelWizardState = {
    step:    1,
    query:   '',
    experts: [],
    dirty:   false,
    visited: new Set([1]),
};

async function renderPanelPhase() {
    // Pre-populate from the loaded session manifest
    if (currentSession) {
        panelWizardState.query = currentSession.query || '';
        // Map manifest experts to ExpertDefinition shape used by the editor
        if (panelWizardState.experts.length === 0 && currentSession.experts.length > 0) {
            panelWizardState.experts = currentSession.experts.map(e => ({
                name:          e.name,
                discipline:    e.discipline || '',
                bias:          e.bias       || '',
                persona_prompt: e.persona_prompt || '',
            }));
        }
        panelWizardState.step = 2;
        panelWizardState.visited.add(2);
    }

    panelWizardState.step === 1 ? _renderStep1() : _renderStep2();
}

// ── Stepper ───────────────────────────────────────────────────────────────────

function _renderStepper() {
    const steps = [{ n: 1, label: 'Research Question' }, { n: 2, label: 'Expert Panel' }];
    return `
        <div class="wizard-stepper">
            ${steps.map((s, i) => {
                const visited  = panelWizardState.visited.has(s.n);
                const active   = panelWizardState.step === s.n;
                const done     = visited && !active;
                const cls      = active ? 'step-active' : done ? 'step-done' : 'step-future';
                const clickable = visited ? `onclick="wizardGoTo(${s.n})"` : '';
                return `
                    ${i > 0 ? '<div class="wizard-connector"></div>' : ''}
                    <div class="wizard-step ${clickable ? 'step-clickable' : ''}" ${clickable}>
                        <div class="wizard-dot ${cls}">${done ? '✓' : s.n}</div>
                        <span class="wizard-label ${cls}">${s.label}</span>
                    </div>`;
            }).join('')}
        </div>`;
}

// ── Step 1: Research question ─────────────────────────────────────────────────

function _renderStep1() {
    contentBody.innerHTML = `
        <div class="panel-editor wizard-panel">
            ${_renderStepper()}
            <div class="question-stage">
                <div class="question-prompt">
                    <h2 class="question-title">What would you like to investigate?</h2>
                    <p class="question-hint">Be as specific as possible. The Moderator will design a panel of experts optimised for your exact question.</p>
                </div>
                <textarea id="query-input" class="question-input" rows="5"
                    placeholder="e.g. Can we simulate froth flotation images indistinguishable from real ones using only operational variables and a small training set?"
                    oninput="onQueryInput()"
                >${_esc(panelWizardState.query)}</textarea>
                <div class="question-meta">
                    <span id="query-char-count" class="query-char">${panelWizardState.query.length} chars</span>
                    <span class="query-tip">Press <kbd>Ctrl</kbd>+<kbd>Enter</kbd> to generate panel</span>
                </div>
            </div>
            <div class="wizard-nav">
                <div></div>
                <button class="panel-btn panel-btn-proceed" id="generate-btn"
                    onclick="wizardAdvance()"
                    ${panelWizardState.query.trim().length < 10 ? 'disabled' : ''}>
                    Generate Panel →
                </button>
            </div>
        </div>`;

    const input = document.getElementById('query-input');
    if (input) {
        input.focus();
        input.addEventListener('keydown', e => { if (e.ctrlKey && e.key === 'Enter') wizardAdvance(); });
    }
}

window.onQueryInput = function () {
    const val = document.getElementById('query-input')?.value || '';
    panelWizardState.query = val;
    const counter = document.getElementById('query-char-count');
    if (counter) counter.textContent = `${val.length} chars`;
    const btn = document.getElementById('generate-btn');
    if (btn) btn.disabled = val.trim().length < 10;
};

// ── Step 2: Panel editor ──────────────────────────────────────────────────────

function _renderStep2() {
    const experts = panelWizardState.experts;
    const rows = experts.map((e, i) => `
        <tr id="expert-row-${i}">
            <td><input class="panel-input" id="pname-${i}"    value="${_esc(e.name)}"           oninput="onPanelEdit()" /></td>
            <td><textarea class="panel-textarea" id="pdisc-${i}" rows="3" oninput="onPanelEdit()">${_esc(e.discipline)}</textarea></td>
            <td><textarea class="panel-textarea" id="pbias-${i}" rows="3" oninput="onPanelEdit()">${_esc(e.bias)}</textarea></td>
            <td><textarea class="panel-textarea" id="ppersona-${i}" rows="3" oninput="onPanelEdit()">${_esc(e.persona_prompt)}</textarea></td>
            <td><button class="panel-remove-btn" onclick="removeExpert(${i})" title="Remove">✕</button></td>
        </tr>`).join('');

    contentBody.innerHTML = `
        <div class="panel-editor wizard-panel">
            ${_renderStepper()}
            <div class="query-review-bar">
                <span class="query-review-label">Research Question:</span>
                <span class="query-review-text">${_esc(panelWizardState.query)}</span>
            </div>
            <div class="panel-header-row">
                <h2 class="panel-title">Expert Panel</h2>
                <span class="panel-count-badge">${experts.length} Expert${experts.length !== 1 ? 's' : ''}</span>
            </div>
            <p class="panel-subtitle">Review and customise each expert before the symposium begins.</p>
            <div class="panel-table-wrapper">
                <table class="panel-table">
                    <thead><tr>
                        <th>Name</th><th>Discipline</th><th>Intellectual Bias</th><th>Persona</th><th></th>
                    </tr></thead>
                    <tbody id="panel-tbody">${rows}</tbody>
                </table>
            </div>
            <div class="panel-actions">
                <div class="panel-action-group">
                    <button class="panel-btn panel-btn-secondary" onclick="addExpert()">+ Add Expert</button>
                </div>
                <div class="panel-action-group panel-action-right">
                    <div class="panel-regen-group">
                        <button class="panel-btn panel-btn-secondary" onclick="regeneratePanel()">⟳ Regenerate with</button>
                        <input type="number" id="regen-count" class="panel-spinbox" value="${experts.length || 5}" min="2" max="6" />
                        <span class="panel-spinbox-label">experts</span>
                    </div>
                    <button class="panel-btn panel-btn-polish" id="polish-btn" onclick="polishPanel()" ${panelWizardState.dirty ? '' : 'disabled'}>
                        ✦ Polish &amp; Align
                    </button>
                    <button class="panel-btn panel-btn-proceed" onclick="proceedPanel()">Proceed →</button>
                </div>
            </div>
            <div class="wizard-nav wizard-nav-back">
                <button class="panel-btn panel-btn-ghost" onclick="wizardRevert()">← Back to Question</button>
            </div>
        </div>`;
}

// ── Wizard navigation ─────────────────────────────────────────────────────────

window.wizardGoTo = function (step) {
    if (!panelWizardState.visited.has(step)) return;
    if (panelWizardState.step === 2) _readPanelFromDOM();
    panelWizardState.step = step;
    renderPanelPhase();
};

window.wizardAdvance = async function () {
    const q = document.getElementById('query-input')?.value?.trim() || panelWizardState.query.trim();
    if (q.length < 10) return;

    const questionChanged = q !== panelWizardState.query;
    if (panelWizardState.visited.has(2) && panelWizardState.experts.length > 0 && questionChanged) {
        if (!confirm('Changing the research question will clear the current panel. Continue?')) return;
        panelWizardState.experts = [];
        panelWizardState.dirty   = false;
    }
    panelWizardState.query = q;

    // Live mode: call the moderator API
    if (window.SERVER_MODE === 'live') {
        await _liveGeneratePanel(q, 5);
        return;
    }

    // Review mode: show spinner then try to load from session files
    contentBody.innerHTML = `
        <div class="panel-editor wizard-panel" style="align-items:center;justify-content:center;gap:16px;">
            ${_renderStepper()}
            <div style="text-align:center;padding:60px 0;">
                <div class="loading-spinner"></div>
                <p style="margin-top:20px;color:var(--text-muted);font-size:14px;">
                    Assembling your expert panel<span class="dots"><span>.</span><span>.</span><span>.</span></span>
                </p>
            </div>
        </div>`;

    await new Promise(r => setTimeout(r, 1400));

    try {
        await _loadExpertsIfNeeded();
        panelWizardState.step = 2;
        panelWizardState.visited.add(2);
        _renderStep2();
    } catch (e) {
        contentBody.innerHTML = `<p style="color:red;padding:20px">${_esc(e.message)}</p>`;
    }
};

async function _liveGeneratePanel(query, expertCount) {
    contentBody.innerHTML = `
        <div class="panel-editor wizard-panel" style="align-items:center;justify-content:center;gap:16px;">
            ${_renderStepper()}
            <div style="text-align:center;padding:60px 0;">
                <div class="loading-spinner"></div>
                <p style="margin-top:20px;color:var(--text-muted);font-size:14px;">
                    Moderator is assembling your expert panel<span class="dots"><span>.</span><span>.</span><span>.</span></span>
                </p>
            </div>
        </div>`;

    let res;
    try {
        res = await fetch(`${API_BASE}/api/sessions/generate-panel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, expert_count: expertCount }),
        });
    } catch (e) {
        contentBody.innerHTML = `<div class="markdown-content"><p style="color:#ef4444;padding:40px;">
            Cannot reach the server. Make sure it's running in live mode:
            <pre style="margin-top:12px;">uv run python -m council.server --mode live</pre></p></div>`;
        return;
    }

    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        contentBody.innerHTML = `<div class="markdown-content"><p style="color:#ef4444;padding:40px;">
            ${_esc(err.detail || 'Failed to generate panel. Check the server logs.')}</p></div>`;
        return;
    }

    const data = await res.json();
    panelWizardState.sessionId = data.session_id;
    panelWizardState.experts = data.experts.map((e, i) => ({
        name:           e.name,
        discipline:     e.discipline || '',
        bias:           e.bias || '',
        persona_prompt: e.persona_prompt || '',
    }));

    // Build minimal currentSession so expertColorClass/Phase views work in live mode
    currentSession = {
        session_id: data.session_id,
        query:      data.query,
        status:     'live',
        experts:    data.experts.map((e, i) => ({
            name: e.name, discipline: e.discipline, color_index: i,
        })),
        files: { panel: null, research: null, rounds: null, dossier: null },
        phases_complete: ['A'],
    };

    panelWizardState.dirty = false;
    panelWizardState.step = 2;
    panelWizardState.visited.add(2);

    const badge = document.getElementById('session-badge-text');
    if (badge) badge.textContent = `Session: ${data.session_id}`;

    _renderStep2();
}

window.wizardRevert = function () {
    if (panelWizardState.step === 2) _readPanelFromDOM();
    panelWizardState.step = 1;
    _renderStep1();
};

// ── Panel helpers ─────────────────────────────────────────────────────────────

async function _loadExpertsIfNeeded() {
    if (panelWizardState.experts.length > 0) return;
    const panelFile = currentSession?.files?.panel;
    if (!panelFile) throw new Error('No panel file found in this session.');
    const res = await fetch(outputUrl(panelFile) + '?t=' + Date.now());
    if (!res.ok) throw new Error('Could not load panel data.');
    panelWizardState.experts = await res.json();
}

function _readPanelFromDOM() {
    panelWizardState.experts = panelWizardState.experts.map((_, i) => ({
        name:          document.getElementById(`pname-${i}`)?.value    || '',
        discipline:    document.getElementById(`pdisc-${i}`)?.value    || '',
        bias:          document.getElementById(`pbias-${i}`)?.value    || '',
        persona_prompt: document.getElementById(`ppersona-${i}`)?.value || '',
    }));
}

window.onPanelEdit = function () {
    panelWizardState.dirty = true;
    const btn = document.getElementById('polish-btn');
    if (btn) btn.disabled = false;
};

window.removeExpert = function (index) {
    _readPanelFromDOM();
    panelWizardState.experts.splice(index, 1);
    _renderStep2();
    onPanelEdit();
};

window.addExpert = function () {
    _readPanelFromDOM();
    panelWizardState.experts.push({
        name:           'Dr. New Expert',
        discipline:     'Field of Study',
        bias:           'Methodological leaning.',
        persona_prompt: "Describe this expert's personality and approach in 2-3 sentences.",
    });
    _renderStep2();
    onPanelEdit();
    setTimeout(() => {
        document.getElementById(`expert-row-${panelWizardState.experts.length - 1}`)
            ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);
};

window.regeneratePanel = async function () {
    const count = parseInt(document.getElementById('regen-count')?.value) || 5;

    if (window.SERVER_MODE === 'live') {
        const q = panelWizardState.query.trim();
        if (q.length < 10) { alert('Please enter a research question first.'); return; }
        const btn = document.querySelector('.panel-regen-group .panel-btn');
        if (btn) { btn.disabled = true; btn.textContent = '⟳ Generating…'; }
        await _liveGeneratePanel(q, count);
        return;
    }

    alert(`To regenerate with ${count} experts, run:\n\nuv run python -m council.main "${panelWizardState.query}" --experts ${count}`);
};

window.polishPanel = function () {
    _readPanelFromDOM();
    const btn = document.getElementById('polish-btn');
    if (btn) { btn.disabled = true; btn.textContent = '✦ Polishing…'; }
    setTimeout(() => {
        panelWizardState.experts = panelWizardState.experts.map(e => ({
            ...e,
            bias:          e.bias.trim().endsWith('.')          ? e.bias.trim()          : e.bias.trim() + '.',
            persona_prompt: e.persona_prompt.trim(),
        }));
        panelWizardState.dirty = false;
        _renderStep2();
    }, 800);
};

window.proceedPanel = async function () {
    _readPanelFromDOM();

    if (window.SERVER_MODE === 'live') {
        const sessionId = panelWizardState.sessionId;
        if (!sessionId) { alert('No session. Generate a panel first.'); return; }

        // Save the edited panel to the server
        let proceedRes;
        try {
            proceedRes = await fetch(`${API_BASE}/api/sessions/${sessionId}/proceed`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: panelWizardState.query,
                    experts: panelWizardState.experts,
                }),
            });
        } catch (e) {
            alert('Cannot reach the server. Make sure it is running in live mode.'); return;
        }

        if (!proceedRes.ok) {
            const err = await proceedRes.json().catch(() => ({}));
            alert('Failed to start session: ' + (err.detail || proceedRes.statusText));
            return;
        }

        // Switch to live dashboard and connect SSE
        _connectLiveSSE(sessionId);
        return;
    }

    alert(`Panel of ${panelWizardState.experts.length} experts confirmed.\n\nTo run the full pipeline:\nuv run python -m council.main "${panelWizardState.query}" --no-confirm`);
};

// ─── Phase B: Research Library ────────────────────────────────────────────────

async function renderResearchPhase() {
    // Live mode: render from accumulated SSE research data
    if (Object.keys(_liveResearch).length > 0 || _liveSSE) {
        _renderLiveResearchPhase();
        return;
    }

    // Review mode: render from files
    const researchFiles = currentSession?.files?.research ?? [];
    if (!researchFiles.length) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">No research files available for this session.</p>';
        return;
    }

    let tabsHtml    = '<div class="sub-tabs">';
    let contentHtml = '<div class="sub-tab-content">';

    for (let i = 0; i < researchFiles.length; i++) {
        const rf          = researchFiles[i];
        const activeClass = i === 0 ? 'active' : '';
        const displayStyle = i === 0 ? 'block' : 'none';

        tabsHtml += `<button class="sub-tab-btn ${activeClass}" onclick="switchSubTab(${i})">${_esc(rf.expert_name)}</button>`;

        try {
            let bodyText = await fetchText(outputUrl(rf.file));

            bodyText = bodyText.replace(/^##\s+(Dr\.|Prof\.|Aggregator Summary).*?\n+/i, '');
            bodyText = bodyText.replace(/^---\s*$/gm, '');

            const stop = '(?=\\n\\n\\*\\*|\\n\\n### |\\n\\n## |\\n\\n---|$)';
            let parsed = bodyText
                .replace(new RegExp(`\\*\\*Source:\\*\\*\\s*(.*?)${stop}`,             'gs'), '<div class="finding-block source-block"><strong>Source:</strong> $1</div>')
                .replace(new RegExp(`\\*\\*Supporting Source:\\*\\*\\s*(.*?)${stop}`,  'gs'), '<div class="finding-block support-block"><strong>Supporting Source:</strong> $1</div>')
                .replace(new RegExp(`\\*\\*Key Finding:\\*\\*\\s*(.*?)${stop}`,        'gs'), '<div class="finding-block key-block"><strong>Key Finding:</strong> $1</div>')
                .replace(new RegExp(`\\*\\*Relevance[^\\*]*:\\*\\*\\s*(.*?)${stop}`,  'gs'), '<div class="finding-block rel-block"><strong>Relevance:</strong> $1</div>');

            const sections = parsed.split(/\n## /);
            let tabHtml = '';
            if (sections[0].trim())
                tabHtml += `<div class="markdown-content header-section">${marked.parse(sections[0])}</div>`;
            for (let j = 1; j < sections.length; j++)
                tabHtml += `<div class="section-card"><div class="markdown-content">${marked.parse('## ' + sections[j])}</div></div>`;

            contentHtml += `<div class="sub-tab-pane" id="expert-pane-${i}" style="display:${displayStyle};">${tabHtml}</div>`;
        } catch (e) {
            contentHtml += `<div class="sub-tab-pane" id="expert-pane-${i}" style="display:${displayStyle};">
                <p style="color:red">Failed to load ${_esc(rf.expert_name)}: ${_esc(e.message)}</p></div>`;
        }
    }

    contentBody.innerHTML = tabsHtml + '</div>' + contentHtml + '</div>';
}

function _renderLiveResearchPhase() {
    const entries = Object.values(_liveResearch);
    if (!entries.length) {
        contentBody.innerHTML = `
            <div style="text-align:center;padding:60px 0;">
                <div class="loading-spinner"></div>
                <p style="margin-top:20px;color:var(--text-muted);">Initialising research phase…</p>
            </div>`;
        return;
    }

    const allDone = entries.every(r => r.status === 'done');

    // While experts are still researching, show live status cards
    if (!allDone) {
        const cards = entries.map(r => {
            const spinning = r.status === 'researching';
            const statusIcon = spinning
                ? '<span class="live-research-spinner"></span>'
                : '<span class="live-research-check">✓</span>';
            const statusText = spinning ? 'Searching the literature…' : 'Research complete';
            const cardClass = spinning ? 'researching' : 'research-done';
            const summaryHtml = (!spinning && r.summary)
                ? `<div class="live-research-summary markdown-content">${marked.parse(r.summary)}</div>`
                : '';

            return `
                <div class="live-research-card ${cardClass}">
                    <div class="live-research-header">
                        ${statusIcon}
                        <strong>${_esc(r.name)}</strong>
                        <span class="live-research-disc">${_esc(r.discipline)}</span>
                    </div>
                    <div class="live-research-status">${statusText}</div>
                    ${summaryHtml}
                </div>`;
        }).join('');

        contentBody.innerHTML = `
            <div style="padding:8px 0;">
                <p style="color:var(--text-muted);margin-bottom:20px;">Experts are researching in parallel — results appear as they complete.</p>
                <div class="live-research-grid">${cards}</div>
            </div>`;
        return;
    }

    // All done — build research file list from _liveResearch and render tabbed view
    const sid = currentSession?.session_id;
    if (!sid) { return; }

    const expertObjs = Object.entries(_liveResearch);
    // Build file list matching the naming convention: {sid}_research_{expert_id}.md
    const researchFiles = expertObjs.map(([id, r]) => ({
        expert_id: id,
        expert_name: r.name,
        file: `${sid}_research_${id}.md`,
    }));

    let tabsHtml    = '<div class="sub-tabs">';
    let contentHtml = '<div class="sub-tab-content">';

    Promise.all(researchFiles.map(async (rf, i) => {
        const activeClass = i === 0 ? 'active' : '';
        const displayStyle = i === 0 ? 'block' : 'none';

        tabsHtml += `<button class="sub-tab-btn ${activeClass}" onclick="switchSubTab(${i})">${_esc(rf.expert_name)}</button>`;

        try {
            let bodyText = await fetchText(outputUrl(rf.file));

            bodyText = bodyText.replace(/^##\s+(Dr\.|Prof\.|Aggregator Summary).*?\n+/i, '');
            bodyText = bodyText.replace(/^---\s*$/gm, '');

            const stop = '(?=\\n\\n\\*\\*|\\n\\n### |\\n\\n## |\\n\\n---|$)';
            let parsed = bodyText
                .replace(new RegExp(`\\*\\*Source:\\*\\*\\s*(.*?)${stop}`,             'gs'), '<div class="finding-block source-block"><strong>Source:</strong> $1</div>')
                .replace(new RegExp(`\\*\\*Supporting Source:\\*\\*\\s*(.*?)${stop}`,  'gs'), '<div class="finding-block support-block"><strong>Supporting Source:</strong> $1</div>')
                .replace(new RegExp(`\\*\\*Key Finding:\\*\\*\\s*(.*?)${stop}`,        'gs'), '<div class="finding-block key-block"><strong>Key Finding:</strong> $1</div>')
                .replace(new RegExp(`\\*\\*Relevance[^\\*]*:\\*\\*\\s*(.*?)${stop}`,  'gs'), '<div class="finding-block rel-block"><strong>Relevance:</strong> $1</div>');

            const sections = parsed.split(/\n## /);
            let tabHtml = '';
            if (sections[0].trim())
                tabHtml += `<div class="markdown-content header-section">${marked.parse(sections[0])}</div>`;
            for (let j = 1; j < sections.length; j++)
                tabHtml += `<div class="section-card"><div class="markdown-content">${marked.parse('## ' + sections[j])}</div></div>`;

            contentHtml += `<div class="sub-tab-pane" id="expert-pane-${i}" style="display:${displayStyle};">${tabHtml}</div>`;
        } catch (e) {
            contentHtml += `<div class="sub-tab-pane" id="expert-pane-${i}" style="display:${displayStyle};">
                <p style="color:red">Failed to load ${_esc(rf.expert_name)}: ${_esc(e.message)}</p></div>`;
        }
    })).then(() => {
        contentBody.innerHTML = `
            <div style="padding:8px 0;">
                <p style="color:#22c55e;margin-bottom:20px;">✓ All ${entries.length} experts have completed their research.</p>
                ${tabsHtml}</div>${contentHtml}</div>`;
    });
}

window.switchSubTab = function (index) {
    document.querySelectorAll('.sub-tab-btn').forEach((btn, i) => btn.classList.toggle('active', i === index));
    document.querySelectorAll('.sub-tab-pane').forEach((pane, i) => { pane.style.display = i === index ? 'block' : 'none'; });
};

// ─── Phase C: The Live Symposium ──────────────────────────────────────────────

async function renderDebatePhase() {
    // Live mode: render from accumulated live debate messages
    if (_liveDebateMessages.length > 0 || _liveSSE) {
        _renderLiveDebatePhase();
        return;
    }

    // Review mode: render from transcript files
    const animId = currentAnimationId;
    const rounds = currentSession?.files?.rounds ?? [];

    if (!rounds.length) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">No debate transcript available for this session.</p>';
        return;
    }

    contentBody.innerHTML = `<div class="chat-container" id="chat-container"></div>`;
    const chatContainer = document.getElementById('chat-container');

    for (const roundInfo of rounds) {
        if (!roundInfo.transcript || animId !== currentAnimationId) return;

        let text;
        try {
            text = await fetchText(outputUrl(roundInfo.transcript));
        } catch (_) { continue; }

        await _animateTranscript(text, animId, chatContainer, roundInfo.round);
    }
}

function _renderLiveDebatePhase() {
    const msgs = _liveDebateMessages;
    if (!msgs.length) {
        contentBody.innerHTML = `
            <div style="text-align:center;padding:60px 0;">
                <div class="loading-spinner"></div>
                <p style="margin-top:20px;color:var(--text-muted);">Waiting for the symposium to begin…</p>
            </div>`;
        return;
    }

    // Render all accumulated messages into the chat container
    let html = '<div class="chat-container" id="chat-container">';
    let lastRound = 0;

    for (const msg of msgs) {
        // Round divider
        if (msg.round !== lastRound) {
            lastRound = msg.round;
            html += `<div class="round-divider"><span>── Round ${msg.round} ──</span></div>`;
        }

        const isAudit = msg.name === 'Rapporteur' || msg.name === 'Discussant';
        const colorCls = isAudit
            ? (msg.name === 'Rapporteur' ? 'rapporteur' : 'discussant')
            : expertColorClass(msg.name);
        const sideCls = isAudit ? 'message-right' : '';
        const avatar = isAudit
            ? (msg.name === 'Rapporteur' ? '⚖' : '🔬')
            : msg.name.replace(/^(Dr\.|Prof\.) /, '').substring(0, 1);

        html += `
            <div class="chat-message ${sideCls} ${colorCls}">
                <div class="chat-avatar">${_esc(avatar)}</div>
                <div class="chat-bubble-wrapper">
                    <div class="chat-header">
                        <strong>${_esc(msg.name)}</strong>
                        <span>${_esc(msg.discipline || '')}</span>
                    </div>
                    <div class="chat-bubble markdown-content">${marked.parse(msg.content)}</div>
                </div>
            </div>`;
    }

    html += '</div>';
    contentBody.innerHTML = html;

    // Scroll to bottom
    const chat = document.getElementById('chat-container');
    if (chat) chat.scrollTop = chat.scrollHeight;
}

async function _animateTranscript(text, animId, chatContainer, roundIndex) {
    const msgRegex = /(\[Turn \d+\]|\[RAPPORTEUR\]|\[DISCUSSANT\]) \*\*(.*?)\*\* \((.*?)\):\n([\s\S]*?)(?=\n(?:\[Turn \d+\]|\[RAPPORTEUR\]|\[DISCUSSANT\])|$)/g;

    const messages = [];
    let currentRound = roundIndex + 1;
    let m;

    while ((m = msgRegex.exec(text)) !== null) {
        const marker  = m[1];
        const name    = m[2];
        const meta    = m[3];
        const content = m[4].trim();

        const rm = meta.match(/Round (\d+)/);
        if (rm) currentRound = parseInt(rm[1]);

        messages.push({
            marker, name, meta, content, round: currentRound,
            isAudit:  marker === '[RAPPORTEUR]' || marker === '[DISCUSSANT]',
            isRapporteur: marker === '[RAPPORTEUR]',
            isDiscussant: marker === '[DISCUSSANT]',
        });
    }

    if (!messages.length) return;

    let renderedRound = null;

    for (const msg of messages) {
        if (animId !== currentAnimationId) return;

        // Round divider when round number changes
        if (msg.round !== renderedRound) {
            renderedRound = msg.round;
            const divider = document.createElement('div');
            divider.className = 'round-divider';
            divider.innerHTML = `<span>── Round ${msg.round} ──</span>`;
            chatContainer.appendChild(divider);
        }

        // Typing indicator
        const indicatorText = msg.isRapporteur
            ? `<strong>Rapporteur</strong> is drafting consensus<span class="dots"><span>.</span><span>.</span><span>.</span></span>`
            : msg.isDiscussant
            ? `<strong>Discussant</strong> is auditing the synthesis<span class="dots"><span>.</span><span>.</span><span>.</span></span>`
            : `<strong>${_esc(msg.name)}</strong> is formulating argument<span class="dots"><span>.</span><span>.</span><span>.</span></span>`;

        const indicator = document.createElement('div');
        indicator.className = `chat-indicator ${msg.isAudit ? 'indicator-right' : ''}`;
        indicator.innerHTML = indicatorText;
        chatContainer.appendChild(indicator);
        chatContainer.scrollTop = chatContainer.scrollHeight;

        await new Promise(r => setTimeout(r, 1200));
        if (animId !== currentAnimationId) return;
        indicator.remove();

        // Message bubble
        const msgWrapper = document.createElement('div');
        msgWrapper.className = `chat-message ${msg.isAudit ? 'message-right ' + auditColorClass(msg.marker) : expertColorClass(msg.name)}`;

        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = msg.isRapporteur ? '⚖' : msg.isDiscussant ? '🔬'
            : msg.name.replace(/^(Dr\.|Prof\.) /, '').substring(0, 1);

        const bubbleWrapper = document.createElement('div');
        bubbleWrapper.className = 'chat-bubble-wrapper';

        const header = document.createElement('div');
        header.className = 'chat-header';
        header.innerHTML = `<strong>${_esc(msg.name)}</strong> <span>${_esc(msg.meta)}</span>`;

        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble markdown-content';

        if (msg.isDiscussant) {
            const approved = /\"approved\":\s*true/i.test(msg.content) || /\bAPPROVED\b/i.test(msg.content);
            const badge = document.createElement('div');
            badge.className = `verdict-badge ${approved ? 'verdict-approved' : 'verdict-rejected'}`;
            badge.textContent = approved ? '✓ APPROVED' : '✗ REJECTED';
            bubbleWrapper.append(header, badge, bubble);
        } else {
            bubbleWrapper.append(header, bubble);
        }

        msg.isAudit ? msgWrapper.append(bubbleWrapper, avatar) : msgWrapper.append(avatar, bubbleWrapper);
        chatContainer.appendChild(msgWrapper);

        // Word-by-word typewriter
        let streamed = '';
        const words = msg.content.split(/(\s+)/);
        for (const word of words) {
            if (animId !== currentAnimationId) return;
            streamed += word;
            if (word.trim()) {
                bubble.innerHTML = marked.parse(streamed);
                chatContainer.scrollTop = chatContainer.scrollHeight;
                await new Promise(r => setTimeout(r, Math.random() * 20 + 15));
            }
        }

        await new Promise(r => setTimeout(r, 800));
    }
}

// ─── Phase D: Evidence Scorecard ─────────────────────────────────────────────

async function renderScorecardPhase() {
    // Live mode: show scorecard-relevant audit messages
    if (_liveSSE) {
        const auditMsgs = _liveDebateMessages.filter(m =>
            m.name === 'Rapporteur' || m.name === 'Discussant'
        );
        if (!auditMsgs.length) {
            contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted);text-align:center;">Evidence scorecard will be compiled after the debate round…</p>';
            return;
        }
        contentBody.innerHTML = `
            <div style="padding:16px;">
                <h3 style="color:var(--text-muted);margin-bottom:12px;">Live Audit Summary</h3>
                ${auditMsgs.map(m => `
                    <div class="chat-message message-right ${m.name === 'Rapporteur' ? 'rapporteur' : 'discussant'}">
                        <div class="chat-avatar">${m.name === 'Rapporteur' ? '⚖' : '🔬'}</div>
                        <div class="chat-bubble-wrapper">
                            <div class="chat-header">
                                <strong>${_esc(m.name)}</strong>
                                <span>${_esc(m.discipline || '')}</span>
                            </div>
                            <div class="chat-bubble markdown-content">${marked.parse(m.content)}</div>
                        </div>
                    </div>
                `).join('')}
                <p style="color:var(--text-muted);text-align:center;margin-top:16px;">Scorecard will finalize when the audit completes…</p>
            </div>`;
        return;
    }

    const rounds = currentSession?.files?.rounds ?? [];
    if (!rounds.length) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">No scorecard available for this session.</p>';
        return;
    }
    const lastRound = [...rounds].reverse().find(r => r.scorecard);

    if (!lastRound?.scorecard) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">No scorecard available for this session.</p>';
        return;
    }

    const text = await fetchText(outputUrl(lastRound.scorecard));
    const entryRegex = /^•\s+\[([^\]]+)\]\s+"([^"]+)"\s+→\s+(\S+)/;
    const entries = text.split('\n')
        .map(l => l.match(entryRegex))
        .filter(Boolean)
        .map(m => ({ name: m[1], claim: m[2], url: m[3] }));

    if (!entries.length) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">No evidence entries found.</p>';
        return;
    }

    const experts = [...new Set(entries.map(e => e.name))];

    function buildGrid(filter) {
        return (filter === 'all' ? entries : entries.filter(e => e.name === filter))
            .map((e, i) => {
                const meta   = claimColorMeta(e.name);
                const isUncited = e.url === 'UNCITED' || e.url.startsWith('⚠');
                const sourceHtml = isUncited
                    ? `<span class="claim-source claim-uncited">⚠ UNCITED — no verifiable source found</span>`
                    : (() => {
                        const domain = (() => { try { return new URL(e.url).hostname; } catch { return e.url; } })();
                        return `<a class="claim-source" href="${_esc(e.url)}" target="_blank" rel="noopener">
                            View Source → <span class="claim-domain">${_esc(domain)}</span>
                        </a>`;
                    })();
                return `
                    <div class="claim-card ${meta.cls} ${isUncited ? 'claim-uncited-card' : ''}" id="claim-${i}">
                        <div class="claim-expert-chip">${_esc(e.name)}</div>
                        <p class="claim-text">"${_esc(e.claim)}"</p>
                        ${sourceHtml}
                    </div>`;
            }).join('');
    }

    contentBody.innerHTML = `
        <div class="scorecard-wrapper">
            <div class="scorecard-toolbar">
                <div class="scorecard-filters" id="sc-filters">
                    <button class="sc-filter-btn active" onclick="setScorecardFilter('all',this)">
                        All <span class="sc-count">${entries.length}</span>
                    </button>
                    ${experts.map(n => `
                        <button class="sc-filter-btn" data-filter="${_esc(n)}" onclick="setScorecardFilter(this.dataset.filter,this)">
                            ${_esc(n)} <span class="sc-count">${entries.filter(e=>e.name===n).length}</span>
                        </button>`).join('')}
                </div>
                <span class="sc-total-label">${entries.length} citations verified</span>
            </div>
            <div class="scorecard-grid" id="scorecard-grid">${buildGrid('all')}</div>
        </div>`;

    window.setScorecardFilter = function (filter, btn) {
        document.querySelectorAll('.sc-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('scorecard-grid').innerHTML = buildGrid(filter);
    };
}

// ─── Phase E: Final Dossier ───────────────────────────────────────────────────

async function renderDossierPhase() {
    // Live mode: show streaming dossier content
    if (_liveSSE) {
        if (!_liveDossier) {
            contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted);text-align:center;">Dossier is being compiled — it will appear here as it streams in…</p>';
            return;
        }
        contentBody.innerHTML = `
            <div style="padding:16px;position:relative;">
                <div style="position:sticky;top:0;background:var(--bg-primary);padding:8px 12px;border-bottom:1px solid var(--border-color);margin-bottom:16px;display:flex;align-items:center;gap:8px;">
                    <span style="color:var(--text-muted);">📄 Dossier compiling in real-time</span>
                    <span class="dots"><span>.</span><span>.</span><span>.</span></span>
                </div>
                <div class="markdown-content" style="max-width:900px;margin:0 auto;">
                    ${marked.parse(_liveDossier)}
                </div>
            </div>`;
        return;
    }

    const dossierFile = currentSession?.files?.dossier;
    if (!dossierFile) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">Dossier not yet generated for this session.</p>';
        return;
    }

    const rawText = await fetchText(outputUrl(dossierFile));

    const headings = [];
    rawText.split('\n').forEach(line => {
        const m = line.match(/^##\s+(.+)/);
        if (m) {
            const anchor = m[1].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
            headings.push({ text: m[1], anchor });
        }
    });

    const tocHtml = headings.map(h =>
        `<li><a class="toc-link" href="#${h.anchor}" onclick="scrollToHeading('${h.anchor}',event)">${_esc(h.text)}</a></li>`
    ).join('');

    contentBody.innerHTML = `
        <div class="dossier-layout">
            <aside class="dossier-toc">
                <div class="toc-header">Contents</div>
                <ul class="toc-list">${tocHtml}</ul>
                <div class="toc-actions">
                    <button class="toc-action-btn" onclick="downloadDossier()" title="Download .md">⬇ Download</button>
                    <button class="toc-action-btn" onclick="copyDossier()" id="copy-btn" title="Copy to clipboard">⎘ Copy</button>
                </div>
            </aside>
            <div class="dossier-body markdown-content" id="dossier-body">${marked.parse(rawText)}</div>
        </div>`;

    document.querySelectorAll('.dossier-body h2').forEach(el => {
        el.id = el.textContent.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
    });

    window._dossierRawText  = rawText;
    window._dossierFilename = dossierFile;

    window.scrollToHeading = function (anchor, e) {
        e.preventDefault();
        const heading = document.getElementById(anchor);
        const body = document.querySelector('.dossier-body');
        if (heading && body) {
            const offset = heading.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
            body.scrollTo({ top: offset - 20, behavior: 'smooth' });
        }
        document.querySelectorAll('.toc-link').forEach(l => l.classList.remove('toc-active'));
        e.target.classList.add('toc-active');
    };

    window.downloadDossier = function () {
        const blob = new Blob([window._dossierRawText], { type: 'text/markdown' });
        const a    = document.createElement('a');
        a.href     = URL.createObjectURL(blob);
        a.download = window._dossierFilename;
        a.click();
        URL.revokeObjectURL(a.href);
    };

    window.copyDossier = function () {
        navigator.clipboard.writeText(window._dossierRawText).then(() => {
            const btn = document.getElementById('copy-btn');
            if (btn) { btn.textContent = '✓ Copied'; setTimeout(() => btn.textContent = '⎘ Copy', 2000); }
        });
    };
}

// ─── Live SSE connection ──────────────────────────────────────────────────────

function _connectLiveSSE(sessionId) {
    // Initialize live data stores
    _liveResearch = {};
    _liveDebateMessages = [];
    _liveCurrentRound = 0;
    _liveDossier = '';
    _reconnectAttempts = 0;
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    if (_liveSSE) { _liveSSE.close(); _liveSSE = null; }
    _liveSSE = new EventSource(`${API_BASE}/api/sessions/${sessionId}/live`);

    _liveSSE.addEventListener('session_start', (e) => {
        const data = JSON.parse(e.data);
        showToast(`Session started — Phase B begins`, 'info');
    });

    _liveSSE.addEventListener('phase_start', (e) => {
        const data = JSON.parse(e.data);
        if (data.phase === 'C') {
            switchPhase('debate');
            showToast('Symposium begins — experts are debating', 'info');
        } else if (data.phase === 'E') {
            switchPhase('dossier');
            showToast('Compiling final dossier', 'info');
        }
        // Mark phase as active in the current session
        if (currentSession && currentSession.phases_complete) {
            if (!currentSession.phases_complete.includes(data.phase)) {
                currentSession.phases_complete.push(data.phase);
            }
        }
    });

    _liveSSE.addEventListener('research_start', (e) => {
        const data = JSON.parse(e.data);
        _liveResearch[data.expert_id] = {
            name: data.expert_name,
            discipline: data.discipline || '',
            status: 'researching',
            summary: '',
        };
        _refreshResearchPhase();
    });

    _liveSSE.addEventListener('research_complete', (e) => {
        const data = JSON.parse(e.data);
        if (_liveResearch[data.expert_id]) {
            _liveResearch[data.expert_id].status = 'done';
            _liveResearch[data.expert_id].summary = data.summary || '';
        }
        _refreshResearchPhase();
        showToast(`${data.expert_name} finished researching`, 'info');
    });

    _liveSSE.addEventListener('phase_complete', (e) => {
        const data = JSON.parse(e.data);
        showToast(`Phase ${data.phase} complete`, 'success');
        // Update phases_complete for live session
        if (currentSession && currentSession.phases_complete) {
            if (!currentSession.phases_complete.includes(data.phase)) {
                currentSession.phases_complete.push(data.phase);
            }
        }
    });

    _liveSSE.addEventListener('round_start', (e) => {
        const data = JSON.parse(e.data);
        _liveCurrentRound = data.round;
        showToast(`Round ${data.round} started`, 'info');
    });

    _liveSSE.addEventListener('debate_typing', (e) => {
        const data = JSON.parse(e.data);
        _renderDebateTyping(data);
    });

    _liveSSE.addEventListener('debate_message', (e) => {
        const data = JSON.parse(e.data);
        _renderDebateTyping(null); // remove typing indicator
        _liveDebateMessages.push(data);
        _renderDebateMessage(data);
    });

    _liveSSE.addEventListener('scorecard_ready', (e) => {
        const data = JSON.parse(e.data);
        showToast('Evidence scorecard compiled', 'success');
        // Refresh scorecard phase if user is viewing it
        const activeBtn = document.querySelector('.nav-btn.active');
        if (activeBtn && activeBtn.dataset.phase === 'scorecard') {
            renderScorecardPhase();
        }
    });

    _liveSSE.addEventListener('audit_result', (e) => {
        const data = JSON.parse(e.data);
        const verdict = data.approved
            ? '✓ Consensus APPROVED'
            : '✗ REJECTED — another round needed';
        _renderAuditVerdict(verdict, data.approved);
        showToast(verdict, data.approved ? 'success' : 'error');
    });

    _liveSSE.addEventListener('dossier_chunk', (e) => {
        const data = JSON.parse(e.data);
        _liveDossier += data.chunk || '';
        // Refresh dossier phase if user is viewing it
        const activeBtn = document.querySelector('.nav-btn.active');
        if (activeBtn && activeBtn.dataset.phase === 'dossier') {
            renderDossierPhase();
        }
    });

    _liveSSE.addEventListener('session_complete', (e) => {
        const data = JSON.parse(e.data);
        _liveSSE.close();
        _liveSSE = null;
        showToast('Session complete! Loading results…', 'success');
        // Load the completed session so all phases are browsable from files
        setTimeout(() => loadSession(data.session_id), 1500);
    });

    _liveSSE.onerror = () => {
        if (_liveSSE && _liveSSE.readyState === EventSource.CLOSED) {
            _liveSSE.close();
            _liveSSE = null;
            if (_reconnectAttempts < 3) {
                _reconnectAttempts++;
                const delay = Math.pow(2, _reconnectAttempts) * 1000; // 2s, 4s, 8s
                showToast(`Connection lost. Reconnecting in ${delay / 1000}s (attempt ${_reconnectAttempts}/3)…`, 'warning');
                _reconnectTimer = setTimeout(() => {
                    _reconnectTimer = null;
                    _connectLiveSSE(sessionId);
                }, delay);
            } else {
                showToast('Connection lost after 3 attempts. The pipeline continues on the server — reload the session when complete.', 'error');
            }
            return;
        }
        showToast('Live connection interrupted. The pipeline continues on the server.', 'error');
    };

    // Navigate to Phase B — it will render the live research view
    switchPhase('research');
}

// ─── Live debate DOM helpers ────────────────────────────────────────────────

function _renderDebateTyping(data) {
    const chat = document.getElementById('chat-container');
    if (!chat) return;
    // Remove previous typing indicator
    const prev = document.getElementById('typing-indicator');
    if (prev) prev.remove();
    if (!data) return;
    const div = document.createElement('div');
    div.id = 'typing-indicator';
    div.className = 'chat-indicator';
    const isAudit = data.name === 'Rapporteur' || data.name === 'Discussant';
    div.innerHTML = isAudit
        ? `<strong>${_esc(data.name)}</strong> is drafting<span class="dots"><span>.</span><span>.</span><span>.</span></span>`
        : `<strong>${_esc(data.name)}</strong> is formulating<span class="dots"><span>.</span><span>.</span><span>.</span></span>`;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function _renderDebateMessage(data) {
    const chat = document.getElementById('chat-container');
    if (!chat) return;
    const isAudit = data.name === 'Rapporteur' || data.name === 'Discussant';
    const colorCls = isAudit
        ? (data.name === 'Rapporteur' ? 'rapporteur' : 'discussant')
        : expertColorClass(data.name);

    const wrapper = document.createElement('div');
    wrapper.className = `chat-message ${isAudit ? 'message-right ' + colorCls : colorCls}`;

    const avatar = document.createElement('div');
    avatar.className = 'chat-avatar';
    avatar.textContent = isAudit
        ? (data.name === 'Rapporteur' ? '⚖' : '🔬')
        : data.name.replace(/^(Dr\.|Prof\.) /, '').substring(0, 1);

    const bubbleWrap = document.createElement('div');
    bubbleWrap.className = 'chat-bubble-wrapper';

    const header = document.createElement('div');
    header.className = 'chat-header';
    header.innerHTML = `<strong>${_esc(data.name)}</strong> <span>${isAudit ? 'Round ' + _liveCurrentRound : _esc(data.discipline || '')}</span>`;

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble markdown-content';
    bubble.innerHTML = marked.parse(data.content);

    bubbleWrap.append(header, bubble);
    isAudit ? wrapper.append(bubbleWrap, avatar) : wrapper.append(avatar, bubbleWrap);
    chat.appendChild(wrapper);
    chat.scrollTop = chat.scrollHeight;
}

function _renderAuditVerdict(verdict, approved) {
    const chat = document.getElementById('chat-container');
    if (!chat) return;
    const div = document.createElement('div');
    div.className = `verdict-banner ${approved ? 'verdict-approved' : 'verdict-rejected'}`;
    div.textContent = verdict;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function _refreshResearchPhase() {
    // Only re-render if we're currently on the research phase
    const activeBtn = document.querySelector('.nav-btn.active');
    if (activeBtn && activeBtn.dataset.phase === 'research') {
        _renderLiveResearchPhase();
    }
}

// ─── Toast notifications ────────────────────────────────────────────────────

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ─── Initial load ─────────────────────────────────────────────────────────────
(async function init() {
    await detectServerMode();

    if (window.SERVER_MODE === 'live') {
        panelWizardState.query = '';
        panelWizardState.experts = [];
        panelWizardState.step = 1;
        panelWizardState.visited = new Set([1]);
        switchPhase('panel');
    } else {
        renderSessionPicker();
    }
})();

async function detectServerMode() {
    try {
        const res = await fetch(`${API_BASE}/api/config`);
        if (res.ok) {
            const config = await res.json();
            window.SERVER_MODE = config.mode;
        } else {
            window.SERVER_MODE = 'review';
        }
    } catch (_) {
        window.SERVER_MODE = 'review';
    }
    const badge = document.getElementById('mode-badge');
    if (badge) {
        badge.textContent = window.SERVER_MODE === 'live' ? '⚡ Live' : '📋 Review';
        badge.className = 'mode-badge mode-' + window.SERVER_MODE;
    }
}
