"""
Sidebar Model Downloader Extension for ComfyUI
Universal downloader supporting HuggingFace, CivitAI, and generic URLs.
With multi-download queue support.
"""

import os
import re
import sys
import time
import shutil
import subprocess
import threading
import json
from pathlib import Path
from urllib.parse import urlparse, unquote
from datetime import datetime
from aiohttp import web
from server import PromptServer

WEB_DIRECTORY = "./web/js"
NODE_CLASS_MAPPINGS = {}
__all__ = ["WEB_DIRECTORY"]

# =============================================
# CONFIGURATION
# =============================================

HF_TOKEN = "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"
CIVITAI_TOKEN = "3bf797ec7a0b65f197ca426ccb8cf193"

# =============================================
# GLOBAL STATE
# =============================================

# Download queue
download_queue = []
queue_lock = threading.Lock()
is_processing = False
cancel_requested = False
current_process = None

# Persistent logs
persistent_logs = []
MAX_LOGS = 200

# =============================================
# UTILITY FUNCTIONS
# =============================================

def format_bytes(bytes_size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

def format_time(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds/60)}m {int(seconds%60)}s"
    else:
        return f"{int(seconds/3600)}h {int((seconds%3600)/60)}m"

def detect_platform(url):
    url_lower = url.lower()
    if 'huggingface.co' in url_lower or 'hf.co' in url_lower:
        return 'huggingface'
    elif 'civitai.com' in url_lower:
        return 'civitai'
    return 'other'

def get_comfyui_base():
    current = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(current))

def get_model_directories():
    base = get_comfyui_base()
    models_path = os.path.join(base, "models")
    
    return {
        "diffusion_models": os.path.join(models_path, "diffusion_models"),
        "text_encoders": os.path.join(models_path, "text_encoders"),
        "loras": os.path.join(models_path, "loras"),
        "vae": os.path.join(models_path, "vae"),
        "clip": os.path.join(models_path, "clip"),
        "clip_vision": os.path.join(models_path, "clip_vision"),
        "checkpoints": os.path.join(models_path, "checkpoints"),
        "upscale_models": os.path.join(models_path, "upscale_models"),
        "controlnet": os.path.join(models_path, "controlnet"),
        "embeddings": os.path.join(models_path, "embeddings"),
    }

def add_log(message, level="info"):
    """Add log entry and send to frontend."""
    global persistent_logs
    entry = {
        "message": message,
        "level": level,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    with queue_lock:
        persistent_logs.append(entry)
        if len(persistent_logs) > MAX_LOGS:
            persistent_logs = persistent_logs[-MAX_LOGS:]
    try:
        PromptServer.instance.send_sync("downloader.log", entry)
    except Exception as e:
        print(f"[Downloader] Log send error: {e}")

def broadcast_state():
    """Send current state to frontend."""
    try:
        with queue_lock:
            state = {
                "queue": list(download_queue),
                "is_processing": is_processing,
                "logs": list(persistent_logs[-50:])
            }
        PromptServer.instance.send_sync("downloader.queue", state)
    except Exception as e:
        print(f"[Downloader] Broadcast error: {e}")

def update_queue_item(item_id, **kwargs):
    """Update an item in the queue."""
    global download_queue
    with queue_lock:
        for item in download_queue:
            if item["id"] == item_id:
                for key, value in kwargs.items():
                    if key in item:
                        item[key] = value
                break
    broadcast_state()

# =============================================
# HuggingFace Functions
# =============================================

def parse_hf_url(url):
    pattern = r'https://huggingface\.co/([^/]+/[^/]+)/resolve/main/(.+)'
    match = re.match(pattern, url)
    if match:
        return match.group(1), match.group(2)
    raise ValueError("Invalid HuggingFace URL format")

def download_huggingface(item_id, url, directory):
    """Download from HuggingFace."""
    try:
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
        from huggingface_hub import hf_hub_download, login
        
        try:
            login(token=HF_TOKEN, add_to_git_credential=False)
        except:
            pass
        
        repo_id, filename = parse_hf_url(url)
        file_name = os.path.basename(filename)
        
        update_queue_item(item_id, detected_filename=file_name, message=f"Downloading {file_name}...")
        add_log(f"HuggingFace: {repo_id} / {file_name}")
        
        os.makedirs(directory, exist_ok=True)
        
        start_time = time.time()
        
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            token=HF_TOKEN
        )
        
        final_path = os.path.join(directory, file_name)
        shutil.copy2(downloaded_path, final_path)
        
        duration = time.time() - start_time
        file_size = os.path.getsize(final_path)
        
        update_queue_item(item_id, 
            status="completed",
            progress=100,
            message=f"Done! {format_bytes(file_size)} in {format_time(duration)}")
        add_log(f"✅ Saved: {final_path}", "success")
        
        return True
        
    except Exception as e:
        update_queue_item(item_id, status="error", message=str(e))
        add_log(f"❌ HF Error: {str(e)}", "error")
        return False

# =============================================
# CivitAI / Aria2 Functions
# =============================================

def prepare_civitai_url(url):
    if 'token=' in url:
        return url
    if CIVITAI_TOKEN:
        separator = '&' if '?' in url else '?'
        return f"{url}{separator}token={CIVITAI_TOKEN}"
    return url

def get_filename_from_url(url):
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/octet-stream, */*',
            'Referer': 'https://civitai.com/'
        }
        prepared_url = prepare_civitai_url(url)
        response = requests.head(prepared_url, headers=headers, allow_redirects=True, timeout=15)
        
        if 'Content-Disposition' in response.headers:
            content_disp = response.headers['Content-Disposition']
            filename_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\\r\\n]+)', content_disp)
            if filename_match:
                return unquote(filename_match.group(1))
        
        parsed_url = urlparse(url)
        url_filename = unquote(os.path.basename(parsed_url.path))
        if url_filename and '.' in url_filename:
            return url_filename
    except:
        pass
    
    return f"model_{int(time.time())}.safetensors"

def download_aria2(item_id, url, directory, custom_filename=None):
    """Download using aria2c."""
    global current_process, cancel_requested
    
    try:
        subprocess.run(['aria2c', '--version'], capture_output=True, check=True)
    except:
        update_queue_item(item_id, status="error", message="aria2c not installed!")
        add_log("❌ aria2c is required for CivitAI downloads", "error")
        return False
    
    filename = custom_filename if custom_filename else get_filename_from_url(url)
    
    update_queue_item(item_id, detected_filename=filename, message=f"Downloading {filename}...")
    add_log(f"Target: {directory}/{filename}")
    
    os.makedirs(directory, exist_ok=True)
    
    prepared_url = prepare_civitai_url(url) if 'civitai' in url.lower() else url
    
    cmd = [
        'aria2c',
        '--file-allocation=none',
        '--max-connection-per-server=4',
        '--split=4',
        '--min-split-size=1M',
        '--continue=true',
        '--allow-overwrite=true',
        '--auto-file-renaming=false',
        '--console-log-level=notice',
        '--summary-interval=1',
        '--check-certificate=false',
        f'--dir={directory}',
        f'--out={filename}',
        '--header=User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        '--header=Accept: application/octet-stream, */*',
        prepared_url
    ]
    
    if 'civitai' in url.lower():
        cmd.append('--header=Referer: https://civitai.com/')
    
    start_time = time.time()
    filepath = os.path.join(directory, filename)
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1
    )
    current_process = process
    
    for line in process.stdout:
        if cancel_requested:
            process.terminate()
            return False
        
        line = line.strip()
        if '[#' in line and 'DL:' in line:
            try:
                pct_match = re.search(r'\((\d+)%\)', line)
                if pct_match:
                    update_queue_item(item_id, progress=int(pct_match.group(1)))
                
                speed_match = re.search(r'DL:([^\s]+)', line)
                if speed_match:
                    update_queue_item(item_id, speed=speed_match.group(1))
                
                eta_match = re.search(r'ETA:([^\]]+)', line)
                if eta_match:
                    update_queue_item(item_id, eta=eta_match.group(1))
            except:
                pass
    
    process.wait()
    current_process = None
    
    if process.returncode == 0 and os.path.exists(filepath):
        duration = time.time() - start_time
        file_size = os.path.getsize(filepath)
        update_queue_item(item_id, 
            status="completed",
            progress=100,
            message=f"Done! {format_bytes(file_size)} in {format_time(duration)}")
        add_log(f"✅ Saved: {filepath}", "success")
        return True
    
    update_queue_item(item_id, status="error", message="Download failed")
    return False

# =============================================
# Queue Processing
# =============================================

def process_queue():
    """Process all items in the queue."""
    global is_processing, cancel_requested
    
    is_processing = True
    cancel_requested = False
    broadcast_state()
    
    add_log("🚀 Queue processing started")
    
    while True:
        # Find next queued item
        next_item = None
        with queue_lock:
            for item in download_queue:
                if item["status"] == "queued":
                    next_item = item
                    break
        
        if not next_item or cancel_requested:
            break
        
        item_id = next_item["id"]
        update_queue_item(item_id, status="downloading", progress=0, message="Starting...")
        
        url = next_item["url"]
        directory = next_item["directory"]
        filename = next_item.get("filename")
        platform = next_item["platform"]
        
        add_log(f"📥 Downloading from {platform.upper()}...")
        
        try:
            if platform == "huggingface":
                download_huggingface(item_id, url, directory)
            else:
                download_aria2(item_id, url, directory, filename)
        except Exception as e:
            update_queue_item(item_id, status="error", message=str(e))
            add_log(f"❌ Error: {str(e)}", "error")
    
    is_processing = False
    broadcast_state()
    add_log("✅ Queue processing completed")

# =============================================
# API ROUTES
# =============================================

@PromptServer.instance.routes.get("/downloader/directories")
async def get_directories(request):
    """Get available model directories."""
    directories = get_model_directories()
    return web.json_response({
        "directories": directories,
        "base": get_comfyui_base()
    })

@PromptServer.instance.routes.post("/downloader/add")
async def add_to_queue(request):
    """Add download to queue."""
    global download_queue
    try:
        data = await request.json()
        url = data.get("url", "").strip()
        directory = data.get("directory", "")
        filename = data.get("filename", "").strip() or None
        
        if not url:
            return web.json_response({"error": "URL is required"}, status=400)
        if not directory:
            return web.json_response({"error": "Directory is required"}, status=400)
        
        item = {
            "id": f"{int(time.time() * 1000)}_{len(download_queue)}",
            "url": url,
            "directory": directory,
            "filename": filename,
            "platform": detect_platform(url),
            "status": "queued",
            "progress": 0,
            "speed": "",
            "eta": "",
            "message": "Waiting in queue...",
            "detected_filename": ""
        }
        
        with queue_lock:
            download_queue.append(item)
        
        add_log(f"➕ Added to queue: {url[:50]}...")
        broadcast_state()
        
        return web.json_response({"status": "added", "id": item["id"]})
        
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/start")
async def start_queue(request):
    """Start processing the queue."""
    global is_processing
    
    if is_processing:
        return web.json_response({"status": "already_running"})
    
    threading.Thread(target=process_queue, daemon=True).start()
    return web.json_response({"status": "started"})

@PromptServer.instance.routes.post("/downloader/cancel")
async def cancel_download(request):
    """Cancel current download."""
    global cancel_requested, current_process
    
    cancel_requested = True
    if current_process:
        try:
            current_process.terminate()
        except:
            pass
    
    add_log("⏹ Download cancelled", "warning")
    return web.json_response({"status": "cancelling"})

@PromptServer.instance.routes.post("/downloader/remove")
async def remove_item(request):
    """Remove item from queue."""
    global download_queue
    try:
        data = await request.json()
        item_id = data.get("id")
        
        with queue_lock:
            download_queue = [item for item in download_queue if item["id"] != item_id]
        
        broadcast_state()
        return web.json_response({"status": "removed"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/clear")
async def clear_completed(request):
    """Clear completed items from queue."""
    global download_queue
    
    with queue_lock:
        download_queue = [item for item in download_queue if item["status"] in ["queued", "downloading"]]
    
    broadcast_state()
    return web.json_response({"status": "cleared"})

@PromptServer.instance.routes.post("/downloader/clear-logs")
async def clear_logs(request):
    """Clear logs."""
    global persistent_logs
    with queue_lock:
        persistent_logs = []
    return web.json_response({"status": "cleared"})

@PromptServer.instance.routes.get("/downloader/state")
async def get_state(request):
    """Get current queue state."""
    with queue_lock:
        state = {
            "queue": list(download_queue),
            "is_processing": is_processing,
            "logs": list(persistent_logs[-50:])
        }
    return web.json_response(state)

# Also keep the old /downloader/start endpoint for backward compatibility with single downloads
@PromptServer.instance.routes.post("/downloader/single")
async def single_download(request):
    """Single download (backward compatibility)."""
    global download_queue, is_processing
    try:
        data = await request.json()
        url = data.get("url", "").strip()
        directory = data.get("directory", "")
        filename = data.get("filename", "").strip() or None
        
        if not url:
            return web.json_response({"error": "URL is required"}, status=400)
        if not directory:
            return web.json_response({"error": "Directory is required"}, status=400)
        
        if is_processing:
            return web.json_response({"error": "Download already in progress"}, status=400)
        
        item = {
            "id": f"{int(time.time() * 1000)}_single",
            "url": url,
            "directory": directory,
            "filename": filename,
            "platform": detect_platform(url),
            "status": "queued",
            "progress": 0,
            "speed": "",
            "eta": "",
            "message": "Waiting...",
            "detected_filename": ""
        }
        
        with queue_lock:
            download_queue.append(item)
        
        broadcast_state()
        threading.Thread(target=process_queue, daemon=True).start()
        
        return web.json_response({"status": "started"})
        
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

print("[SidebarDownloader] Extension loaded with queue support")