import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "My.DownloaderSidebar",
    async setup() {
        // Listen for download status updates
        api.addEventListener("downloader.status", (event) => {
            updateUI(event.detail);
        });

        api.addEventListener("downloader.log", (event) => {
            addLog(event.detail);
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

                    // Container styles
                    Object.assign(el.style, {
                        display: "flex",
                        flexDirection: "column",
                        padding: "16px",
                        gap: "12px",
                        color: "var(--fg-color)",
                        height: "100%",
                        boxSizing: "border-box",
                        overflow: "auto"
                    });

                    // Header
                    const header = document.createElement("div");
                    header.innerHTML = `
                        <h3 style="margin: 0 0 4px 0; font-size: 16px;">🚀 Model Downloader</h3>
                        <p style="margin: 0; font-size: 11px; opacity: 0.7;">HuggingFace • CivitAI • Direct URLs</p>
                    `;
                    el.appendChild(header);

                    // Create main form section
                    const formSection = createFormSection();
                    el.appendChild(formSection);

                    // Progress section
                    const progressSection = createProgressSection();
                    el.appendChild(progressSection);

                    // Log section
                    const logSection = createLogSection();
                    el.appendChild(logSection);

                    // Load directories
                    loadDirectories();
                }
            });

        } else {
            console.warn("ComfyUI version doesn't support Sidebar API V1.");
        }
    }
});

// Store references
let elements = {};
let currentState = { status: "idle" };

function createFormSection() {
    const section = document.createElement("div");
    section.style.cssText = "display: flex; flex-direction: column; gap: 10px;";

    // URL Input
    const urlGroup = document.createElement("div");
    urlGroup.innerHTML = `<label style="font-size: 12px; font-weight: 500; margin-bottom: 4px; display: block;">Download URL</label>`;

    const urlInput = document.createElement("input");
    urlInput.type = "text";
    urlInput.id = "downloader-url";
    urlInput.placeholder = "https://huggingface.co/... or https://civitai.com/...";
    Object.assign(urlInput.style, {
        width: "100%",
        padding: "10px",
        border: "1px solid var(--border-color, #444)",
        borderRadius: "6px",
        backgroundColor: "var(--input-background, #1a1a1a)",
        color: "var(--fg-color)",
        fontSize: "12px",
        boxSizing: "border-box"
    });
    urlGroup.appendChild(urlInput);
    elements.urlInput = urlInput;

    // Platform indicator
    const platformIndicator = document.createElement("div");
    platformIndicator.id = "platform-indicator";
    platformIndicator.style.cssText = "font-size: 11px; opacity: 0.7; min-height: 16px;";
    urlGroup.appendChild(platformIndicator);
    elements.platformIndicator = platformIndicator;

    urlInput.addEventListener("input", () => {
        const url = urlInput.value.toLowerCase();
        if (url.includes("huggingface.co") || url.includes("hf.co")) {
            platformIndicator.innerHTML = "🤗 <span style='color: #ffcc00;'>HuggingFace</span> detected";
        } else if (url.includes("civitai.com")) {
            platformIndicator.innerHTML = "🎨 <span style='color: #4cc9f0;'>CivitAI</span> detected";
        } else if (url.length > 10) {
            platformIndicator.innerHTML = "🌐 <span style='color: #888;'>Generic URL</span>";
        } else {
            platformIndicator.innerHTML = "";
        }
    });

    section.appendChild(urlGroup);

    // Directory dropdown
    const dirGroup = document.createElement("div");
    dirGroup.innerHTML = `<label style="font-size: 12px; font-weight: 500; margin-bottom: 4px; display: block;">Target Directory</label>`;

    const dirSelect = document.createElement("select");
    dirSelect.id = "downloader-directory";
    Object.assign(dirSelect.style, {
        width: "100%",
        padding: "10px",
        border: "1px solid var(--border-color, #444)",
        borderRadius: "6px",
        backgroundColor: "var(--input-background, #1a1a1a)",
        color: "var(--fg-color)",
        fontSize: "12px",
        boxSizing: "border-box",
        cursor: "pointer"
    });
    dirSelect.innerHTML = `<option value="">Loading directories...</option>`;
    dirGroup.appendChild(dirSelect);
    elements.dirSelect = dirSelect;

    // Custom directory input (hidden by default)
    const customDirInput = document.createElement("input");
    customDirInput.type = "text";
    customDirInput.id = "custom-directory";
    customDirInput.placeholder = "Enter custom path...";
    customDirInput.style.cssText = `
        width: 100%; padding: 10px; margin-top: 8px;
        border: 1px solid var(--border-color, #444);
        border-radius: 6px; background: var(--input-background, #1a1a1a);
        color: var(--fg-color); font-size: 12px; box-sizing: border-box;
        display: none;
    `;
    dirGroup.appendChild(customDirInput);
    elements.customDirInput = customDirInput;

    dirSelect.addEventListener("change", () => {
        customDirInput.style.display = dirSelect.value === "custom" ? "block" : "none";
    });

    section.appendChild(dirGroup);

    // Optional filename
    const filenameGroup = document.createElement("div");
    filenameGroup.innerHTML = `<label style="font-size: 12px; font-weight: 500; margin-bottom: 4px; display: block;">Custom Filename <span style="opacity: 0.5">(optional)</span></label>`;

    const filenameInput = document.createElement("input");
    filenameInput.type = "text";
    filenameInput.id = "downloader-filename";
    filenameInput.placeholder = "Auto-detect from URL";
    Object.assign(filenameInput.style, {
        width: "100%",
        padding: "10px",
        border: "1px solid var(--border-color, #444)",
        borderRadius: "6px",
        backgroundColor: "var(--input-background, #1a1a1a)",
        color: "var(--fg-color)",
        fontSize: "12px",
        boxSizing: "border-box"
    });
    filenameGroup.appendChild(filenameInput);
    elements.filenameInput = filenameInput;
    section.appendChild(filenameGroup);

    // Buttons
    const buttonGroup = document.createElement("div");
    buttonGroup.style.cssText = "display: flex; gap: 8px; margin-top: 4px;";

    const downloadBtn = document.createElement("button");
    downloadBtn.id = "download-btn";
    downloadBtn.innerHTML = "⬇️ Download";
    Object.assign(downloadBtn.style, {
        flex: "1",
        padding: "12px",
        border: "none",
        borderRadius: "6px",
        backgroundColor: "#2563eb",
        color: "white",
        fontSize: "13px",
        fontWeight: "600",
        cursor: "pointer",
        transition: "background-color 0.2s"
    });
    downloadBtn.onmouseenter = () => downloadBtn.style.backgroundColor = "#1d4ed8";
    downloadBtn.onmouseleave = () => downloadBtn.style.backgroundColor = "#2563eb";
    downloadBtn.onclick = startDownload;
    elements.downloadBtn = downloadBtn;

    const cancelBtn = document.createElement("button");
    cancelBtn.id = "cancel-btn";
    cancelBtn.innerHTML = "✖ Cancel";
    Object.assign(cancelBtn.style, {
        padding: "12px 16px",
        border: "none",
        borderRadius: "6px",
        backgroundColor: "#dc2626",
        color: "white",
        fontSize: "13px",
        fontWeight: "600",
        cursor: "pointer",
        display: "none",
        transition: "background-color 0.2s"
    });
    cancelBtn.onmouseenter = () => cancelBtn.style.backgroundColor = "#b91c1c";
    cancelBtn.onmouseleave = () => cancelBtn.style.backgroundColor = "#dc2626";
    cancelBtn.onclick = cancelDownload;
    elements.cancelBtn = cancelBtn;

    buttonGroup.appendChild(downloadBtn);
    buttonGroup.appendChild(cancelBtn);
    section.appendChild(buttonGroup);

    return section;
}

function createProgressSection() {
    const section = document.createElement("div");
    section.id = "progress-section";
    section.style.cssText = "display: none; padding: 12px; background: var(--bg-secondary, #252525); border-radius: 8px;";

    section.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span id="progress-filename" style="font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px;"></span>
            <span id="progress-platform" style="font-size: 11px; padding: 2px 8px; border-radius: 4px; background: #333;"></span>
        </div>
        <div style="width: 100%; height: 8px; background: #333; border-radius: 4px; overflow: hidden; margin-bottom: 8px;">
            <div id="progress-bar" style="height: 100%; width: 0%; background: linear-gradient(90deg, #2563eb, #4cc9f0); transition: width 0.3s; border-radius: 4px;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 11px; opacity: 0.8;">
            <span id="progress-percent">0%</span>
            <span id="progress-speed"></span>
            <span id="progress-eta"></span>
        </div>
        <div id="progress-message" style="margin-top: 8px; font-size: 12px; opacity: 0.9;"></div>
    `;

    elements.progressSection = section;
    return section;
}

function createLogSection() {
    const section = document.createElement("div");
    section.style.cssText = "flex: 1; min-height: 100px; display: flex; flex-direction: column;";

    section.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 12px; font-weight: 500;">Log</span>
            <button id="clear-log-btn" style="font-size: 10px; padding: 2px 8px; border: none; background: transparent; color: var(--fg-color); opacity: 0.6; cursor: pointer;">Clear</button>
        </div>
    `;

    const logContainer = document.createElement("div");
    logContainer.id = "log-container";
    Object.assign(logContainer.style, {
        flex: "1",
        minHeight: "80px",
        maxHeight: "150px",
        overflowY: "auto",
        padding: "8px",
        background: "var(--bg-secondary, #1a1a1a)",
        borderRadius: "6px",
        fontSize: "11px",
        fontFamily: "monospace",
        lineHeight: "1.5"
    });
    section.appendChild(logContainer);
    elements.logContainer = logContainer;

    section.querySelector("#clear-log-btn").onclick = () => {
        logContainer.innerHTML = "";
    };

    return section;
}

async function loadDirectories() {
    try {
        const response = await api.fetchApi("/downloader/directories");
        const data = await response.json();

        const select = elements.dirSelect;
        select.innerHTML = "";

        const defaultOption = document.createElement("option");
        defaultOption.value = "";
        defaultOption.textContent = "-- Select Directory --";
        select.appendChild(defaultOption);

        for (const [name, path] of Object.entries(data.directories)) {
            const option = document.createElement("option");
            option.value = path;
            option.textContent = name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
            select.appendChild(option);
        }

        const customOption = document.createElement("option");
        customOption.value = "custom";
        customOption.textContent = "📁 Custom Directory...";
        select.appendChild(customOption);

    } catch (e) {
        console.error("Failed to load directories:", e);
        elements.dirSelect.innerHTML = `<option value="">Error loading directories</option>`;
    }
}

async function startDownload() {
    const url = elements.urlInput.value.trim();
    let directory = elements.dirSelect.value;
    const filename = elements.filenameInput.value.trim();

    if (!url) {
        addLog({ message: "Please enter a URL", level: "error" });
        return;
    }

    if (directory === "custom") {
        directory = elements.customDirInput.value.trim();
    }

    if (!directory) {
        addLog({ message: "Please select a directory", level: "error" });
        return;
    }

    try {
        const response = await api.fetchApi("/downloader/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url, directory, filename })
        });

        const result = await response.json();

        if (result.error) {
            addLog({ message: result.error, level: "error" });
        } else {
            setDownloadingUI(true);
        }
    } catch (e) {
        addLog({ message: `Failed to start: ${e.message}`, level: "error" });
    }
}

async function cancelDownload() {
    try {
        await api.fetchApi("/downloader/cancel", { method: "POST" });
    } catch (e) {
        console.error("Cancel failed:", e);
    }
}

function setDownloadingUI(downloading) {
    elements.downloadBtn.style.display = downloading ? "none" : "block";
    elements.cancelBtn.style.display = downloading ? "block" : "none";
    elements.progressSection.style.display = downloading ? "block" : "none";

    elements.urlInput.disabled = downloading;
    elements.dirSelect.disabled = downloading;
    elements.filenameInput.disabled = downloading;
}

function updateUI(state) {
    currentState = state;

    if (state.status === "downloading") {
        setDownloadingUI(true);

        document.getElementById("progress-filename").textContent = state.filename || "Downloading...";
        document.getElementById("progress-platform").textContent = state.platform?.toUpperCase() || "";
        document.getElementById("progress-bar").style.width = `${state.progress || 0}%`;
        document.getElementById("progress-percent").textContent = `${state.progress || 0}%`;
        document.getElementById("progress-speed").textContent = state.speed || "";
        document.getElementById("progress-eta").textContent = state.eta ? `ETA: ${state.eta}` : "";
        document.getElementById("progress-message").textContent = state.message || "";

    } else if (state.status === "completed" || state.status === "error" || state.status === "cancelled") {
        document.getElementById("progress-bar").style.width = state.status === "completed" ? "100%" : "0%";
        document.getElementById("progress-message").textContent = state.message || state.status;

        // Reset UI after delay
        setTimeout(() => {
            setDownloadingUI(false);
        }, 2000);

    } else if (state.status === "idle") {
        setDownloadingUI(false);
    }
}

function addLog(data) {
    const container = elements.logContainer;
    if (!container) return;

    const entry = document.createElement("div");
    entry.style.cssText = "margin-bottom: 4px; word-break: break-word;";

    const colors = {
        error: "#ef4444",
        warning: "#f59e0b",
        success: "#22c55e",
        info: "#888"
    };

    const time = data.timestamp || new Date().toLocaleTimeString().slice(0, 5);
    entry.innerHTML = `<span style="opacity: 0.5;">[${time}]</span> <span style="color: ${colors[data.level] || colors.info}">${data.message}</span>`;

    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
}