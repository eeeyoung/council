// gui/app.js

// ─── Global state ─────────────────────────────────────────────────────────────
let currentSession    = null;  // manifest object from /api/sessions/{id}
let currentAnimationId = 0;

// Live-mode data stores (populated by SSE events)
let _liveResearch = {};        // {expert_id: {name, discipline, status:'researching'|'done', summary}}
let _liveResearchStatus = '';  // current sub-phase message (B1/B2/B3)
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
    console.warn('[switchPhase] phaseId=' + phaseId + ' currentSession=' + !!currentSession + ' mode=' + window.SERVER_MODE);
    // Clean up all animation timers when switching phases
    if (_deliberationTimer) { clearInterval(_deliberationTimer); _deliberationTimer = null; }
    if (_shelvesTimer)     { clearInterval(_shelvesTimer);     _shelvesTimer = null; }
    if (_stampTimer)       { clearInterval(_stampTimer);       _stampTimer = null; }
    if (_bubbleTimer)      { clearInterval(_bubbleTimer);      _bubbleTimer = null; }
    if (_courtroomTimer)   { clearInterval(_courtroomTimer);   _courtroomTimer = null; }

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
                    Run the SYMPOSIUM pipeline to produce output files, then start the server:
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

function _updateNewSessionBtnState() {
    const btn = document.getElementById('new-session-btn');
    if (!btn) return;
    if (_liveSSE) {
        btn.classList.add('action-btn-disabled');
        btn.textContent = '⏳ Session Running';
    } else {
        btn.classList.remove('action-btn-disabled');
        btn.textContent = '+ New Session';
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
        _updateNewSessionBtnState();
    }

    currentSession = null;
    _liveResearch = {};
    _liveDebateMessages = [];
    try {
        sessionStorage.removeItem('council_debate_session');
        sessionStorage.removeItem('council_debate_messages');
    } catch (_) {}
    _liveCurrentRound = 0;
    _liveDossier = '';
    _deliberationInProgress = false;
    _pendingDeliberationCount = 0;
    if (_deliberationTimer) { clearInterval(_deliberationTimer); _deliberationTimer = null; }
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
    step:              1,
    query:             '',
    expectationType:   'definitive_answer',
    expectationDetail: '',
    expectationCriteria: '',
    experts:           [],
    sessionId:         null,
    dirty:             false,
    visited:           new Set([1]),
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

    // If deliberation is in progress (fetch pending), show the animation again
    if (_deliberationInProgress) {
        _startCouncilDeliberation(_pendingDeliberationCount);
        return;
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
    const expTypes = [
        ['definitive_answer', 'Definitive Answer — reach a clear conclusion'],
        ['feasible_plan', 'Feasible Plan — detailed implementation roadmap'],
        ['balanced_overview', 'Balanced Overview — survey competing viewpoints'],
        ['research_roadmap', 'Research Roadmap — prioritize future directions'],
        ['decision_analysis', 'Decision Analysis — weigh alternatives, recommend one'],
        ['hypothesis_evaluation', 'Hypothesis Evaluation — test a specific hypothesis'],
        ['custom', 'Custom — describe your own desired outcome'],
    ];
    const expOptions = expTypes.map(([val, label]) =>
        `<option value="${val}" ${panelWizardState.expectationType === val ? 'selected' : ''}>${label}</option>`
    ).join('');

    contentBody.innerHTML = `
        <div class="panel-editor wizard-panel">
            ${_renderStepper()}
            <div class="question-stage">
                <div class="question-prompt">
                    <h2 class="question-title">What would you like to investigate?</h2>
                    <p class="question-hint">Be as specific as possible. The Moderator will design a panel of experts optimised for your exact question.</p>
                </div>
                <textarea id="query-input" class="question-input" rows="4"
                    placeholder="e.g. Can we simulate froth flotation images indistinguishable from real ones using only operational variables and a small training set?"
                    oninput="onQueryInput()"
                >${_esc(panelWizardState.query)}</textarea>
                <div class="question-meta">
                    <span id="query-char-count" class="query-char">${panelWizardState.query.length} chars</span>
                    <span class="query-tip">Press <kbd>Ctrl</kbd>+<kbd>Enter</kbd> to generate panel</span>
                </div>
            </div>
            <div class="expectation-stage" style="margin-top:20px;padding:16px;background:var(--bg-secondary);border-radius:8px;">
                <label style="font-weight:600;display:block;margin-bottom:8px;">What kind of outcome do you expect?</label>
                <select id="expectation-type" class="panel-input" onchange="onExpectationChange()"
                    style="width:100%;margin-bottom:10px;">
                    ${expOptions}
                </select>
                <textarea id="expectation-detail" class="panel-input" rows="2"
                    placeholder="Optional: add specific detail or context about what you want (e.g. 'I need concrete next steps for my R&D team')"
                    oninput="onExpectationChange()"
                    style="width:100%;">${_esc(panelWizardState.expectationDetail)}</textarea>
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

window.onExpectationChange = function () {
    panelWizardState.expectationType = document.getElementById('expectation-type')?.value || '';
    panelWizardState.expectationDetail = document.getElementById('expectation-detail')?.value || '';
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
    if (_deliberationInProgress) return;  // Prevent double-click during fetch

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
    // ── Start deliberation animation BEFORE the API call ────────────────
    _deliberationInProgress = true;
    _pendingDeliberationCount = expertCount;
    _startCouncilDeliberation(expertCount);

    let res;
    try {
        res = await fetch(`${API_BASE}/api/sessions/generate-panel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query,
                expert_count: expertCount,
                expectation_type: panelWizardState.expectationType,
                expectation_detail: panelWizardState.expectationDetail,
            }),
        });
    } catch (e) {
        _deliberationInProgress = false;
        clearInterval(_deliberationTimer);
        _deliberationTimer = null;
        contentBody.innerHTML = `<div class="markdown-content"><p style="color:#ef4444;padding:40px;">
            Cannot reach the server. Make sure it's running in live mode:
            <pre style="margin-top:12px;">uv run python -m council.server --mode live</pre></p></div>`;
        return;
    }

    if (!res.ok) {
        _deliberationInProgress = false;
        clearInterval(_deliberationTimer);
        _deliberationTimer = null;
        const err = await res.json().catch(() => ({}));
        contentBody.innerHTML = `<div class="markdown-content"><p style="color:#ef4444;padding:40px;">
            ${_esc(err.detail || 'Failed to generate panel. Check the server logs.')}</p></div>`;
        return;
    }

    const data = await res.json();
    panelWizardState.sessionId = data.session_id;
    panelWizardState.expectationCriteria = data.expectation_criteria || '';
    panelWizardState.experts = data.experts.map((e, i) => ({
        name:           e.name,
        discipline:     e.discipline || '',
        bias:           e.bias || '',
        persona_prompt: e.persona_prompt || '',
    }));

    // Settle the deliberation animation on the real experts
    await _settleCouncilTable(data.experts);
    _deliberationInProgress = false;
    _pendingDeliberationCount = 0;

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

    // Only render step 2 if the user is still on Phase A
    const activeBtn = document.querySelector('.nav-btn.active');
    if (activeBtn && activeBtn.dataset.phase === 'panel') {
        _renderStep2();
    }
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

// ── Council Table Deliberation Animation ──────────────────────────────────────

const _PHILOSOPHER_POOL = [
    ['Socratyes', 'Platoueau', 'Aristarchus', 'Parmenidion', 'Heraclitron',
     'Thalestine', 'Pythagorine', 'Empedocrate', 'Anaxagorine', 'Democriton',
     'Epicurian', 'Zenoflux', 'Diogenite', 'Plotinian', 'Hypatienne',
     'Kantwell', 'Hegelight', 'Nietzschen', 'Foucavie', 'Arendelle'],
    ['Quantum Physics', 'Neuroscience', 'Materials Science', 'Computational Biology',
     'Climate Systems', 'Evolutionary Theory', 'Cognitive Psychology', 'Plasma Dynamics',
     'Information Geometry', 'Molecular Engineering', 'Astrobiology', 'Geochemistry',
     'Network Theory', 'Linguistic Anthropology', 'Synthetic Biology', 'Game Theory',
     'Fluid Mechanics', 'Condensed Matter', 'Quantum Information', 'Biomechanics'],
];

let _deliberationTimer = null;

function _startCouncilDeliberation(count) {
    const colors = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f472b6', '#fb923c'];

    // Build chair slots around the table
    let chairSlots = '';
    for (let i = 0; i < count; i++) {
        const angle = (i / count) * 360 - 90;
        const rad = (angle * Math.PI) / 180;
        const r = 130;
        const x = Math.cos(rad) * r;
        const y = Math.sin(rad) * r;
        chairSlots += `
            <div class="council-chair council-slot-${i}" style="
                position:absolute;
                left:calc(50% + ${x}px);
                top:calc(50% + ${y}px);
                transform:translate(-50%,-50%);
                text-align:center;width:120px;
            ">
                <div class="council-avatar" style="
                    width:56px;height:56px;border-radius:50%;margin:0 auto 6px;
                    display:flex;align-items:center;justify-content:center;
                    font-size:22px;font-weight:700;transition:all 0.4s;
                "></div>
                <div class="council-name" style="font-size:12px;font-weight:600;
                    color:var(--text-primary);transition:all 0.4s;"></div>
                <div class="council-disc" style="font-size:11px;
                    color:var(--text-muted);transition:all 0.4s;"></div>
            </div>`;
    }

    contentBody.innerHTML = `
        <div class="panel-editor wizard-panel" style="align-items:center;justify-content:center;">
            ${_renderStepper()}
            <div class="council-table" style="position:relative;width:340px;height:340px;margin:30px auto;">
                <div class="council-table-center" style="
                    position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
                    width:90px;height:90px;border-radius:50%;
                    background:var(--bg-secondary);
                    border:2px dashed var(--border-color);
                    display:flex;align-items:center;justify-content:center;
                    font-size:13px;color:var(--text-muted);text-align:center;
                ">Deliberating</div>
                ${chairSlots}
            </div>
            <p id="council-status" style="color:var(--text-muted);font-size:14px;text-align:center;
                min-height:20px;"></p>
        </div>`;

    // Cycle random names/disciplines through the chairs
    const names = _PHILOSOPHER_POOL[0];
    const discs = _PHILOSOPHER_POOL[1];
    const statuses = [
        'Reviewing candidate disciplines…',
        'Consulting the literature…',
        'Evaluating methodological fit…',
        'Assembling optimal panel composition…',
        'Balancing epistemic perspectives…',
        'Screening for intellectual tension…',
    ];

    function shuffle() {
        for (let i = 0; i < count; i++) {
            const slot = document.querySelector(`.council-slot-${i}`);
            if (!slot) continue;
            const avatar = slot.querySelector('.council-avatar');
            const name = slot.querySelector('.council-name');
            const disc = slot.querySelector('.council-disc');
            if (!avatar || !name || !disc) continue;

            const ci = Math.floor(Math.random() * colors.length);
            const ni = Math.floor(Math.random() * names.length);
            const di = Math.floor(Math.random() * discs.length);

            avatar.style.background = colors[ci] + '22';
            avatar.style.borderColor = colors[ci];
            avatar.style.color = colors[ci];
            avatar.textContent = names[ni].substring(0, 2);
            name.textContent = names[ni];
            disc.textContent = discs[di];
        }
        const status = document.getElementById('council-status');
        if (status) {
            status.textContent = statuses[Math.floor(Math.random() * statuses.length)];
        }
    }

    shuffle();
    _deliberationTimer = setInterval(shuffle, 800);
}

async function _settleCouncilTable(experts) {
    // Stop the random cycling
    clearInterval(_deliberationTimer);
    _deliberationTimer = null;

    const colors = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f472b6', '#fb923c'];

    // Fade out all current chairs (query by class prefix, not regex)
    const currentSlots = document.querySelectorAll('[class*="council-slot-"]');
    const slotCount = currentSlots.length || 4;
    for (let i = 0; i < slotCount; i++) {
        const slot = document.querySelector(`.council-slot-${i}`);
        if (slot) slot.style.opacity = '0';
    }
    await new Promise(r => setTimeout(r, 300));

    // Update chairs with real experts
    for (let i = 0; i < experts.length; i++) {
        const e = experts[i];
        const slot = document.querySelector(`.council-slot-${i}`);
        if (!slot) continue;
        const avatar = slot.querySelector('.council-avatar');
        const name = slot.querySelector('.council-name');
        const disc = slot.querySelector('.council-disc');
        if (!avatar || !name || !disc) continue;

        avatar.style.background = colors[i % colors.length] + '22';
        avatar.style.borderColor = colors[i % colors.length];
        avatar.style.color = colors[i % colors.length];
        avatar.textContent = (e.name || '').replace(/^(Dr\.|Prof\.) /, '').substring(0, 2);
        name.textContent = e.name;
        disc.textContent = e.discipline || '';
        slot.style.opacity = '1';

        const status = document.getElementById('council-status');
        if (status) status.textContent = `${e.name} has joined the council`;
        await new Promise(r => setTimeout(r, 500));
    }

    await new Promise(r => setTimeout(r, 600));
    const status = document.getElementById('council-status');
    if (status) status.textContent = `Council assembled — ${experts.length} experts ready`;
    await new Promise(r => setTimeout(r, 1000));
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
                    expectation_type: panelWizardState.expectationType,
                    expectation_detail: panelWizardState.expectationDetail,
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

let _shelvesTimer = null;
let _shelfBooks = [];
let _courtroomTimer = null;
let _deliberationInProgress = false;
let _pendingDeliberationCount = 0;

function _renderLiveResearchPhase() {
    const entries = Object.values(_liveResearch);
    const status = _liveResearchStatus || '';
    if (!entries.length && !status.startsWith('B1')) {
        contentBody.innerHTML = `
            <div style="text-align:center;padding:60px 0;">
                <div class="loading-spinner"></div>
                <p style="margin-top:20px;color:var(--text-muted);">Initialising research phase…</p>
            </div>`;
        return;
    }

    const allDone = entries.every(r => r.status === 'done');

    // ── B1: Library Shelves Filling ────────────────────────────────────
    if (status.startsWith('B1') && !allDone) {
        _renderLibraryShelves(entries);
        return;
    }

    // ── B2: Stamp Verification ─────────────────────────────────────────
    if (status.startsWith('B2') && !allDone) {
        _renderStampVerification(entries);
        return;
    }

    // ── B3: Thought Bubbles ────────────────────────────────────────────
    if (status.startsWith('B3') && !allDone) {
        _renderThoughtBubbles(entries);
        return;
    }

    // ── Default: status cards ──────────────────────────────────────────
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
                <p style="color:var(--text-muted);margin-bottom:20px;">${_esc(status || 'Experts are researching…')}</p>
                <div class="live-research-grid">${cards}</div>
            </div>`;
        return;
    }

    // All done — build research file list from _liveResearch and render tabbed view
    if (_shelvesTimer) { clearInterval(_shelvesTimer); _shelvesTimer = null; }
    const sid = currentSession?.session_id;
    if (!sid) { return; }

    const expertObjs = Object.entries(_liveResearch);
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
    // Check both in-memory and sessionStorage for persisted messages
    let hasPersistedMessages = _liveDebateMessages.length > 0;
    if (!hasPersistedMessages) {
        try {
            const storedSession = sessionStorage.getItem('council_debate_session');
            const currentId = currentSession?.session_id || panelWizardState?.sessionId;
            if (storedSession && currentId && storedSession === currentId) {
                const saved = sessionStorage.getItem('council_debate_messages');
                if (saved && JSON.parse(saved).length) hasPersistedMessages = true;
            }
        } catch (_) {}
    }
    console.log('[Phase C] renderDebatePhase. inMemory=', _liveDebateMessages.length,
        'hasPersisted=', hasPersistedMessages, '_liveSSE=', !!_liveSSE,
        'podiumInit=', _podiumInitialized);

    // Live / persisted mode: render from accumulated debate messages
    if (hasPersistedMessages || _liveSSE) {
        console.log('[Phase C] Using LIVE render path');
        _renderLiveDebatePhase();
        return;
    }

    // Review mode: render from transcript files
    console.log('[Phase C] Using REVIEW render path. rounds=',
        currentSession?.files?.rounds?.length);
    const animId = currentAnimationId;
    const rounds = currentSession?.files?.rounds ?? [];

    if (!rounds.length) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">No debate transcript available for this session.</p>';
        return;
    }

    const podium = _renderPodium();
    contentBody.innerHTML = podium + '<div class="chat-container" id="chat-container"></div>';
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
    let msgs = _liveDebateMessages;
    // If in-memory array is empty, try to restore from sessionStorage
    if (!msgs.length) {
        try {
            const storedSession = sessionStorage.getItem('council_debate_session');
            const currentId = currentSession?.session_id || panelWizardState?.sessionId;
            // Only restore if the stored messages belong to the current session
            if (storedSession && currentId && storedSession === currentId) {
                const saved = sessionStorage.getItem('council_debate_messages');
                if (saved) {
                    const parsed = JSON.parse(saved);
                    if (parsed.length) {
                        _liveDebateMessages = parsed;
                        msgs = _liveDebateMessages;
                        console.log('[Phase C] Restored', msgs.length, 'messages from sessionStorage');
                    }
                }
            }
        } catch (_) {}
    }
    if (!msgs.length) {
        contentBody.innerHTML = `
            <div style="text-align:center;padding:60px 0;">
                <div class="loading-spinner"></div>
                <p style="margin-top:20px;color:var(--text-muted);">Waiting for the symposium to begin…</p>
            </div>`;
        return;
    }

    // Render podium + chat container
    const podium = _podiumInitialized ? _renderPodium() : '';
    let html = podium;
    html += '<div class="chat-container" id="chat-container">';
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
                    <div class="chat-bubble markdown-content${isAudit ? '' : ' structured'}">${marked.parse(isAudit ? msg.content : _preprocessStructuredMarkdown(msg.content))}</div>
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
        const isStructuredReview = !msg.isAudit;
        bubble.className = 'chat-bubble markdown-content' + (isStructuredReview ? ' structured' : '');

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
    // Live mode: show Rapporteur synthesis if available
    if (_liveSSE) {
        const auditMsgs = _liveDebateMessages.filter(m => m.name === 'Rapporteur');
        if (auditMsgs.length) {
            _renderSynthesisPanel(auditMsgs);
        } else {
            contentBody.innerHTML = `
                <div style="text-align:center;padding:60px 0;">
                    <div class="loading-spinner"></div>
                    <p style="margin-top:20px;color:var(--text-muted);">Waiting for synthesis…</p>
                </div>`;
        }
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

    let entries;
    try {
        const text = await fetchText(outputUrl(lastRound.scorecard));
        entries = JSON.parse(text);
    } catch (_) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">Could not parse scorecard data.</p>';
        return;
    }

    if (!entries || !entries.length) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">No evidence entries found.</p>';
        return;
    }

    const experts = [...new Set(entries.map(e => e.agent_name))];

    function claimTypeBadge(entry) {
        const ct = entry.claim_type || 'empirical';
        switch (ct) {
            case 'position':
                return '<span class="claim-type-badge badge-position">Thesis statement</span>';
            case 'inference':
                return '<span class="claim-type-badge badge-inference">Expert reasoning</span>';
            default:
                return '';
        }
    }

    function sourceBadge(entry) {
        const ct = entry.claim_type || 'empirical';
        // Non-empirical claims: neutral badge
        if (ct === 'position' || ct === 'inference') {
            return '';
        }
        // Empirical claim with no source
        if (!entry.source_url) {
            return '<span class="claim-source-badge badge-no-source">No source cited</span>';
        }
        // Has source — check verification
        switch (entry.verification_status) {
            case 'verified':
                return '<span class="claim-source-badge badge-verified">✓ Verified</span>';
            case 'misattributed':
                return '<span class="claim-source-badge badge-misattributed">⚠ Misattributed</span>';
            case 'unverifiable':
                return '<span class="claim-source-badge badge-unverifiable">? Unverifiable</span>';
            default:
                return '';
        }
    }

    function buildGrid(filter) {
        return (filter === 'all' ? entries : entries.filter(e => e.agent_name === filter))
            .map((e, i) => {
                const meta = claimColorMeta(e.agent_name);
                const ctBadge = claimTypeBadge(e);
                const srcBadge = sourceBadge(e);
                const hasUrl = e.source_url && e.source_url.startsWith('http');

                let sourceHtml = '';
                if (hasUrl) {
                    const domain = (() => { try { return new URL(e.source_url).hostname; } catch { return e.source_url; } })();
                    sourceHtml = `<a class="claim-source-link" href="${_esc(e.source_url)}" target="_blank" rel="noopener">
                        → ${_esc(domain)}</a>`;
                }

                let quoteHtml = '';
                if (e.source_quote) {
                    quoteHtml = `<blockquote class="claim-quote">${_esc(e.source_quote)}</blockquote>`;
                }

                let noteHtml = '';
                if (e.relevance_note) {
                    noteHtml = `<span class="claim-note">${_esc(e.relevance_note)}</span>`;
                }

                const badges = [ctBadge, srcBadge].filter(Boolean).join('');

                return `
                    <div class="claim-card ${meta.cls}" id="claim-${i}">
                        <div class="claim-card-header">
                            <div class="claim-expert-chip">${_esc(e.agent_name)}</div>
                            <div class="claim-badges">${badges}</div>
                        </div>
                        <p class="claim-text">"${_esc(e.claim)}"</p>
                        ${quoteHtml}
                        <div class="claim-card-footer">
                            ${sourceHtml}
                            ${noteHtml}
                        </div>
                    </div>`;
            }).join('');
    }

    const verifiedCount = entries.filter(e => e.verification_status === 'verified').length;
    const issueCount = entries.filter(e => e.verification_status === 'misattributed' || (!e.source_url && e.claim_type === 'empirical')).length;

    contentBody.innerHTML = `
        <div class="scorecard-wrapper">
            <div class="scorecard-summary">
                <span class="sc-stat sc-verified">✓ ${verifiedCount} verified</span>
                <span class="sc-stat sc-total">${entries.length} total</span>
                ${issueCount > 0 ? `<span class="sc-stat sc-issues">${issueCount} need attention</span>` : ''}
            </div>
            <div class="scorecard-toolbar">
                <div class="scorecard-filters" id="sc-filters">
                    <button class="sc-filter-btn active" onclick="setScorecardFilter('all',this)">
                        All <span class="sc-count">${entries.length}</span>
                    </button>
                    ${experts.map(n => `
                        <button class="sc-filter-btn" data-filter="${_esc(n)}" onclick="setScorecardFilter(this.dataset.filter,this)">
                            ${_esc(n)} <span class="sc-count">${entries.filter(e=>e.agent_name===n).length}</span>
                        </button>`).join('')}
                </div>
            </div>
            <div class="scorecard-grid" id="scorecard-grid">${buildGrid('all')}</div>
        </div>`;

    window.setScorecardFilter = function (filter, btn) {
        document.querySelectorAll('.sc-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('scorecard-grid').innerHTML = buildGrid(filter);
    };
}

// ── Synthesis Panel (Phase D, live mode) ─────────────────────────────────────

function _renderSynthesisPanel(auditMsgs) {
    if (!auditMsgs.length) return;
    const synthesis = auditMsgs[auditMsgs.length - 1];

    contentBody.innerHTML = `
        <div class="synthesis-panel">
            <div class="synthesis-header">
                <h2>📋 Rapporteur Synthesis</h2>
                <span class="synthesis-round">Round ${synthesis.round || 1}</span>
            </div>
            <div class="synthesis-body markdown-content">
                ${marked.parse(synthesis.content)}
            </div>
        </div>`;
}

// ── Courtroom Drama (Phase D) ───────────────────────────────────────────────

function _renderCourtroom(auditMsgs) {
    const round = _liveCurrentRound || 1;

    _stopCourtroomAnimation();

    contentBody.innerHTML = `
        <div id="courtroom-stage" style="
            display:flex;flex-direction:column;gap:0;height:100%;
        ">
            <div id="courtroom-header" style="
                text-align:center;padding:8px 0 4px;
                font-size:12px;font-weight:600;color:var(--text-muted);
                letter-spacing:1px;text-transform:uppercase;
            ">⚖️ Courtroom — Round ${round} — Audit in Session</div>
            <div class="courtroom-arena" style="
                display:flex;align-items:center;justify-content:center;
                gap:24px;padding:16px 24px 12px;
                position:relative;min-height:160px;
            ">
                <!-- Rapporteur (Left) -->
                <div class="courtroom-figure" id="courtroom-rapporteur" style="
                    display:flex;flex-direction:column;align-items:center;gap:6px;
                    flex:1;max-width:180px;transition:all 0.5s;
                ">
                    <div class="courtroom-avatar" style="
                        width:64px;height:64px;border-radius:50%;
                        background:rgba(167,139,250,0.12);
                        border:3px solid rgba(167,139,250,0.5);
                        color:#a78bfa;display:flex;align-items:center;
                        justify-content:center;font-size:30px;
                        transition:all 0.5s;position:relative;
                    ">⚖️</div>
                    <div style="font-weight:700;color:#a78bfa;font-size:14px;">Rapporteur</div>
                    <div class="courtroom-status" id="courtroom-status-left" style="
                        font-size:11px;color:var(--text-muted);text-align:center;
                        min-height:16px;transition:all 0.4s;
                    ">Awaiting synthesis…</div>
                </div>

                <!-- Center: Gavel + Action Zone -->
                <div class="courtroom-center" id="courtroom-center" style="
                    display:flex;flex-direction:column;align-items:center;
                    gap:8px;flex:0 0 auto;position:relative;
                ">
                    <div id="courtroom-gavel" style="
                        font-size:48px;cursor:default;
                        transition:transform 0.15s;transform-origin:bottom right;
                        filter:drop-shadow(0 2px 8px rgba(167,139,250,0.3));
                    ">🔨</div>
                    <div id="courtroom-objection" style="
                        position:absolute;top:50%;left:50%;transform:translate(-50%,-50%) scale(0);
                        font-weight:900;font-size:18px;letter-spacing:2px;
                        white-space:nowrap;transition:all 0.3s cubic-bezier(0.34,1.56,0.64,1);
                        pointer-events:none;
                    "></div>
                </div>

                <!-- Discussant (Right) -->
                <div class="courtroom-figure" id="courtroom-discussant" style="
                    display:flex;flex-direction:column;align-items:center;gap:6px;
                    flex:1;max-width:180px;transition:all 0.5s;
                ">
                    <div class="courtroom-avatar" style="
                        width:64px;height:64px;border-radius:50%;
                        background:rgba(251,146,60,0.12);
                        border:3px solid rgba(251,146,60,0.5);
                        color:#fb923c;display:flex;align-items:center;
                        justify-content:center;font-size:30px;
                        transition:all 0.5s;position:relative;
                    ">🔬</div>
                    <div style="font-weight:700;color:#fb923c;font-size:14px;">Discussant</div>
                    <div class="courtroom-status" id="courtroom-status-right" style="
                        font-size:11px;color:var(--text-muted);text-align:center;
                        min-height:16px;transition:all 0.4s;
                    ">Waiting for draft…</div>
                </div>
            </div>
            <!-- Chat area for audit messages -->
            <div id="courtroom-chat" style="
                flex:1;overflow-y:auto;padding:0 16px 16px;
                display:flex;flex-direction:column;gap:10px;
            ">${_renderCourtroomMessages(auditMsgs)}</div>
        </div>`;

    // Start self-animation
    _startCourtroomAnimation();
}

function _renderCourtroomMessages(msgs) {
    if (!msgs.length) {
        return `<p style="color:var(--text-muted);text-align:center;padding:20px;
            font-size:13px;">The Rapporteur will present a synthesis, then the Discussant will cross-examine it…</p>`;
    }
    return msgs.map(m => {
        const isRapp = m.name === 'Rapporteur';
        const sideCls = isRapp ? 'rapporteur' : 'discussant';
        const avatar = isRapp ? '⚖️' : '🔬';
        return `
            <div class="chat-message message-right ${sideCls}">
                <div class="chat-avatar">${avatar}</div>
                <div class="chat-bubble-wrapper">
                    <div class="chat-header">
                        <strong>${_esc(m.name)}</strong>
                        <span>${_esc(m.discipline || '')}</span>
                    </div>
                    <div class="chat-bubble markdown-content">${marked.parse(m.content)}</div>
                </div>
            </div>`;
    }).join('');
}

function _startCourtroomAnimation() {
    if (_courtroomTimer) return;

    const rapporteurStatuses = [
        'Reviewing testimony…',
        'Weighing the evidence…',
        'Drafting synthesis…',
        'Cross-referencing claims…',
        'Formulating consensus…',
    ];
    const discussantStatuses = [
        'Examining the brief…',
        'Checking citations…',
        'Probing for weaknesses…',
        'Evaluating methodology…',
        'Preparing cross-examination…',
    ];
    let tick = 0;

    _courtroomTimer = setInterval(() => {
        tick++;

        // Cycle status texts
        const leftStatus = document.getElementById('courtroom-status-left');
        const rightStatus = document.getElementById('courtroom-status-right');
        if (leftStatus && Math.random() < 0.4) {
            leftStatus.textContent = rapporteurStatuses[Math.floor(Math.random() * rapporteurStatuses.length)];
        }
        if (rightStatus && Math.random() < 0.4) {
            rightStatus.textContent = discussantStatuses[Math.floor(Math.random() * discussantStatuses.length)];
        }

        // Gavel pulse — gentle bob every few ticks
        const gavel = document.getElementById('courtroom-gavel');
        if (gavel && tick % 3 === 0) {
            gavel.style.transform = 'rotate(-20deg) scale(1.15)';
            setTimeout(() => {
                if (gavel) gavel.style.transform = 'rotate(0deg) scale(1)';
            }, 200);
        }

        // Occasional ambient pulse on avatars
        if (tick % 5 === 0) {
            const leftAv = document.querySelector('#courtroom-rapporteur .courtroom-avatar');
            const rightAv = document.querySelector('#courtroom-discussant .courtroom-avatar');
            if (leftAv) {
                leftAv.style.boxShadow = '0 0 24px rgba(167,139,250,0.4)';
                setTimeout(() => { if (leftAv) leftAv.style.boxShadow = 'none'; }, 600);
            }
            if (rightAv) {
                rightAv.style.boxShadow = '0 0 24px rgba(251,146,60,0.4)';
                setTimeout(() => { if (rightAv) rightAv.style.boxShadow = 'none'; }, 600);
            }
        }
    }, 1200);
}

function _stopCourtroomAnimation() {
    if (_courtroomTimer) {
        clearInterval(_courtroomTimer);
        _courtroomTimer = null;
    }
}

function _updateCourtroomFigure(name) {
    const isRapp = name === 'Rapporteur';
    const leftFig = document.getElementById('courtroom-rapporteur');
    const rightFig = document.getElementById('courtroom-discussant');
    const leftStatus = document.getElementById('courtroom-status-left');
    const rightStatus = document.getElementById('courtroom-status-right');

    if (!leftFig || !rightFig) return;

    if (isRapp) {
        leftFig.style.transform = 'scale(1.08)';
        leftFig.style.opacity = '1';
        rightFig.style.transform = 'scale(0.95)';
        rightFig.style.opacity = '0.5';
        if (leftStatus) leftStatus.textContent = 'Drafting synthesis…';
        if (rightStatus) rightStatus.textContent = 'Waiting…';
        // Glow on rapporteur avatar
        const av = leftFig.querySelector('.courtroom-avatar');
        if (av) av.style.boxShadow = '0 0 32px rgba(167,139,250,0.6)';
    } else {
        rightFig.style.transform = 'scale(1.08)';
        rightFig.style.opacity = '1';
        leftFig.style.transform = 'scale(0.95)';
        leftFig.style.opacity = '0.5';
        if (rightStatus) rightStatus.textContent = 'Cross-examining…';
        if (leftStatus) leftStatus.textContent = 'Under review…';
        // Glow on discussant avatar
        const av = rightFig.querySelector('.courtroom-avatar');
        if (av) av.style.boxShadow = '0 0 32px rgba(251,146,60,0.6)';
    }

    // Reset other avatar glow
    const otherAv = (isRapp ? rightFig : leftFig).querySelector('.courtroom-avatar');
    if (otherAv) otherAv.style.boxShadow = 'none';
}

function _courtroomAddMessage(data) {
    const chat = document.getElementById('courtroom-chat');
    if (!chat) return;

    // Remove placeholder if present
    const placeholder = chat.querySelector('p');
    if (placeholder && placeholder.textContent.includes('Rapporteur will present')) {
        placeholder.remove();
    }

    const isRapp = data.name === 'Rapporteur';
    const sideCls = isRapp ? 'rapporteur' : 'discussant';
    const avatar = isRapp ? '⚖️' : '🔬';
    const div = document.createElement('div');
    div.className = `chat-message message-right ${sideCls}`;
    div.innerHTML = `
        <div class="chat-avatar">${avatar}</div>
        <div class="chat-bubble-wrapper">
            <div class="chat-header">
                <strong>${_esc(data.name)}</strong>
                <span>${_esc(data.discipline || '')}</span>
            </div>
            <div class="chat-bubble markdown-content">${marked.parse(data.content)}</div>
        </div>`;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;

    // Clear figure highlights
    const leftFig = document.getElementById('courtroom-rapporteur');
    const rightFig = document.getElementById('courtroom-discussant');
    if (leftFig) { leftFig.style.transform = 'scale(1)'; leftFig.style.opacity = '1'; }
    if (rightFig) { rightFig.style.transform = 'scale(1)'; rightFig.style.opacity = '1'; }
}

function _courtroomShowVerdict(approved, verdictText, issues) {
    _stopCourtroomAnimation();

    const gavel = document.getElementById('courtroom-gavel');
    const header = document.getElementById('courtroom-header');
    const leftAv = document.querySelector('#courtroom-rapporteur .courtroom-avatar');
    const rightAv = document.querySelector('#courtroom-discussant .courtroom-avatar');

    // Gavel strike animation
    if (gavel) {
        gavel.style.transform = 'rotate(-35deg) scale(1.3)';
        gavel.style.transition = 'transform 0.1s';
        setTimeout(() => {
            if (gavel) {
                gavel.style.transform = 'rotate(0deg) scale(1)';
                gavel.style.transition = 'transform 0.3s cubic-bezier(0.34,1.56,0.64,1)';
            }
        }, 150);
    }

    // Flash the avatars
    const verdictColor = approved ? '#22c55e' : '#ef4444';
    [leftAv, rightAv].forEach(av => {
        if (!av) return;
        av.style.transition = 'all 0.3s';
        av.style.borderColor = verdictColor;
        av.style.boxShadow = `0 0 40px ${verdictColor}44`;
    });

    // Update header with verdict
    if (header) {
        header.innerHTML = approved
            ? '⚖️ <span style="color:#22c55e;">VERDICT: APPROVED</span> — Consensus Reached'
            : '⚖️ <span style="color:#ef4444;">VERDICT: REJECTED</span> — Another Round Required';
    }

    // Show objection burst if rejected
    if (!approved) {
        const objection = document.getElementById('courtroom-objection');
        if (objection) {
            objection.textContent = issues.length ? `ISSUES FOUND (${issues.length})` : 'OBJECTION!';
            objection.style.color = '#ef4444';
            objection.style.transform = 'translate(-50%,-50%) scale(1)';
            setTimeout(() => {
                if (objection) objection.style.transform = 'translate(-50%,-50%) scale(0)';
            }, 2500);
        }
    }

    // Add verdict banner to chat
    const chat = document.getElementById('courtroom-chat');
    if (chat) {
        const banner = document.createElement('div');
        banner.style.cssText = `
            text-align:center;padding:12px 20px;margin:8px 0;
            border-radius:8px;font-weight:700;font-size:14px;
            background:${approved ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)'};
            border:1px solid ${approved ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)'};
            color:${approved ? '#22c55e' : '#ef4444'};
        `;
        banner.textContent = verdictText;
        if (issues.length) {
            const issuesDiv = document.createElement('div');
            issuesDiv.style.cssText = 'font-weight:400;font-size:12px;margin-top:4px;color:var(--text-muted);';
            issuesDiv.textContent = 'Issues: ' + issues.join('; ');
            banner.appendChild(issuesDiv);
        }
        chat.appendChild(banner);
        chat.scrollTop = chat.scrollHeight;
    }

    // Reset after a moment
    setTimeout(() => {
        if (leftAv) { leftAv.style.borderColor = 'rgba(167,139,250,0.5)'; leftAv.style.boxShadow = 'none'; }
        if (rightAv) { rightAv.style.borderColor = 'rgba(251,146,60,0.5)'; rightAv.style.boxShadow = 'none'; }
    }, 3000);
}

function _courtroomShowExpectation(met, msg) {
    const chat = document.getElementById('courtroom-chat');
    const gavel = document.getElementById('courtroom-gavel');
    if (!chat) return;

    // Light gavel tap
    if (gavel) {
        gavel.style.transform = 'rotate(-12deg) scale(1.1)';
        gavel.style.transition = 'transform 0.1s';
        setTimeout(() => {
            if (gavel) {
                gavel.style.transform = 'rotate(0deg) scale(1)';
                gavel.style.transition = 'transform 0.3s cubic-bezier(0.34,1.56,0.64,1)';
            }
        }, 120);
    }

    const color = met ? '#22c55e' : '#f59e0b';
    const banner = document.createElement('div');
    banner.style.cssText = `
        text-align:center;padding:10px 20px;margin:4px 0;
        border-radius:8px;font-weight:600;font-size:13px;
        background:${color}11;border:1px solid ${color}44;
        color:${color};
    `;
    banner.textContent = msg;
    chat.appendChild(banner);
    chat.scrollTop = chat.scrollHeight;
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

function _connectLiveSSE(sessionId, isReconnect = false) {
    // Initialize live data stores (preserve debate messages across reconnects)
    _liveResearch = {};
    if (!isReconnect) {
        _liveDebateMessages = [];
        try {
            sessionStorage.removeItem('council_debate_session');
            sessionStorage.removeItem('council_debate_messages');
        } catch (_) {}
    }
    _liveCurrentRound = 0;
    _liveDossier = '';
    _liveResearchStatus = '';
    _shelfBooks = [];
    _stampSources = [];
    _podiumInitialized = false;
    // Remove old podium
    const oldPodium = document.getElementById('podium-stage');
    if (oldPodium) oldPodium.remove();
    if (_shelvesTimer) { clearInterval(_shelvesTimer); _shelvesTimer = null; }
    if (_stampTimer) { clearInterval(_stampTimer); _stampTimer = null; }
    if (_bubbleTimer) { clearInterval(_bubbleTimer); _bubbleTimer = null; }
    if (_courtroomTimer) { clearInterval(_courtroomTimer); _courtroomTimer = null; }
    _reconnectAttempts = 0;
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    if (_liveSSE) { _liveSSE.close(); _liveSSE = null; }
    _liveSSE = new EventSource(`${API_BASE}/api/sessions/${sessionId}/live`);
    _updateNewSessionBtnState();

    _liveSSE.addEventListener('session_start', (e) => {
        const data = JSON.parse(e.data);
        showToast(`Session started — Phase B begins`, 'info');
    });

    _liveSSE.addEventListener('phase_start', (e) => {
        const data = JSON.parse(e.data);
        if (data.phase === 'C') {
            switchPhase('debate');
            showToast('Symposium begins — experts are debating', 'info');
        } else if (data.phase === 'D') {
            switchPhase('scorecard');
            showToast('Courtroom is in session — audit begins', 'info');
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

    _liveSSE.addEventListener('research_status', (e) => {
        const data = JSON.parse(e.data);
        _liveResearchStatus = data.message || '';
        _refreshResearchPhase();
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
        _initPodium();
        showToast(`Round ${data.round} started`, 'info');
    });

    _liveSSE.addEventListener('debate_typing', (e) => {
        const data = JSON.parse(e.data);
        _renderDebateTyping(data);
        _updatePodium(data.name);
        // Update courtroom if user is viewing Phase D
        const activeBtn = document.querySelector('.nav-btn.active');
        if (activeBtn && activeBtn.dataset.phase === 'scorecard') {
            _updateCourtroomFigure(data.name);
        }
    });

    _liveSSE.addEventListener('debate_message', (e) => {
        const data = JSON.parse(e.data);
        _renderDebateTyping(null);
        _liveDebateMessages.push(data);
        // Persist to sessionStorage so messages survive reconnect / page issues
        try {
            sessionStorage.setItem('council_debate_session', sessionId);
            sessionStorage.setItem('council_debate_messages', JSON.stringify(_liveDebateMessages));
        } catch (_) {}
        _renderDebateMessage(data);
        _updatePodium(null); // clear spotlight
        // Add message to courtroom if user is viewing Phase D
        const activeBtn = document.querySelector('.nav-btn.active');
        if (activeBtn && activeBtn.dataset.phase === 'scorecard') {
            _courtroomAddMessage(data);
        }
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
        // Animate gavel verdict in courtroom
        const activeBtn = document.querySelector('.nav-btn.active');
        if (activeBtn && activeBtn.dataset.phase === 'scorecard') {
            _courtroomShowVerdict(data.approved, verdict, data.issues || []);
        }
    });

    _liveSSE.addEventListener('expectation_result', (e) => {
        const data = JSON.parse(e.data);
        const msg = data.met
            ? '✓ Expectation MET — proceeding to dossier'
            : '✗ Expectation NOT MET — another round needed';
        _renderAuditVerdict(msg, data.met);
        showToast(msg, data.met ? 'success' : 'warning');
        // Show expectation verdict in courtroom
        const activeBtn = document.querySelector('.nav-btn.active');
        if (activeBtn && activeBtn.dataset.phase === 'scorecard') {
            _courtroomShowExpectation(data.met, msg);
        }
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
        if (_liveSSE) {
            _liveSSE.close();
            _liveSSE = null;
        }
        _updateNewSessionBtnState();
        // Cancel any pending reconnect — session finished successfully
        if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
        _reconnectAttempts = 0;
        showToast('Session complete! Loading results…', 'success');
        // Load the completed session so all phases are browsable from files
        setTimeout(() => loadSession(data.session_id), 1500);
    });

    _liveSSE.onerror = () => {
        if (_liveSSE && _liveSSE.readyState === EventSource.CLOSED) {
            _liveSSE.close();
            _liveSSE = null;
            _updateNewSessionBtnState();
            if (_reconnectAttempts < 3) {
                _reconnectAttempts++;
                const delay = Math.pow(2, _reconnectAttempts) * 1000; // 2s, 4s, 8s
                showToast(`Connection lost. Reconnecting in ${delay / 1000}s (attempt ${_reconnectAttempts}/3)…`, 'warning');
                _reconnectTimer = setTimeout(() => {
                    _reconnectTimer = null;
                    _connectLiveSSE(sessionId, true);
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

// ── Podium Spotlight (Phase C) ────────────────────────────────────────────────

let _podiumInitialized = false;

function _renderPodium() {
    const experts = currentSession?.experts || [];
    if (!experts.length) return '';

    const colors = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f472b6', '#fb923c'];
    const pods = experts.map((e, i) => `
        <div class="podium-spot" data-name="${_esc(e.name)}" style="
            display:flex;flex-direction:column;align-items:center;gap:4px;
            transition:all 0.5s;opacity:0.35;flex:1;max-width:120px;
        ">
            <div class="podium-avatar" style="
                width:44px;height:44px;border-radius:50%;
                background:${colors[i % colors.length]}22;
                border:2px solid ${colors[i % colors.length]};
                color:${colors[i % colors.length]};
                display:flex;align-items:center;justify-content:center;
                font-size:18px;font-weight:700;transition:all 0.5s;
            ">${_esc((e.name || '').replace(/^(Dr\.|Prof\.) /, '').substring(0, 2))}</div>
            <div style="font-size:10px;font-weight:600;color:var(--text-primary);text-align:center;
                line-height:1.2;">${_esc(e.name)}</div>
        </div>`).join('');

    return `
        <div id="podium-stage" style="
            position:relative;height:100px;max-width:600px;margin:0 auto 12px;
            background:linear-gradient(to top,var(--bg-secondary),transparent);
            border-radius:12px;overflow:hidden;
        ">
            <div style="
                position:absolute;top:8px;left:50%;transform:translateX(-50%);
                width:60px;height:3px;border-radius:2px;
                background:radial-gradient(circle at center,var(--text-muted),transparent);
                opacity:0.4;
            "></div>
            <div style="
                position:absolute;bottom:0;left:0;right:0;height:2px;
                background:var(--border-color);opacity:0.2;
            "></div>
            <div style="
                display:flex;justify-content:center;align-items:flex-end;
                gap:4px;padding:0 16px 8px;height:100%;
            ">${pods}</div>
        </div>`;
}

function _initPodium() {
    _podiumInitialized = true;
}

function _updatePodium(activeName) {
    const spots = document.querySelectorAll('.podium-spot');
    spots.forEach(spot => {
        const name = spot.dataset.name;
        if (activeName && name === activeName) {
            spot.style.opacity = '1';
            spot.style.transform = 'translateY(-8px)';
            const avatar = spot.querySelector('.podium-avatar');
            if (avatar) { avatar.style.boxShadow = '0 0 20px rgba(167,139,250,0.5)'; avatar.style.transform = 'scale(1.15)'; }
        } else {
            spot.style.opacity = '0.35';
            spot.style.transform = 'translateY(0)';
            const avatar = spot.querySelector('.podium-avatar');
            if (avatar) { avatar.style.boxShadow = 'none'; avatar.style.transform = 'scale(1)'; }
        }
    });
}

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
    if (isAudit) {
        div.innerHTML = `<strong>${_esc(data.name)}</strong> is drafting<span class="dots"><span>.</span><span>.</span><span>.</span></span>`;
    } else {
        div.innerHTML = `<strong>${_esc(data.name)}</strong> is formulating<span class="dots"><span>.</span><span>.</span><span>.</span></span>`;
    }
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function _preprocessStructuredMarkdown(md) {
    // Convert **Keywords:** chip1, chip2, chip3 into HTML chip tags
    return md.replace(/\*\*Keywords:\*\*\s*(.+?)(?:\n|$)/, (_, keywords) => {
        const chips = keywords.split(',').map(k =>
            `<span class="keyword-chip">${_esc(k.trim())}</span>`
        ).join('');
        return `<div class="keyword-row">${chips}</div>`;
    });
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
        ? (data.name === 'Rapporteur' ? '📋' : '🔬')
        : data.name.replace(/^(Dr\.|Prof\.) /, '').substring(0, 1);

    const bubbleWrap = document.createElement('div');
    bubbleWrap.className = 'chat-bubble-wrapper';

    const header = document.createElement('div');
    header.className = 'chat-header';
    const roleLabel = isAudit
        ? (data.name === 'Rapporteur' ? 'Synthesis' : data.discipline || '')
        : data.discipline || '';
    header.innerHTML = `<strong>${_esc(data.name)}</strong> <span>${isAudit ? 'Round ' + _liveCurrentRound : _esc(roleLabel)}</span>`;

    const bubble = document.createElement('div');
    const isStructured = !isAudit;
    bubble.className = 'chat-bubble markdown-content' + (isStructured ? ' structured' : '');
    bubble.innerHTML = marked.parse(isStructured ? _preprocessStructuredMarkdown(data.content) : data.content);

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
    const activeBtn = document.querySelector('.nav-btn.active');
    if (activeBtn && activeBtn.dataset.phase === 'research') {
        _renderLiveResearchPhase();
    }
}

// ── Library Shelves Animation (Phase B1) ─────────────────────────────────────

const _BOOK_TITLES = [
    'arXiv:2305.12', 'Nature 592', 'Science 378', 'Cell 185', 'PNAS 120',
    'Phys. Rev. D', 'J. Neurosci.', 'Lancet 401', 'ACM Comput.', 'IEEE Trans.',
    'NeurIPS 23', 'ICML Proc.', 'J. Fluid Mech.', 'Angew. Chem.', 'PLoS ONE',
    'eLife 12', 'Acta Mater.', 'Astrophys. J.', 'Geology 51', 'Mol. Cell 83',
];

function _renderLibraryShelves(experts) {
    const colors = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f472b6', '#fb923c'];

    // Build expert legend
    const legend = experts.map((r, i) => `
        <div style="display:flex;align-items:center;gap:6px;font-size:12px;">
            <span style="width:10px;height:10px;border-radius:2px;background:${colors[i % colors.length]};flex-shrink:0;"></span>
            <span style="color:var(--text-primary);">${_esc(r.name)}</span>
        </div>
    `).join('');

    // Build 5 shelf rows
    let shelvesHtml = '';
    for (let s = 0; s < 5; s++) {
        shelvesHtml += `
            <div class="library-shelf" style="
                position:relative;height:48px;margin-bottom:8px;
                border-bottom:3px solid var(--border-color);
                display:flex;align-items:flex-end;gap:3px;padding:0 4px;
            " id="shelf-${s}">
            </div>`;
    }

    contentBody.innerHTML = `
        <div style="padding:20px 16px;">
            <p style="color:var(--text-muted);margin-bottom:12px;text-align:center;">
                ${_esc(_liveResearchStatus || 'B1 · Collecting sources — scouring the literature…')}
            </p>
            <div style="display:flex;justify-content:center;gap:20px;margin-bottom:20px;flex-wrap:wrap;">
                ${legend}
            </div>
            <div class="library-shelves" style="
                max-width:700px;margin:0 auto;padding:16px;
                background:var(--bg-secondary);border-radius:12px;
            " id="library-shelves">
                <div style="
                    display:flex;align-items:center;gap:6px;
                    color:var(--text-muted);font-size:12px;margin-bottom:12px;
                ">
                    <span>📚</span> <span id="shelf-book-count">0 sources collected</span>
                </div>
                ${shelvesHtml}
            </div>
        </div>`;

    // Start adding books to shelves
    _shelfBooks = [];
    if (_shelvesTimer) clearInterval(_shelvesTimer);

    function addBook() {
        const shelfIndex = Math.floor(Math.random() * 5);
        const shelf = document.getElementById(`shelf-${shelfIndex}`);
        if (!shelf) return;

        const ei = _shelfBooks.length % experts.length;
        const color = colors[ei % colors.length];
        const title = _BOOK_TITLES[Math.floor(Math.random() * _BOOK_TITLES.length)];
        const h = 18 + Math.random() * 24; // random book height

        const book = document.createElement('div');
        book.className = 'shelf-book';
        book.style.cssText = `
            width:${42 + Math.random() * 28}px;height:${h}px;
            background:${color};opacity:0.85;border-radius:2px 2px 0 0;
            flex-shrink:0;transition:all 0.3s;
            font-size:8px;color:#fff;display:flex;align-items:flex-end;
            padding:1px 2px;writing-mode:vertical-rl;overflow:hidden;
        `;
        book.textContent = title;
        shelf.appendChild(book);

        _shelfBooks.push({ shelf: shelfIndex, color, title });
        const count = document.getElementById('shelf-book-count');
        if (count) count.textContent = `${_shelfBooks.length} sources collected`;
    }

    // Initial burst
    for (let i = 0; i < 3; i++) addBook();
    // Then add periodically
    _shelvesTimer = setInterval(addBook, 600);
}

// ── Stamp Verification Animation (Phase B2) ──────────────────────────────────

let _stampTimer = null;
let _stampSources = [];

function _renderStampVerification(experts) {
    const colors = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f472b6', '#fb923c'];

    // Generate mock sources from the shelves
    if (_shelfBooks.length && !_stampSources.length) {
        _stampSources = _shelfBooks.map((b, i) => ({
            id: i, label: b.title, color: b.color, status: 'pending'
        }));
    }
    if (!_stampSources.length) {
        // Fallback if no shelves data
        for (let i = 0; i < 12; i++) {
            _stampSources.push({
                id: i,
                label: _BOOK_TITLES[Math.floor(Math.random() * _BOOK_TITLES.length)],
                color: colors[Math.floor(Math.random() * colors.length)],
                status: 'pending',
            });
        }
    }

    function renderConveyor() {
        const items = _stampSources.map((s, i) => {
            const stampIcon = s.status === 'verified' ? '<span style="color:#22c55e;">✓</span>'
                : s.status === 'rejected' ? '<span style="color:#ef4444;">✗</span>'
                : '<span style="color:var(--text-muted);">○</span>';
            return `
                <div class="stamp-item" style="
                    display:flex;align-items:center;gap:8px;padding:6px 10px;
                    background:var(--bg-primary);border-radius:6px;
                    border:1px solid var(--border-color);
                    font-size:12px;transition:all 0.3s;
                    ${s.status === 'rejected' ? 'opacity:0.5;text-decoration:line-through;' : ''}
                ">
                    <span style="width:8px;height:8px;border-radius:2px;background:${s.color};flex-shrink:0;"></span>
                    <span style="color:var(--text-primary);flex:1;">${s.label}</span>
                    ${stampIcon}
                </div>`;
        }).join('');

        const v = _stampSources.filter(s => s.status === 'verified').length;
        const r = _stampSources.filter(s => s.status === 'rejected').length;
        const p = _stampSources.filter(s => s.status === 'pending').length;

        contentBody.innerHTML = `
            <div style="padding:20px 16px;">
                <p style="color:var(--text-muted);margin-bottom:16px;text-align:center;">
                    ${_esc(_liveResearchStatus || 'B2 · Verifying sources…')}
                </p>
                <div style="display:flex;justify-content:center;gap:24px;margin-bottom:16px;font-size:13px;">
                    <span style="color:#22c55e;">✓ ${v} verified</span>
                    <span style="color:var(--text-muted);">○ ${p} pending</span>
                    <span style="color:#ef4444;">✗ ${r} rejected</span>
                </div>
                <div style="max-width:500px;margin:0 auto;display:flex;flex-direction:column;gap:4px;"
                    id="stamp-conveyor">
                    ${items}
                </div>
            </div>`;
    }

    renderConveyor();

    // Stamp items one by one
    if (_stampTimer) clearInterval(_stampTimer);
    _stampTimer = setInterval(() => {
        const pending = _stampSources.filter(s => s.status === 'pending');
        if (!pending.length) { clearInterval(_stampTimer); return; }
        const next = pending[0];
        // ~80% verified, ~20% rejected (simulated)
        next.status = Math.random() < 0.8 ? 'verified' : 'rejected';
        renderConveyor();
    }, 500);
}

// ── Thought Bubbles Animation (Phase B3) ─────────────────────────────────────

let _bubbleTimer = null;

function _renderThoughtBubbles(experts) {
    if (_stampTimer) { clearInterval(_stampTimer); _stampTimer = null; }
    const colors = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f472b6', '#fb923c'];

    const _THOUGHTS = [
        'Analysing structural properties…',
        'Cross-referencing findings…',
        'Evaluating statistical significance…',
        'Synthesising disciplinary insights…',
        'Comparing methodological approaches…',
        'Identifying emergent patterns…',
        'Forming preliminary hypotheses…',
        'Weighing evidence strength…',
    ];

    function renderBubbles() {
        const cards = experts.map((r, i) => {
            const thought = _THOUGHTS[Math.floor(Math.random() * _THOUGHTS.length)];
            return `
                <div class="thought-card" style="
                    text-align:center;padding:16px;
                    background:var(--bg-primary);border-radius:12px;
                    border:2px solid ${colors[i % colors.length]}22;
                ">
                    <div class="thought-avatar" style="
                        width:48px;height:48px;border-radius:50%;
                        background:${colors[i % colors.length]}22;
                        border:2px solid ${colors[i % colors.length]};
                        color:${colors[i % colors.length]};
                        display:flex;align-items:center;justify-content:center;
                        margin:0 auto 8px;font-size:20px;font-weight:700;
                    ">${_esc(r.name.replace(/^(Dr\.|Prof\.) /, '').substring(0, 2))}</div>
                    <div style="font-size:13px;font-weight:600;color:var(--text-primary);">
                        ${_esc(r.name)}
                    </div>
                    <div style="font-size:11px;color:var(--text-muted);margin-bottom:10px;">
                        ${_esc(r.discipline)}
                    </div>
                    <div class="thought-bubble" style="
                        position:relative;padding:10px 14px;
                        background:${colors[i % colors.length]}0d;
                        border:1px solid ${colors[i % colors.length]}33;
                        border-radius:16px;font-size:11px;
                        color:var(--text-muted);animation:pulse 2s ease-in-out infinite;
                    ">
                        <div class="thought-dots" style="display:flex;gap:3px;justify-content:center;">
                            <span style="animation:dotPulse 1.4s infinite;">.</span>
                            <span style="animation:dotPulse 1.4s .2s infinite;">.</span>
                            <span style="animation:dotPulse 1.4s .4s infinite;">.</span>
                        </div>
                        <div style="margin-top:4px;font-style:italic;">${thought}</div>
                    </div>
                </div>`;
        }).join('');

        contentBody.innerHTML = `
            <div style="padding:20px 16px;">
                <p style="color:var(--text-muted);margin-bottom:20px;text-align:center;">
                    ${_esc(_liveResearchStatus || 'B3 · Analysing sources — forming evidence-based opinions…')}
                </p>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;
                    max-width:700px;margin:0 auto;" id="thought-grid">
                    ${cards}
                </div>
            </div>`;
    }

    renderBubbles();

    if (_bubbleTimer) clearInterval(_bubbleTimer);
    _bubbleTimer = setInterval(renderBubbles, 2000);
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
    _updateNewSessionBtnState();
}
