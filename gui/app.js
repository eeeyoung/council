// gui/app.js

//let currentPhase = 'setup';
let currentAnimationId = 0;

// Configure marked.js to use highlight.js for code blocks
marked.setOptions({
    highlight: function (code, lang) {
        const language = hljs.getLanguage(lang) ? lang : 'plaintext';
        return hljs.highlight(code, { language }).value;
    },
    gfm: true,
    breaks: true
});

const contentBody = document.getElementById('content-body');
const phaseTitle = document.getElementById('phase-title');

// Map phases to the mock file paths
const mockFiles = {
    'panel': '/outputs/ba71cf60_panel.json',
    'research': '/outputs/ba71cf60_research.md',
    'debate': '/outputs/ba71cf60_transcript.md',
    'scorecard': '/outputs/ba71cf60_scorecard.md',
    'dossier': '/outputs/ba71cf60_dossier.md'
};

const phaseTitles = {
    'panel': 'The Expert Panel',
    'research': 'Research Library',
    'debate': 'The Live Symposium',
    'scorecard': 'Evidence Scorecard',
    'dossier': 'Final Dossier'
};

async function loadMarkdown(url) {
    try {
        const response = await fetch(url + '?t=' + Date.now());
        if (!response.ok) throw new Error('File not found');
        const text = await response.text();
        return marked.parse(text);
    } catch (e) {
        return `<div class="markdown-content"><p style="color: #ef4444;">Error loading mock data: ${e.message}</p>
        <p>Make sure you started the local server from the root directory!</p></div>`;
    }
}

async function switchPhase(phaseId) {
    // Update active button
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.phase === phaseId) btn.classList.add('active');
    });

    phaseTitle.innerText = phaseTitles[phaseId];
    contentBody.innerHTML = '<div class="loading-spinner"></div>';

    if (phaseId === 'panel') {
        await renderPanelPhase();
        return;
    }

    currentAnimationId++;

    try {
        if (phaseId === 'research') {
            await renderResearchPhase();
        } else if (phaseId === 'debate') {
            await renderDebatePhase();
        } else if (phaseId === 'scorecard') {
            await renderScorecardPhase();
        } else if (phaseId === 'dossier') {
            await renderDossierPhase();
        } else {
            const url = mockFiles[phaseId];
            const response = await fetch(url + '?t=' + Date.now());
            if (!response.ok) throw new Error('File not found');
            let text = await response.text();

            const html = marked.parse(text);
            contentBody.innerHTML = `<div class="markdown-content">${html}</div>`;
        }
    } catch (e) {
        contentBody.innerHTML = `<div class="markdown-content"><p style="color: #ef4444;">Error loading mock data: ${e.message}</p>
        <p>Make sure you started the local server from the root directory!</p></div>`;
    }
}

const mockResearchFiles = [
    { id: 'dr_elena_vasquez', name: 'Dr. Elena Vasquez', url: '/outputs/ba71cf60_research_dr_elena_vasquez.md' },
    { id: 'dr_kenji_tanaka', name: 'Dr. Kenji Tanaka', url: '/outputs/ba71cf60_research_dr_kenji_tanaka.md' },
    { id: 'dr_sarah_mbeki', name: 'Dr. Sarah Mbeki', url: '/outputs/ba71cf60_research_dr_sarah_mbeki.md' },
    { id: '__aggregation__', name: 'Aggregator Summary', url: '/outputs/ba71cf60_research___aggregation__.md' }
];

// ─── Phase A: Two-Step Wizard ─────────────────────────────────────────────────

const panelWizardState = {
    step: 1,
    query: 'Can we simulate froth flotation images indistinguishable from real ones using only operational variables (frother, collector, air flow) and a small set of real images?',
    experts: [],
    dirty: false,
    visited: new Set([1]),
};

async function renderPanelPhase() {
    if (panelWizardState.step === 1) {
        _renderStep1();
    } else {
        _renderStep2();
    }
}

// ── Step Indicator ────────────────────────────────────────────────────────────

function _renderStepper() {
    const steps = [
        { n: 1, label: 'Research Question' },
        { n: 2, label: 'Expert Panel' },
    ];
    return `
        <div class="wizard-stepper">
            ${steps.map((s, i) => {
                const visited = panelWizardState.visited.has(s.n);
                const active  = panelWizardState.step === s.n;
                const done    = visited && !active;
                const cls     = active ? 'step-active' : done ? 'step-done' : 'step-future';
                const clickable = visited ? `onclick="wizardGoTo(${s.n})"` : '';
                return `
                    ${i > 0 ? '<div class="wizard-connector"></div>' : ''}
                    <div class="wizard-step ${clickable ? 'step-clickable' : ''}" ${clickable}>
                        <div class="wizard-dot ${cls}">${done ? '✓' : s.n}</div>
                        <span class="wizard-label ${cls}">${s.label}</span>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

// ── Step 1: Research Question ─────────────────────────────────────────────────

function _renderStep1() {
    contentBody.innerHTML = `
        <div class="panel-editor wizard-panel">
            ${_renderStepper()}

            <div class="question-stage">
                <div class="question-prompt">
                    <h2 class="question-title">What would you like to investigate?</h2>
                    <p class="question-hint">Be as specific as possible. The Moderator will design a panel of experts optimised for your exact question.</p>
                </div>

                <textarea
                    id="query-input"
                    class="question-input"
                    rows="5"
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
        </div>
    `;

    const input = document.getElementById('query-input');
    if (input) {
        input.focus();
        // Ctrl+Enter shortcut
        input.addEventListener('keydown', e => {
            if (e.ctrlKey && e.key === 'Enter') wizardAdvance();
        });
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

// ── Step 2: Expert Panel Editor ───────────────────────────────────────────────

async function _loadExpertsIfNeeded() {
    if (panelWizardState.experts.length === 0) {
        const res = await fetch(mockFiles['panel'] + '?t=' + Date.now());
        if (!res.ok) throw new Error('Could not load panel data.');
        panelWizardState.experts = await res.json();
    }
}

function _renderStep2() {
    const experts = panelWizardState.experts;
    const rows = experts.map((e, i) => `
        <tr id="expert-row-${i}">
            <td><input class="panel-input" id="pname-${i}" value="${_esc(e.name)}" oninput="onPanelEdit()" /></td>
            <td><input class="panel-input" id="pdisc-${i}" value="${_esc(e.discipline)}" oninput="onPanelEdit()" /></td>
            <td><input class="panel-input" id="pbias-${i}" value="${_esc(e.bias)}" oninput="onPanelEdit()" /></td>
            <td><textarea class="panel-textarea" id="ppersona-${i}" rows="3" oninput="onPanelEdit()">${_esc(e.persona_prompt)}</textarea></td>
            <td><button class="panel-remove-btn" onclick="removeExpert(${i})" title="Remove expert">✕</button></td>
        </tr>
    `).join('');

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
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Discipline</th>
                            <th>Intellectual Bias</th>
                            <th>Persona</th>
                            <th></th>
                        </tr>
                    </thead>
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
                        <input type="number" id="regen-count" class="panel-spinbox" value="5" min="2" max="8" />
                        <span class="panel-spinbox-label">experts</span>
                    </div>
                    <button class="panel-btn panel-btn-polish" id="polish-btn" onclick="polishPanel()" ${panelWizardState.dirty ? '' : 'disabled'}>
                        ✦ Polish &amp; Align
                    </button>
                    <button class="panel-btn panel-btn-proceed" onclick="proceedPanel()">
                        Proceed →
                    </button>
                </div>
            </div>

            <div class="wizard-nav wizard-nav-back">
                <button class="panel-btn panel-btn-ghost" onclick="wizardRevert()">← Back to Question</button>
            </div>
        </div>
    `;
}

// ── Wizard Navigation ─────────────────────────────────────────────────────────

window.wizardGoTo = function (step) {
    if (!panelWizardState.visited.has(step)) return;
    if (panelWizardState.step === 2) _readPanelFromDOM();
    panelWizardState.step = step;
    renderPanelPhase();
};

window.wizardAdvance = async function () {
    const q = document.getElementById('query-input')?.value?.trim() || panelWizardState.query.trim();
    if (q.length < 10) return;

    // If already on Step 2 with expert edits and question changed — warn
    const questionChanged = q !== panelWizardState.query;
    if (panelWizardState.visited.has(2) && panelWizardState.experts.length > 0 && questionChanged) {
        const confirmed = confirm(
            'Changing the research question will regenerate the expert panel.\n\nYour current panel edits will be lost. Continue?'
        );
        if (!confirmed) return;
        panelWizardState.experts = [];
        panelWizardState.dirty = false;
    }

    panelWizardState.query = q;

    // Show a brief loading state
    contentBody.innerHTML = `
        <div class="panel-editor wizard-panel" style="align-items:center;justify-content:center;gap:16px;">
            ${_renderStepper()}
            <div style="text-align:center;padding:60px 0;">
                <div class="loading-spinner"></div>
                <p style="margin-top:20px;color:var(--text-muted);font-size:14px;">Assembling your expert panel<span class="dots"><span>.</span><span>.</span><span>.</span></span></p>
            </div>
        </div>
    `;

    await new Promise(r => setTimeout(r, 1400)); // Simulate API call

    try {
        await _loadExpertsIfNeeded();
        panelWizardState.step = 2;
        panelWizardState.visited.add(2);
        _renderStep2();
    } catch (e) {
        contentBody.innerHTML = `<p style="color:red;padding:20px">${e.message}</p>`;
    }
};

window.wizardRevert = function () {
    if (panelWizardState.step === 2) _readPanelFromDOM();
    panelWizardState.step = 1;
    _renderStep1();
};

// ── Panel Editing Helpers ─────────────────────────────────────────────────────

function _esc(str) {
    return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _readPanelFromDOM() {
    panelWizardState.experts = panelWizardState.experts.map((_, i) => ({
        name: document.getElementById(`pname-${i}`)?.value || '',
        discipline: document.getElementById(`pdisc-${i}`)?.value || '',
        bias: document.getElementById(`pbias-${i}`)?.value || '',
        persona_prompt: document.getElementById(`ppersona-${i}`)?.value || '',
    }));
}

window.onPanelEdit = function () {
    panelWizardState.dirty = true;
    const polishBtn = document.getElementById('polish-btn');
    if (polishBtn) polishBtn.disabled = false;
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
        name: 'Dr. New Expert',
        discipline: 'Field of Study',
        bias: 'Methodological leaning.',
        persona_prompt: "Describe this expert's personality and approach in 2-3 sentences."
    });
    _renderStep2();
    onPanelEdit();
    setTimeout(() => {
        const lastRow = document.getElementById(`expert-row-${panelWizardState.experts.length - 1}`);
        if (lastRow) lastRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);
};

window.regeneratePanel = function () {
    const count = document.getElementById('regen-count')?.value || 5;
    alert(`[Mock Mode] This would call the backend to regenerate a panel of ${count} experts for:\n\n"${panelWizardState.query}"`);
};

window.polishPanel = function () {
    _readPanelFromDOM();
    const btn = document.getElementById('polish-btn');
    if (btn) { btn.disabled = true; btn.textContent = '✦ Polishing…'; }
    setTimeout(() => {
        panelWizardState.experts = panelWizardState.experts.map(e => ({
            ...e,
            bias: e.bias.trim().endsWith('.') ? e.bias.trim() : e.bias.trim() + '.',
            persona_prompt: e.persona_prompt.trim()
        }));
        panelWizardState.dirty = false;
        _renderStep2();
        alert('[Mock Mode] In the full version, this sends your edits to the LLM to rephrase and align terminology.');
    }, 1000);
};

window.proceedPanel = function () {
    _readPanelFromDOM();
    alert(`[Mock Mode] Panel of ${panelWizardState.experts.length} experts confirmed.\nIn the full version, this triggers Phase B parallel research.`);
};


async function renderResearchPhase() {
    let tabsHtml = '<div class="sub-tabs">';
    let contentHtml = '<div class="sub-tab-content">';

    for (let i = 0; i < mockResearchFiles.length; i++) {
        const file = mockResearchFiles[i];
        const activeClass = i === 0 ? 'active' : '';
        const displayStyle = i === 0 ? 'block' : 'none';

        tabsHtml += `<button class="sub-tab-btn ${activeClass}" onclick="switchSubTab(${i})">${file.name}</button>`;

        try {
            const res = await fetch(file.url + '?t=' + Date.now());
            if (!res.ok) throw new Error('File not found');
            let bodyText = await res.text();

            // Normalize Windows line endings to Unix line endings for regex compatibility
            bodyText = bodyText.replace(/\r\n/g, '\n');

            // 1. Remove redundant tab name headers if they exist at the very top
            bodyText = bodyText.replace(/^##\s+(Dr\.|Aggregator Summary).*?\n+/i, '');
            // 2. Remove horizontal rules as we will use CSS cards to separate sections
            bodyText = bodyText.replace(/^---\s*$/gm, '');

            // 3. Apply the finding block regexes
            // We terminate the block capture when we see a new block (**), a new finding (###), a new section (##), or a divider (---)
            const stopRegex = '(?=\\n\\n\\*\\*|\\n\\n### |\\n\\n## |\\n\\n---|$)';
            let parsedBody = bodyText
                .replace(new RegExp(`\\*\\*Source:\\*\\*\\s*(.*?)${stopRegex}`, 'gs'), '<div class="finding-block source-block"><strong>Source:</strong> $1</div>')
                .replace(new RegExp(`\\*\\*Supporting Source:\\*\\*\\s*(.*?)${stopRegex}`, 'gs'), '<div class="finding-block support-block"><strong>Supporting Source:</strong> $1</div>')
                .replace(new RegExp(`\\*\\*Key Finding:\\*\\*\\s*(.*?)${stopRegex}`, 'gs'), '<div class="finding-block key-block"><strong>Key Finding:</strong> $1</div>')
                .replace(new RegExp(`\\*\\*Relevance[^\\*]*:\\*\\*\\s*(.*?)${stopRegex}`, 'gs'), '<div class="finding-block rel-block"><strong>Relevance:</strong> $1</div>');

            // 4. Split into hierarchical sections (H2)
            let sections = parsedBody.split(/\n## /);

            let tabContentHtml = '';

            // The first chunk contains H1 (if any) and text before the first H2
            if (sections[0].trim()) {
                tabContentHtml += `<div class="markdown-content header-section">${marked.parse(sections[0])}</div>`;
            }

            // The remaining chunks are H2 sections
            for (let j = 1; j < sections.length; j++) {
                let sectionText = "## " + sections[j];
                tabContentHtml += `<div class="section-card"><div class="markdown-content">${marked.parse(sectionText)}</div></div>`;
            }

            contentHtml += `<div class="sub-tab-pane" id="expert-pane-${i}" style="display: ${displayStyle};">${tabContentHtml}</div>`;
        } catch (e) {
            contentHtml += `<div class="sub-tab-pane" id="expert-pane-${i}" style="display: ${displayStyle};"><p style="color:red">Failed to load ${file.name}: ${e.message}</p></div>`;
        }
    }

    tabsHtml += '</div>';
    contentHtml += '</div>';

    contentBody.innerHTML = tabsHtml + contentHtml;
}

window.switchSubTab = function (index) {
    document.querySelectorAll('.sub-tab-btn').forEach((btn, i) => {
        btn.classList.toggle('active', i === index);
    });
    document.querySelectorAll('.sub-tab-pane').forEach((pane, i) => {
        pane.style.display = i === index ? 'block' : 'none';
    });
};

function startNewSession() {
    alert("This is a mock UI. In the full version, this will open the query input modal.");
}

async function renderDebatePhase() {
    const animId = currentAnimationId;
    const url = mockFiles['debate'];
    const response = await fetch(url + '?t=' + Date.now());
    if (!response.ok) throw new Error('File not found');
    let text = await response.text();
    text = text.replace(/\r\n/g, '\n');

    const contentBody = document.getElementById('content-body');
    contentBody.innerHTML = `<div class="chat-container" id="chat-container"></div>`;
    const chatContainer = document.getElementById('chat-container');

    // Parse ALL message types: expert turns, host synthesis, host verdicts
    // Format: [Turn N] **Name** (Discipline):\ncontent
    //         [HOST-A] **Synthesis Host** (Round N):\ncontent
    //         [HOST-B] **Hostile Peer Reviewer** (Round N):\ncontent
    const messageRegex = /(\[Turn \d+\]|\[HOST-A\]|\[HOST-B\]) \*\*(.*?)\*\* \((.*?)\):\n([\s\S]*?)(?=\n(?:\[Turn \d+\]|\[HOST-A\]|\[HOST-B\])|$)/g;
    let match;
    const messages = [];
    let currentRound = 1;

    while ((match = messageRegex.exec(text)) !== null) {
        const marker = match[1];
        const name = match[2];
        const meta = match[3]; // discipline or "Round N"
        const content = match[4].trim();

        // Detect round transitions from HOST-A/B meta
        const roundMatch = meta.match(/Round (\d+)/);
        if (roundMatch) currentRound = parseInt(roundMatch[1]);

        messages.push({
            marker,
            name,
            meta,
            content,
            round: currentRound,
            isHost: marker === '[HOST-A]' || marker === '[HOST-B]',
            isHostA: marker === '[HOST-A]',
            isHostB: marker === '[HOST-B]',
        });
    }

    if (messages.length === 0) {
        chatContainer.innerHTML = '<p style="padding: 20px; color: var(--text-muted);">Waiting for debate to begin...</p>';
        return;
    }

    let renderedRound = null;

    // Typewriter Queue Engine
    for (let i = 0; i < messages.length; i++) {
        if (animId !== currentAnimationId) return;
        const msg = messages[i];

        // Insert round divider when round changes
        if (msg.round !== renderedRound) {
            renderedRound = msg.round;
            const divider = document.createElement('div');
            divider.className = 'round-divider';
            divider.innerHTML = `<span>── Round ${msg.round} ──</span>`;
            chatContainer.appendChild(divider);
        }

        // Indicator text differs by speaker type
        const indicatorText = msg.isHostA
            ? `<strong>Synthesis Host</strong> is drafting consensus<span class="dots"><span>.</span><span>.</span><span>.</span></span>`
            : msg.isHostB
            ? `<strong>Peer Reviewer</strong> is auditing the synthesis<span class="dots"><span>.</span><span>.</span><span>.</span></span>`
            : `<strong>${msg.name}</strong> is formulating argument<span class="dots"><span>.</span><span>.</span><span>.</span></span>`;

        const indicator = document.createElement('div');
        indicator.className = `chat-indicator ${msg.isHost ? 'indicator-right' : ''}`;
        indicator.innerHTML = indicatorText;
        chatContainer.appendChild(indicator);
        chatContainer.scrollTop = chatContainer.scrollHeight;

        await new Promise(r => setTimeout(r, 1200));
        if (animId !== currentAnimationId) return;
        indicator.remove();

        // Create bubble wrapper
        const msgWrapper = document.createElement('div');
        msgWrapper.className = `chat-message ${msg.isHost ? 'message-right ' + getHostColorClass(msg.marker) : getExpertColorClass(msg.name)}`;

        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = msg.isHostA ? '⚖' : msg.isHostB ? '🔬' : msg.name.replace('Dr. ', '').substring(0, 1);

        const bubbleWrapper = document.createElement('div');
        bubbleWrapper.className = 'chat-bubble-wrapper';

        const header = document.createElement('div');
        header.className = 'chat-header';
        header.innerHTML = `<strong>${msg.name}</strong> <span>${msg.meta}</span>`;

        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble markdown-content';

        // Host B: show APPROVED/REJECTED badge
        if (msg.isHostB) {
            const approved = /\"approved\":\s*true/i.test(msg.content) || /APPROVED/i.test(msg.content);
            const badge = document.createElement('div');
            badge.className = `verdict-badge ${approved ? 'verdict-approved' : 'verdict-rejected'}`;
            badge.textContent = approved ? '✓ APPROVED' : '✗ REJECTED';
            bubbleWrapper.appendChild(header);
            bubbleWrapper.appendChild(badge);
            bubbleWrapper.appendChild(bubble);
        } else {
            bubbleWrapper.appendChild(header);
            bubbleWrapper.appendChild(bubble);
        }

        if (msg.isHost) {
            msgWrapper.appendChild(bubbleWrapper);
            msgWrapper.appendChild(avatar);
        } else {
            msgWrapper.appendChild(avatar);
            msgWrapper.appendChild(bubbleWrapper);
        }

        chatContainer.appendChild(msgWrapper);

        // Stream text word by word
        let streamedText = '';
        const words = msg.content.split(/(\s+)/);
        for (let j = 0; j < words.length; j++) {
            if (animId !== currentAnimationId) return;
            streamedText += words[j];
            if (words[j].trim().length > 0) {
                bubble.innerHTML = marked.parse(streamedText);
                chatContainer.scrollTop = chatContainer.scrollHeight;
                await new Promise(r => setTimeout(r, Math.random() * 20 + 15));
            }
        }

        await new Promise(r => setTimeout(r, 800));
    }
}

function getExpertColorClass(name) {
    if (name.includes('Vasquez')) return 'expert-cyan';
    if (name.includes('Tanaka')) return 'expert-magenta';
    if (name.includes('Mbeki')) return 'expert-green';
    return 'expert-default';
}

function getHostColorClass(marker) {
    return marker === '[HOST-A]' ? 'host-a' : 'host-b';
}

// ─── Phase D: Evidence Scorecard ─────────────────────────────────────────────

const EXPERT_COLORS = {
    'vasquez': { cls: 'claim-cyan',    label: 'Vasquez' },
    'tanaka':  { cls: 'claim-magenta', label: 'Tanaka'  },
    'mbeki':   { cls: 'claim-green',   label: 'Mbeki'   },
};

function _expertCls(name) {
    const n = (name || '').toLowerCase();
    if (n.includes('vasquez')) return EXPERT_COLORS['vasquez'];
    if (n.includes('tanaka'))  return EXPERT_COLORS['tanaka'];
    if (n.includes('mbeki'))   return EXPERT_COLORS['mbeki'];
    return { cls: 'claim-default', label: name };
}

async function renderScorecardPhase() {
    const res = await fetch(mockFiles['scorecard'] + '?t=' + Date.now());
    if (!res.ok) throw new Error('Scorecard file not found');
    const text = await res.text();
    const lines = text.replace(/\r\n/g, '\n').split('\n');

    // Parse bullet entries: • [Name] "claim" → URL
    const entries = [];
    const entryRegex = /^•\s+\[([^\]]+)\]\s+"([^"]+)"\s+→\s+(\S+)/;
    for (const line of lines) {
        const m = line.match(entryRegex);
        if (m) entries.push({ name: m[1], claim: m[2], url: m[3] });
    }

    if (entries.length === 0) {
        contentBody.innerHTML = '<p style="padding:20px;color:var(--text-muted)">No evidence entries found.</p>';
        return;
    }

    // Build filter buttons from unique expert names
    const experts = [...new Set(entries.map(e => e.name))];
    let activeFilter = 'all';

    function buildGrid(filter) {
        const filtered = filter === 'all' ? entries : entries.filter(e => e.name === filter);
        return filtered.map((e, i) => {
            const meta = _expertCls(e.name);
            const domain = (() => { try { return new URL(e.url).hostname; } catch { return e.url; } })();
            return `
                <div class="claim-card ${meta.cls}" id="claim-${i}">
                    <div class="claim-expert-chip">${e.name}</div>
                    <p class="claim-text">"${e.claim}"</p>
                    <a class="claim-source" href="${e.url}" target="_blank" rel="noopener">
                        View Source → <span class="claim-domain">${domain}</span>
                    </a>
                </div>`;
        }).join('');
    }

    contentBody.innerHTML = `
        <div class="scorecard-wrapper">
            <div class="scorecard-toolbar">
                <div class="scorecard-filters" id="sc-filters">
                    <button class="sc-filter-btn active" onclick="setScorecardFilter('all', this)">All <span class="sc-count">${entries.length}</span></button>
                    ${experts.map(n => `
                        <button class="sc-filter-btn" onclick="setScorecardFilter('${n}', this)">
                            ${n} <span class="sc-count">${entries.filter(e => e.name === n).length}</span>
                        </button>`).join('')}
                </div>
                <span class="sc-total-label">${entries.length} citations verified</span>
            </div>
            <div class="scorecard-grid" id="scorecard-grid">
                ${buildGrid('all')}
            </div>
        </div>
    `;

    window.setScorecardFilter = function(filter, btn) {
        document.querySelectorAll('.sc-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('scorecard-grid').innerHTML = buildGrid(filter);
    };
}

// ─── Phase E: Final Dossier ───────────────────────────────────────────────────

async function renderDossierPhase() {
    const res = await fetch(mockFiles['dossier'] + '?t=' + Date.now());
    if (!res.ok) throw new Error('Dossier file not found');
    const rawText = await res.text();
    const normalized = rawText.replace(/\r\n/g, '\n');

    // Extract H2 headings for Table of Contents
    const headings = [];
    normalized.split('\n').forEach((line, idx) => {
        const m = line.match(/^##\s+(.+)/);
        if (m) {
            const anchor = m[1].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
            headings.push({ text: m[1], anchor });
        }
    });

    const tocHtml = headings.map(h => `
        <li><a class="toc-link" href="#${h.anchor}" onclick="scrollToHeading('${h.anchor}', event)">${h.text}</a></li>
    `).join('');

    const bodyHtml = marked.parse(normalized);

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
            <div class="dossier-body markdown-content" id="dossier-body">
                ${bodyHtml}
            </div>
        </div>
    `;

    // Add IDs to H2 elements for anchor scrolling
    document.querySelectorAll('.dossier-body h2').forEach(el => {
        const anchor = el.textContent.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
        el.id = anchor;
    });

    window._dossierRawText = rawText;

    window.scrollToHeading = function(anchor, e) {
        e.preventDefault();
        const el = document.getElementById(anchor);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        document.querySelectorAll('.toc-link').forEach(l => l.classList.remove('toc-active'));
        e.target.classList.add('toc-active');
    };

    window.downloadDossier = function() {
        const blob = new Blob([window._dossierRawText], { type: 'text/markdown' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'ba71cf60_dossier.md';
        a.click();
        URL.revokeObjectURL(a.href);
    };

    window.copyDossier = function() {
        navigator.clipboard.writeText(window._dossierRawText).then(() => {
            const btn = document.getElementById('copy-btn');
            if (btn) { btn.textContent = '✓ Copied'; setTimeout(() => btn.textContent = '⎘ Copy', 2000); }
        });
    };
}

// Initial load — start at Phase A
switchPhase('panel');
