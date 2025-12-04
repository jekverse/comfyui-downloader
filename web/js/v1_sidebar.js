import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "My.DownloaderSidebar",
    async setup() {
        // Listen for queue updates
        api.addEventListener("downloader.queue", (event) => {
            updateQueueUI(event.detail);
        });

        api.addEventListener("downloader.log", (event) => {
            addLogEntry(event.detail);
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

                    // Main container with modern styling
                    Object.assign(el.style, {
                        display: "flex",
                        flexDirection: "column",
                        padding: "0",
                        height: "100%",
                        boxSizing: "border-box",
                        background: "linear-gradient(180deg, rgba(15,15,20,0.95) 0%, rgba(10,10,15,0.98) 100%)",
                        color: "#e0e0e0",
                        fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
                        overflow: "hidden"
                    });

                    // Add CSS styles
                    injectStyles();

                    // Header
                    el.appendChild(createHeader());

                    // Add form section
                    el.appendChild(createAddForm());

                    // Queue section
                    el.appendChild(createQueueSection());

                    // Log section
                    el.appendChild(createLogSection());

                    // Load initial state
                    loadInitialState();
                }
            });

        } else {
            console.warn("ComfyUI version doesn't support Sidebar API V1.");
        }
    }
});

// Store references
let elements = {};
let state = { queue: [], logs: [], is_processing: false };

function injectStyles() {
    if (document.getElementById('downloader-styles')) return;

    const style = document.createElement('style');
    style.id = 'downloader-styles';
    style.textContent = `
        .dl-container * {
            box-sizing: border-box;
        }
        
        .dl-input {
            width: 100%;
            padding: 12px 14px;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            background: rgba(255,255,255,0.04);
            color: #e0e0e0;
            font-size: 13px;
            transition: all 0.2s ease;
            outline: none;
        }
        
        .dl-input:focus {
            border-color: rgba(99, 102, 241, 0.6);
            background: rgba(255,255,255,0.06);
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
        }
        
        .dl-input::placeholder {
            color: rgba(255,255,255,0.3);
        }
        
        .dl-select {
            width: 100%;
            padding: 12px 14px;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            background: rgba(255,255,255,0.04);
            color: #e0e0e0;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s ease;
            outline: none;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23888' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 12px center;
        }
        
        .dl-select:focus {
            border-color: rgba(99, 102, 241, 0.6);
        }
        
        .dl-btn {
            padding: 12px 20px;
            border: none;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        
        .dl-btn-primary {
            background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
        }
        
        .dl-btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
        }
        
        .dl-btn-secondary {
            background: rgba(255,255,255,0.06);
            color: #a0a0a0;
            border: 1px solid rgba(255,255,255,0.1);
        }
        
        .dl-btn-secondary:hover {
            background: rgba(255,255,255,0.1);
            color: #e0e0e0;
        }
        
        .dl-btn-danger {
            background: rgba(239, 68, 68, 0.15);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.2);
        }
        
        .dl-btn-danger:hover {
            background: rgba(239, 68, 68, 0.25);
        }
        
        .dl-btn-success {
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(34, 197, 94, 0.3);
        }
        
        .dl-queue-item {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 12px;
            padding: 14px;
            margin-bottom: 10px;
            transition: all 0.2s ease;
        }
        
        .dl-queue-item:hover {
            background: rgba(255,255,255,0.05);
            border-color: rgba(255,255,255,0.1);
        }
        
        .dl-queue-item.downloading {
            border-color: rgba(99, 102, 241, 0.4);
            box-shadow: 0 0 20px rgba(99, 102, 241, 0.1);
        }
        
        .dl-queue-item.completed {
            border-color: rgba(34, 197, 94, 0.4);
        }
        
        .dl-queue-item.error {
            border-color: rgba(239, 68, 68, 0.4);
        }
        
        .dl-progress-bar {
            width: 100%;
            height: 6px;
            background: rgba(255,255,255,0.1);
            border-radius: 3px;
            overflow: hidden;
            margin: 10px 0;
        }
        
        .dl-progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #6366f1, #8b5cf6, #a855f7);
            border-radius: 3px;
            transition: width 0.3s ease;
            background-size: 200% 100%;
            animation: shimmer 2s linear infinite;
        }
        
        @keyframes shimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
        
        .dl-badge {
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .dl-badge-hf {
            background: rgba(255, 204, 0, 0.15);
            color: #fcd34d;
        }
        
        .dl-badge-civitai {
            background: rgba(76, 201, 240, 0.15);
            color: #67e8f9;
        }
        
        .dl-badge-other {
            background: rgba(156, 163, 175, 0.15);
            color: #9ca3af;
        }
        
        .dl-badge-queued {
            background: rgba(156, 163, 175, 0.15);
            color: #9ca3af;
        }
        
        .dl-badge-downloading {
            background: rgba(99, 102, 241, 0.2);
            color: #a5b4fc;
        }
        
        .dl-badge-completed {
            background: rgba(34, 197, 94, 0.15);
            color: #86efac;
        }
        
        .dl-badge-error {
            background: rgba(239, 68, 68, 0.15);
            color: #fca5a5;
        }
        
        .dl-log-entry {
            padding: 6px 0;
            font-size: 11px;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            border-bottom: 1px solid rgba(255,255,255,0.03);
            word-break: break-word;
        }
        
        .dl-log-time {
            opacity: 0.4;
            margin-right: 8px;
        }
        
        .dl-section {
            padding: 16px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        
        .dl-section-title {
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: rgba(255,255,255,0.4);
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .dl-scrollable {
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: rgba(255,255,255,0.1) transparent;
        }
        
        .dl-scrollable::-webkit-scrollbar {
            width: 6px;
        }
        
        .dl-scrollable::-webkit-scrollbar-track {
            background: transparent;
        }
        
        .dl-scrollable::-webkit-scrollbar-thumb {
            background: rgba(255,255,255,0.1);
            border-radius: 3px;
        }
        
        .dl-empty-state {
            text-align: center;
            padding: 30px 20px;
            color: rgba(255,255,255,0.3);
            font-size: 13px;
        }
        
        .dl-platform-indicator {
            font-size: 11px;
            margin-top: 6px;
            min-height: 18px;
        }
    `;
    document.head.appendChild(style);
}

function createHeader() {
    const header = document.createElement('div');
    header.className = 'dl-section';
    header.style.cssText = 'background: linear-gradient(135deg, rgba(99,102,241,0.1) 0%, rgba(139,92,246,0.05) 100%); border-bottom: 1px solid rgba(99,102,241,0.2);';
    header.innerHTML = `
        <div style="display: flex; align-items: center; gap: 12px;">
            <div style="width: 40px; height: 40px; border-radius: 12px; background: linear-gradient(135deg, #6366f1, #8b5cf6); display: flex; align-items: center; justify-content: center; font-size: 18px;">
                ⬇️
            </div>
            <div>
                <div style="font-size: 16px; font-weight: 700; letter-spacing: -0.3px;">Model Downloader</div>
                <div style="font-size: 11px; opacity: 0.5; margin-top: 2px;">HuggingFace • CivitAI • Direct URLs</div>
            </div>
        </div>
    `;
    return header;
}

function createAddForm() {
    const section = document.createElement('div');
    section.className = 'dl-section';
    section.innerHTML = `
        <div class="dl-section-title">Add Download</div>
        <div style="display: flex; flex-direction: column; gap: 12px;">
            <div>
                <input type="text" id="dl-url" class="dl-input" placeholder="Paste model URL here...">
                <div id="dl-platform-indicator" class="dl-platform-indicator"></div>
            </div>
            <div style="display: flex; gap: 8px;">
                <select id="dl-directory" class="dl-select" style="flex: 1;"></select>
            </div>
            <input type="text" id="dl-custom-dir" class="dl-input" placeholder="Custom directory path..." style="display: none;">
            <input type="text" id="dl-filename" class="dl-input" placeholder="Custom filename (optional)">
            <div style="display: flex; gap: 8px;">
                <button id="dl-add-btn" class="dl-btn dl-btn-secondary" style="flex: 1;">
                    <span>➕</span> Add to Queue
                </button>
                <button id="dl-add-start-btn" class="dl-btn dl-btn-primary" style="flex: 1;">
                    <span>⚡</span> Add & Start
                </button>
            </div>
        </div>
    `;

    // Store references
    elements.urlInput = section.querySelector('#dl-url');
    elements.platformIndicator = section.querySelector('#dl-platform-indicator');
    elements.dirSelect = section.querySelector('#dl-directory');
    elements.customDirInput = section.querySelector('#dl-custom-dir');
    elements.filenameInput = section.querySelector('#dl-filename');

    // Event listeners
    elements.urlInput.addEventListener('input', updatePlatformIndicator);
    elements.dirSelect.addEventListener('change', () => {
        elements.customDirInput.style.display = elements.dirSelect.value === 'custom' ? 'block' : 'none';
    });

    section.querySelector('#dl-add-btn').onclick = () => addToQueue(false);
    section.querySelector('#dl-add-start-btn').onclick = () => addToQueue(true);

    // Load directories
    loadDirectories();

    return section;
}

function createQueueSection() {
    const section = document.createElement('div');
    section.className = 'dl-section';
    section.style.cssText = 'flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden;';
    section.innerHTML = `
        <div class="dl-section-title">
            <span>Download Queue <span id="dl-queue-count" style="opacity: 0.5;">(0)</span></span>
            <div style="display: flex; gap: 6px;">
                <button id="dl-start-btn" class="dl-btn dl-btn-success" style="padding: 6px 12px; font-size: 11px;">▶ Start</button>
                <button id="dl-clear-btn" class="dl-btn dl-btn-secondary" style="padding: 6px 12px; font-size: 11px;">Clear Done</button>
            </div>
        </div>
        <div id="dl-queue-list" class="dl-scrollable" style="flex: 1; min-height: 0;"></div>
    `;

    elements.queueCount = section.querySelector('#dl-queue-count');
    elements.queueList = section.querySelector('#dl-queue-list');
    elements.startBtn = section.querySelector('#dl-start-btn');
    elements.clearBtn = section.querySelector('#dl-clear-btn');

    elements.startBtn.onclick = startQueue;
    elements.clearBtn.onclick = clearCompleted;

    return section;
}

function createLogSection() {
    const section = document.createElement('div');
    section.style.cssText = 'height: 150px; display: flex; flex-direction: column; border-top: 1px solid rgba(255,255,255,0.05);';
    section.innerHTML = `
        <div class="dl-section-title" style="padding: 12px 16px 8px;">
            <span>Activity Log</span>
            <button id="dl-clear-log-btn" style="background: transparent; border: none; color: rgba(255,255,255,0.4); font-size: 10px; cursor: pointer;">Clear</button>
        </div>
        <div id="dl-log-container" class="dl-scrollable" style="flex: 1; padding: 0 16px 12px; min-height: 0;"></div>
    `;

    elements.logContainer = section.querySelector('#dl-log-container');
    section.querySelector('#dl-clear-log-btn').onclick = clearLogs;

    return section;
}

function updatePlatformIndicator() {
    const url = elements.urlInput.value.toLowerCase();
    const indicator = elements.platformIndicator;

    if (url.includes('huggingface.co') || url.includes('hf.co')) {
        indicator.innerHTML = `<span class="dl-badge dl-badge-hf">🤗 HuggingFace</span>`;
    } else if (url.includes('civitai.com')) {
        indicator.innerHTML = `<span class="dl-badge dl-badge-civitai">🎨 CivitAI</span>`;
    } else if (url.length > 15) {
        indicator.innerHTML = `<span class="dl-badge dl-badge-other">🌐 Direct URL</span>`;
    } else {
        indicator.innerHTML = '';
    }
}

async function loadDirectories() {
    try {
        const response = await api.fetchApi('/downloader/directories');
        const data = await response.json();

        const select = elements.dirSelect;
        select.innerHTML = '<option value="">Select directory...</option>';

        for (const [name, path] of Object.entries(data.directories)) {
            const option = document.createElement('option');
            option.value = path;
            option.textContent = name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            select.appendChild(option);
        }

        const customOption = document.createElement('option');
        customOption.value = 'custom';
        customOption.textContent = '📁 Custom Path...';
        select.appendChild(customOption);

    } catch (e) {
        console.error('Failed to load directories:', e);
    }
}

async function loadInitialState() {
    try {
        const response = await api.fetchApi('/downloader/state');
        const data = await response.json();
        updateQueueUI(data);

        // Restore logs
        if (data.logs) {
            data.logs.forEach(log => addLogEntry(log, false));
        }
    } catch (e) {
        console.error('Failed to load state:', e);
    }
}

async function addToQueue(autoStart) {
    const url = elements.urlInput.value.trim();
    let directory = elements.dirSelect.value;
    const filename = elements.filenameInput.value.trim();

    if (!url) {
        addLogEntry({ message: 'Please enter a URL', level: 'error' });
        return;
    }

    if (directory === 'custom') {
        directory = elements.customDirInput.value.trim();
    }

    if (!directory) {
        addLogEntry({ message: 'Please select a directory', level: 'error' });
        return;
    }

    try {
        await api.fetchApi('/downloader/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, directory, filename: filename || null })
        });

        // Clear inputs
        elements.urlInput.value = '';
        elements.filenameInput.value = '';
        elements.platformIndicator.innerHTML = '';

        if (autoStart) {
            startQueue();
        }

    } catch (e) {
        addLogEntry({ message: `Failed to add: ${e.message}`, level: 'error' });
    }
}

async function startQueue() {
    try {
        await api.fetchApi('/downloader/start', { method: 'POST' });
    } catch (e) {
        console.error('Failed to start:', e);
    }
}

async function cancelDownload() {
    try {
        await api.fetchApi('/downloader/cancel', { method: 'POST' });
    } catch (e) {
        console.error('Failed to cancel:', e);
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
        console.error('Failed to remove:', e);
    }
}

async function clearCompleted() {
    try {
        await api.fetchApi('/downloader/clear', { method: 'POST' });
    } catch (e) {
        console.error('Failed to clear:', e);
    }
}

async function clearLogs() {
    try {
        await api.fetchApi('/downloader/clear-logs', { method: 'POST' });
        elements.logContainer.innerHTML = '';
    } catch (e) {
        console.error('Failed to clear logs:', e);
    }
}

function updateQueueUI(data) {
    state = data;

    // Update button states
    if (data.is_processing) {
        elements.startBtn.innerHTML = '⏹ Stop';
        elements.startBtn.className = 'dl-btn dl-btn-danger';
        elements.startBtn.onclick = cancelDownload;
    } else {
        elements.startBtn.innerHTML = '▶ Start';
        elements.startBtn.className = 'dl-btn dl-btn-success';
        elements.startBtn.onclick = startQueue;
    }

    // Update queue count
    elements.queueCount.textContent = `(${data.queue.length})`;

    // Render queue items
    if (data.queue.length === 0) {
        elements.queueList.innerHTML = `
            <div class="dl-empty-state">
                <div style="font-size: 32px; margin-bottom: 10px; opacity: 0.3;">📭</div>
                <div>Queue is empty</div>
                <div style="font-size: 11px; margin-top: 4px; opacity: 0.5;">Add URLs above to start downloading</div>
            </div>
        `;
        return;
    }

    elements.queueList.innerHTML = data.queue.map(item => {
        const platformClass = item.platform === 'huggingface' ? 'dl-badge-hf' :
            item.platform === 'civitai' ? 'dl-badge-civitai' : 'dl-badge-other';
        const statusClass = `dl-badge-${item.status}`;
        const itemClass = item.status;

        const filename = item.detected_filename || item.filename || 'Detecting...';
        const displayUrl = item.url.length > 50 ? item.url.substring(0, 50) + '...' : item.url;

        return `
            <div class="dl-queue-item ${itemClass}" data-id="${item.id}">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                    <div style="flex: 1; min-width: 0;">
                        <div style="font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${filename}</div>
                        <div style="font-size: 10px; opacity: 0.4; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${displayUrl}</div>
                    </div>
                    <button class="dl-remove-btn" style="background: transparent; border: none; color: rgba(255,255,255,0.3); cursor: pointer; padding: 4px; font-size: 14px;">&times;</button>
                </div>
                <div style="display: flex; gap: 6px; margin-bottom: 8px;">
                    <span class="dl-badge ${platformClass}">${item.platform}</span>
                    <span class="dl-badge ${statusClass}">${item.status}</span>
                </div>
                ${item.status === 'downloading' ? `
                    <div class="dl-progress-bar">
                        <div class="dl-progress-fill" style="width: ${item.progress}%;"></div>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 10px; opacity: 0.6;">
                        <span>${item.progress}%</span>
                        <span>${item.speed || ''}</span>
                        <span>${item.eta ? 'ETA: ' + item.eta : ''}</span>
                    </div>
                ` : ''}
                <div style="font-size: 11px; opacity: 0.6; margin-top: 6px;">${item.message || ''}</div>
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

function addLogEntry(data, scroll = true) {
    if (!elements.logContainer) return;

    const colors = {
        error: '#f87171',
        warning: '#fbbf24',
        success: '#4ade80',
        info: 'rgba(255,255,255,0.6)'
    };

    const entry = document.createElement('div');
    entry.className = 'dl-log-entry';
    entry.innerHTML = `
        <span class="dl-log-time">[${data.timestamp || new Date().toLocaleTimeString().slice(0, 5)}]</span>
        <span style="color: ${colors[data.level] || colors.info}">${data.message}</span>
    `;

    elements.logContainer.appendChild(entry);

    if (scroll) {
        elements.logContainer.scrollTop = elements.logContainer.scrollHeight;
    }
}