"""
Sidebar Model Downloader Extension for ComfyUI
Universal downloader using aria2 for all platforms.
Supports HuggingFace, CivitAI, and generic URLs.
"""

import os
import shutil
import re
import time
import subprocess
import threading
import signal
import pty
import select
import fcntl
import termios
import struct
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
DOWNLOAD_PROVIDER = "hf_hub" # Options: "aria2", "hf_hub"

# Enable high performance transfer for HF
os.environ["HF_XET_HIGH_PERFORMANCE"] = "1"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

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
    # base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # models = os.path.join(base, "models")
    models = "/root/volume/ComfyUI/models"
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

def broadcast_state(force=False):
    """Broadcast queue state. Throttled to max once per 500ms unless forced."""
    global _last_broadcast_time
    now = time.time()
    if not force and hasattr(broadcast_state, '_last_time') and (now - broadcast_state._last_time) < 0.5:
        return
    broadcast_state._last_time = now
    try:
        with queue_lock:
            state = {"queue": list(download_queue), "is_processing": is_processing, "logs": persistent_logs[-50:]}
        PromptServer.instance.send_sync("downloader.queue", state)
    except:
        pass

def update_item(item_id, force_broadcast=False, **kwargs):
    with queue_lock:
        for item in download_queue:
            if item["id"] == item_id:
                item.update(kwargs)
                break
    # Force broadcast on status changes, throttle on progress-only updates
    should_force = force_broadcast or 'status' in kwargs
    broadcast_state(force=should_force)

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
# HF DOWNLOADER
# =============================================

def download_with_hf(item_id, url, directory, custom_filename):
    """Download using huggingface_hub with hf_transfer."""
    global current_process, cancel_requested
    
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        update_item(item_id, status="error", message="huggingface_hub not installed!")
        add_log("❌ huggingface_hub is required. Install with: pip install huggingface_hub hf_transfer", "error")
        return False

    # Check if URL is valid HF URL
    if 'huggingface.co' not in url and 'hf.co' not in url:
        return False

    # Extract repo_id and filename
    # Expected format: https://huggingface.co/user/repo/blob/branch/filename
    # or https://huggingface.co/user/repo/resolve/branch/filename
    
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        
        # path_parts: ['user', 'repo', 'blob', 'branch', 'filename...']
        if len(path_parts) < 5:
            raise ValueError("Invalid HF URL format")
            
        repo_id = f"{path_parts[0]}/{path_parts[1]}"
        revision = path_parts[3]
        hf_filename = '/'.join(path_parts[4:])  # full path in repo (e.g. split_files/vae/ae.safetensors)
        filename = os.path.basename(hf_filename)  # just the file name (e.g. ae.safetensors)
        
        # Use custom filename if provided
        if custom_filename:
            filename = custom_filename
        
        update_item(item_id, detected_filename=filename, message=f"Downloading {filename} (HF)...")
        add_log(f"📁 {directory}/{filename} (HF)")
        
        start_time = time.time()
        
        update_item(item_id, message="Downloading with HF Transfer (Speed optimized)...")
        
        file_path = hf_hub_download(
            repo_id=repo_id,
            filename=hf_filename,
            revision=revision,
            local_dir=directory,
            force_download=False,
        )
        
        # Move file from nested HF path to flat target directory
        target_path = os.path.join(directory, filename)
        if os.path.abspath(file_path) != os.path.abspath(target_path):
            if os.path.exists(target_path):
                os.remove(target_path)
            os.rename(file_path, target_path)
            
            # Cleanup junk intermediate directories created by hf_hub_download
            top_level_dir = hf_filename.split('/')[0]
            junk_dir = os.path.join(directory, top_level_dir)
            if top_level_dir != filename and os.path.isdir(junk_dir):
                shutil.rmtree(junk_dir, ignore_errors=True)
                add_log(f"🧹 Cleaned up junk folder: {top_level_dir}", "info")
            
            file_path = target_path
        
        # Also cleanup .huggingface metadata directory if created
        hf_meta_dir = os.path.join(directory, ".huggingface")
        if os.path.isdir(hf_meta_dir):
            shutil.rmtree(hf_meta_dir, ignore_errors=True)

        duration = time.time() - start_time
        size = os.path.getsize(file_path)
        update_item(item_id, status="completed", progress=100, 
                   message=f"✅ {format_bytes(size)} in {format_time(duration)}")
        add_log(f"✅ Complete: {filename}", "success")
        return True

    except Exception as e:
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
        
        url = next_item["url"]
        platform = next_item["platform"]
        provider = next_item.get("provider", DOWNLOAD_PROVIDER)
        
        add_log(f"📥 {platform.upper()} via {provider}: {url[:50]}...")
        
        try:
            success = False
            # Choose provider
            if provider == "hf_hub" and platform == "huggingface":
                 success = download_with_hf(
                    item_id, 
                    url, 
                    next_item["directory"], 
                    next_item.get("filename")
                )
            
            # Fallback or default to aria2
            if not success and not cancel_requested and next_item["status"] != "completed" and next_item["status"] != "error":
                if provider == "hf_hub" and platform == "huggingface":
                     add_log("⚠️ HF Download failed or not valid, trying aria2...", "warning")
                
                download_with_aria2(
                    item_id, 
                    url, 
                    next_item["directory"], 
                    next_item.get("filename"),
                    platform
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
        provider = data.get("provider", DOWNLOAD_PROVIDER).strip()
        
        if not url:
            return web.json_response({"error": "URL required"}, status=400)
        if not directory:
            return web.json_response({"error": "Directory required"}, status=400)
        
        item = {
            "id": f"{int(time.time()*1000)}_{len(download_queue)}",
            "url": url,
            "directory": directory,
            "filename": filename,
            "provider": provider,
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

# =============================================
# TERMINAL
# =============================================

# Terminal global state (prefixed to avoid collision with downloader's current_process)
terminal_process = None
terminal_master_fd = None
terminal_lock = threading.Lock()
terminal_shell_starting = False
terminal_cwd = os.getcwd()

def find_shell():
    """Find available shell."""
    for shell in ["/bin/bash", "/bin/sh", "/usr/bin/bash", "/usr/bin/sh"]:
        if os.path.exists(shell):
            return shell
    for name in ["bash", "sh", "ash", "dash"]:
        path = shutil.which(name)
        if path:
            return path
    return None

def terminal_output_reader(master_fd):
    """Reads output from PTY and sends to frontend via WebSocket."""
    global terminal_master_fd
    try:
        while terminal_master_fd == master_fd:
            try:
                r, w, x = select.select([master_fd], [], [], 0.05)
                if master_fd in r:
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                    text = data.decode('utf-8', errors='replace')
                    try:
                        PromptServer.instance.send_sync("downloader.terminal.output", {
                            "text": text,
                            "type": "stdout"
                        })
                    except:
                        pass
            except (OSError, ValueError):
                break
    except Exception as e:
        print(f"[Downloader Terminal] Output reader error: {e}")

def terminal_monitor_process(proc, master_fd):
    """Waits for process to finish and cleans up."""
    global terminal_process, terminal_master_fd
    try:
        proc.wait()
    except:
        pass

    with terminal_lock:
        if terminal_process == proc:
            terminal_process = None
            if terminal_master_fd == master_fd:
                try:
                    os.close(master_fd)
                except:
                    pass
                terminal_master_fd = None

    try:
        PromptServer.instance.send_sync("downloader.terminal.status", {"running": False})
    except:
        pass

def start_terminal_shell():
    """Starts a persistent shell if not already running."""
    global terminal_process, terminal_master_fd, terminal_cwd, terminal_shell_starting

    if terminal_shell_starting:
        return False

    with terminal_lock:
        if terminal_process and terminal_process.poll() is None:
            return True
        terminal_shell_starting = True

    shell = find_shell()
    if not shell:
        terminal_shell_starting = False
        return False

    try:
        master_fd, slave_fd = pty.openpty()

        try:
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        except:
            pass

        env = os.environ.copy()
        env['TERM'] = 'xterm-256color'
        env['SHELL'] = shell
        env['PS1'] = '\\[\\033[32m\\]\\u@\\h\\[\\033[0m\\]:\\[\\033[34m\\]\\w\\[\\033[0m\\]\\$ '

        process = subprocess.Popen(
            [shell],
            cwd=terminal_cwd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            preexec_fn=os.setsid,
            close_fds=True
        )

        os.close(slave_fd)

        with terminal_lock:
            terminal_process = process
            terminal_master_fd = master_fd

        reader_thread = threading.Thread(target=terminal_output_reader, args=(master_fd,), daemon=True)
        reader_thread.start()

        monitor_thread = threading.Thread(target=terminal_monitor_process, args=(process, master_fd), daemon=True)
        monitor_thread.start()

        print(f"[Downloader Terminal] Shell started: {shell} (PID: {process.pid})")
        terminal_shell_starting = False
        return True

    except Exception as e:
        print(f"[Downloader Terminal] Failed to start shell: {e}")
        terminal_shell_starting = False
        return False

@PromptServer.instance.routes.post("/downloader/terminal/execute")
async def terminal_execute(request):
    global terminal_process, terminal_master_fd
    try:
        data = await request.json()
        command = data.get("command", "")

        if not terminal_process or terminal_process.poll() is not None:
            def start_in_bg():
                if start_terminal_shell():
                    time.sleep(0.3)
                    with terminal_lock:
                        if terminal_master_fd:
                            try:
                                os.write(terminal_master_fd, b'\n')
                            except:
                                pass
            threading.Thread(target=start_in_bg, daemon=True).start()
            return web.json_response({"status": "starting"})

        with terminal_lock:
            if terminal_master_fd:
                try:
                    if command:
                        os.write(terminal_master_fd, command.encode('utf-8'))
                    return web.json_response({"status": "input_sent"})
                except Exception as e:
                    return web.json_response({"error": f"Write failed: {e}"}, status=500)

        return web.json_response({"error": "No terminal session"}, status=500)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/terminal/interrupt")
async def terminal_interrupt(request):
    global terminal_process
    with terminal_lock:
        if terminal_process and terminal_process.poll() is None:
            try:
                os.killpg(os.getpgid(terminal_process.pid), signal.SIGINT)
                return web.json_response({"status": "interrupted"})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"error": "No running process"}, status=400)

@PromptServer.instance.routes.post("/downloader/terminal/resize")
async def terminal_resize(request):
    global terminal_master_fd
    try:
        data = await request.json()
        cols = data.get("cols", 80)
        rows = data.get("rows", 24)

        with terminal_lock:
            if terminal_master_fd:
                fcntl.ioctl(terminal_master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                return web.json_response({"status": "resized"})
        return web.json_response({"error": "No terminal session"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# =============================================
# FILE MANAGER
# =============================================

FILE_MANAGER_ROOT = os.path.realpath("/root/volume/ComfyUI")

def safe_path(requested_path):
    """Resolve and validate path is within FILE_MANAGER_ROOT."""
    resolved = os.path.realpath(os.path.join(FILE_MANAGER_ROOT, requested_path))
    if not resolved.startswith(FILE_MANAGER_ROOT):
        return None
    return resolved

@PromptServer.instance.routes.post("/downloader/files/list")
async def files_list(request):
    """List directory contents."""
    try:
        data = await request.json()
        rel_path = data.get("path", "")
        target = safe_path(rel_path)
        if not target:
            return web.json_response({"error": "Invalid path"}, status=400)
        if not os.path.isdir(target):
            return web.json_response({"error": "Not a directory"}, status=400)

        items = []
        try:
            entries = sorted(os.listdir(target), key=lambda x: (not os.path.isdir(os.path.join(target, x)), x.lower()))
        except PermissionError:
            return web.json_response({"error": "Permission denied"}, status=403)

        for name in entries:
            if name.startswith('.'):
                continue
            full = os.path.join(target, name)
            is_dir = os.path.isdir(full)
            try:
                stat = os.stat(full)
                items.append({
                    "name": name,
                    "is_dir": is_dir,
                    "size": stat.st_size if not is_dir else 0,
                    "mtime": stat.st_mtime
                })
            except (OSError, PermissionError):
                items.append({"name": name, "is_dir": is_dir, "size": 0, "mtime": 0})

        return web.json_response({"items": items, "path": os.path.relpath(target, FILE_MANAGER_ROOT)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/files/delete")
async def files_delete(request):
    """Delete a file or directory."""
    try:
        data = await request.json()
        rel_path = data.get("path", "")
        target = safe_path(rel_path)
        if not target or target == os.path.realpath(FILE_MANAGER_ROOT):
            return web.json_response({"error": "Invalid path"}, status=400)
        if not os.path.exists(target):
            return web.json_response({"error": "Not found"}, status=404)

        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
        return web.json_response({"status": "deleted"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/files/rename")
async def files_rename(request):
    """Rename a file or directory."""
    try:
        data = await request.json()
        rel_path = data.get("path", "")
        new_name = data.get("new_name", "").strip()
        if not new_name or '/' in new_name or '\\' in new_name:
            return web.json_response({"error": "Invalid name"}, status=400)

        target = safe_path(rel_path)
        if not target or target == os.path.realpath(FILE_MANAGER_ROOT):
            return web.json_response({"error": "Invalid path"}, status=400)
        if not os.path.exists(target):
            return web.json_response({"error": "Not found"}, status=404)

        new_path = os.path.join(os.path.dirname(target), new_name)
        if os.path.exists(new_path):
            return web.json_response({"error": "Name already exists"}, status=409)
        os.rename(target, new_path)
        return web.json_response({"status": "renamed"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/files/copy")
async def files_copy(request):
    """Copy a file or directory."""
    try:
        data = await request.json()
        src_path = data.get("source", "")
        dst_path = data.get("destination", "")

        source = safe_path(src_path)
        destination = safe_path(dst_path)
        if not source or not destination:
            return web.json_response({"error": "Invalid path"}, status=400)
        if not os.path.exists(source):
            return web.json_response({"error": "Source not found"}, status=404)

        # Destination is a directory - copy into it
        if os.path.isdir(destination):
            dest_name = os.path.basename(source)
            final_dest = os.path.join(destination, dest_name)
            # Handle name collision
            if os.path.exists(final_dest):
                base, ext = os.path.splitext(dest_name)
                final_dest = os.path.join(destination, f"{base}_copy{ext}")
        else:
            final_dest = destination

        if os.path.isdir(source):
            shutil.copytree(source, final_dest)
        else:
            shutil.copy2(source, final_dest)
        return web.json_response({"status": "copied"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/files/move")
async def files_move(request):
    """Move (cut+paste) a file or directory."""
    try:
        data = await request.json()
        src_path = data.get("source", "")
        dst_path = data.get("destination", "")

        source = safe_path(src_path)
        destination = safe_path(dst_path)
        if not source or not destination:
            return web.json_response({"error": "Invalid path"}, status=400)
        if source == os.path.realpath(FILE_MANAGER_ROOT):
            return web.json_response({"error": "Cannot move root"}, status=400)
        if not os.path.exists(source):
            return web.json_response({"error": "Source not found"}, status=404)

        if os.path.isdir(destination):
            final_dest = os.path.join(destination, os.path.basename(source))
        else:
            final_dest = destination

        shutil.move(source, final_dest)
        return web.json_response({"status": "moved"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/files/mkdir")
async def files_mkdir(request):
    """Create a new directory."""
    try:
        data = await request.json()
        rel_path = data.get("path", "")
        target = safe_path(rel_path)
        if not target:
            return web.json_response({"error": "Invalid path"}, status=400)
        if os.path.exists(target):
            return web.json_response({"error": "Already exists"}, status=409)
        os.makedirs(target, exist_ok=True)
        return web.json_response({"status": "created"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

print("[Downloader] Loaded - aria2 powered + terminal + file manager")