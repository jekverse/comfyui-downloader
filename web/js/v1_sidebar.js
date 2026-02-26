import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Global state - persists across tab open/close
let globalState = {
    queue: [],
    is_processing: false,
    is_add_collapsed: false
};

let elements = {};

app.registerExtension({
    name: "My.DownloaderSidebar",
    async setup() {
        // Listen for queue updates
        api.addEventListener("downloader.queue", (event) => {
            globalState = event.detail;
            if (elements.queueList) {
                renderQueue();
            }
        });

        if (app.extensionManager && app.extensionManager.registerSidebarTab) {

            app.extensionManager.registerSidebarTab({
                id: "model-downloader-tab",
                icon: "pi pi-download",
                title: "Model Downloader",
                tooltip: "Download AI Models",
                type: "custom",

                render: (el) => {
                    el.innerHTML = "";
                    elements = {}; // Reset element references

                    // Container styles
                    Object.assign(el.style, {
                        display: "flex",
                        flexDirection: "column",
                        padding: "0",
                        height: "100%",
                        boxSizing: "border-box",
                        background: "#0d0d12",
                        color: "#e0e0e0",
                        fontFamily: "system-ui, -apple-system, sans-serif",
                        overflow: "hidden"
                    });

                    // Inject styles
                    injectStyles();

                    // Tab Bar
                    const tabBar = document.createElement('div');
                    tabBar.className = 'dl-tab-bar';
                    el.appendChild(tabBar);

                    const tab1 = document.createElement('button');
                    tab1.className = 'dl-tab-btn active';
                    tab1.textContent = 'Model Downloader';
                    tabBar.appendChild(tab1);

                    const tab2 = document.createElement('button');
                    tab2.className = 'dl-tab-btn';
                    tab2.textContent = 'New Tab';
                    tabBar.appendChild(tab2);

                    // Content 1: Model Downloader
                    const content1 = document.createElement('div');
                    content1.className = 'dl-tab-content active';
                    el.appendChild(content1);

                    // Build UI for Tab 1
                    content1.appendChild(createHeader());
                    content1.appendChild(createAddForm());
                    content1.appendChild(createQueueSection());

                    // Content 2: New Tab
                    const content2 = document.createElement('div');
                    content2.className = 'dl-tab-content';
                    content2.style.padding = '20px';
                    content2.style.justifyContent = 'center';
                    content2.style.alignItems = 'center';
                    content2.innerHTML = '<div style="font-size:16px; opacity:0.7;">ini adalah menu baru</div>';
                    el.appendChild(content2);

                    // Tab Switching Logic
                    tab1.onclick = () => {
                        tab1.classList.add('active');
                        tab2.classList.remove('active');
                        content1.classList.add('active');
                        content2.classList.remove('active');
                    };
                    tab2.onclick = () => {
                        tab1.classList.remove('active');
                        tab2.classList.add('active');
                        content1.classList.remove('active');
                        content2.classList.add('active');
                    };

                    // Load state from server
                    loadState();
                }
            });

        } else {
            console.warn("ComfyUI doesn't support Sidebar API V1");
        }
    }
});

function injectStyles() {
    if (document.getElementById('dl-styles')) return;

    const style = document.createElement('style');
    style.id = 'dl-styles';
    style.textContent = `
        .dl-section {
            padding: 14px 16px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .dl-label {
            font-size: 11px;
            font-weight: 600;
            color: rgba(255,255,255,0.5);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        .dl-input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            background: rgba(255,255,255,0.05);
            color: #e0e0e0;
            font-size: 13px;
            outline: none;
            box-sizing: border-box;
            transition: border-color 0.2s;
        }
        .dl-input:focus {
            border-color: #6366f1;
        }
        .dl-input::placeholder {
            color: rgba(255,255,255,0.3);
        }
        .dl-select {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            background: #1a1a1f;
            color: #e0e0e0;
            font-size: 13px;
            cursor: pointer;
            outline: none;
            box-sizing: border-box;
        }
        .dl-select option {
            background: #1a1a1f;
            color: #e0e0e0;
            padding: 8px;
        }
        .dl-btn {
            padding: 10px 16px;
            border: none;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .dl-btn-primary {
            background: linear-gradient(135deg, #6366f1, #8b5cf6);
            color: white;
        }
        .dl-btn-primary:hover {
            opacity: 0.9;
        }
        .dl-btn-secondary {
            background: rgba(255,255,255,0.08);
            color: #ccc;
        }
        .dl-btn-secondary:hover {
            background: rgba(255,255,255,0.12);
        }
        .dl-btn-danger {
            background: rgba(239,68,68,0.2);
            color: #f87171;
        }
        .dl-btn-success {
            background: linear-gradient(135deg, #22c55e, #16a34a);
            color: white;
        }
        .dl-queue-item {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            padding: 12px;
            margin-bottom: 8px;
        }
        .dl-queue-item.downloading {
            border-color: rgba(99,102,241,0.5);
        }
        .dl-queue-item.completed {
            border-color: rgba(34,197,94,0.5);
        }
        .dl-queue-item.error {
            border-color: rgba(239,68,68,0.5);
        }
        .dl-progress {
            width: 100%;
            height: 4px;
            background: rgba(255,255,255,0.1);
            border-radius: 2px;
            overflow: hidden;
            margin: 8px 0;
        }
        .dl-progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #6366f1, #a855f7);
            border-radius: 2px;
            transition: width 0.3s;
        }
        .dl-badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .dl-badge-hf { background: rgba(255,204,0,0.15); color: #fcd34d; }
        .dl-badge-civitai { background: rgba(76,201,240,0.15); color: #67e8f9; }
        .dl-badge-other { background: rgba(156,163,175,0.15); color: #9ca3af; }
        .dl-badge-queued { background: rgba(156,163,175,0.15); color: #9ca3af; }
        .dl-badge-downloading { background: rgba(99,102,241,0.2); color: #a5b4fc; }
        .dl-badge-completed { background: rgba(34,197,94,0.15); color: #86efac; }
        .dl-badge-error { background: rgba(239,68,68,0.15); color: #fca5a5; }
        .dl-badge-cancelled { background: rgba(156,163,175,0.15); color: #9ca3af; }
        .dl-scrollable {
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: rgba(255,255,255,0.15) transparent;
        }
        .dl-scrollable::-webkit-scrollbar { width: 5px; }
        .dl-scrollable::-webkit-scrollbar-track { background: transparent; }
        .dl-scrollable::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 3px; }
        .dl-scrollable::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 3px; }
        .dl-modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 9999;
        }
        .dl-modal {
            background: #1a1a1f;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 20px;
            min-width: 300px;
            max-width: 400px;
            max-height: 80vh;
            overflow-y: auto;
        }
        .dl-modal-title {
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .dl-template-item {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .dl-template-item:hover {
            border-color: rgba(99,102,241,0.5);
            background: rgba(99,102,241,0.1);
        }
        .dl-template-name {
            font-weight: 600;
            font-size: 13px;
        }
        .dl-template-desc {
            font-size: 11px;
            opacity: 0.5;
            margin-top: 4px;
        }
        .dl-template-count {
            font-size: 10px;
            color: #a5b4fc;
            margin-top: 4px;
        }
        .dl-tab-bar {
            display: flex;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            background: rgba(0,0,0,0.2);
            flex-shrink: 0;
        }
        .dl-tab-btn {
            flex: 1;
            padding: 12px;
            background: none;
            border: none;
            color: rgba(255,255,255,0.5);
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }
        .dl-tab-btn:hover {
            color: rgba(255,255,255,0.8);
            background: rgba(255,255,255,0.02);
        }
        .dl-tab-btn.active {
            color: #6366f1;
            border-bottom-color: #6366f1;
            background: rgba(99,102,241,0.05);
        }
        .dl-tab-content {
            display: none;
            flex: 1;
            flex-direction: column;
            min-height: 0;
            overflow: hidden;
        }
        .dl-tab-content.active {
            display: flex;
        }
    `;
    document.head.appendChild(style);
}

function createHeader() {
    const div = document.createElement('div');
    div.className = 'dl-section';
    div.style.background = 'linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.05))';
    div.innerHTML = `
        <div style="display:flex; align-items:center; gap:12px;">
            <div style="width:36px; height:36px; border-radius:10px; background:linear-gradient(135deg,#6366f1,#8b5cf6); display:flex; align-items:center; justify-content:center; font-size:16px;">⬇️</div>
            <div>
                <div style="font-size:15px; font-weight:700;">Model Downloader</div>
                <div style="font-size:10px; opacity:0.5;">HuggingFace • CivitAI • URLs</div>
            </div>
        </div>
    `;
    return div;
}

function createAddForm() {
    const container = document.createElement('div');
    container.className = 'dl-section';
    container.style.display = 'flex';
    container.style.flexDirection = 'column';
    container.style.gap = '12px';

    // Header
    const header = document.createElement('div');
    header.style.cssText = 'display:flex; justify-content:space-between; align-items:center; cursor:pointer; user-select:none;';
    header.innerHTML = `
        <div class="dl-label" style="margin:0;">Add Download</div>
        <div id="dl-add-toggle" style="font-size:12px; transition:transform 0.2s; color:rgba(255,255,255,0.5);">▼</div>
    `;

    // Content wrapper
    const content = document.createElement('div');
    content.style.cssText = 'display:flex; flex-direction:column; gap:10px; overflow:hidden;';

    content.innerHTML = `
        <input type="text" id="dl-url" class="dl-input" placeholder="Paste model URL here...">
        <div id="dl-platform" style="font-size:11px; min-height:16px;"></div>
        
        <div style="display:flex; gap:8px;">
             <select id="dl-provider" class="dl-select" style="flex:1;">
                <option value="hf_hub">🤗 HF Transfer (Default)</option>
                <option value="aria2">🚀 Aria2</option>
            </select>
        </div>

        <select id="dl-dir" class="dl-select"></select>
        <input type="text" id="dl-custom-dir" class="dl-input" placeholder="Custom directory path..." style="display:none;">
        <input type="text" id="dl-filename" class="dl-input" placeholder="Custom filename (optional)">
        <div style="display:flex; gap:8px;">
            <button id="dl-add-btn" class="dl-btn dl-btn-secondary" style="flex:1;">➕ Add to Queue</button>
            <button id="dl-add-start-btn" class="dl-btn dl-btn-primary" style="flex:1;">⚡ Add & Start</button>
        </div>
        <button id="dl-template-btn" class="dl-btn dl-btn-secondary" style="width:100%;">📋 From Template</button>
    `;

    container.appendChild(header);
    container.appendChild(content);

    elements.urlInput = content.querySelector('#dl-url');
    elements.platformDiv = content.querySelector('#dl-platform');
    elements.providerSelect = content.querySelector('#dl-provider');
    elements.dirSelect = content.querySelector('#dl-dir');
    elements.customDirInput = content.querySelector('#dl-custom-dir');
    elements.filenameInput = content.querySelector('#dl-filename');

    // Toggle logic
    const updateVisibility = () => {
        const toggleBtn = header.querySelector('#dl-add-toggle');
        if (globalState.is_add_collapsed) {
            content.style.display = 'none';
            toggleBtn.style.transform = 'rotate(-90deg)';
        } else {
            content.style.display = 'flex';
            toggleBtn.style.transform = 'rotate(0deg)';
        }
    };

    header.onclick = () => {
        globalState.is_add_collapsed = !globalState.is_add_collapsed;
        updateVisibility();
    };

    // Initial state
    updateVisibility();

    // URL change handler
    elements.urlInput.addEventListener('input', () => {
        const url = elements.urlInput.value;
        const urlLower = url.toLowerCase();

        if (urlLower.includes('huggingface.co') || urlLower.includes('hf.co')) {
            elements.platformDiv.innerHTML = '<span class="dl-badge dl-badge-hf">🤗 HuggingFace</span>';

            try {
                // Auto-extract filename for HuggingFace
                // Remove query parameters
                const cleanUrl = url.split('?')[0];
                const parts = cleanUrl.split('/');
                const filename = parts[parts.length - 1];

                // Only update if we found a potential filename
                if (filename && filename.includes('.') && elements.filenameInput.value === '') {
                    elements.filenameInput.value = filename;
                }
            } catch (e) {
                console.warn('Failed to extract filename from HF URL', e);
            }

        } else if (urlLower.includes('civitai.com')) {
            elements.platformDiv.innerHTML = '<span class="dl-badge dl-badge-civitai">🎨 CivitAI</span>';
        } else if (urlLower.length > 10) {
            elements.platformDiv.innerHTML = '<span class="dl-badge dl-badge-other">🌐 Direct URL</span>';
        } else {
            elements.platformDiv.innerHTML = '';
        }
    });

    // Directory change handler
    elements.dirSelect.addEventListener('change', () => {
        elements.customDirInput.style.display = elements.dirSelect.value === 'custom' ? 'block' : 'none';
    });

    // Button handlers
    container.querySelector('#dl-add-btn').onclick = () => addDownload(false);
    container.querySelector('#dl-add-start-btn').onclick = () => addDownload(true);
    container.querySelector('#dl-template-btn').onclick = () => showTemplateModal();

    // Load directories
    loadDirectories();

    return container;
}

function createQueueSection() {
    const div = document.createElement('div');
    div.className = 'dl-section';
    div.style.cssText = 'flex:1; display:flex; flex-direction:column; min-height:0; overflow:hidden;';

    div.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <div class="dl-label" style="margin:0;">Queue <span id="dl-count">(0)</span></div>
            <div style="display:flex; gap:6px;">
                <button id="dl-start-btn" class="dl-btn dl-btn-success" style="padding:6px 12px; font-size:11px;">▶ Start</button>
                <button id="dl-save-btn" class="dl-btn dl-btn-secondary" style="padding:6px 12px; font-size:11px;">💾 Save</button>
                <button id="dl-clear-btn" class="dl-btn dl-btn-secondary" style="padding:6px 12px; font-size:11px;">Clear</button>
            </div>
        </div>
        <div id="dl-queue" class="dl-scrollable" style="flex:1; min-height:0;"></div>
    `;

    elements.queueCount = div.querySelector('#dl-count');
    elements.queueList = div.querySelector('#dl-queue');
    elements.startBtn = div.querySelector('#dl-start-btn');
    elements.saveBtn = div.querySelector('#dl-save-btn');
    elements.clearBtn = div.querySelector('#dl-clear-btn');

    elements.startBtn.onclick = startQueue;
    elements.saveBtn.onclick = showSaveTemplateModal;
    elements.clearBtn.onclick = clearCompleted;

    return div;
}

function showSaveTemplateModal() {
    if (!globalState.queue || !globalState.queue.length) {
        alert("Queue is empty! Add downloads first to save as template.");
        return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'dl-modal-overlay';

    const modal = document.createElement('div');
    modal.className = 'dl-modal';
    modal.innerHTML = `
        <div class="dl-modal-title">💾 Save Queue as Template</div>
        <div style="display:flex; flex-direction:column; gap:10px;">
            <div style="font-size:12px; opacity:0.7; margin-bottom:5px;">
                Saving ${globalState.queue.length} item(s) to a new template.
            </div>
            <input type="text" id="tpl-name" class="dl-input" placeholder="Template Name">
            <input type="text" id="tpl-desc" class="dl-input" placeholder="Description (optional)">
            <div style="display:flex; gap:8px; margin-top:10px;">
                <button id="tpl-cancel" class="dl-btn dl-btn-secondary" style="flex:1;">Cancel</button>
                <button id="tpl-confirm" class="dl-btn dl-btn-primary" style="flex:1;">Save</button>
            </div>
        </div>
    `;

    modal.querySelector('#tpl-cancel').onclick = () => overlay.remove();
    modal.querySelector('#tpl-confirm').onclick = async () => {
        const name = modal.querySelector('#tpl-name').value.trim();
        const desc = modal.querySelector('#tpl-desc').value.trim();

        if (!name) {
            alert("Name is required");
            return;
        }

        // Extract items from queue
        const downloads = globalState.queue.map(item => ({
            url: item.url,
            directory: item.directory,
            filename: item.filename || item.detected_filename || null
        }));

        try {
            await api.fetchApi('/downloader/save-template', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    description: desc,
                    downloads
                })
            });

            alert("Template saved!");
            overlay.remove();
        } catch (e) {
            alert("Save failed: " + e.message);
        }
    };

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
}

async function loadDirectories() {
    try {
        const res = await api.fetchApi('/downloader/directories');
        const data = await res.json();

        elements.dirSelect.innerHTML = '<option value="">Select directory...</option>';

        for (const [name, path] of Object.entries(data.directories)) {
            const opt = document.createElement('option');
            opt.value = path;
            opt.textContent = name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            elements.dirSelect.appendChild(opt);
        }

        const custom = document.createElement('option');
        custom.value = 'custom';
        custom.textContent = '📁 Custom Path...';
        elements.dirSelect.appendChild(custom);

    } catch (e) {
        console.error('Load directories failed:', e);
    }
}

async function loadState() {
    try {
        const res = await api.fetchApi('/downloader/state');
        const data = await res.json();
        globalState = data;

        renderQueue();

        renderQueue();
    } catch (e) {
        console.error('Load state failed:', e);
    }
}

async function addDownload(autoStart) {
    const url = elements.urlInput.value.trim();
    let directory = elements.dirSelect.value;
    const filename = elements.filenameInput.value.trim();

    if (!url) {
        alert('Please enter a URL');
        return;
    }

    if (directory === 'custom') {
        directory = elements.customDirInput.value.trim();
    }

    if (!directory) {
        alert('Please select a directory');
        return;
    }

    const provider = elements.providerSelect.value;

    try {
        await api.fetchApi('/downloader/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, directory, filename: filename || null, provider })
        });

        // Clear inputs
        elements.urlInput.value = '';
        elements.filenameInput.value = '';
        elements.platformDiv.innerHTML = '';

        if (autoStart) {
            startQueue();
        }
    } catch (e) {
        console.error('Add failed:', e);
        alert('Failed to add download: ' + e.message);
    }
}

async function startQueue() {
    try {
        await api.fetchApi('/downloader/start', { method: 'POST' });
    } catch (e) {
        console.error('Start failed:', e);
    }
}

async function cancelDownload() {
    try {
        await api.fetchApi('/downloader/cancel', { method: 'POST' });
    } catch (e) {
        console.error('Cancel failed:', e);
    }
}

async function removeItem(id) {
    try {
        await api.fetchApi('/downloader/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id })
        });
    } catch (e) {
        console.error('Remove failed:', e);
    }
}

async function clearCompleted() {
    try {
        await api.fetchApi('/downloader/clear', { method: 'POST' });
    } catch (e) {
        console.error('Clear failed:', e);
    }
}



function renderQueue() {
    if (!elements.queueList) return;

    const queue = globalState.queue || [];
    const isProcessing = globalState.is_processing;

    // Update count
    if (elements.queueCount) {
        elements.queueCount.textContent = `(${queue.length})`;
    }

    // Update start/stop button
    if (elements.startBtn) {
        if (isProcessing) {
            elements.startBtn.innerHTML = '⏹ Stop';
            elements.startBtn.className = 'dl-btn dl-btn-danger';
            elements.startBtn.onclick = cancelDownload;
        } else {
            elements.startBtn.innerHTML = '▶ Start';
            elements.startBtn.className = 'dl-btn dl-btn-success';
            elements.startBtn.onclick = startQueue;
        }
    }

    // Render queue items
    if (queue.length === 0) {
        elements.queueList.innerHTML = `
            <div style="text-align:center; padding:30px; color:rgba(255,255,255,0.3);">
                <div style="font-size:28px; margin-bottom:8px;">📭</div>
                <div style="font-size:12px;">Queue is empty</div>
            </div>
        `;
        return;
    }

    elements.queueList.innerHTML = queue.map(item => {
        const platformClass = item.platform === 'huggingface' ? 'hf' : item.platform === 'civitai' ? 'civitai' : 'other';
        const filename = item.detected_filename || item.filename || 'Detecting...';
        const shortUrl = item.url.length > 45 ? item.url.substring(0, 45) + '...' : item.url;

        return `
            <div class="dl-queue-item ${item.status}" data-id="${item.id}">
                <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                    <div style="flex:1; min-width:0;">
                        <div style="font-weight:600; font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${filename}</div>
                        <div style="font-size:10px; opacity:0.4; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${shortUrl}</div>
                    </div>
                    <button class="dl-remove-btn" style="background:none; border:none; color:rgba(255,255,255,0.3); cursor:pointer; padding:0; font-size:16px; line-height:1;">×</button>
                </div>
                <div style="display:flex; gap:6px; margin-top:6px;">
                    <span class="dl-badge dl-badge-${platformClass}">${item.platform}</span>
                    <span class="dl-badge dl-badge-${item.status}">${item.status}</span>
                </div>
                ${item.status === 'downloading' ? `
                    <div class="dl-progress">
                        <div class="dl-progress-bar" style="width:${item.progress}%;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:10px; opacity:0.6;">
                        <span>${item.progress}%</span>
                        <span>${item.speed || ''}</span>
                        <span>${item.eta ? 'ETA: ' + item.eta : ''}</span>
                    </div>
                ` : ''}
                <div style="font-size:10px; opacity:0.5; margin-top:4px;">${item.message || ''}</div>
            </div>
        `;
    }).join('');

    // Add remove handlers
    elements.queueList.querySelectorAll('.dl-remove-btn').forEach(btn => {
        btn.onclick = (e) => {
            const id = e.target.closest('.dl-queue-item').dataset.id;
            removeItem(id);
        };
    });
}



// =============================================
// TEMPLATE MODAL
// =============================================

async function showTemplateModal() {
    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'dl-modal-overlay';
    overlay.onclick = (e) => {
        if (e.target === overlay) overlay.remove();
    };

    const modal = document.createElement('div');
    modal.className = 'dl-modal';
    modal.innerHTML = `
        <div class="dl-modal-title">
            <span>📋 Select Template</span>
            <button id="dl-modal-close" style="background:none; border:none; color:#fff; font-size:18px; cursor:pointer;">×</button>
        </div>
        <div id="dl-template-list" style="min-height:100px;">
            <div style="text-align:center; padding:20px; opacity:0.5;">Loading templates...</div>
        </div>
    `;

    modal.querySelector('#dl-modal-close').onclick = () => overlay.remove();
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Load templates
    try {
        const res = await api.fetchApi('/downloader/templates');
        const data = await res.json();
        const listEl = modal.querySelector('#dl-template-list');

        if (!data.templates || data.templates.length === 0) {
            listEl.innerHTML = `
                <div style="text-align:center; padding:20px; opacity:0.5;">
                    <div style="font-size:24px; margin-bottom:8px;">📭</div>
                    <div>No templates found</div>
                    <div style="font-size:10px; margin-top:4px;">Add .json files to templates/ folder</div>
                </div>
            `;
            return;
        }

        listEl.innerHTML = data.templates.map(t => `
            <div class="dl-template-item" data-filename="${t.filename}">
                <div class="dl-template-name">${t.name}</div>
                ${t.description ? `<div class="dl-template-desc">${t.description}</div>` : ''}
                <div class="dl-template-count">${t.count} download(s)</div>
            </div>
        `).join('');

        // Add click handlers
        listEl.querySelectorAll('.dl-template-item').forEach(item => {
            item.onclick = async () => {
                const filename = item.dataset.filename;
                await loadTemplateItems(filename);
                overlay.remove();
            };
        });

    } catch (e) {
        console.error('Failed to load templates:', e);
        modal.querySelector('#dl-template-list').innerHTML = `
            <div style="text-align:center; padding:20px; color:#f87171;">
                Failed to load templates
            </div>
        `;
    }
}

async function loadTemplateItems(filename) {
    try {
        const res = await api.fetchApi(`/downloader/template/${filename}`);
        const data = await res.json();

        if (data.error) {
            alert('Error: ' + data.error);
            return;
        }

        const downloads = data.downloads || [];

        for (const dl of downloads) {
            // Auto-extract filename from URL if not specified
            let extractedFilename = dl.filename || null;
            if (!extractedFilename) {
                extractedFilename = extractFilenameFromUrl(dl.url);
            }

            await api.fetchApi('/downloader/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: dl.url,
                    directory: dl.directory,
                    filename: extractedFilename
                })
            });
        }

        alert(`Added ${downloads.length} item(s) from template "${data.name}"`);

    } catch (e) {
        console.error('Failed to load template items:', e);
        alert('Failed to load template: ' + e.message);
    }
}

function extractFilenameFromUrl(url) {
    try {
        const cleanUrl = url.split('?')[0];
        const parts = cleanUrl.split('/');
        return parts[parts.length - 1];
    } catch {
        return null;
    }
}