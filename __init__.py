"""
Sidebar Model Downloader Extension for ComfyUI
Universal downloader using aria2 for all platforms.
Supports HuggingFace, CivitAI, and generic URLs.
"""

import os
import re
import time
import subprocess
import threading
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

CIVITAI_TOKEN = "3bf797ec7a0b65f197ca426ccb8cf193"

# =============================================
# GLOBAL STATE
# =============================================

download_queue = []
queue_lock = threading.Lock()
is_processing = False
cancel_requested = False
current_process = None
current_item_id = None
persistent_logs = []

# =============================================
# UTILITIES
# =============================================

def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def format_time(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds/60)}m {int(seconds%60)}s"
    return f"{int(seconds/3600)}h {int((seconds%3600)/60)}m"

def detect_platform(url):
    url_lower = url.lower()
    if 'huggingface.co' in url_lower or 'hf.co' in url_lower:
        return 'huggingface'
    elif 'civitai.com' in url_lower:
        return 'civitai'
    return 'other'

def get_model_directories():
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    models = os.path.join(base, "models")
    return {
        "diffusion_models": os.path.join(models, "diffusion_models"),
        "text_encoders": os.path.join(models, "text_encoders"),
        "loras": os.path.join(models, "loras"),
        "vae": os.path.join(models, "vae"),
        "clip": os.path.join(models, "clip"),
        "clip_vision": os.path.join(models, "clip_vision"),
        "checkpoints": os.path.join(models, "checkpoints"),
        "upscale_models": os.path.join(models, "upscale_models"),
        "controlnet": os.path.join(models, "controlnet"),
        "embeddings": os.path.join(models, "embeddings"),
    }

def add_log(message, level="info"):
    entry = {"message": message, "level": level, "timestamp": datetime.now().strftime("%H:%M:%S")}
    with queue_lock:
        persistent_logs.append(entry)
        if len(persistent_logs) > 200:
            del persistent_logs[:-200]
    try:
        PromptServer.instance.send_sync("downloader.log", entry)
    except:
        pass

def broadcast_state():
    try:
        with queue_lock:
            state = {"queue": list(download_queue), "is_processing": is_processing, "logs": persistent_logs[-50:]}
        PromptServer.instance.send_sync("downloader.queue", state)
    except:
        pass

def update_item(item_id, **kwargs):
    with queue_lock:
        for item in download_queue:
            if item["id"] == item_id:
                item.update(kwargs)
                break
    broadcast_state()

# =============================================
# FILENAME DETECTION
# =============================================

def get_filename_from_url(url, platform):
    """Auto-detect filename from URL or HTTP headers."""
    
    # Try to get from HTTP headers first
    try:
        import requests
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'}
        if platform == 'civitai':
            headers['Referer'] = 'https://civitai.com/'
            if CIVITAI_TOKEN and 'token=' not in url:
                url = f"{url}{'&' if '?' in url else '?'}token={CIVITAI_TOKEN}"
        
        resp = requests.head(url, headers=headers, allow_redirects=True, timeout=15)
        
        if 'Content-Disposition' in resp.headers:
            match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\\r\\n]+)', resp.headers['Content-Disposition'])
            if match:
                return unquote(match.group(1))
    except:
        pass
    
    # Extract from URL path
    parsed = urlparse(url)
    path = unquote(parsed.path)
    filename = os.path.basename(path)
    
    # Clean query params from filename
    if '?' in filename:
        filename = filename.split('?')[0]
    
    if filename and '.' in filename:
        return filename
    
    return f"model_{int(time.time())}.safetensors"

def prepare_url(url, platform):
    """Prepare URL with authentication if needed."""
    if platform == 'civitai' and CIVITAI_TOKEN and 'token=' not in url:
        return f"{url}{'&' if '?' in url else '?'}token={CIVITAI_TOKEN}"
    return url

# =============================================
# ARIA2 DOWNLOADER
# =============================================

def download_with_aria2(item_id, url, directory, custom_filename, platform):
    """Download using aria2c with parallel connections."""
    global current_process, cancel_requested
    
    # Check aria2 installed
    try:
        subprocess.run(['aria2c', '--version'], capture_output=True, check=True)
    except:
        update_item(item_id, status="error", message="aria2c not installed!")
        add_log("❌ aria2c is required. Install with: apt install aria2", "error")
        return False
    
    # Determine filename
    filename = custom_filename if custom_filename else get_filename_from_url(url, platform)
    update_item(item_id, detected_filename=filename, message=f"Downloading {filename}...")
    add_log(f"📁 {directory}/{filename}")
    
    os.makedirs(directory, exist_ok=True)
    
    # Prepare URL with auth
    prepared_url = prepare_url(url, platform)
    
    # Build aria2c command
    cmd = [
        'aria2c',
        '--file-allocation=none',
        '--max-connection-per-server=16',
        '--split=16',
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
        '--header=Accept: */*',
    ]
    
    if platform == 'civitai':
        cmd.append('--header=Referer: https://civitai.com/')
    
    cmd.append(prepared_url)
    
    filepath = os.path.join(directory, filename)
    start_time = time.time()
    
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                   universal_newlines=True, bufsize=1)
        current_process = process
        
        for line in process.stdout:
            if cancel_requested:
                process.terminate()
                process.wait()
                current_process = None
                update_item(item_id, status="cancelled", message="Cancelled")
                return False
            
            # Parse aria2 progress output
            if '[#' in line and 'DL:' in line:
                try:
                    pct = re.search(r'\((\d+)%\)', line)
                    speed = re.search(r'DL:([^\s]+)', line)
                    eta = re.search(r'ETA:([^\]]+)', line)
                    
                    updates = {}
                    if pct: updates['progress'] = int(pct.group(1))
                    if speed: updates['speed'] = speed.group(1)
                    if eta: updates['eta'] = eta.group(1)
                    if updates: update_item(item_id, **updates)
                except:
                    pass
        
        process.wait()
        current_process = None
        
        if cancel_requested:
            update_item(item_id, status="cancelled", message="Cancelled")
            return False
        
        if process.returncode == 0 and os.path.exists(filepath):
            duration = time.time() - start_time
            size = os.path.getsize(filepath)
            update_item(item_id, status="completed", progress=100, 
                       message=f"✅ {format_bytes(size)} in {format_time(duration)}")
            add_log(f"✅ Complete: {filename}", "success")
            return True
        
        update_item(item_id, status="error", message=f"Failed (code: {process.returncode})")
        add_log(f"❌ aria2 exit: {process.returncode}", "error")
        return False
        
    except Exception as e:
        current_process = None
        if not cancel_requested:
            update_item(item_id, status="error", message=str(e))
            add_log(f"❌ {e}", "error")
        return False

# =============================================
# QUEUE PROCESSING
# =============================================

def process_queue():
    global is_processing, cancel_requested, current_item_id
    
    is_processing = True
    cancel_requested = False
    broadcast_state()
    add_log("🚀 Queue started")
    
    while not cancel_requested:
        # Get next queued item
        next_item = None
        with queue_lock:
            for item in download_queue:
                if item["status"] == "queued":
                    next_item = item.copy()
                    break
        
        if not next_item:
            break
        
        item_id = next_item["id"]
        current_item_id = item_id
        update_item(item_id, status="downloading", progress=0, message="Starting...")
        
        add_log(f"📥 {next_item['platform'].upper()}: {next_item['url'][:50]}...")
        
        try:
            download_with_aria2(
                item_id, 
                next_item["url"], 
                next_item["directory"], 
                next_item.get("filename"),
                next_item["platform"]
            )
        except Exception as e:
            if not cancel_requested:
                update_item(item_id, status="error", message=str(e))
        
        current_item_id = None
        time.sleep(0.3)
    
    is_processing = False
    broadcast_state()
    add_log("✅ Queue finished" if not cancel_requested else "⏹ Queue stopped")

# =============================================
# API ROUTES
# =============================================

@PromptServer.instance.routes.get("/downloader/directories")
async def api_directories(request):
    return web.json_response({"directories": get_model_directories()})

@PromptServer.instance.routes.post("/downloader/add")
async def api_add(request):
    global download_queue
    try:
        data = await request.json()
        url = data.get("url", "").strip()
        directory = data.get("directory", "").strip()
        filename_raw = data.get("filename")
        filename = filename_raw.strip() if filename_raw else None
        
        if not url:
            return web.json_response({"error": "URL required"}, status=400)
        if not directory:
            return web.json_response({"error": "Directory required"}, status=400)
        
        item = {
            "id": f"{int(time.time()*1000)}_{len(download_queue)}",
            "url": url,
            "directory": directory,
            "filename": filename,
            "platform": detect_platform(url),
            "status": "queued",
            "progress": 0,
            "speed": "",
            "eta": "",
            "message": "Queued",
            "detected_filename": ""
        }
        
        with queue_lock:
            download_queue.append(item)
        
        add_log(f"➕ Added: {url[:50]}...")
        broadcast_state()
        return web.json_response({"status": "added", "id": item["id"]})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/start")
async def api_start(request):
    if is_processing:
        return web.json_response({"status": "already_running"})
    threading.Thread(target=process_queue, daemon=True).start()
    return web.json_response({"status": "started"})

@PromptServer.instance.routes.post("/downloader/cancel")
async def api_cancel(request):
    global cancel_requested, current_process, is_processing
    
    cancel_requested = True
    if current_process:
        try:
            current_process.terminate()
        except:
            pass
    if current_item_id:
        update_item(current_item_id, status="cancelled", message="Cancelled")
    
    add_log("⏹ Cancelled", "warning")
    time.sleep(0.2)
    is_processing = False
    broadcast_state()
    return web.json_response({"status": "cancelled"})

@PromptServer.instance.routes.post("/downloader/remove")
async def api_remove(request):
    global download_queue
    data = await request.json()
    item_id = data.get("id")
    with queue_lock:
        download_queue = [i for i in download_queue if i["id"] != item_id]
    broadcast_state()
    return web.json_response({"status": "removed"})

@PromptServer.instance.routes.post("/downloader/clear")
async def api_clear(request):
    global download_queue
    with queue_lock:
        download_queue = [i for i in download_queue if i["status"] in ["queued", "downloading"]]
    broadcast_state()
    return web.json_response({"status": "cleared"})

@PromptServer.instance.routes.post("/downloader/clear-logs")
async def api_clear_logs(request):
    global persistent_logs
    with queue_lock:
        persistent_logs.clear()
    return web.json_response({"status": "cleared"})

@PromptServer.instance.routes.get("/downloader/state")
async def api_state(request):
    with queue_lock:
        return web.json_response({
            "queue": list(download_queue),
            "is_processing": is_processing,
            "logs": persistent_logs[-50:]
        })

# =============================================
# TEMPLATE API
# =============================================

def get_templates_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

@PromptServer.instance.routes.get("/downloader/templates")
async def api_list_templates(request):
    """List all available template files."""
    templates_dir = get_templates_dir()
    templates = []
    
    if os.path.exists(templates_dir):
        for filename in os.listdir(templates_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(templates_dir, filename)
                try:
                    import json
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    templates.append({
                        "filename": filename,
                        "name": data.get("name", filename.replace('.json', '')),
                        "description": data.get("description", ""),
                        "count": len(data.get("downloads", []))
                    })
                except Exception as e:
                    templates.append({
                        "filename": filename,
                        "name": filename.replace('.json', ''),
                        "description": f"Error: {str(e)}",
                        "count": 0
                    })
    
    return web.json_response({"templates": templates})

@PromptServer.instance.routes.get("/downloader/template/{filename}")
async def api_get_template(request):
    """Get the content of a specific template."""
    filename = request.match_info.get('filename', '')
    
    if not filename.endswith('.json'):
        filename += '.json'
    
    templates_dir = get_templates_dir()
    filepath = os.path.join(templates_dir, filename)
    
    if not os.path.exists(filepath):
        return web.json_response({"error": "Template not found"}, status=404)
    
    try:
        import json
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Resolve directory names to full paths
        directories = get_model_directories()
        for download in data.get("downloads", []):
            dir_key = download.get("directory", "")
            if dir_key in directories:
                download["directory"] = directories[dir_key]
        
        return web.json_response(data)
    except Exception as e:
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/save-template")
async def api_save_template(request):
    """Save a new template."""
    try:
        data = await request.json()
        name = data.get("name", "").strip()
        description = data.get("description", "").strip()
        downloads = data.get("downloads", [])
        
        if not name:
            return web.json_response({"error": "Template name is required"}, status=400)
        
        if not downloads:
            return web.json_response({"error": "No downloads in template"}, status=400)

        # Sanitize filename
        safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)
        filename = f"{safe_name}.json"
        
        templates_dir = get_templates_dir()
        os.makedirs(templates_dir, exist_ok=True)
        filepath = os.path.join(templates_dir, filename)
        
        # Don't overwrite existing files with different names unless explicit
        if os.path.exists(filepath):
            # Simple check to avoid instant overwrite, though user might intend update.
            # For now, append timestamp if exists to be safe, or just overwrite.
            # Let's overwrite as it's a save action.
            pass

        template_data = {
            "name": name,
            "description": description,
            "downloads": downloads
        }
        
        import json
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(template_data, f, indent=2)
            
        return web.json_response({"status": "saved", "filename": filename})
        
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

print("[Downloader] Loaded - aria2 powered")