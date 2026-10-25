/**
 * KISAAN BHAROSA - CLIENT APPLICATION ARCHITECTURE
 * Laboratory-Grade Agritech Verification & Phytosanitary Portal
 */

// Application State
const state = {
    user: null,
    token: localStorage.getItem('kb_token') || null,
    currentTab: 'audit',
    currentScan: null,
    scans: [],
    products: [],
    productCategories: [],
    priceRegistry: [],
    reports: [],
    cameraStream: null,
    engine: null,
    pendingUploadScanId: null,
};

// API Helper
const CREDENTIAL_ENDPOINTS = ['/api/auth/login', '/api/auth/register'];

// Requests must not hang forever: a hung fetch leaves the button spinner running and
// gives the grower no way to tell a slow server from a dead one.
const DEFAULT_REQUEST_TIMEOUT_MS = 20000;
// Photo audits bill per call and can legitimately run for the length of the engine's
// own timeout, so they get a longer budget than a list request.
const ANALYSIS_TIMEOUT_MS = 90000;

function describeError(detail, fallback) {
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail)) {
        // FastAPI returns a list of validation problems, not a sentence.
        const parts = detail.map(item => {
            const field = (item.loc || []).filter(part => part !== 'body').join('.');
            return field ? `${field}: ${item.msg}` : item.msg;
        }).filter(Boolean);
        return parts.length ? parts.join('; ') : fallback;
    }
    if (detail && typeof detail === 'object') {
        return detail.message || detail.code || fallback;
    }
    return fallback;
}

async function apiCall(endpoint, options = {}) {
    const headers = options.headers || {};
    if (state.token) {
        headers['Authorization'] = `Bearer ${state.token}`;
    }
    if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }
    const { timeoutMs, ...fetchOptions } = options;

    try {
        const response = await fetch(endpoint, {
            ...fetchOptions,
            headers,
            signal: AbortSignal.timeout(timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS),
        });
        const isAttemptedCredential = CREDENTIAL_ENDPOINTS.some(path => endpoint.startsWith(path));
        if (response.status === 401 && state.token && !isAttemptedCredential) {
            // The stored token expired; the next sign-in has to be a fresh one.
            logoutUser();
            throw new Error('Your session expired. Please sign in again.');
        }
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            const error = new Error(describeError(errData.detail, 'The server could not complete this request.'));
            if (errData.detail && typeof errData.detail === 'object' && !Array.isArray(errData.detail)) {
                error.payload = errData.detail;
            }
            throw error;
        }
        if (response.status === 204) return null;
        return await response.json();
    } catch (err) {
        if (err.name === 'TimeoutError' || err.name === 'AbortError') {
            err.message = 'The server took too long to respond. Please try again.';
        } else if (err instanceof TypeError) {
            // fetch throws TypeError for anything the browser could not reach.
            err.message = 'Could not reach the server. Check your connection and try again.';
        }
        showToast(err.message, 'error');
        throw err;
    }
}

// Toast Notifications (Zero Emojis)
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    const borderClass = type === 'error' ? 'border-red-500 bg-red-50 text-red-900' :
                        type === 'success' ? 'border-emerald-600 bg-emerald-50 text-emerald-900' :
                        'border-slate-600 bg-white text-slate-800';

    toast.className = `p-4 rounded-md border-l-4 shadow-md text-xs font-medium flex items-center justify-between mb-2 transition-all transform duration-200 ${borderClass}`;
    toast.innerHTML = `
        <span>${escapeHtml(message)}</span>
        <button type="button" data-toast-dismiss aria-label="Dismiss notification" class="ml-4 text-slate-400 hover:text-slate-700">✕</button>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Initialization
document.addEventListener('DOMContentLoaded', async () => {
    initAuth();
    initNavigation();
    initDropzone();
    initCamera();
    initForms();
    initGlobalHandlers();

    // Load initial data
    await loadInitialData();
});

async function loadInitialData() {
    await Promise.allSettled([
        loadEngineStatus(),
        loadScansRegistry(),
        loadDirectory(),
        loadPriceRegistry(),
        loadFraudReports(),
        loadAnalyticsSummary(),
    ]);
}

// A status probe must never interrupt the portal with an error toast: if it fails, the
// browser-run path simply is not offered.
async function loadEngineStatus() {
    try {
        const response = await fetch('/api/scans/engine/status', {
            signal: AbortSignal.timeout(DEFAULT_REQUEST_TIMEOUT_MS),
        });
        state.engine = response.ok ? await response.json() : null;
    } catch (err) {
        state.engine = null;
    }
}

// -----------------------------------------------------------------------------
// Authentication
// -----------------------------------------------------------------------------
function initAuth() {
    const token = localStorage.getItem('kb_token');
    if (token) {
        state.token = token;
        apiCall('/api/auth/me')
            .then(user => {
                state.user = user;
                updateAuthUI();
            })
            .catch(() => {
                logoutUser();
            });
    } else {
        updateAuthUI();
    }
}

function updateAuthUI() {
    const authActions = document.getElementById('auth-actions');
    const userProfileBar = document.getElementById('user-profile-bar');
    const inspectorTabBtn = document.getElementById('tab-btn-dashboard');

    if (state.user) {
        authActions.classList.add('hidden');
        userProfileBar.classList.remove('hidden');
        document.getElementById('profile-name').textContent = state.user.full_name;
        document.getElementById('profile-role').textContent = state.user.role.toUpperCase();

        if (state.user.role === 'inspector' || state.user.role === 'admin') {
            if (inspectorTabBtn) inspectorTabBtn.classList.remove('hidden');
        } else {
            if (inspectorTabBtn) inspectorTabBtn.classList.add('hidden');
        }
    } else {
        authActions.classList.remove('hidden');
        userProfileBar.classList.add('hidden');
        if (inspectorTabBtn) inspectorTabBtn.classList.add('hidden');
    }
}

function logoutUser() {
    localStorage.removeItem('kb_token');
    state.token = null;
    state.user = null;
    updateAuthUI();
    showToast('Logged out successfully.', 'info');
    switchTab('audit');
    refreshScopedLists();
}

// The scan register and the complaint list are scoped to whoever is signed in, so both
// have to be re-read (or cleared) whenever the session changes.
function refreshScopedLists() {
    loadScansRegistry();
    loadFraudReports();
}

// -----------------------------------------------------------------------------
// Navigation Tabs
// -----------------------------------------------------------------------------
function initNavigation() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            switchTab(tab);
        });
    });
}

function switchTab(tabName) {
    state.currentTab = tabName;
    document.querySelectorAll('.tab-btn').forEach(btn => {
        if (btn.dataset.tab === tabName) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    document.querySelectorAll('.tab-pane').forEach(pane => {
        if (pane.id === `tab-pane-${tabName}`) {
            pane.classList.remove('hidden');
        } else {
            pane.classList.add('hidden');
        }
    });

    // Refresh tab-specific data
    if (tabName === 'registry') loadScansRegistry();
    if (tabName === 'directory') loadDirectory();
    if (tabName === 'reports') loadFraudReports();
    if (tabName === 'dashboard') loadAnalyticsSummary();
}

// -----------------------------------------------------------------------------
// Image Specimen Dropzone & Upload
// -----------------------------------------------------------------------------
let selectedFile = null;

function initDropzone() {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');

    if (!dropzone || !fileInput) return;

    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleFileSelection(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            handleFileSelection(e.target.files[0]);
        }
    });

    document.getElementById('btn-analyze').addEventListener('click', runAuditAnalysis);
    // The clear button sits inside the dropzone, so its click would otherwise reopen
    // the file picker.
    document.getElementById('btn-clear-preview').addEventListener('click', (e) => {
        e.stopPropagation();
        clearFileSelection();
    });
}

function handleFileSelection(file) {
    if (!file.type.match(/image\/(jpeg|png|webp|jpg)/)) {
        showToast('Only JPG, PNG, and WEBP image files are supported.', 'error');
        return;
    }
    if (file.size > 15 * 1024 * 1024) {
        showToast('File size must be under 15 MB.', 'error');
        return;
    }

    selectedFile = file;

    const reader = new FileReader();
    reader.onload = (e) => {
        document.getElementById('preview-img').src = e.target.result;
        document.getElementById('upload-prompt').classList.add('hidden');
        document.getElementById('preview-container').classList.remove('hidden');
        document.getElementById('btn-analyze').disabled = false;
    };
    reader.readAsDataURL(file);
}

function clearFileSelection() {
    selectedFile = null;
    document.getElementById('file-input').value = '';
    document.getElementById('preview-img').src = '';
    document.getElementById('preview-container').classList.add('hidden');
    document.getElementById('upload-prompt').classList.remove('hidden');
    document.getElementById('btn-analyze').disabled = true;
    document.getElementById('diagnostic-results').classList.add('hidden');
    document.getElementById('empty-audit-state').classList.remove('hidden');
}

// -----------------------------------------------------------------------------
// Live WebRTC Camera Capture
// -----------------------------------------------------------------------------
function initCamera() {
    const openCamBtn = document.getElementById('btn-open-camera');
    const modal = document.getElementById('camera-modal');
    const video = document.getElementById('camera-video');
    const captureBtn = document.getElementById('btn-capture-photo');
    const closeBtn = document.getElementById('btn-close-camera');

    if (!openCamBtn) return;

    openCamBtn.addEventListener('click', async () => {
        try {
            state.cameraStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 } }
            });
            video.srcObject = state.cameraStream;
            modal.classList.remove('hidden');
        } catch (err) {
            showToast('Unable to access camera: ' + err.message, 'error');
        }
    });

    closeBtn.addEventListener('click', () => {
        stopCamera();
        modal.classList.add('hidden');
    });

    captureBtn.addEventListener('click', () => {
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 480;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

        canvas.toBlob((blob) => {
            const capturedFile = new File([blob], `camera_${Date.now()}.jpg`, { type: 'image/jpeg' });
            stopCamera();
            modal.classList.add('hidden');
            handleFileSelection(capturedFile);
        }, 'image/jpeg', 0.92);
    });
}

function stopCamera() {
    if (state.cameraStream) {
        state.cameraStream.getTracks().forEach(track => track.stop());
        state.cameraStream = null;
    }
}

// -----------------------------------------------------------------------------
// Execute Audit & Diagnostic Inspection
// -----------------------------------------------------------------------------
async function runAuditAnalysis() {
    if (!selectedFile) return;

    const btnAnalyze = document.getElementById('btn-analyze');
    const progressBar = document.getElementById('audit-progress');
    const progressFill = document.getElementById('audit-progress-fill');
    const progressLabel = document.getElementById('audit-progress-label');

    btnAnalyze.disabled = true;
    progressBar.classList.remove('hidden');
    progressFill.style.width = '100%';
    progressLabel.textContent = 'Auditing the photograph. This can take up to a minute.';

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
        const result = await apiCall('/api/scans/analyze', {
            method: 'POST',
            body: formData,
            timeoutMs: ANALYSIS_TIMEOUT_MS,
        });

        progressBar.classList.add('hidden');
        renderDiagnosticReport(result);
        showToast(`Audit completed successfully: ${result.scan_ref}`, 'success');
    } catch (err) {
        progressBar.classList.add('hidden');
        const payload = err.payload;
        if (payload && payload.scan_id && payload.analysis_status !== 'COMPLETED') {
            // The photograph is stored and awaiting an engine. Show the record as pending
            // rather than leaving the panel on the previous result, and remember which
            // record this capture belongs to so the browser path can offer its own model.
            state.pendingUploadScanId = payload.scan_id;
            renderDiagnosticReport({
                id: payload.scan_id,
                scan_ref: payload.scan_ref,
                analysis_status: payload.analysis_status,
                analysis_error: payload.message,
                analysis_model: null,
                analysis_latency_ms: null,
                verdict: null,
                verdict_source: null,
                properties: [],
                image_url: null,
            });
        }
    } finally {
        btnAnalyze.disabled = false;
        if (state.token) loadScansRegistry();
        loadAnalyticsSummary();
    }
}

// -----------------------------------------------------------------------------
// Browser-run analysis (Puter.js)
//
// There is no server-side key for this path: the model is called from this page using
// the visitor's own Puter session. Whatever it answers is treated as an unverified claim
// until the server has validated it against the audit schema, and the server stamps it as
// browser-supplied so the report page can never render it as laboratory evidence.
// -----------------------------------------------------------------------------
const PUTER_FALLBACK_MODEL = 'gpt-5.6-luna';
// A vision call plus a Puter sign-in round trip; longer than the server engine's budget.
const PUTER_TIMEOUT_MS = 180000;

const PUTER_PROMPT = [
    'You are an agricultural input auditor and phytosanitary inspector working for a',
    'Pakistani regulatory desk. Examine the attached photograph and report only what is',
    'actually visible in it.',
    '1. CLASSIFY: "Agricultural Input Package" (seed bag, fertiliser sack, pesticide',
    'container), "Crop Specimen" (leaf, stem, fruit, whole plant) or "Unidentified Sample"',
    'if the subject cannot be determined.',
    '2. For an input package, inspect the printed brand and manufacturer, PSQCA mark and',
    'licence number, bag size, printed MRP, batch/lot printing quality, seal or hologram,',
    'and packaging weave, and judge each against Pakistani certification requirements.',
    '3. For a crop specimen, identify the crop and describe visible lesions, discolouration',
    'patterns, sporulation or pest signs, and give the treatment threshold advised by',
    'Punjab/Sindh/Khyber Pakhtunkhwa agricultural extension services.',
    '4. Return 5 to 7 technical properties. Each needs an observed value that a second',
    'inspector could verify from the photograph itself, plus the benchmark it is judged',
    "against. Use 'INCONCLUSIVE' for any marker you cannot actually see.",
    '5. If the photograph is too blurry, dark, distant or off-subject to audit, set',
    'classification to "Unidentified Sample", verdict to "INCONCLUSIVE", keep the',
    'confidence score low and say in the executive summary what must be re-photographed.',
    'Never guess a brand, batch number or pathogen that is not visible.',
    '6. Output only the JSON object described by the supplied schema. No emojis, no',
    'marketing language, no conversational filler.',
].join('\n');

// Mirrors app/schemas/scan.py DiagnosticReport. Kept by hand because the model is on the
// far side of the network and cannot be handed our Pydantic classes.
const PUTER_REPORT_SCHEMA = {
    type: 'object',
    additionalProperties: false,
    required: [
        'classification', 'subject_name', 'verdict', 'confidence_score',
        'executive_summary', 'properties', 'regulatory_alignment', 'protocol_action',
    ],
    properties: {
        classification: {
            type: 'string',
            enum: ['Agricultural Input Package', 'Crop Specimen', 'Unidentified Sample'],
        },
        subject_name: { type: 'string' },
        verdict: {
            type: 'string',
            enum: [
                'VERIFIED AUTHENTIC', 'COUNTERFEIT SUSPECTED', 'HEALTHY SPECIMEN',
                'DISEASE DETECTED', 'INCONCLUSIVE',
            ],
        },
        confidence_score: { type: 'integer', minimum: 0, maximum: 100 },
        executive_summary: { type: 'string' },
        properties: {
            type: 'array',
            items: {
                type: 'object',
                additionalProperties: false,
                required: ['property_name', 'status', 'observed_value', 'benchmark_standard'],
                properties: {
                    property_name: { type: 'string' },
                    status: { type: 'string', enum: ['PASSED', 'FLAGGED', 'INCONCLUSIVE'] },
                    observed_value: { type: 'string' },
                    benchmark_standard: { type: 'string' },
                },
            },
        },
        regulatory_alignment: { type: 'string' },
        protocol_action: { type: 'string' },
    },
};

function puterReady() {
    return !!(window.puter && window.puter.ai && typeof window.puter.ai.chat === 'function');
}

function puterModelName() {
    return (state.engine && state.engine.browser_fallback && state.engine.browser_fallback.model)
        || PUTER_FALLBACK_MODEL;
}

// Puter does not expose an AbortSignal on chat(), so a stalled call is bounded here. The
// request may still be billed once the model has it; the record stays pending either way.
function withTimeout(promise, ms, message) {
    let timer;
    const guard = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(message)), ms);
    });
    return Promise.race([promise, guard]).finally(() => clearTimeout(timer));
}

function textFromChatResponse(response) {
    const content = response && response.message ? response.message.content : response;
    if (typeof content === 'string') return content;
    if (Array.isArray(content)) {
        return content.map(part => (typeof part === 'string' ? part : (part && part.text) || '')).join('');
    }
    return content === undefined || content === null ? '' : String(content);
}

function parseModelJson(raw) {
    const text = raw.trim();
    // Even with a forced JSON schema some models wrap the object in prose or code fences,
    // so only the outermost brace pair is taken.
    const start = text.indexOf('{');
    const end = text.lastIndexOf('}');
    if (start === -1 || end <= start) {
        throw new Error('The model replied with something that is not a report. Please try again.');
    }
    return JSON.parse(text.slice(start, end + 1));
}

// A freshly captured photograph is already a File; a record reopened from the register is
// not, so its stored image is fetched back and rewrapped before the model can see it.
async function puterImageFile(report) {
    if (selectedFile && state.pendingUploadScanId === report.id) {
        return selectedFile;
    }
    if (!report.image_url) {
        throw new Error('There is no photograph attached to this record.');
    }
    const response = await fetch(report.image_url, { signal: AbortSignal.timeout(DEFAULT_REQUEST_TIMEOUT_MS) });
    if (!response.ok) {
        throw new Error('The stored photograph could not be read for browser analysis.');
    }
    const blob = await response.blob();
    const name = report.image_url.split('/').pop() || 'specimen.jpg';
    return new File([blob], name, { type: blob.type || 'image/jpeg' });
}

async function analyzeWithPuter() {
    const report = state.currentScan;
    if (!report) return;

    if (!state.token) {
        showToast('Sign in first: a browser verdict has to be attached to your record.', 'error');
        return;
    }
    if (!puterReady()) {
        showToast('Puter.js did not load. Check your connection and reload the page.', 'error');
        return;
    }

    const button = document.getElementById('btn-puter-analyze');
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Asking the model...';

    try {
        const file = await puterImageFile(report);
        const model = puterModelName();
        const started = performance.now();

        const response = await withTimeout(
            puter.ai.chat(PUTER_PROMPT, file, {
                model,
                outputFormat: { type: 'json_schema', schema: PUTER_REPORT_SCHEMA, name: 'diagnostic_report', strict: true },
            }),
            PUTER_TIMEOUT_MS,
            'The model did not answer in time. The record is still awaiting analysis.',
        );
        const latencyMs = Math.round(performance.now() - started);
        const parsed = parseModelJson(textFromChatResponse(response));

        const stored = await apiCall(`/api/scans/${report.id}/client-analysis`, {
            method: 'POST',
            body: JSON.stringify({ ...parsed, provider_model: model, latency_ms: latencyMs }),
        });

        renderDiagnosticReport(stored);
        showToast(`Browser verdict recorded for ${stored.scan_ref}. Flagged as not server-verified.`, 'success');
    } catch (err) {
        // apiCall has already surfaced a server rejection; a model-side failure has not.
        if (!err.payload) showToast(err.message || 'Browser analysis failed. The photograph is still saved.', 'error');
    } finally {
        button.disabled = false;
        button.textContent = originalLabel;
        loadScansRegistry();
    }
}

function renderDiagnosticReport(report) {
    document.getElementById('empty-audit-state').classList.add('hidden');
    const container = document.getElementById('diagnostic-results');
    container.classList.remove('hidden');

    state.currentScan = report;

    const analysed = report.analysis_status === 'COMPLETED' && !!report.verdict;
    document.getElementById('report-ref').textContent = report.scan_ref;

    const image = document.getElementById('report-image');
    if (report.image_url) {
        image.src = report.image_url;
        image.alt = `Photograph submitted for ${report.scan_ref}`;
        image.classList.remove('hidden');
    } else {
        image.removeAttribute('src');
        image.classList.add('hidden');
    }

    renderRecordActions(report, analysed);

    const notice = document.getElementById('report-pending-notice');
    const puterArea = document.getElementById('puter-analyze-area');
    if (!analysed) {
        notice.classList.remove('hidden');
        document.getElementById('report-pending-reason').textContent =
            report.analysis_error
            || (report.analysis_status === 'FAILED'
                ? 'The analysis engine could not produce a report from this photograph.'
                : 'The photograph is stored and will be audited once an analysis engine is available.');
        // Offered only when the deployment allows it and the visitor is signed in: the
        // verdict has to be attached to a record they own. A photograph is needed too,
        // either the one just captured or the stored one this record points at.
        const offered = !!(state.engine && state.engine.browser_fallback && state.engine.browser_fallback.enabled)
            && !!state.token
            && (!!report.image_url || state.pendingUploadScanId === report.id);
        puterArea.classList.toggle('hidden', !offered);
    } else {
        notice.classList.add('hidden');
        puterArea.classList.add('hidden');
    }

    // Verdict card styles
    const card = document.getElementById('report-verdict-card');
    card.className = 'audit-card p-6';
    const vUpper = analysed ? report.verdict.toUpperCase() : '';

    let borderClass = 'border-l-neutral';
    let badgeClass = 'badge-neutral';

    if (vUpper === 'VERIFIED AUTHENTIC') {
        borderClass = 'border-l-authentic';
        badgeClass = 'badge-authentic';
    } else if (vUpper === 'HEALTHY SPECIMEN') {
        borderClass = 'border-l-authentic';
        badgeClass = 'badge-healthy';
    } else if (vUpper === 'COUNTERFEIT SUSPECTED') {
        borderClass = 'border-l-fraud';
        badgeClass = 'badge-fraud';
    } else if (vUpper === 'DISEASE DETECTED') {
        borderClass = 'border-l-diseased';
        badgeClass = 'badge-diseased';
    }

    card.classList.add(borderClass);

    // Populate primary values
    const badgeEl = document.getElementById('report-badge');
    badgeEl.className = `badge ${badgeClass}`;
    badgeEl.textContent = analysed
        ? report.verdict
        : (report.analysis_status === 'FAILED' ? 'ANALYSIS FAILED' : 'AWAITING ANALYSIS');

    document.getElementById('report-subject-name').textContent =
        report.subject_name || 'Unaudited photograph';
    document.getElementById('report-summary').textContent =
        report.executive_summary || 'No report has been produced for this photograph yet.';
    document.getElementById('report-classification').textContent =
        report.classification || 'Not classified';
    document.getElementById('report-confidence').textContent =
        analysed && report.confidence_score !== null ? `${report.confidence_score}%` : '—';
    document.getElementById('report-provenance').textContent = provenanceLabel(report);
    document.getElementById('report-regulatory').textContent = report.regulatory_alignment || 'N/A';
    document.getElementById('report-protocol').textContent = report.protocol_action || 'N/A';

    // Populate properties table
    const tableBody = document.getElementById('report-properties-body');
    tableBody.innerHTML = '';

    if (!report.properties.length) {
        tableBody.innerHTML = `
            <tr><td colspan="3" class="py-6 text-center text-xs text-slate-400">
                No measured properties - this record has not been analysed.
            </td></tr>`;
    }

    report.properties.forEach(prop => {
        const row = document.createElement('tr');
        row.className = 'border-b border-slate-100 hover:bg-slate-50 text-xs';

        let pBadge = 'badge-neutral';
        if (prop.status === 'PASSED') pBadge = 'badge-passed';
        else if (prop.status === 'FLAGGED') pBadge = 'badge-flagged';
        else if (prop.status === 'INCONCLUSIVE') pBadge = 'badge-warn';

        row.innerHTML = `
            <td class="py-3 px-4 font-semibold text-slate-800">${escapeHtml(prop.property_name)}</td>
            <td class="py-3 px-4 text-slate-700">
                <div>${escapeHtml(prop.observed_value)}</div>
                <div class="text-[11px] text-slate-400 mt-0.5">Benchmark: ${escapeHtml(prop.benchmark_standard)}</div>
            </td>
            <td class="py-3 px-4 text-right">
                <span class="badge ${pBadge}">${escapeHtml(prop.status)}</span>
            </td>
        `;
        tableBody.appendChild(row);
    });

    // Populate Report Fraud Button action
    const btnReportFraud = document.getElementById('btn-report-current-scan');
    if (vUpper === 'COUNTERFEIT SUSPECTED') {
        btnReportFraud.classList.remove('hidden');
        btnReportFraud.onclick = () => {
            openFraudModalWithData({
                product_name: report.subject_name,
                evidence_notes: `Flagged under audit reference ${report.scan_ref}: ${report.executive_summary}`
            });
        };
    } else {
        btnReportFraud.classList.add('hidden');
    }
}

// -----------------------------------------------------------------------------
// Scans Registry Table (Search, Filter, Persistence)
// -----------------------------------------------------------------------------
async function loadScansRegistry() {
    const searchField = document.getElementById('search-registry');
    if (!state.token) {
        state.scans = [];
        renderScansTable([]);
        return;
    }
    const q = (searchField?.value || '').trim();
    const verdict = document.getElementById('filter-verdict').value;
    const classification = document.getElementById('filter-classification').value;
    const analysisStatus = document.getElementById('filter-analysis-status').value;

    const params = new URLSearchParams();
    if (q) params.append('q', q);
    if (verdict) params.append('verdict', verdict);
    if (classification) params.append('classification', classification);
    if (analysisStatus) params.append('analysis_status', analysisStatus);

    try {
        const scans = await apiCall(`/api/scans/?${params.toString()}`);
        state.scans = scans;
        renderScansTable(scans);
    } catch (err) {
        // Handled in apiCall
    }
}

function renderScansTable(scans) {
    const tbody = document.getElementById('registry-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (scans.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-8 text-xs text-slate-400">
                    ${state.user
                        ? 'No inspection records yet. Upload a photograph to start the register.'
                        : 'Sign in to open your inspection register.'}
                </td>
            </tr>
        `;
        return;
    }

    scans.forEach(scan => {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-slate-200 hover:bg-slate-50 text-xs transition-colors';

        const dateStr = new Date(scan.created_at).toLocaleDateString('en-PK', {
            day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
        });

        tr.innerHTML = `
            <td class="py-3 px-4 font-mono font-medium text-slate-700">${escapeHtml(scan.scan_ref)}</td>
            <td class="py-3 px-4">
                <div class="font-semibold text-slate-900">${escapeHtml(scan.subject_name || 'Unaudited photograph')}</div>
                <div class="text-[11px] text-slate-500">${escapeHtml(scan.classification || '')}</div>
            </td>
            <td class="py-3 px-4">${renderVerdictBadge(scan)}</td>
            <td class="py-3 px-4 font-mono font-semibold text-slate-800">${
                scan.analysis_status === 'COMPLETED' && scan.confidence_score !== null
                    ? `${scan.confidence_score}%`
                    : '&mdash;'
            }</td>
            <td class="py-3 px-4 text-slate-500">${dateStr}</td>
            <td class="py-3 px-4 text-right space-x-2">
                <button type="button" class="text-slate-600 hover:text-emerald-700 font-medium" data-scan-id="${scan.id}" aria-label="Inspect ${escapeHtml(scan.scan_ref)}">Inspect</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// A record can be stored before any engine has looked at it, so the register never
// invents a verdict cell for it.
function renderVerdictBadge(scan) {
    if (scan.analysis_status !== 'COMPLETED' || !scan.verdict) {
        const label = scan.analysis_status === 'FAILED' ? 'Analysis failed' : 'Awaiting analysis';
        return `<span class="badge badge-neutral">${label}</span>`;
    }
    let badgeClass = 'badge-neutral';
    const v = scan.verdict.toUpperCase();
    if (v === 'VERIFIED AUTHENTIC') badgeClass = 'badge-authentic';
    else if (v === 'HEALTHY SPECIMEN') badgeClass = 'badge-healthy';
    else if (v === 'COUNTERFEIT SUSPECTED') badgeClass = 'badge-fraud';
    else if (v === 'DISEASE DETECTED') badgeClass = 'badge-diseased';

    let caveat = '';
    if (scan.analysis_model === 'placeholder_engine') {
        caveat = '<div class="text-[10px] text-amber-700 mt-1">Not engine-verified</div>';
    } else if (scan.verdict_source === 'browser') {
        caveat = '<div class="text-[10px] text-amber-700 mt-1">Browser verdict - not server-verified</div>';
    }
    return `<span class="badge ${badgeClass}">${escapeHtml(scan.verdict)}</span>${caveat}`;
}

async function viewScanDetails(scanId) {
    try {
        const scan = await apiCall(`/api/scans/${scanId}`);
        renderDiagnosticReport(scan);
        switchTab('audit');
        window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
        // Handled
    }
}

function provenanceLabel(report) {
    if (report.analysis_status !== 'COMPLETED' || !report.analysis_model) return 'Not run';
    if (report.analysis_model === 'placeholder_engine') {
        return 'Legacy placeholder engine - not photo-verified';
    }
    const latency = report.analysis_latency_ms !== null
        ? ` in ${report.analysis_latency_ms} ms`
        : '';
    if (report.verdict_source === 'browser') {
        return `${report.analysis_model}${latency} - drawn in the browser, not verified by this server`;
    }
    return `${report.analysis_model}${latency}`;
}

function renderRecordActions(report, analysed) {
    const reanalyze = document.getElementById('btn-reanalyze');
    const remove = document.getElementById('btn-delete-scan');
    const signedIn = !!state.token;

    reanalyze.classList.toggle('hidden', analysed || !signedIn);
    remove.classList.toggle('hidden', !signedIn);
    reanalyze.onclick = () => reanalyzeCurrentScan(report.id, reanalyze);
    remove.onclick = () => deleteCurrentScan(report.id);
}

async function reanalyzeCurrentScan(scanId, button) {
    button.disabled = true;
    button.textContent = 'Analysing...';
    try {
        const scan = await apiCall(`/api/scans/${scanId}/reanalyze`, {
            method: 'POST',
            timeoutMs: ANALYSIS_TIMEOUT_MS,
        });
        renderDiagnosticReport(scan);
        showToast(`${scan.scan_ref}: ${scan.verdict}`, 'success');
    } catch (err) {
        // apiCall reported it; reload so the stored status is what the user sees.
        await viewScanDetails(scanId);
    } finally {
        button.disabled = false;
        button.textContent = 'Run Analysis Again';
        loadScansRegistry();
    }
}

async function deleteCurrentScan(scanId) {
    const confirmed = window.confirm('Delete this audit record and its photograph?');
    if (!confirmed) return;
    try {
        await apiCall(`/api/scans/${scanId}`, { method: 'DELETE' });
        document.getElementById('diagnostic-results').classList.add('hidden');
        document.getElementById('empty-audit-state').classList.remove('hidden');
        state.currentScan = null;
        showToast('Audit record deleted.', 'success');
    } catch (err) {
        // Handled
    } finally {
        loadScansRegistry();
        loadAnalyticsSummary();
    }
}

// -----------------------------------------------------------------------------
// Official Directory & Subsidy Guide
// -----------------------------------------------------------------------------
async function loadDirectory() {
    const filter = document.getElementById('directory-category-filter');
    const category = filter ? filter.value : '';
    const params = category ? `?category=${encodeURIComponent(category)}` : '';

    try {
        const [products, categories] = await Promise.all([
            apiCall(`/api/directory/products${params}`),
            state.productCategories.length
                ? Promise.resolve(state.productCategories)
                : apiCall('/api/directory/categories'),
        ]);
        state.products = products;
        state.productCategories = categories;
        renderCategoryOptions(categories);
        renderDirectoryTable(products);
    } catch (err) {
        // Handled
    }
}

// The choices come from the registered products themselves, so a new category is
// filterable the moment it exists in the database instead of needing a markup edit.
function renderCategoryOptions(categories) {
    const select = document.getElementById('directory-category-filter');
    if (!select) return;
    const current = [...select.options].map(o => o.value);
    const expected = ['', ...categories];
    if (current.join('|') === expected.join('|')) return;

    const previous = select.value;
    select.innerHTML = '';
    const all = document.createElement('option');
    all.value = '';
    all.textContent = 'All Categories';
    select.appendChild(all);
    categories.forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    });
    select.value = previous && categories.includes(previous) ? previous : '';
}

function renderDirectoryTable(products) {
    const tbody = document.getElementById('directory-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    products.forEach(p => {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-slate-200 hover:bg-slate-50 text-xs';

        tr.innerHTML = `
            <td class="py-3 px-4">
                <div class="font-semibold text-slate-900">${escapeHtml(p.brand_name)}</div>
                <div class="text-[11px] text-slate-500">${escapeHtml(p.manufacturer)}</div>
            </td>
            <td class="py-3 px-4 text-slate-700">${escapeHtml(p.category)}</td>
            <td class="py-3 px-4 font-mono text-slate-600">${escapeHtml(p.bag_size)}</td>
            <td class="py-3 px-4 font-mono font-semibold text-emerald-700">PKR ${p.official_mrp_pkr.toLocaleString()}</td>
            <td class="py-3 px-4 font-mono text-slate-500">PKR ${p.subsidy_amount_pkr.toLocaleString()}</td>
            <td class="py-3 px-4 font-mono text-slate-600">${escapeHtml(p.psqca_license_no)}</td>
        `;
        tbody.appendChild(tr);
    });
}

// Price Difference Calculator
async function loadPriceRegistry() {
    try {
        // The calculator always needs the full notified-price list, independent of the
        // category filter applied to the directory table.
        const products = await apiCall('/api/directory/products');
        state.priceRegistry = products;
        renderCalculatorOptions(products);
    } catch (err) {
        // Handled
    }
}

function renderCalculatorOptions(products) {
    const select = document.getElementById('calc-product-select');
    if (!select) return;
    const previous = select.value;

    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Choose product...';
    select.appendChild(placeholder);

    products.forEach(p => {
        const option = document.createElement('option');
        option.value = String(p.id);
        option.textContent = `${p.brand_name} (${p.bag_size}) - PKR ${p.official_mrp_pkr.toLocaleString()}`;
        select.appendChild(option);
    });

    if (previous) select.value = previous;
}

function initPriceCalculator() {
    const dealerInput = document.getElementById('calc-dealer-price');
    const select = document.getElementById('calc-product-select');
    const output = document.getElementById('calc-output');

    if (!dealerInput || !select) return;

    const calculate = () => {
        const selectedId = parseInt(select.value);
        const dealerPrice = parseFloat(dealerInput.value);

        if (!selectedId || isNaN(dealerPrice)) {
            output.innerHTML = '<span class="text-slate-400">Select product and enter quoted price.</span>';
            return;
        }

        const product = state.priceRegistry.find(p => p.id === selectedId);
        if (!product) return;

        const diff = dealerPrice - product.official_mrp_pkr;
        if (diff <= 0) {
            output.innerHTML = '<span class="text-emerald-700 font-semibold">Price aligns with or is below government notified rate.</span>';
            return;
        }

        output.textContent = '';
        const verdict = document.createElement('div');
        verdict.className = 'text-red-700 font-semibold';
        verdict.textContent = `Illegal Markup Detected: +PKR ${diff.toLocaleString()} over official notified rate (PKR ${product.official_mrp_pkr.toLocaleString()})`;
        output.appendChild(verdict);

        const fileReport = document.createElement('button');
        fileReport.className = 'mt-2 text-xs text-red-800 underline font-medium';
        fileReport.textContent = 'File Excessive Pricing Report';
        fileReport.addEventListener('click', () => openFraudModalWithData({
            product_name: product.brand_name,
            price_charged_pkr: dealerPrice,
        }));
        output.appendChild(fileReport);
    };

    dealerInput.addEventListener('input', calculate);
    select.addEventListener('change', calculate);
}

// -----------------------------------------------------------------------------
// Fraud Reporting
// -----------------------------------------------------------------------------
async function loadFraudReports() {
    if (!state.token) {
        renderReportsTable([]);
        return;
    }
    try {
        const reports = await apiCall('/api/reports/');
        state.reports = reports;
        renderReportsTable(reports);
    } catch (err) {
        // Handled
    }
}

function renderReportsTable(reports) {
    const tbody = document.getElementById('reports-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (reports.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-8 text-xs text-slate-400">
                    ${state.user
                        ? 'No complaints filed from this account yet.'
                        : 'Sign in to see the complaints you have filed.'}
                </td>
            </tr>
        `;
        return;
    }

    reports.forEach(r => {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-slate-200 hover:bg-slate-50 text-xs';

        let badgeClass = 'badge-pending';
        if (r.status === 'INVESTIGATION_OPENED') badgeClass = 'badge-warn';
        else if (r.status === 'ACTION_TAKEN' || r.status === 'RESOLVED') badgeClass = 'badge-resolved';

        const isInspector = state.user && (state.user.role === 'inspector' || state.user.role === 'admin');

        tr.innerHTML = `
            <td class="py-3 px-4 font-mono font-medium text-slate-700">${escapeHtml(r.report_ref)}</td>
            <td class="py-3 px-4">
                <div class="font-semibold text-slate-900">${escapeHtml(r.dealer_name)}</div>
                <div class="text-[11px] text-slate-500">${escapeHtml(r.dealer_location)}</div>
            </td>
            <td class="py-3 px-4">
                <div class="text-slate-800 font-medium">${escapeHtml(r.product_name)}</div>
                <div class="text-[11px] text-slate-400">Batch: ${escapeHtml(r.suspected_batch || 'Unspecified')}</div>
            </td>
            <td class="py-3 px-4 text-slate-600">${escapeHtml(r.evidence_notes.substring(0, 75))}...</td>
            <td class="py-3 px-4">
                <span class="badge ${badgeClass}">${escapeHtml(r.status.replace('_', ' '))}</span>
            </td>
            <td class="py-3 px-4 text-right">
                ${isInspector ? `
                    <select data-report-id="${r.id}" aria-label="Change case status for ${escapeHtml(r.report_ref)}" class="text-xs border border-slate-300 rounded p-1 bg-white">
                        <option value="PENDING_REVIEW" ${r.status==='PENDING_REVIEW'?'selected':''}>Pending</option>
                        <option value="INVESTIGATION_OPENED" ${r.status==='INVESTIGATION_OPENED'?'selected':''}>Investigating</option>
                        <option value="ACTION_TAKEN" ${r.status==='ACTION_TAKEN'?'selected':''}>Action Taken</option>
                        <option value="RESOLVED" ${r.status==='RESOLVED'?'selected':''}>Resolved</option>
                    </select>
                ` : `<span class="text-slate-400 text-[11px]">Registered</span>`}
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function updateReportStatus(reportId, newStatus) {
    try {
        await apiCall(`/api/reports/${reportId}/status`, {
            method: 'PATCH',
            body: JSON.stringify({ status: newStatus }),
        });
        showToast('Report investigation status updated.', 'success');
    } catch (err) {
        // Handled
    } finally {
        // Re-read from the server either way, so a rejected change cannot leave the
        // control displaying a status that was never stored.
        loadFraudReports();
    }
}

// -----------------------------------------------------------------------------
// Analytics Summary (Dashboard)
// -----------------------------------------------------------------------------
async function loadAnalyticsSummary() {
    try {
        const data = await apiCall('/api/analytics/summary');
        document.getElementById('kpi-total-scans').textContent = data.total_scans.toLocaleString();
        document.getElementById('kpi-authentic').textContent = data.authentic_count.toLocaleString();
        document.getElementById('kpi-counterfeit').textContent = data.counterfeit_count.toLocaleString();
        document.getElementById('kpi-diseased').textContent = data.disease_count.toLocaleString();
        document.getElementById('kpi-reports').textContent = data.total_reports.toLocaleString();
        document.getElementById('kpi-auth-rate').textContent = `${data.authenticity_rate}%`;
    } catch (err) {
        // Handled
    }
}

// -----------------------------------------------------------------------------
// Forms & Modals
// -----------------------------------------------------------------------------
function initForms() {
    // Auth Forms
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const unlock = lockSubmit(loginForm);
            const email = document.getElementById('login-email').value.trim();
            const password = document.getElementById('login-password').value;

            try {
                const res = await apiCall('/api/auth/login', {
                    method: 'POST',
                    body: JSON.stringify({ email, password }),
                });
                state.token = res.access_token;
                state.user = res.user;
                localStorage.setItem('kb_token', res.access_token);
                updateAuthUI();
                closeModal('login-modal');
                showToast(`Welcome back, ${res.user.full_name}`, 'success');
                refreshScopedLists();
            } catch (err) {
                // Handled in apiCall
            } finally {
                unlock();
            }
        });
    }

    const registerForm = document.getElementById('register-form');
    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const unlock = lockSubmit(registerForm);
            const email = document.getElementById('reg-email').value.trim();
            const password = document.getElementById('reg-password').value;
            const full_name = document.getElementById('reg-fullname').value.trim();
            const organization = document.getElementById('reg-org').value.trim();
            const district = document.getElementById('reg-district').value.trim();

            try {
                const res = await apiCall('/api/auth/register', {
                    method: 'POST',
                    body: JSON.stringify({ email, password, full_name, organization, district }),
                });
                state.token = res.access_token;
                state.user = res.user;
                localStorage.setItem('kb_token', res.access_token);
                updateAuthUI();
                closeModal('register-modal');
                showToast(`Account registered successfully. Signed in as ${res.user.full_name}`, 'success');
                refreshScopedLists();
            } catch (err) {
                // Handled
            } finally {
                unlock();
            }
        });
    }

    // Fraud Report Form
    const fraudForm = document.getElementById('fraud-report-form');
    if (fraudForm) {
        fraudForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const unlock = lockSubmit(fraudForm);
            const payload = {
                dealer_name: document.getElementById('frd-dealer-name').value.trim(),
                dealer_location: document.getElementById('frd-dealer-location').value.trim(),
                product_name: document.getElementById('frd-product-name').value.trim(),
                suspected_batch: document.getElementById('frd-batch').value.trim() || null,
                price_charged_pkr: parseInt(document.getElementById('frd-price').value) || null,
                evidence_notes: document.getElementById('frd-notes').value.trim(),
            };

            try {
                const res = await apiCall('/api/reports/', {
                    method: 'POST',
                    body: JSON.stringify(payload),
                });
                closeModal('fraud-modal');
                fraudForm.reset();
                showToast(`Non-compliance report filed successfully under reference #${res.report_ref}`, 'success');
                loadFraudReports();
                loadAnalyticsSummary();
                switchTab('reports');
            } catch (err) {
                // Handled
            } finally {
                unlock();
            }
        });
    }

    // Registry Search and Filters
    const searchReg = document.getElementById('search-registry');
    if (searchReg) {
        searchReg.addEventListener('input', debounce(() => loadScansRegistry(), 300));
    }
    ['filter-verdict', 'filter-classification', 'filter-analysis-status'].forEach(id => {
        const control = document.getElementById(id);
        if (control) control.addEventListener('change', () => loadScansRegistry());
    });

    // Directory Filter
    const dirFilter = document.getElementById('directory-category-filter');
    if (dirFilter) {
        dirFilter.addEventListener('change', () => loadDirectory());
    }

    initPriceCalculator();
}

// A form stays locked while its request is in flight; a double-clicked complaint
// button would otherwise file the same allegation twice.
function lockSubmit(form) {
    const button = form.querySelector('button[type="submit"]');
    if (!button) return () => {};
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Working...';
    return () => {
        button.disabled = false;
        button.textContent = originalLabel;
    };
}

let lastFocusedBeforeModal = null;

function openModal(modalId) {
    const m = document.getElementById(modalId);
    if (!m) return;
    lastFocusedBeforeModal = document.activeElement;
    m.classList.remove('hidden');
    const firstField = m.querySelector('input, select, textarea');
    (firstField || m.querySelector('button')).focus();
}

function closeModal(modalId) {
    const m = document.getElementById(modalId);
    if (!m) return;
    m.classList.add('hidden');
    if (lastFocusedBeforeModal && document.contains(lastFocusedBeforeModal)) {
        lastFocusedBeforeModal.focus();
    }
}

function openModals() {
    return [...document.querySelectorAll('[role="dialog"]')].filter(m => !m.classList.contains('hidden'));
}

// One listener owns every dynamic button, so markup built later needs no inline handlers.
function initGlobalHandlers() {
    document.addEventListener('click', (e) => {
        const opener = e.target.closest('[data-modal-open]');
        if (opener) {
            openModal(opener.dataset.modalOpen);
            return;
        }
        const closer = e.target.closest('[data-modal-close]');
        if (closer) {
            closeModal(closer.dataset.modalClose);
            return;
        }
        if (e.target.closest('[data-action="puter-analyze"]')) {
            analyzeWithPuter();
            return;
        }
        if (e.target.closest('[data-action="logout"]')) {
            logoutUser();
            return;
        }
        const dismissal = e.target.closest('[data-toast-dismiss]');
        if (dismissal) {
            dismissal.closest('#toast-container > div').remove();
            return;
        }
        const inspect = e.target.closest('[data-scan-id]');
        if (inspect) {
            viewScanDetails(Number(inspect.dataset.scanId));
            return;
        }
        // Clicking the dimmed backdrop around a dialog closes it.
        if (e.target.matches('[role="dialog"]')) {
            if (e.target.id === 'camera-modal') stopCamera();
            e.target.classList.add('hidden');
        }
    });

    document.addEventListener('change', (e) => {
        const statusControl = e.target.closest('[data-report-id]');
        if (statusControl) updateReportStatus(Number(statusControl.dataset.reportId), e.target.value);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        const top = openModals().pop();
        if (!top) return;
        if (top.id === 'camera-modal') stopCamera();
        closeModal(top.id);
    });
}

function openFraudModalWithData(data = {}) {
    if (data.product_name) {
        document.getElementById('frd-product-name').value = data.product_name;
    }
    if (data.price_charged_pkr) {
        document.getElementById('frd-price').value = data.price_charged_pkr;
    }
    if (data.evidence_notes) {
        document.getElementById('frd-notes').value = data.evidence_notes;
    }
    openModal('fraud-modal');
}

function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}
