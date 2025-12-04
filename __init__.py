"""
Sidebar Model Downloader Extension for ComfyUI
Universal downloader supporting HuggingFace, CivitAI, and generic URLs.
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

# Global Download State
download_state = {
    "status": "idle",  # idle, downloading, completed, error, cancelled
    "progress": 0,
    "speed": "",
    "eta": "",
    "filename": "",
    "message": "",
    "platform": "",
    "process": None,
    "cancel_requested": False
}
download_lock = threading.Lock()

# =============================================
# UTILITY FUNCTIONS
# =============================================

def format_bytes(bytes_size):
    """Format bytes to human readable."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

def format_time(seconds):
    """Format seconds to readable time."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        return f"{hours}h {mins}m"

def detect_platform(url):
    """Detect platform from URL."""
    url_lower = url.lower()
    if 'huggingface.co' in url_lower or 'hf.co' in url_lower:
        return 'huggingface'
    elif 'civitai.com' in url_lower:
        return 'civitai'
    else:
        return 'other'

def get_comfyui_base():
    """Get ComfyUI base directory."""
    # Try to find ComfyUI directory
    current = os.path.dirname(os.path.abspath(__file__))
    # Go up from custom_nodes/sidebar to ComfyUI root
    comfyui_root = os.path.dirname(os.path.dirname(current))
    return comfyui_root

def get_model_directories():
    """Get available model directories."""
    base = get_comfyui_base()
    models_path = os.path.join(base, "models")
    
    directories = {
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
    return directories

def update_state(**kwargs):
    """Thread-safe state update."""
    global download_state
    with download_lock:
        for key, value in kwargs.items():
            if key in download_state:
                download_state[key] = value
        # Send update to frontend
        try:
            state_copy = {k: v for k, v in download_state.items() if k != 'process'}
            PromptServer.instance.send_sync("downloader.status", state_copy)
        except:
            pass

def send_log(message, level="info"):
    """Send log message to frontend."""
    try:
        PromptServer.instance.send_sync("downloader.log", {
            "message": message,
            "level": level,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
    except:
        pass

# =============================================
# HUGGING FACE DOWNLOADER
# =============================================

def parse_hf_url(url):
    """Parse HuggingFace URL to extract repo_id and filename."""
    pattern = r'https://huggingface\.co/([^/]+/[^/]+)/resolve/main/(.+)'
    match = re.match(pattern, url)
    if match:
        repo_id = match.group(1)
        filename = match.group(2)
        return repo_id, filename
    raise ValueError("Invalid HuggingFace URL format")

def download_huggingface(url, directory):
    """Download from HuggingFace using hf_transfer."""
    global download_state
    
    try:
        # Enable hf_transfer
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
        
        from huggingface_hub import hf_hub_download, login
        
        # Login
        send_log(f"Logging in as HuggingFace user...")
        try:
            login(token=HF_TOKEN, add_to_git_credential=False)
        except:
            pass
        
        # Parse URL
        repo_id, filename = parse_hf_url(url)
        file_name = os.path.basename(filename)
        
        update_state(filename=file_name, message=f"Downloading {file_name}...")
        send_log(f"Repository: {repo_id}")
        send_log(f"File: {file_name}")
        
        # Create directory
        os.makedirs(directory, exist_ok=True)
        
        start_time = time.time()
        
        # Download
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            token=HF_TOKEN,
            resume_download=True
        )
        
        # Copy to target directory
        final_path = os.path.join(directory, file_name)
        shutil.copy2(downloaded_path, final_path)
        
        end_time = time.time()
        duration = end_time - start_time
        
        if os.path.exists(final_path):
            file_size = os.path.getsize(final_path)
            speed = file_size / max(duration, 0.1)
            
            update_state(
                status="completed",
                progress=100,
                message=f"Completed! {format_bytes(file_size)} in {format_time(duration)}"
            )
            send_log(f"✅ Download complete: {final_path}", "success")
            return True
        else:
            update_state(status="error", message="File not found after download")
            return False
            
    except Exception as e:
        update_state(status="error", message=str(e))
        send_log(f"❌ Error: {str(e)}", "error")
        return False

# =============================================
# CIVITAI / ARIA2 DOWNLOADER
# =============================================

def prepare_civitai_url(url):
    """Prepare CivitAI URL with token."""
    if 'token=' in url:
        return url
    if CIVITAI_TOKEN:
        separator = '&' if '?' in url else '?'
        return f"{url}{separator}token={CIVITAI_TOKEN}"
    return url

def get_filename_from_url(url):
    """Get filename from CivitAI or URL."""
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
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
        
        # Fallback to URL path
        parsed_url = urlparse(url)
        url_filename = unquote(os.path.basename(parsed_url.path))
        if url_filename and '.' in url_filename:
            return url_filename
            
    except Exception as e:
        send_log(f"Could not detect filename: {e}", "warning")
    
    return f"model_{int(time.time())}.safetensors"

def download_aria2(url, directory, custom_filename=None):
    """Download using aria2c."""
    global download_state
    
    try:
        # Check aria2
        try:
            subprocess.run(['aria2c', '--version'], capture_output=True, check=True)
        except:
            update_state(status="error", message="aria2c not installed")
            send_log("❌ aria2c is not installed. Please install it first.", "error")
            return False
        
        # Get filename
        if custom_filename:
            filename = custom_filename
        else:
            filename = get_filename_from_url(url)
        
        update_state(filename=filename, message=f"Downloading {filename}...")
        send_log(f"Filename: {filename}")
        
        # Create directory
        os.makedirs(directory, exist_ok=True)
        
        # Prepare URL
        prepared_url = prepare_civitai_url(url) if 'civitai' in url.lower() else url
        
        # Build aria2c command
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
            '--human-readable=true',
            '--show-console-readout=true',
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
        
        # Run aria2c
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        with download_lock:
            download_state['process'] = process
        
        # Parse output for progress
        for line in process.stdout:
            if download_state.get('cancel_requested'):
                process.terminate()
                update_state(status="cancelled", message="Download cancelled")
                send_log("Download cancelled by user", "warning")
                return False
            
            line = line.strip()
            if line:
                # Parse progress from aria2 output
                # Format: [#abc 1.2MiB/5.0GiB(0%) CN:4 DL:10MiB ETA:8m30s]
                if '[#' in line and 'DL:' in line:
                    try:
                        # Extract percentage
                        pct_match = re.search(r'\((\d+)%\)', line)
                        if pct_match:
                            progress = int(pct_match.group(1))
                            update_state(progress=progress)
                        
                        # Extract speed
                        speed_match = re.search(r'DL:([^\s]+)', line)
                        if speed_match:
                            update_state(speed=speed_match.group(1))
                        
                        # Extract ETA
                        eta_match = re.search(r'ETA:([^\]]+)', line)
                        if eta_match:
                            update_state(eta=eta_match.group(1))
                            
                    except:
                        pass
        
        process.wait()
        
        with download_lock:
            download_state['process'] = None
        
        if process.returncode == 0 and os.path.exists(filepath):
            end_time = time.time()
            duration = end_time - start_time
            file_size = os.path.getsize(filepath)
            
            update_state(
                status="completed",
                progress=100,
                message=f"Completed! {format_bytes(file_size)} in {format_time(duration)}"
            )
            send_log(f"✅ Download complete: {filepath}", "success")
            return True
        else:
            update_state(status="error", message=f"Download failed (code: {process.returncode})")
            send_log(f"❌ Download failed", "error")
            return False
            
    except Exception as e:
        update_state(status="error", message=str(e))
        send_log(f"❌ Error: {str(e)}", "error")
        return False

# =============================================
# MAIN DOWNLOAD HANDLER
# =============================================

def do_download(url, directory, custom_filename=None):
    """Main download function with platform detection."""
    global download_state
    
    platform = detect_platform(url)
    
    update_state(
        status="downloading",
        progress=0,
        speed="",
        eta="",
        filename="",
        message="Starting download...",
        platform=platform,
        cancel_requested=False
    )
    
    send_log(f"Platform detected: {platform.upper()}")
    send_log(f"Target directory: {directory}")
    
    if platform == 'huggingface':
        return download_huggingface(url, directory)
    else:
        return download_aria2(url, directory, custom_filename)

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

@PromptServer.instance.routes.post("/downloader/start")
async def start_download(request):
    """Start a download."""
    global download_state
    
    try:
        data = await request.json()
        url = data.get("url", "").strip()
        directory = data.get("directory", "")
        custom_filename = data.get("filename", "").strip() or None
        
        if not url:
            return web.json_response({"error": "URL is required"}, status=400)
        
        if not directory:
            return web.json_response({"error": "Directory is required"}, status=400)
        
        # Check if already downloading
        with download_lock:
            if download_state["status"] == "downloading":
                return web.json_response({"error": "Download already in progress"}, status=400)
        
        # Start download in background thread
        def download_thread():
            do_download(url, directory, custom_filename)
        
        thread = threading.Thread(target=download_thread, daemon=True)
        thread.start()
        
        return web.json_response({"status": "started"})
        
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/downloader/cancel")
async def cancel_download(request):
    """Cancel current download."""
    global download_state
    
    with download_lock:
        if download_state["status"] == "downloading":
            download_state["cancel_requested"] = True
            if download_state.get("process"):
                try:
                    download_state["process"].terminate()
                except:
                    pass
            return web.json_response({"status": "cancelling"})
    
    return web.json_response({"error": "No active download"}, status=400)

@PromptServer.instance.routes.get("/downloader/status")
async def get_status(request):
    """Get current download status."""
    with download_lock:
        state_copy = {k: v for k, v in download_state.items() if k != 'process'}
    return web.json_response(state_copy)

print("[SidebarDownloader] Extension loaded")