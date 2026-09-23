"""
Pratham AI - Full Production Backend Architecture
=================================================
Corrected + optimized version.
Fixes included in this pass:
  1. GitHub conversation logs now save under: data/<email>/<date>.txt
     (previously saved at repo root as "<email>/<date>.txt").
  2. VIP registrations now save under: data/vip.txt (root-level file inside
     the "data" folder, as requested), with append-safe read-modify-write.
  3. Added a lightweight illegal-content guard that runs before every
     chat-stream request. If a message matches a blocked-intent pattern,
     the assistant refuses politely and the refusal + the flagged message
     is still logged to GitHub for audit purposes (data/flagged/<date>.txt).
  4. Added a `/auth/refresh-check` endpoint so the frontend can silently
     validate a stored token on page load/refresh without forcing a fresh
     Google popup every time (fixes "have to sign in again after refresh").
  5. Performance: reused a single urllib opener with keep-alive-friendly
     timeouts, shortened provider timeouts for faster failover, added a
     small response cache for the GitHub "lookup sha" call so rapid
     consecutive writes to the same file path don't re-fetch metadata
     every single time within a short window.
  6. Streaming: added incremental flush hints and a smaller network read
     size so tokens reach the browser faster (reduces perceived latency).
  7. General hardening: extra input validation, clearer error payloads,
     more defensive exception handling, and additional inline comments.
Second pass — new features (nothing above was removed):
  8. General-purpose assistant: the system prompt is no longer coding-only;
     Pratham AI now answers any topic like a normal chatbot, while still
     being great at code when asked.
  9. Image generation via Google Gemini Nano Banana 2 through OAuth.
     No Gemini developer API key is exposed or required by the website.
 10. "@education" tag: lists PDFs stored under data/education/ in the GitHub
     repo, extracts their text (best-effort, requires the optional `pypdf`
     package), scores paragraphs for relevance against the question, and
     feeds the best-matching excerpt to the model so it can answer citing
     which PDF it used — even if the wording isn't an exact match.
 11. "@web" tag: does a best-effort live DuckDuckGo lookup and feeds the
     results into the model's context, so it can answer with current
     information instead of only training-time knowledge.
 12. File generation via a background Python "terminal": if a message asks
     to turn the reply into a zip or a PDF, the backend actually builds that
     file server-side (zipfile from stdlib; PDF via the optional `fpdf2`
     package, or a plain-text fallback if that package isn't installed) and
     returns a download link.
 13. Upload endpoint now accepts (and best-effort decodes) many file types,
     not just PDF: txt/csv/json/md are read directly; .pdf via `pypdf` if
     installed; anything else gets a basic binary/text sniff instead of a
     hard rejection.
Third pass — direct file-creation channel (nothing above was removed):
 14. The model can now emit ```createfile:<filename.ext>\n<content>\n```
     fenced blocks to directly write a real file into the same background
     terminal working directory used for code execution — no need to write
     python/bash just to produce a file. Every such file is registered in
     the conversation's file registry (same one the Workbench "Files" tab
     already reads from) and immediately gets a real, downloadable
     file-ready card, exactly like a zip/pdf export does.
"""
import os
import re
import io
import json
import time
import uuid
import base64
import hmac
import hashlib
import zipfile
import urllib.request
import urllib.parse
import sys
import subprocess
import tempfile
import shutil
import textwrap
import mimetypes
import difflib
import shlex
import zlib
import threading
from datetime import datetime, timezone
from functools import wraps
try:
    from pypdf import PdfReader as _PdfReader
    _PDF_READ_SUPPORTED = True
except ImportError:
    try:
        from PyPDF2 import PdfReader as _PdfReader
        _PDF_READ_SUPPORTED = True
    except ImportError:
        _PDF_READ_SUPPORTED = False
try:
    import fitz as _fitz           
    _FITZ_SUPPORTED = True
except ImportError:
    _FITZ_SUPPORTED = False
try:
    import pdfplumber as _pdfplumber
    _PDFPLUMBER_SUPPORTED = True
except ImportError:
    _PDFPLUMBER_SUPPORTED = False
try:
    from fpdf import FPDF as _FPDF
    _PDF_WRITE_SUPPORTED = True
except ImportError:
    _PDF_WRITE_SUPPORTED = False
from flask import Flask, request, Response, jsonify, stream_with_context
from flask_cors import CORS
try:
    from supabase import create_client as _supabase_create
    _supabase_sdk = True
except ImportError:
    _supabase_sdk = False
app = Flask(__name__)
PRATHAM_AGENT_SHARED_SECRET = os.environ.get("PRATHAM_AGENT_SHARED_SECRET", "").strip()
PRATHAM_AI_MODE = os.environ.get("PRATHAM_AI_MODE", "google_oauth").strip().lower()
PRATHAM_AGENT_ONLY = PRATHAM_AI_MODE == "agent"
PRATHAM_AGENT_STALE_CLAIM_SECONDS = int(os.environ.get("PRATHAM_AGENT_STALE_CLAIM_SECONDS", "300"))
_PRATHAM_AGENT_JOBS = {}
_PRATHAM_AGENT_LOCK = threading.RLock()
def _agent_authorized():
    if not PRATHAM_AGENT_SHARED_SECRET:
        return False
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    supplied = auth[7:].strip()
    return bool(supplied) and hmac.compare_digest(supplied, PRATHAM_AGENT_SHARED_SECRET)
def _agent_job_public(job):
    return {
        "jobId": job["jobId"],
        "conversationId": job["conversationId"],
        "userId": job["userId"],
        "message": job["message"],
        "conversationHistory": job.get("conversationHistory", []),
        "attachments": job.get("attachments", []),
        "referenceImageMediaIds": job.get("referenceImageMediaIds", []),
        "createdAt": job["createdAt"],
        "status": job["status"],
    }
def _agent_event(job, payload):
    event = dict(payload or {})
    event.setdefault("jobId", job["jobId"])
    event.setdefault("conversationId", job["conversationId"])
    event.setdefault("status", job["status"])
    job.setdefault("events", []).append(event)
    job["event_queue"].append(event)
    job["event_condition"].notify_all()
def _agent_create_job(user_id, user_email, conv_id, message, history, attachments, refs):
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _PRATHAM_AGENT_LOCK:
        q = __import__("collections").deque()
        job = {
            "jobId": job_id,
            "conversationId": conv_id,
            "userId": user_id,
            "userEmail": user_email,
            "message": message,
            "conversationHistory": history[-10:],
            "attachments": attachments or [],
            "referenceImageMediaIds": refs or [],
            "createdAt": now,
            "claimedAt": None,
            "completedAt": None,
            "status": "QUEUED",
            "result": None,
            "event_queue": q,
            "events": [],
        }
        job["event_condition"] = threading.Condition(_PRATHAM_AGENT_LOCK)
        _PRATHAM_AGENT_JOBS[job_id] = job
        _agent_event(job, {"type": "metadata", "status": "QUEUED", "message": "Queued for Pratham Universal Agent."})
    return job
@app.route("/api/agent/jobs/pending", methods=["GET", "OPTIONS"])
@app.route("/api/app/agent/jobs/pending", methods=["GET", "OPTIONS"])
def agent_jobs_pending():
    if request.method == "OPTIONS":
        return _cors_preflight()
    if not _agent_authorized():
        return jsonify({"error": "Agent authentication failed."}), 401
    now = time.time()
    jobs = []
    with _PRATHAM_AGENT_LOCK:
        for job in _PRATHAM_AGENT_JOBS.values():
            if job["status"] == "CLAIMED" and job.get("claimedAt"):
                try:
                    stale = now - datetime.fromisoformat(job["claimedAt"].replace("Z", "+00:00")).timestamp()
                except Exception:
                    stale = 0
                if stale > PRATHAM_AGENT_STALE_CLAIM_SECONDS:
                    job["status"] = "QUEUED"
                    job["claimedAt"] = None
            if job["status"] == "QUEUED":
                job["status"] = "CLAIMED"
                job["claimedAt"] = datetime.now(timezone.utc).isoformat()
                _agent_event(job, {"type": "progress", "status": "CLAIMED", "message": "Universal Agent claimed the job."})
                jobs.append(_agent_job_public(job))
                if len(jobs) >= 10:
                    break
    return jsonify({"ok": True, "jobs": jobs})
@app.route("/api/agent/jobs/<job_id>/events", methods=["POST", "OPTIONS"])
@app.route("/api/app/agent/jobs/<job_id>/events", methods=["POST", "OPTIONS"])
def agent_job_event_callback(job_id):
    if request.method == "OPTIONS":
        return _cors_preflight()
    if not _agent_authorized():
        return jsonify({"error": "Agent authentication failed."}), 401
    body = request.get_json(silent=True) or {}
    with _PRATHAM_AGENT_LOCK:
        job = _PRATHAM_AGENT_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job."}), 404
        status = str(body.get("status") or body.get("type") or "PROCESSING").upper()
        message = body.get("message") or body.get("question") or ""
        job["status"] = status
        _agent_event(job, {
            "type": body.get("type", "progress"),
            "status": status,
            "message": message,
            "question": body.get("question"),
        })
        terminal = status in {"COMPLETED", "FAILED", "CANCELLED", "WAITING_FOR_USER"}
        if terminal and status != "WAITING_FOR_USER":
            result = body.get("result") or {}
            job["result"] = result
            if status == "COMPLETED":
                final_message = result.get("message") or body.get("message") or ""
                if final_message:
                    _append_message(job["conversationId"], "assistant", final_message)
                for image in result.get("images", []) or []:
                    url = image.get("url") if isinstance(image, dict) else None
                    if url:
                        _append_message(job["conversationId"], "assistant", f"![generated image]({url})")
            job["completedAt"] = datetime.now(timezone.utc).isoformat()
            _agent_event(job, {"type": "complete", "status": status, "result": result})
        elif status == "WAITING_FOR_USER":
            _agent_event(job, {"type": "clarification", "status": status, "question": body.get("question") or message})
    return jsonify({"ok": True, "jobId": job_id, "status": status})
_SITE_DOMAIN = os.environ.get("SITE_DOMAIN", "https://prathamai.vercel.app")
@app.route("/robots.txt")
def robots_txt():
    body = f"User-agent: *\nAllow: /\n\nSitemap: {_SITE_DOMAIN}/sitemap.xml\n"
    return Response(body, mimetype="text/plain")
@app.route("/sitemap.xml")
def sitemap_xml():
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'  <url><loc>{_SITE_DOMAIN}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n'
        '</urlset>\n'
    )
    return Response(body, mimetype="application/xml")
CORS(app, resources={
    r"/*": {
        "origins": [
            "https://prathamai.vercel.app",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5000",
            "http://127.0.0.1:5000",
            "*"
        ]
    }
}, supports_credentials=True)
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY", "").strip()
def _collect_groq_keys() -> list:
    keys = []
    primary = os.environ.get("GROQ_API_KEY", "").strip()
    if primary:
        keys.extend([k.strip() for k in primary.split(",") if k.strip()])
    for suffix in range(2, 11):                                     
        extra = os.environ.get(f"GROQ_API_KEY_{suffix}", "").strip()
        if extra:
            keys.append(extra)
    seen = set()
    unique_keys = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            unique_keys.append(k)
    return unique_keys
GROQ_API_KEYS = _collect_groq_keys()
OPENROUTER_API_KEY   = os.environ.get("OPENROUTER_API_KEY", "").strip()
CEREBRAS_API_KEY     = os.environ.get("CEREBRAS_API_KEY", "").strip()
MISTRAL_API_KEY      = os.environ.get("MISTRAL_API_KEY", "").strip()
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "https://ksroorygbrhwpnqtjbxo.supabase.co").strip()
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
GITHUB_TOKEN         = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO          = os.environ.get("GITHUB_REPO", "pratham31sinha-boop/PrathamAI").strip()
VIP_SECRET_CODE      = os.environ.get("VIP_SECRET_CODE", "31082011").strip()
SESSION_SECRET       = os.environ.get("SESSION_SECRET", "pratham-ai-dev-secret-change-me").strip()
SESSION_TOKEN_TTL_DAYS = int(os.environ.get("SESSION_TOKEN_TTL_DAYS", "30"))
ALLOW_INSECURE_DEV_AUTH = os.environ.get("ALLOW_INSECURE_DEV_AUTH", "0").strip().lower() in {"1", "true", "yes", "on"}
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "352716901368-sp0550kmd9jb9ob4b5adrq6npltq4jht.apps.googleusercontent.com").strip()
GOOGLE_GEMINI_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_GEMINI_OAUTH_CLIENT_ID", GOOGLE_OAUTH_CLIENT_ID).strip()
GOOGLE_CLOUD_PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT_ID", "").strip()
GEMINI_CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-3.8-flash").strip()
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image").strip()
GEMINI_OAUTH_SCOPES = os.environ.get("GEMINI_OAUTH_SCOPES", "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/generative-language.retriever").strip()
GEMINI_ACCESS_TOKEN_HEADER = "X-Gemini-Access-Token"
QWEN_WORKER_URL       = os.environ.get("QWEN_WORKER_URL", "").strip().rstrip("/")
PRATHAM_WORKER_TOKEN  = os.environ.get("PRATHAM_WORKER_TOKEN", "").strip()
WORKER_ONLINE_TIMEOUT_SECONDS = int(os.environ.get("WORKER_ONLINE_TIMEOUT_SECONDS", "360"))
WORKER_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("WORKER_REQUEST_TIMEOUT_SECONDS", "120"))
QWEN_WORKER_SIMPLE_CONTEXT_TOKENS = int(os.environ.get("QWEN_WORKER_SIMPLE_CONTEXT_TOKENS", "1024"))
QWEN_WORKER_CODE_CONTEXT_TOKENS = int(os.environ.get("QWEN_WORKER_CODE_CONTEXT_TOKENS", "4096"))
QWEN_WORKER_SIMPLE_MAX_NEW_TOKENS = int(os.environ.get("QWEN_WORKER_SIMPLE_MAX_NEW_TOKENS", "256"))
QWEN_WORKER_CODE_MAX_NEW_TOKENS = int(os.environ.get("QWEN_WORKER_CODE_MAX_NEW_TOKENS", "1536"))
QWEN_WORKER_SIMPLE_SYSTEM_CHARS = int(os.environ.get("QWEN_WORKER_SIMPLE_SYSTEM_CHARS", "1100"))
QWEN_WORKER_CODE_SYSTEM_CHARS = int(os.environ.get("QWEN_WORKER_CODE_SYSTEM_CHARS", "2200"))
QWEN_WORKER_SIMPLE_HISTORY_MESSAGES = int(os.environ.get("QWEN_WORKER_SIMPLE_HISTORY_MESSAGES", "2"))
QWEN_WORKER_CODE_HISTORY_MESSAGES = int(os.environ.get("QWEN_WORKER_CODE_HISTORY_MESSAGES", "6"))
QWEN_WORKER_SIMPLE_MAX_CHARS = int(os.environ.get("QWEN_WORKER_SIMPLE_MAX_CHARS", "3200"))
QWEN_WORKER_CODE_MAX_CHARS = int(os.environ.get("QWEN_WORKER_CODE_MAX_CHARS", "12000"))
QWEN_WORKER_RECENT_MESSAGE_CHAR_LIMIT = int(os.environ.get("QWEN_WORKER_RECENT_MESSAGE_CHAR_LIMIT", "2600"))
QWEN_WORKER_SPECIAL_CONTEXT_CHAR_LIMIT = int(os.environ.get("QWEN_WORKER_SPECIAL_CONTEXT_CHAR_LIMIT", "2200"))
QWEN_WORKER_LOOKUP_CACHE_SECONDS = int(os.environ.get("QWEN_WORKER_LOOKUP_CACHE_SECONDS", "360"))
_worker_registry: dict = {}
_worker_registry_lock = threading.Lock()
_WORKER_REGISTRY_GH_PATH = "data/worker_registry.json"
_worker_gh_cache = {"data": None, "t": 0}
_WORKER_GH_CACHE_TTL = 15           
def _github_repo_slug() -> str:
    return GITHUB_REPO.replace("https://github.com/", "").strip("/")
def _load_worker_from_github() -> dict:
    now_ts = time.time()
    if _worker_gh_cache["data"] and (now_ts - _worker_gh_cache["t"]) < _WORKER_GH_CACHE_TTL:
        return _worker_gh_cache["data"]
    if not GITHUB_TOKEN:
        return None
    repo_clean = _github_repo_slug()
    url = f"https://api.github.com/repos/{repo_clean}/contents/{_WORKER_REGISTRY_GH_PATH}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            meta = json.loads(resp.read().decode('utf-8'))
            if meta.get("content"):
                raw = base64.b64decode(meta["content"].replace("\n", "")).decode('utf-8')
                data = json.loads(raw)
                _worker_gh_cache["data"] = data
                _worker_gh_cache["t"] = now_ts
                return data
    except Exception:
        pass
    return None
def _save_worker_to_github(entry: dict) -> bool:
    if not GITHUB_TOKEN:
        return False
    cached = _worker_gh_cache.get("data")
    if cached and cached.get("endpoint_url") == entry.get("endpoint_url") and (time.time() - _worker_gh_cache.get("t", 0)) < 600:
        return True
    repo_clean = _github_repo_slug()
    url = f"https://api.github.com/repos/{repo_clean}/contents/{_WORKER_REGISTRY_GH_PATH}"
    sha = None
    try:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            meta = json.loads(resp.read().decode('utf-8'))
            sha = meta.get("sha")
    except Exception:
        pass
    content_str = json.dumps(entry, indent=2)
    b64 = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
    packet = {
        "message": f"Pratham AI worker registry: {entry.get('worker_id')} -> {entry.get('endpoint_url')}",
        "content": b64
    }
    if sha:
        packet["sha"] = sha
    req_put = urllib.request.Request(
        url,
        data=json.dumps(packet).encode('utf-8'),
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3+json"
        },
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req_put, timeout=8) as resp:
            ok = resp.status in (200, 201)
            if ok:
                _worker_gh_cache["data"] = dict(entry)
                _worker_gh_cache["t"] = time.time()
                print(f"[WORKER][GITHUB] Persisted worker '{entry.get('worker_id')}' endpoint={entry.get('endpoint_url')}")
            return ok
    except Exception as exc:
        print(f"[WORKER][GITHUB] Persist error: {exc}")
        return False
def _worker_upsert(entry: dict):
    with _worker_registry_lock:
        _worker_registry[entry["worker_id"]] = entry
    try:
        with open("/tmp/worker_registry.json", "w", encoding="utf-8") as tf:
            json.dump(entry, tf)
    except Exception:
        pass
    if SUPABASE_CONFIGURED:
        try:
            row = dict(entry)
            row["last_seen_epoch"] = row["last_seen_epoch"]
            _supabase.table("workers").upsert(row, on_conflict="worker_id").execute()
            print(f"[WORKER][SUPABASE] Upserted worker '{entry['worker_id']}' endpoint={entry.get('endpoint_url')}")
        except Exception as exc:
            print(f"[WORKER][SUPABASE] upsert failed (falling back to durable storage): {exc}")
    if GITHUB_TOKEN:
        try:
            _save_worker_to_github(entry)
        except Exception as exc:
            print(f"[WORKER][GITHUB] persist error: {exc}")
def _worker_touch_latency(worker_id: str, latency_ms: int):
    """Update local latency telemetry without a GitHub/Supabase write."""
    if not worker_id or worker_id == "static-worker":
        return
    try:
        with _worker_registry_lock:
            entry = _worker_registry.get(worker_id)
            if entry is not None:
                entry["latency_ms"] = int(latency_ms)
    except Exception:
        pass
def _worker_get_latest() -> dict:
    now = time.time()
    with _worker_registry_lock:
        entries = list(_worker_registry.values())
    if entries:
        candidate = max(entries, key=lambda e: e.get("last_seen_epoch", 0))
        if (now - candidate.get("last_seen_epoch", 0)) <= max(45, QWEN_WORKER_LOOKUP_CACHE_SECONDS):
            return candidate
    try:
        if os.path.exists("/tmp/worker_registry.json"):
            with open("/tmp/worker_registry.json", "r", encoding="utf-8") as tf:
                disk_entry = json.load(tf)
                if disk_entry and (now - disk_entry.get("last_seen_epoch", 0)) <= WORKER_ONLINE_TIMEOUT_SECONDS:
                    with _worker_registry_lock:
                        _worker_registry[disk_entry["worker_id"]] = disk_entry
                    return disk_entry
    except Exception:
        pass
    if SUPABASE_CONFIGURED:
        try:
            r = (_supabase.table("workers").select("*")
                 .order("last_seen_epoch", desc=True).limit(1).execute())
            if r.data:
                worker_row = r.data[0]
                with _worker_registry_lock:
                    _worker_registry[worker_row["worker_id"]] = worker_row
                return worker_row
        except Exception as exc:
            print(f"[WORKER][SUPABASE] read failed: {exc}")
    if GITHUB_TOKEN:
        try:
            gh_worker = _load_worker_from_github()
            if gh_worker:
                with _worker_registry_lock:
                    _worker_registry[gh_worker["worker_id"]] = gh_worker
                return gh_worker
        except Exception as exc:
            print(f"[WORKER][GITHUB] read failed: {exc}")
    if entries:
        return max(entries, key=lambda e: e.get("last_seen_epoch", 0))
    static_url = os.environ.get("QWEN_WORKER_URL", QWEN_WORKER_URL or "").strip().rstrip("/")
    if static_url:
        return {
            "worker_id": "static-worker",
            "endpoint_url": static_url,
            "status": "online",
            "model": "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
            "gpu": "Tesla T4",
            "vram_gb": 14.56,
            "last_seen_epoch": time.time(),
        }
    return None
print("[STARTUP] AI mode=%s | Gemini OAuth=%s | Cloud project=%s | chat=%s | image=%s | insecure-dev-auth=%s" % (
    PRATHAM_AI_MODE, "configured" if GOOGLE_GEMINI_OAUTH_CLIENT_ID else "missing",
    "configured" if GOOGLE_CLOUD_PROJECT_ID else "MISSING", GEMINI_CHAT_MODEL, GEMINI_IMAGE_MODEL,
    ALLOW_INSECURE_DEV_AUTH
))
CREATOR_EMAILS = {"pratham31sinha@gmail.com", "pratham08sinha@gmail.com", "pratham310811@gmail.com"}
SUPABASE_CONFIGURED = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY and _supabase_sdk)
_supabase = None
if SUPABASE_CONFIGURED:
    try:
        _supabase = _supabase_create(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        print(f"[INIT] Persistent layer connected: {SUPABASE_URL}")
    except Exception:
        SUPABASE_CONFIGURED = False
_mem_convos: dict = {}
_gh_sha_cache: dict = {}
_GH_CACHE_TTL = 8           
def _github_repo_slug() -> str:
    return GITHUB_REPO.replace("https://github.com/", "").strip("/")
def _write_to_github_repository(target_file_path: str, contents_payload: str) -> bool:
    """
    Appends `contents_payload` to `target_file_path` inside the configured
    GitHub repository. Creates the file (and implicitly the folder path,
    since GitHub's contents API creates intermediate folders automatically)
    if it does not already exist.
    IMPORTANT FIX (this was the cause of "saving replaces old content
    instead of appending"): GitHub's Contents API only inlines the file's
    `content` field for files under ~1MB. Once a growing file like
    data/public_data.txt crosses that size, the API keeps returning a valid
    `sha` but a null/empty `content` field — the old code treated that as
    "existing content is empty" and PUT the file with ONLY the new entry,
    silently wiping everything previously saved. Now, whenever `content` is
    missing/empty but the file's reported `size` is greater than 0 (i.e. it
    genuinely has content GitHub just didn't inline), the real content is
    fetched via the item's own `download_url` instead, so appends are always
    appends — regardless of how large the file has grown.
    """
    if not GITHUB_TOKEN:
        return False
    repo_clean = _github_repo_slug()
    encoded_target_path = "/".join(urllib.parse.quote(segment, safe="") for segment in target_file_path.split("/") if segment)
    endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{encoded_target_path}"
    sha_reference_token = None
    existing_content = ""
    cache_hit = _gh_sha_cache.get(target_file_path)
    now_ts = time.time()
    if cache_hit and (now_ts - cache_hit["t"]) < _GH_CACHE_TTL:
        sha_reference_token = cache_hit["sha"]
        existing_content = cache_hit["content"]
    else:
        req_lookup = urllib.request.Request(
            endpoint_target_url,
            headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        )
        try:
            with urllib.request.urlopen(req_lookup, timeout=10) as lookup_response:
                meta_data = json.loads(lookup_response.read().decode('utf-8'))
                sha_reference_token = meta_data.get("sha")
                if meta_data.get("content"):
                    existing_content = base64.b64decode(meta_data["content"].replace("\n", "")).decode('utf-8')
                elif meta_data.get("size", 0) > 0 and meta_data.get("download_url"):
                    try:
                        raw_req = urllib.request.Request(
                            meta_data["download_url"],
                            headers={"Authorization": f"token {GITHUB_TOKEN}"}
                        )
                        with urllib.request.urlopen(raw_req, timeout=20) as raw_resp:
                            existing_content = raw_resp.read().decode('utf-8', errors='replace')
                    except Exception as raw_exc:
                        print(f"[GITHUB][LARGE-FILE FETCH FAULT] {target_file_path}: {raw_exc}")
                        return False
        except Exception:
            pass
    compiled_body_string = existing_content + contents_payload
    encoded_binary_bytes = base64.b64encode(compiled_body_string.encode('utf-8')).decode('utf-8')
    mutation_packet = {
        "message": f"Pratham AI sync: {target_file_path}",
        "content": encoded_binary_bytes
    }
    if sha_reference_token:
        mutation_packet["sha"] = sha_reference_token
    request_dispatcher = urllib.request.Request(
        endpoint_target_url,
        data=json.dumps(mutation_packet).encode('utf-8'),
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3+json"
        },
        method="PUT"
    )
    try:
        with urllib.request.urlopen(request_dispatcher, timeout=15) as operation_result:
            ok = operation_result.status in [200, 201]
            if ok:
                try:
                    result_body = json.loads(operation_result.read().decode('utf-8'))
                    new_sha = result_body.get("content", {}).get("sha")
                    _gh_sha_cache[target_file_path] = {
                        "sha": new_sha, "content": compiled_body_string, "t": time.time()
                    }
                except Exception:
                    _gh_sha_cache.pop(target_file_path, None)
            return ok
    except Exception as exc:
        print(f"[GITHUB][FAULT] {exc}")
        return False
_vip_cache = {"entries": {}, "t": 0}
_VIP_CACHE_TTL = 30                                                      
def _fetch_vip_directory() -> dict:
    now_ts = time.time()
    if _vip_cache["entries"] and (now_ts - _vip_cache["t"]) < _VIP_CACHE_TTL:
        return _vip_cache["entries"]
    entries = {}
    if not GITHUB_TOKEN:
        return entries
    repo_clean = _github_repo_slug()
    endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/data/vip.txt"
    req_lookup = urllib.request.Request(
        endpoint_target_url,
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    )
    try:
        with urllib.request.urlopen(req_lookup, timeout=10) as lookup_response:
            meta_data = json.loads(lookup_response.read().decode('utf-8'))
            if meta_data.get("content"):
                raw_text = base64.b64decode(meta_data["content"].replace("\n", "")).decode('utf-8')
                for row in raw_text.splitlines():
                    row = row.strip()
                    if not row or "Email:" not in row:
                        continue
                    parts = {}
                    for chunk in row.split(" | "):
                        if ":" in chunk:
                            key, _, val = chunk.partition(":")
                            parts[key.strip().lower()] = val.strip()
                    email = parts.get("email", "").lower()
                    if email:
                        entries[email] = {
                            "name": parts.get("name", ""),
                            "relationship": parts.get("relation", ""),
                            "timestamp": parts.get("timestamp", "")
                        }
    except Exception as exc:
        print(f"[VIP][FETCH FAULT] {exc}")
    _vip_cache["entries"] = entries
    _vip_cache["t"] = now_ts
    return entries
def _lookup_vip(email: str):
    if not email:
        return None
    return _fetch_vip_directory().get(email.lower())
_generated_files_store: dict = {}
_GENERATED_FILE_TTL = 3600          
_ZIP_INTENT_RE = re.compile(r"\bzip\b", re.IGNORECASE)
_PDF_INTENT_RE = re.compile(r"\bpdf\b", re.IGNORECASE)
def _is_export_intent(message: str, regex: "re.Pattern") -> bool:
    """
    Loose but practical intent check: true if the keyword ('zip'/'pdf')
    appears anywhere in the message, UNLESS the message is clearly a
    question about the format itself (contains '?') rather than a request
    to package the reply as a file. This intentionally matches phrasings
    like "zip it", "make it a zip", "as a pdf", "download this as zip",
    etc. — the earlier stricter pattern missed most of these.
    """
    if "?" in message:
        return False
    return bool(regex.search(message))
def _prune_generated_files():
    cutoff = time.time() - _GENERATED_FILE_TTL
    stale = [tok for tok, entry in _generated_files_store.items() if entry["t"] < cutoff]
    for tok in stale:
        _generated_files_store.pop(tok, None)
def _store_generated_file(data: bytes, filename: str, mimetype: str) -> str:
    _prune_generated_files()
    token = uuid.uuid4().hex
    _generated_files_store[token] = {"bytes": data, "filename": filename, "mimetype": mimetype, "t": time.time()}
    return token
_FINALDOC_RE = re.compile(r"```finaldoc\s*\n([\s\S]*?)```", re.IGNORECASE)
_EXPORT_FILLER_LINE_RE = re.compile(
    r"^\s*("
    r"i'?d be happy to.*|"
    r"here'?s a (brief |short )?(document|essay|write[- ]?up).*|"
    r"i hope this (document|essay|file) meets.*|"
    r"(the )?backend will (automatically )?(take care of|package|convert|create|build).*|"
    r"no need to run any commands.*|"
    r"you (can|will be able to) download.*|"
    r"your (pdf|zip|file) (file )?is (being generated|ready).*|"
    r"(as i mentioned( earlier)?,?\s*)?the (backend|system) will.*"
    r")\s*$",
    re.IGNORECASE
)
def _strip_export_filler(text: str) -> str:
    kept_lines = [ln for ln in text.split("\n") if not _EXPORT_FILLER_LINE_RE.match(ln)]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines))
    return cleaned.strip()
def _extract_export_content(assistant_text: str) -> str:
    """
    Returns the text that should actually go INTO an exported file (pdf/zip/
    any other extension). Prefers a dedicated ```finaldoc fenced block if the
    model provided one (per the system prompt, that block should contain
    ONLY the clean deliverable — no "I'd be happy to..." / "your file is
    ready!" chatter around it). If no such block exists, falls back to the
    full reply with filler lines stripped out via `_strip_export_filler`,
    rather than exporting the raw chat response (including its own
    commentary about the export) verbatim.
    """
    m = _FINALDOC_RE.search(assistant_text)
    if m:
        return _strip_export_filler(m.group(1).strip())
    return _strip_export_filler(assistant_text)
def _build_zip_from_response(assistant_text: str, workdir: str = None, deliverable_name: str = "content.txt") -> bytes:
    """
    Fix for the "zip contains the wrong content" bug: the clean deliverable
    (the ```finaldoc block, or the filler-stripped full reply — see
    `_extract_export_content`) is ALWAYS written into the zip under
    `deliverable_name` first, since that's the thing the person actually
    asked for. Any REAL files the background terminal created in `workdir`
    during this same request (via python/bash execution or a ```createfile:
    block) are added alongside as extras, not as a silent replacement — so a
    request like "write an essay, zip it" reliably gets the essay in the
    zip, even if unrelated scratch files exist in the terminal's workdir
    from something else the model did in the same turn.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        deliverable_text = _extract_export_content(assistant_text)
        zf.writestr(deliverable_name, deliverable_text)
        if workdir and os.path.isdir(workdir):
            for root, _dirs, files in os.walk(workdir):
                for fname in files:
                    full_path = os.path.join(root, fname)
                    arcname = os.path.relpath(full_path, workdir)
                    try:
                        zf.write(full_path, arcname)
                    except Exception:
                        continue
    buf.seek(0)
    return buf.read()
_PDF_UNICODE_SUBSTITUTIONS = {
    "∠": "angle ", "°": " deg", "∘": " deg", "√": "sqrt", "×": "x", "÷": "/",
    "≠": "!=", "≅": "~=", "≈": "~=", "≤": "<=", "≥": ">=", "⊥": "perp",
    "∥": "parallel", "→": "->", "⟹": "=>", "∴": "therefore", "∵": "because",
    "±": "+/-", "∆": "delta", "π": "pi", "θ": "theta", "α": "alpha", "β": "beta",
    "△": "triangle ", "∈": "in", "∞": "infinity", "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "•": "-", "​": "",
    "⁰": "^0", "¹": "^1", "²": "^2", "³": "^3", "⁴": "^4", "⁵": "^5",
    "⁶": "^6", "⁷": "^7", "⁸": "^8", "⁹": "^9", "⁺": "^+", "⁻": "^-",
    "₀": "_0", "₁": "_1", "₂": "_2", "₃": "_3", "₄": "_4", "₅": "_5",
    "₆": "_6", "₇": "_7", "₈": "_8", "₉": "_9",
    "…": "...", "→": "->", "←": "<-", "↑": "^", "↓": "v", "✓": "OK", "✗": "x",
    "€": "EUR", "£": "GBP", "₹": "Rs.", "™": "(TM)", "®": "(R)", "©": "(C)",
}
_PDF_UNICODE_RE = re.compile("|".join(re.escape(k) for k in _PDF_UNICODE_SUBSTITUTIONS))
def _sanitize_unicode_for_pdf(text: str) -> str:
    return _PDF_UNICODE_RE.sub(lambda m: _PDF_UNICODE_SUBSTITUTIONS[m.group(0)], text)
def _escape_pdf_literal_text(s: str) -> str:
    s = _sanitize_unicode_for_pdf(s)
    s = s.encode('latin-1', 'replace').decode('latin-1')
    return s.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')
def _markdownish_lines_for_pdf(text: str, max_width_chars: int):
    """
    Converts lightly-markdown-formatted text (# / ## / ### / #### headings,
    **bold** lines and inline bold, `* `/`- ` bullets, and `---` horizontal
    rules — the style the model actually writes) into a flat list of
    (font_key, size_delta, rendered_line) tuples ready to lay out on a page.
    This covers the common case seen in practice without needing a full
    markdown/HTML parser.
    """
    rendered = []
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            rendered.append(("F1", 0, ""))
            continue
        if re.match(r'^[-*_]{3,}$', stripped):
            continue
        md_heading_match = re.match(r'^(#{1,4})\s+(.*)$', stripped)
        if md_heading_match:
            level = len(md_heading_match.group(1))
            size_delta = max(4 - level, 1)                                                 
            heading_text = re.sub(r'\*\*(.+?)\*\*', r'\1', md_heading_match.group(2))
            rendered.append(("F2", size_delta, heading_text))
            continue
        heading_match = re.match(r'^\*\*(.+?)\*\*:?$', stripped)
        if heading_match:
            rendered.append(("F2", 2, heading_match.group(1)))
            continue
        bullet_match = re.match(r'^[\*\-]\s+(.+)$', stripped)
        if bullet_match:
            content = re.sub(r'\*\*(.+?)\*\*', r'\1', bullet_match.group(1))
            wrapped = textwrap.wrap(content, width=max(10, max_width_chars - 2)) or ['']
            for i, w in enumerate(wrapped):
                prefix = "- " if i == 0 else "  "
                rendered.append(("F1", 0, prefix + w))
            continue
        content = re.sub(r'\*\*(.+?)\*\*', r'\1', stripped)
        wrapped = textwrap.wrap(content, width=max_width_chars) or ['']
        for w in wrapped:
            rendered.append(("F1", 0, w))
    return rendered or [("F1", 0, "")]
_DIAGRAM_MARKER_RE = re.compile(r"\[DIAGRAM:\s*([^\]\n]+?)\s*\]")
def _extract_diagram_files(assistant_text: str) -> dict:
    """Finds every ```createfile:<name>.html block in the response whose
    content actually contains an <svg> element, and returns {filename: svg_markup}.
    These are the diagrams the model draws for geometry/construction questions
    (see the GEOMETRY/DIAGRAMS system prompt rule) — this lets the PDF
    exporter pull the real diagram back out and embed it as an image,
    instead of the PDF only ever containing text."""
    diagrams = {}
    for filename, content in _extract_createfile_blocks(assistant_text):
        if "<svg" in content.lower():
            diagrams[filename] = content
    return diagrams
def _rasterize_svg_to_rgb(svg_text: str, target_width_px: int = 900):
    """Renders an SVG string to a flat RGB pixel buffer using PyMuPDF (the
    same optional dependency already used for PDF text extraction — see
    _FITZ_SUPPORTED). Returns (width, height, raw_rgb_bytes) or None if
    PyMuPDF isn't installed or the SVG fails to parse. No PIL/Pillow needed:
    fitz.Pixmap already exposes raw, uncompressed RGB samples directly."""
    if not _FITZ_SUPPORTED:
        return None
    try:
        doc = _fitz.open(stream=svg_text.encode("utf-8"), filetype="svg")
        page = doc[0]
        zoom = target_width_px / max(page.rect.width, 1)
        matrix = _fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.width, pix.height, bytes(pix.samples)
    except Exception as exc:
        print(f"[PDF][DIAGRAM RASTERIZE FAULT] {exc}")
        return None
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^\s\)]+)\)")
def _fetch_and_rasterize_remote_image(url: str, target_width_px: int = 900, timeout: int = 20):
    """Downloads a remote raster image referenced as ![...](url) in the
    assistant's reply and returns
    (width, height, raw_rgb_bytes) for PDF embedding — same shape as
    _rasterize_svg_to_rgb. Requires Pillow; returns None (and the PDF export
    simply skips that image, same as an unresolved diagram marker) if
    Pillow isn't installed or the fetch/decode fails for any reason."""
    try:
        from PIL import Image as _PILImage
    except ImportError:
        print("[PDF][REMOTE IMAGE] Pillow not installed — cannot embed remote images in PDF export.")
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PrathamAI PDF export)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
        img = _PILImage.open(io.BytesIO(raw_bytes)).convert("RGB")
        if img.width > target_width_px:
            ratio = target_width_px / img.width
            img = img.resize((target_width_px, max(1, int(img.height * ratio))))
        return img.width, img.height, img.tobytes()
    except Exception as exc:
        print(f"[PDF][REMOTE IMAGE FETCH FAULT] {url} -> {exc}")
        return None
def _build_pdf_content_items(text: str, diagram_files: dict, max_width_chars: int):
    """Splits `text` on [DIAGRAM: filename] markers (the convention the
    system prompt tells the model to use for construction/geometry
    questions) into an ordered list of items:
      {"type": "line", "font": "F1"/"F2", "size_delta": int, "text": str}
      {"type": "image", "width": int, "height": int, "rgb": bytes}
    laid out in the same order they appear in the model's answer — so a
    circumcircle diagram for question 38 lands right after question 38's
    text, not dumped at the end of the document. A marker whose filename
    doesn't match any real diagram the model created (typo, or the diagram
    generation failed) is simply skipped — the surrounding text still gets
    exported, just without that one image, rather than crashing the whole
    export."""
    embed_points = []
    for m in _DIAGRAM_MARKER_RE.finditer(text):
        embed_points.append(("diagram", m.start(), m.end(), m.group(1).strip()))
    for m in _MARKDOWN_IMAGE_RE.finditer(text):
        embed_points.append(("remote_image", m.start(), m.end(), m.group(1).strip()))
    embed_points.sort(key=lambda p: p[1])
    items = []
    last_end = 0
    for kind, start, end, value in embed_points:
        if start < last_end:
            continue                                                        
        chunk = text[last_end:start]
        if chunk.strip():
            items.extend(_markdownish_lines_for_pdf(chunk, max_width_chars))
        if kind == "diagram":
            filename = value
            svg_markup = diagram_files.get(filename)
            if svg_markup:
                rasterized = _rasterize_svg_to_rgb(svg_markup)
                if rasterized:
                    width, height, rgb = rasterized
                    items.append({"type": "image", "width": width, "height": height, "rgb": rgb})
                else:
                    items.append(("F1", 0, f"[Diagram '{filename}' could not be rendered for this PDF export.]"))
            else:
                print(f"[PDF][DIAGRAM] marker referenced '{filename}' but no matching createfile diagram was found in this response.")
        else:                                                      
            rasterized = _fetch_and_rasterize_remote_image(value)
            if rasterized:
                width, height, rgb = rasterized
                items.append({"type": "image", "width": width, "height": height, "rgb": rgb})
            else:
                items.append(("F1", 0, "[Generated image could not be embedded in this PDF export.]"))
        last_end = end
    tail = text[last_end:]
    if tail.strip():
        items.extend(_markdownish_lines_for_pdf(tail, max_width_chars))
    return items or [("F1", 0, "")]
def _write_pdf_with_diagrams(text: str, diagram_files: dict) -> bytes:
    """Same PDF writer as _write_minimal_pdf (stdlib-only, hand-written PDF
    object table), extended to also embed real raster images at
    [DIAGRAM: filename] marker points — this is what actually gets a
    circumcircle/construction diagram INTO the downloaded PDF, not just
    shown in the chat interface. Falls back to plain _write_minimal_pdf
    automatically (via the caller) when there's nothing to embed."""
    base_font_size = 11
    leading = 15
    margin_left = 50
    margin_right = 50
    page_width, page_height = 612, 792                      
    margin_top_y = page_height - 50
    margin_bottom_y = 50
    max_width_chars = 92
    content_width_pts = page_width - margin_left - margin_right
    max_image_height_pts = 380                                              
    content_items = _build_pdf_content_items(text, diagram_files, max_width_chars)
    objects = {}
    next_obj_num = [1]
    def alloc():
        n = next_obj_num[0]; next_obj_num[0] += 1; return n
    catalog_num = alloc()
    pages_num = alloc()
    font_regular_num = alloc()
    font_bold_num = alloc()
    pages = []                                                                   
    cur_page = {"lines": [], "images": []}
    cur_y = margin_top_y
    image_counter = 0
    def start_new_page():
        nonlocal cur_page, cur_y
        pages.append(cur_page)
        cur_page = {"lines": [], "images": []}
        cur_y = margin_top_y
    for item in content_items:
        if isinstance(item, dict) and item.get("type") == "image":
            nat_w, nat_h = item["width"], item["height"]
            max_disp_w = min(content_width_pts, 320)                           
            disp_w = max_disp_w
            disp_h = disp_w * (nat_h / max(nat_w, 1))
            if disp_h > max_image_height_pts:
                disp_h = max_image_height_pts
                disp_w = disp_h * (nat_w / max(nat_h, 1))
            if (cur_y - disp_h) < margin_bottom_y:
                start_new_page()
            image_counter += 1
            img_name = f"Im{image_counter}"
            img_obj_num = alloc()
            objects[img_obj_num] = {"__image__": True, "width": nat_w, "height": nat_h, "rgb": item["rgb"]}
            place_y = cur_y - disp_h
            place_x = margin_left + (content_width_pts - disp_w) / 2                         
            cur_page["images"].append((img_name, img_obj_num, place_x, place_y, disp_w, disp_h))
            cur_y -= (disp_h + 12)                               
        else:
            font_key, size_delta, line_text = item
            if (cur_y - leading) < margin_bottom_y:
                start_new_page()
            cur_page["lines"].append((cur_y, font_key, size_delta, line_text))
            cur_y -= leading
    pages.append(cur_page)
    pages = [p for p in pages if p["lines"] or p["images"]] or [{"lines": [(margin_top_y, "F1", 0, "")], "images": []}]
    page_nums, content_nums = [], []
    for _ in pages:
        page_nums.append(alloc())
        content_nums.append(alloc())
    content_bodies = []
    for page in pages:
        stream_parts = []
        runs = []
        current_run = []
        prev_y = None
        for y, font_key, size_delta, line_text in page["lines"]:
            if prev_y is not None and abs(prev_y - y - leading) > 0.01:
                runs.append(current_run)
                current_run = []
            current_run.append((y, font_key, size_delta, line_text))
            prev_y = y
        if current_run:
            runs.append(current_run)
        for run in runs:
            stream_parts.append("BT")
            stream_parts.append(f"{leading} TL")
            stream_parts.append(f"{margin_left} {run[0][0]} Td")
            first = True
            for _y, font_key, size_delta, line_text in run:
                size = base_font_size + size_delta
                font_ref = "/F2" if font_key == "F2" else "/F1"
                stream_parts.append(f"{font_ref} {size} Tf")
                if not first:
                    stream_parts.append("T*")
                escaped = _escape_pdf_literal_text(line_text)
                stream_parts.append(f"({escaped}) Tj")
                first = False
            stream_parts.append("ET")
        for img_name, _obj_num, x, y, w, h in page["images"]:
            stream_parts.append(f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {y:.2f} cm /{img_name} Do Q")
        content_bodies.append("\n".join(stream_parts))
    objects[catalog_num] = f"<< /Type /Catalog /Pages {pages_num} 0 R >>"
    kids_refs = " ".join(f"{n} 0 R" for n in page_nums)
    objects[pages_num] = f"<< /Type /Pages /Kids [{kids_refs}] /Count {len(page_nums)} >>"
    objects[font_regular_num] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[font_bold_num] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
    for i, page_num in enumerate(page_nums):
        content_num = content_nums[i]
        page = pages[i]
        xobject_entries = " ".join(f"/{name} {obj_num} 0 R" for name, obj_num, *_ in page["images"])
        resources = f"/Font << /F1 {font_regular_num} 0 R /F2 {font_bold_num} 0 R >>"
        if xobject_entries:
            resources += f" /XObject << {xobject_entries} >>"
        objects[page_num] = (
            f"<< /Type /Page /Parent {pages_num} 0 R /Resources << {resources} >> "
            f"/MediaBox [0 0 {page_width} {page_height}] /Contents {content_num} 0 R >>"
        )
        body = content_bodies[i]
        objects[content_num] = f"<< /Length {len(body.encode('latin-1', 'replace'))} >>\nstream\n{body}\nendstream"
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objects.keys()):
        offsets[num] = buf.tell()
        obj = objects[num]
        if isinstance(obj, dict) and obj.get("__image__"):
            raw_rgb = obj["rgb"]
            compressed = zlib.compress(raw_rgb, level=6)
            buf.write(f"{num} 0 obj\n".encode('latin-1'))
            buf.write((
                f"<< /Type /XObject /Subtype /Image /Width {obj['width']} /Height {obj['height']} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(compressed)} >>\n"
            ).encode('latin-1'))
            buf.write(b"stream\n")
            buf.write(compressed)
            buf.write(b"\nendstream\nendobj\n")
        else:
            buf.write(f"{num} 0 obj\n".encode('latin-1'))
            buf.write(obj.encode('latin-1', 'replace'))
            buf.write(b"\nendobj\n")
    xref_offset = buf.tell()
    total_objs = next_obj_num[0]
    buf.write(f"xref\n0 {total_objs}\n".encode('latin-1'))
    buf.write(b"0000000000 65535 f \n")
    for num in range(1, total_objs):
        buf.write(f"{offsets.get(num, 0):010d} 00000 n \n".encode('latin-1'))
    buf.write(b"trailer\n")
    buf.write(f"<< /Size {total_objs} /Root {catalog_num} 0 R >>\n".encode('latin-1'))
    buf.write(b"startxref\n")
    buf.write(f"{xref_offset}\n".encode('latin-1'))
    buf.write(b"%%EOF")
    return buf.getvalue()
def _write_minimal_pdf(text: str) -> bytes:
    """
    Builds a real, valid multi-page PDF directly from scratch using nothing
    but the standard library — no fpdf2, no reportlab, no external `pandoc`/
    `wkhtmltopdf` binary. Uses the standard 14 PDF base fonts (Helvetica /
    Helvetica-Bold), which every PDF viewer already has built in, so bold
    headings and bullet lists render properly without embedding any font
    file. Handles line-wrapping and pagination manually and writes the PDF's
    object table + xref + trailer by hand per the PDF 1.4 spec.
    """
    base_font_size = 11
    heading_font_size = 13
    leading = 15
    margin_left = 50
    margin_top = 792 - 50                                                        
    max_width_chars = 92
    lines_per_page = 55
    rendered_lines = _markdownish_lines_for_pdf(text, max_width_chars)
    pages = [rendered_lines[i:i + lines_per_page] for i in range(0, len(rendered_lines), lines_per_page)] or [[("F1", 0, "")]]
    objects = {}
    next_obj_num = [1]
    def alloc():
        n = next_obj_num[0]
        next_obj_num[0] += 1
        return n
    catalog_num = alloc()
    pages_num = alloc()
    font_regular_num = alloc()
    font_bold_num = alloc()
    page_nums, content_nums = [], []
    for _ in pages:
        page_nums.append(alloc())
        content_nums.append(alloc())
    content_bodies = []
    for page_lines in pages:
        stream_parts = [f"{leading} TL", f"{margin_left} {margin_top} Td"]
        first = True
        for font_key, size_delta, line in page_lines:
            size = base_font_size + size_delta
            font_ref = "/F2" if font_key == "F2" else "/F1"
            stream_parts.append(f"{font_ref} {size} Tf")
            if not first:
                stream_parts.append("T*")
            escaped = _escape_pdf_literal_text(line)
            stream_parts.append(f"({escaped}) Tj")
            first = False
        body = "BT\n" + "\n".join(stream_parts) + "\nET"
        content_bodies.append(body)
    objects[catalog_num] = f"<< /Type /Catalog /Pages {pages_num} 0 R >>"
    kids_refs = " ".join(f"{n} 0 R" for n in page_nums)
    objects[pages_num] = f"<< /Type /Pages /Kids [{kids_refs}] /Count {len(page_nums)} >>"
    objects[font_regular_num] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[font_bold_num] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
    for i, page_num in enumerate(page_nums):
        content_num = content_nums[i]
        objects[page_num] = (
            f"<< /Type /Page /Parent {pages_num} 0 R "
            f"/Resources << /Font << /F1 {font_regular_num} 0 R /F2 {font_bold_num} 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_num} 0 R >>"
        )
        body = content_bodies[i]
        objects[content_num] = f"<< /Length {len(body.encode('latin-1', 'replace'))} >>\nstream\n{body}\nendstream"
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objects.keys()):
        offsets[num] = buf.tell()
        buf.write(f"{num} 0 obj\n".encode('latin-1'))
        buf.write(objects[num].encode('latin-1', 'replace'))
        buf.write(b"\nendobj\n")
    xref_offset = buf.tell()
    total_objs = next_obj_num[0]
    buf.write(f"xref\n0 {total_objs}\n".encode('latin-1'))
    buf.write(b"0000000000 65535 f \n")
    for num in range(1, total_objs):
        buf.write(f"{offsets.get(num, 0):010d} 00000 n \n".encode('latin-1'))
    buf.write(b"trailer\n")
    buf.write(f"<< /Size {total_objs} /Root {catalog_num} 0 R >>\n".encode('latin-1'))
    buf.write(b"startxref\n")
    buf.write(f"{xref_offset}\n".encode('latin-1'))
    buf.write(b"%%EOF")
    return buf.getvalue()
def _build_pdf_from_response(assistant_text: str):
    """Returns (bytes, filename, mimetype). Always produces a real .pdf via
    the dependency-free writer above, using the clean extracted deliverable
    content (not the full chat reply with "I'd be happy to..." framing).
    If the response contains [DIAGRAM: filename] markers AND a matching
    ```createfile:filename.html SVG diagram (see the system prompt's
    GEOMETRY/DIAGRAMS rule — this is how construction/circumcircle-style
    questions get their figure drawn), the diagram-aware writer embeds the
    real rasterized diagram into the PDF at that exact point. Falls back to
    the plain text-only writer when there's nothing to embed, or if
    PyMuPDF (needed to rasterize the SVG) isn't installed."""
    try:
        clean_content = _extract_export_content(assistant_text)
        diagram_files = _extract_diagram_files(assistant_text) if _DIAGRAM_MARKER_RE.search(clean_content) else {}
        if diagram_files and _FITZ_SUPPORTED:
            pdf_bytes = _write_pdf_with_diagrams(clean_content, diagram_files)
        else:
            if _DIAGRAM_MARKER_RE.search(clean_content) and not _FITZ_SUPPORTED:
                print("[PDF][DIAGRAM] response references diagram markers but PyMuPDF isn't installed "
                      "on the server — add 'PyMuPDF' to requirements.txt to enable diagram embedding in PDFs.")
            pdf_bytes = _write_minimal_pdf(clean_content)
        return pdf_bytes, "generated.pdf", "application/pdf"
    except Exception as exc:
        print(f"[PDF][BUILD FAULT] {exc}")
        return assistant_text.encode("utf-8"), "generated.txt", "text/plain"
_GENERIC_EXTENSION_RE = re.compile(
    r"\b(?:as\s+an?|make\s+(?:it|this)\s+an?|download\s+(?:as|this\s+as)|export\s+(?:as|to)|"
    r"convert\s+(?:this\s+|it\s+)?to|save\s+(?:this\s+|it\s+)?as)\s+(?:an?\s+)?\.?([a-zA-Z0-9]{1,6})\b",
    re.IGNORECASE
)
_EXPLICIT_DOT_EXTENSION_RE = re.compile(r"\.([a-zA-Z][a-zA-Z0-9]{1,9})\b")
_HANDLED_EXTENSIONS = {"zip", "pdf"}                                               
_EXPORT_STOPWORDS = {
    "write", "make", "made", "create", "created", "generate", "generated", "give", "give me",
    "download", "convert", "save", "export", "please", "pls", "plz", "can", "you", "the",
    "a", "an", "this", "it", "into", "to", "as", "in", "on", "of", "for", "me", "and",
    "file", "files", "zip", "pdf", "format", "form", "output", "document", "doc", "now",
    "want", "need", "my", "with", "using", "having",
}
def _derive_export_basename(message: str, deliverable_text: str = "") -> str:
    """Best-effort topic slug for export filenames. Tries, in order:
    1. A short markdown heading (# Title / **Title**) at the top of the
       cleaned deliverable content, since the model is asked to lead with
       a clear title for exported documents.
    2. The user's own request message with command/format stopwords
       stripped out (so "write an essay on the french revolution as a pdf"
       becomes "essay-french-revolution").
    3. A generic "pratham_ai_output" fallback if neither yields anything
       usable.
    """
    if deliverable_text:
        first_lines = deliverable_text.strip().split("\n")[:3]
        for line in first_lines:
            stripped = line.strip().lstrip("#").strip()
            stripped = re.sub(r'^\*\*(.+?)\*\*$', r'\1', stripped).strip()
            if 3 <= len(stripped) <= 80 and not stripped.lower().startswith(("here", "sure", "okay", "i'd")):
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", stripped).strip("-").lower()
                if slug:
                    return slug[:60]
    words = re.findall(r"[a-zA-Z0-9]+", message.lower())
    meaningful = [w for w in words if w not in _EXPORT_STOPWORDS and len(w) > 1]
    if meaningful:
        slug = "-".join(meaningful[:8])
        if slug:
            return slug[:60]
    return "pratham_ai_output"
def _detect_generic_extension_intent(message: str):
    if "?" in message:
        return None
    m = _EXPLICIT_DOT_EXTENSION_RE.search(message)
    if not m:
        m = _GENERIC_EXTENSION_RE.search(message)
    if not m:
        return None
    ext = m.group(1).lower()
    if ext in _HANDLED_EXTENSIONS:
        return None
    return ext
_STOPWORDS = {"a","an","the","of","on","in","to","for","and","or","about","write","make","create",
              "please","me","my","this","that","as","zip","pdf","file","download","essay","report",
              "document","it","into","generate","draft","short","long","give"}
def _derive_export_filename(user_message: str, ext: str, fallback_content: str = "") -> str:
    """
    Builds a human-meaningful filename (e.g. "climate_change_essay.zip" instead
    of a generic "pratham_ai_output.zip") from the actual topic of the
    request. Strips common command/stopwords ("write", "essay", "as a zip",
    etc.) and keeps the meaningful nouns, falling back to the first line of
    the generated content, then to a generic name only as a last resort.
    """
    def slugify(words, max_words=6):
        cleaned = [w.lower() for w in words if w.lower() not in _STOPWORDS and len(w) > 1]
        cleaned = cleaned[:max_words]
        slug = "_".join(re.sub(r"[^a-zA-Z0-9]", "", w) for w in cleaned if re.sub(r"[^a-zA-Z0-9]", "", w))
        return slug
    words = re.findall(r"[a-zA-Z0-9']+", user_message)
    slug = slugify(words)
    if not slug and fallback_content:
        first_line = fallback_content.strip().split("\n", 1)[0]
        first_line = re.sub(r'^\*\*|\*\*$', '', first_line.strip())
        words = re.findall(r"[a-zA-Z0-9']+", first_line)
        slug = slugify(words)
    if not slug:
        slug = "pratham_ai_output"
    return f"{slug}.{ext}"
def _build_generic_file_from_response(assistant_text: str, ext: str, workdir: str = None):
    """Returns (bytes, filename, mimetype) for an arbitrary requested
    extension. Prefers a real file the terminal actually created in workdir
    matching that extension; otherwise packages the clean exported content
    as bytes with a best-guess mimetype."""
    if workdir and os.path.isdir(workdir):
        for root, _dirs, files in os.walk(workdir):
            for fname in files:
                if fname.lower().endswith("." + ext):
                    try:
                        with open(os.path.join(root, fname), "rb") as f:
                            data = f.read()
                        mimetype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
                        return data, fname, mimetype
                    except Exception:
                        continue
    content = _extract_export_content(assistant_text)
    mimetype = mimetypes.guess_type("generated." + ext)[0] or "application/octet-stream"
    return content.encode("utf-8", "replace"), f"generated.{ext}", mimetype
@app.route("/download/<token>", methods=["GET"])
@app.route("/api/download/<token>", methods=["GET"])
@app.route("/api/app/download/<token>", methods=["GET"])
def download_generated_file(token):
    entry = _generated_files_store.get(token)
    if not entry:
        return jsonify({"error": "This download has expired or does not exist."}), 404
    resp = Response(entry["bytes"], mimetype=entry["mimetype"])
    resp.headers["Content-Disposition"] = f'attachment; filename="{entry["filename"]}"'
    return resp
_education_cache = {"files": {}, "listing_t": 0}
_EDUCATION_LISTING_TTL = 120           
def _github_list_dir(path: str):
    """
    IMPORTANT FIX: folder/file names with spaces (e.g. "Social Science",
    "Chapter 1 Understanding Civilisation.pdf") were being inserted into the
    GitHub API URL completely raw. urllib does NOT auto-encode spaces (or
    other special characters) in a URL string, so a request like
    ".../contents/data/education/Social Science" was malformed and GitHub
    quietly returned nothing usable — which is exactly why book listing
    worked (folder names without spaces resolved fine) but chapter listing
    for "Social Science" came back empty even though the files were really
    there. Each path segment is now percent-encoded individually (keeping
    the "/" separators intact) before the request is made.
    """
    if not GITHUB_TOKEN:
        return []
    repo_clean = _github_repo_slug()
    encoded_path = "/".join(urllib.parse.quote(segment, safe="") for segment in path.split("/") if segment)
    endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{encoded_path}"
    req_lookup = urllib.request.Request(
        endpoint_target_url,
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    )
    try:
        with urllib.request.urlopen(req_lookup, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data if isinstance(data, list) else []
    except Exception as exc:
        print(f"[EDU][LIST FAULT] {exc}")
        return []
def _github_fetch_file_bytes(download_url: str):
    try:
        req = urllib.request.Request(download_url, headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except Exception as exc:
        print(f"[EDU][FETCH FAULT] {exc}")
        return None
def _extract_image_metadata(raw_bytes: bytes, ext: str) -> str:
    """
    Pure-stdlib image metadata extraction (no Pillow/vision model needed):
    reads the real file headers to report actual width/height/color info.
    This is real file data the AI can reason from ("this is a 1080x1920
    portrait PNG with alpha"), not pixel-content understanding — that still
    needs a vision-capable model, which isn't wired up here.
    """
    try:
        size_kb = round(len(raw_bytes) / 1024, 1)
        if ext == "png" and raw_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            width = int.from_bytes(raw_bytes[16:20], "big")
            height = int.from_bytes(raw_bytes[20:24], "big")
            bit_depth = raw_bytes[24]
            color_type = raw_bytes[25]
            color_map = {0: "grayscale", 2: "RGB", 3: "palette", 4: "grayscale+alpha", 6: "RGBA"}
            color_desc = color_map.get(color_type, f"type {color_type}")
            return f"PNG image, {width}x{height}px, {bit_depth}-bit {color_desc}, {size_kb} KB"
        if ext == "gif" and raw_bytes[:6] in (b"GIF87a", b"GIF89a"):
            width = int.from_bytes(raw_bytes[6:8], "little")
            height = int.from_bytes(raw_bytes[8:10], "little")
            return f"GIF image, {width}x{height}px, {size_kb} KB"
        if ext in ("jpg", "jpeg") and raw_bytes[:2] == b"\xff\xd8":
            i = 2
            while i < len(raw_bytes) - 9:
                if raw_bytes[i] != 0xFF:
                    i += 1
                    continue
                marker = raw_bytes[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    height = int.from_bytes(raw_bytes[i + 5:i + 7], "big")
                    width = int.from_bytes(raw_bytes[i + 7:i + 9], "big")
                    channels = raw_bytes[i + 9]
                    return f"JPEG image, {width}x{height}px, {channels} channel(s), {size_kb} KB"
                seg_len = int.from_bytes(raw_bytes[i + 2:i + 4], "big")
                i += 2 + seg_len
            return f"JPEG image, {size_kb} KB (dimensions marker not found)"
        return f"{ext.upper()} image, {size_kb} KB (header parsing not implemented for this format)"
    except Exception as exc:
        print(f"[IMAGE META][FAULT] {exc}")
        return ""
_IMAGE_DEEP_ANALYSIS_SCRIPT = r"""
import sys, os, struct, zlib
path = sys.argv[1]
size_bytes = os.path.getsize(path)
print(f"File size: {size_bytes} bytes ({size_bytes/1024:.1f} KB)")
# Prefer Pillow for the richest possible real info, if it's installed.
try:
    from PIL import Image, ExifTags
    with Image.open(path) as img:
        print(f"Format: {img.format}")
        print(f"Mode: {img.mode}")
        print(f"Size: {img.width}x{img.height}")
        print(f"Has transparency info: {'transparency' in img.info}")
        if img.info:
            for k, v in img.info.items():
                sval = str(v)
                if len(sval) > 200:
                    sval = sval[:200] + "...(truncated)"
                print(f"info[{k}]: {sval}")
        exif = getattr(img, "_getexif", lambda: None)()
        if exif:
            print("EXIF tags found:")
            for tag_id, value in exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, tag_id)
                sval = str(value)
                if len(sval) > 150:
                    sval = sval[:150] + "...(truncated)"
                print(f"  {tag_name}: {sval}")
        else:
            print("No EXIF data found.")
    print("(Pillow was used for this analysis.)")
    sys.exit(0)
except ImportError:
    print("(Pillow not installed on server — falling back to manual byte-level parsing.)")
except Exception as e:
    print(f"(Pillow analysis failed: {e} — falling back to manual byte-level parsing.)")
with open(path, "rb") as f:
    data = f.read()
if data[:8] == b"\x89PNG\r\n\x1a\n":
    print("Detected: PNG")
    pos = 8
    chunk_types_seen = []
    while pos < len(data) - 8:
        length = struct.unpack(">I", data[pos:pos+4])[0]
        ctype = data[pos+4:pos+8].decode("ascii", errors="replace")
        chunk_types_seen.append(ctype)
        chunk_data = data[pos+8:pos+8+length]
        if ctype == "IHDR" and len(chunk_data) >= 13:
            width, height, bit_depth, color_type, compression, filter_m, interlace = struct.unpack(">IIBBBBB", chunk_data[:13])
            color_map = {0: "grayscale", 2: "RGB", 3: "palette", 4: "grayscale+alpha", 6: "RGBA"}
            print(f"IHDR: {width}x{height}, {bit_depth}-bit {color_map.get(color_type, color_type)}, "
                  f"interlace={'Adam7' if interlace else 'none'}")
        elif ctype == "gAMA" and len(chunk_data) >= 4:
            gamma = struct.unpack(">I", chunk_data[:4])[0] / 100000
            print(f"gAMA (gamma): {gamma}")
        elif ctype == "pHYs" and len(chunk_data) >= 9:
            ppux, ppuy, unit = struct.unpack(">IIB", chunk_data[:9])
            print(f"pHYs (pixel density): {ppux}x{ppuy} per unit, unit={'meter' if unit == 1 else 'unknown'}")
        elif ctype in ("tEXt", "iTXt", "zTXt"):
            try:
                if ctype == "tEXt":
                    key, _, val = chunk_data.partition(b"\x00")
                    print(f"{ctype} metadata: {key.decode(errors='replace')} = {val.decode(errors='replace')[:200]}")
                else:
                    print(f"{ctype} metadata chunk present ({len(chunk_data)} bytes)")
            except Exception:
                print(f"{ctype} metadata chunk present ({len(chunk_data)} bytes, could not decode)")
        elif ctype == "sRGB":
            print("sRGB color profile chunk present.")
        elif ctype == "iCCP":
            print(f"ICC color profile embedded ({len(chunk_data)} bytes).")
        pos += 8 + length + 4  # length + type + data + CRC
        if ctype == "IEND":
            break
    print(f"All chunk types found, in order: {', '.join(chunk_types_seen)}")
elif data[:2] == b"\xff\xd8":
    print("Detected: JPEG")
    i = 2
    markers_found = []
    while i < len(data) - 4:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i+1]
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > len(data):
            break
        seg_len = struct.unpack(">H", data[i+2:i+4])[0]
        markers_found.append(hex(marker))
        if marker == 0xE1 and data[i+4:i+9] == b"Exif\x00":
            print("EXIF segment (APP1) present.")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i+5:i+9])
            channels = data[i+9]
            print(f"SOF: {width}x{height}, {channels} channel(s)")
        if marker == 0xDA:
            break
        i += 2 + seg_len
    print(f"JPEG markers seen: {', '.join(markers_found)}")
elif data[:6] in (b"GIF87a", b"GIF89a"):
    print("Detected: GIF")
    width, height = struct.unpack("<HH", data[6:10])
    flags = data[10]
    has_gct = bool(flags & 0x80)
    gct_size = 2 ** ((flags & 0x07) + 1) if has_gct else 0
    print(f"Dimensions: {width}x{height}, global color table: {has_gct} ({gct_size} colors)")
    frame_count = data.count(b"\x21\xf9\x04")
    print(f"Approximate animation frame count (via graphic control extensions): {frame_count}")
else:
    print("Format not recognized by manual parser (not PNG/JPEG/GIF signature).")
"""
def _analyze_image_via_terminal(raw_bytes: bytes, ext: str, filename_hint: str = "upload") -> str:
    """Writes the uploaded image to a real scratch directory and runs the
    deep-analysis script above via the SAME background terminal execution
    engine (`_run_code_block`) used for the AI's own code blocks — this is
    genuine subprocess execution against the real file, not a canned
    description. Returns the script's stdout (the full analysis text), or
    the lightweight header-sniff result as a fallback if execution fails."""
    workdir = _new_terminal_workdir()
    try:
        safe_name = f"{filename_hint or 'upload'}.{ext}".replace("/", "_").replace("..", "_")
        image_path = os.path.join(workdir, safe_name)
        with open(image_path, "wb") as f:
            f.write(raw_bytes)
        script_with_path = _IMAGE_DEEP_ANALYSIS_SCRIPT.replace(
            'path = sys.argv[1]', f'path = {image_path!r}'
        )
        stdout, stderr, rc = _run_code_block("python", script_with_path, cwd=workdir)
        result = stdout.strip()
        if stderr.strip():
            result += f"\n(stderr during analysis: {stderr.strip()[:300]})"
        if not result:
            result = _extract_image_metadata(raw_bytes, ext)
        return result
    except Exception as exc:
        print(f"[IMAGE DEEP ANALYSIS][FAULT] {exc}")
        return _extract_image_metadata(raw_bytes, ext)
    finally:
        _cleanup_terminal_workdir(workdir)
def _text_extraction_quality_score(text: str) -> float:
    """Cheap 0.0-1.0 quality heuristic used to pick the best of several
    extraction attempts: fraction of characters that are letters (any
    script, via str.isalpha — this correctly counts Devanagari letters, not
    just ASCII), digits, or normal punctuation/whitespace, versus control
    characters / replacement characters / other extraction-noise symbols
    that show up when a library mishandles a script's encoding."""
    if not text or not text.strip():
        return 0.0
    good = sum(1 for c in text if c.isalpha() or c.isdigit() or c.isspace() or c in ".,;:!?()-'\"।॥")
    return good / max(1, len(text))
def _extract_pdf_text_with_pypdf(pdf_bytes: bytes) -> str:
    if not _PDF_READ_SUPPORTED:
        return ""
    try:
        reader = _PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        print(f"[EDU][EXTRACT FAULT pypdf] {exc}")
        return ""
def _extract_pdf_text_with_fitz(pdf_bytes: bytes) -> str:
    """PyMuPDF (fitz) — generally the most reliable of the three for
    Devanagari/Indic scripts in practice, since it reads glyph positions
    and Unicode mapping more robustly than pypdf's simpler approach."""
    if not _FITZ_SUPPORTED:
        return ""
    try:
        doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            return "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    except Exception as exc:
        print(f"[EDU][EXTRACT FAULT fitz] {exc}")
        return ""
def _extract_pdf_text_with_pdfplumber(pdf_bytes: bytes) -> str:
    if not _PDFPLUMBER_SUPPORTED:
        return ""
    try:
        with _pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:
        print(f"[EDU][EXTRACT FAULT pdfplumber] {exc}")
        return ""
def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """
    THE FIX for Sanskrit/Hindi (and any other complex-script) PDFs coming
    back empty/garbled: instead of relying on pypdf alone (which is known to
    mishandle Devanagari conjuncts/ligatures), this now runs every text
    extractor that's actually installed on the server — PyMuPDF (fitz),
    pdfplumber, and pypdf/PyPDF2 — scores each result's quality, and returns
    whichever came out cleanest. If none are installed except pypdf, this
    behaves exactly as before (no regression), but installing PyMuPDF or
    pdfplumber on the server (add "PyMuPDF" or "pdfplumber" to
    requirements.txt) will make Sanskrit/Hindi chapters extract properly
    without any further code change needed.
    """
    candidates = []
    fitz_text = _extract_pdf_text_with_fitz(pdf_bytes)
    if fitz_text:
        candidates.append(("fitz", fitz_text))
    plumber_text = _extract_pdf_text_with_pdfplumber(pdf_bytes)
    if plumber_text:
        candidates.append(("pdfplumber", plumber_text))
    pypdf_text = _extract_pdf_text_with_pypdf(pdf_bytes)
    if pypdf_text:
        candidates.append(("pypdf", pypdf_text))
    if not candidates:
        return ""
    best_method, best_text = max(candidates, key=lambda item: _text_extraction_quality_score(item[1]))
    print(f"[EDU][EXTRACT] used {best_method} (score={_text_extraction_quality_score(best_text):.2f}, "
          f"{len(candidates)} extractor(s) available)")
    return best_text
def _refresh_education_library():
    now_ts = time.time()
    if _education_cache["files"] and (now_ts - _education_cache["listing_t"]) < _EDUCATION_LISTING_TTL:
        return
    entries = _github_list_dir("data/education")
    for entry in entries:
        if not entry.get("name", "").lower().endswith(".pdf"):
            continue
        sha = entry.get("sha")
        name = entry.get("name")
        cached = _education_cache["files"].get(name)
        if cached and cached.get("sha") == sha and cached.get("text"):
            continue
        raw = _github_fetch_file_bytes(entry.get("download_url"))
        if raw is None:
            continue
        text = _extract_pdf_text(raw)
        if text:
            _education_cache["files"][name] = {"sha": sha, "text": text}
    _education_cache["listing_t"] = now_ts
def _find_best_education_excerpt(question: str):
    """
    Very lightweight relevance scoring: splits every cached PDF's text into
    paragraphs and scores each paragraph by how many question keywords it
    contains. This intentionally does NOT require an exact phrase match —
    the goal is "most relevant", not "identical text".
    """
    _refresh_education_library()
    if not _education_cache["files"]:
        return None
    question_words = set(re.findall(r"[a-zA-Z]{3,}", question.lower()))
    if not question_words:
        return None
    best = {"score": 0, "filename": None, "excerpt": ""}
    for filename, data in _education_cache["files"].items():
        text = data.get("text", "")
        if not text:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for para in paragraphs:
            para_words = set(re.findall(r"[a-zA-Z]{3,}", para.lower()))
            score = len(question_words & para_words)
            if score > best["score"]:
                best = {"score": score, "filename": filename, "excerpt": para[:1800]}
    return best if best["filename"] else None
def _find_best_excerpt_in_text(question: str, text: str, label: str = None):
    """Reusable paragraph-relevance scorer, used both for the whole-library
    scan (below) and for a single selected book/chapter's text."""
    question_words = set(re.findall(r"[a-zA-Z]{3,}", question.lower()))
    if not question_words or not text:
        return None
    best = {"score": 0, "excerpt": ""}
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for para in paragraphs:
        para_words = set(re.findall(r"[a-zA-Z]{3,}", para.lower()))
        score = len(question_words & para_words)
        if score > best["score"]:
            best = {"score": score, "excerpt": para[:1800]}
    if best["score"] == 0:
        best["excerpt"] = text[:1800]
    if label:
        best["label"] = label
    return best
_education_books_cache = {"books": [], "t": 0}
_EDUCATION_BOOKS_TTL = 120           
_education_chapter_text_cache = {}                                                  
def _list_education_books():
    now_ts = time.time()
    if _education_books_cache["books"] and (now_ts - _education_books_cache["t"]) < _EDUCATION_BOOKS_TTL:
        return _education_books_cache["books"]
    entries = _github_list_dir("data/education")
    books = sorted(e.get("name") for e in entries if e.get("type") == "dir" and e.get("name"))
    _education_books_cache["books"] = books
    _education_books_cache["t"] = now_ts
    return books
def _list_education_chapters(book: str):
    if not book:
        return []
    safe_book = book.replace("..", "").strip("/")
    entries = _github_list_dir(f"data/education/{safe_book}")
    chapters = sorted(
        e.get("name") for e in entries
        if e.get("type") == "file" and e.get("name", "").lower().endswith(".pdf")
    )
    return chapters
def _fetch_chapter_text(book: str, chapter: str) -> str:
    """
    THE FIX for "still can't read the PDF even after adding PyMuPDF": this
    cache used to store EVERY extraction result, including empty/failed
    ones, keyed by the file's sha. Since a PDF's sha never changes unless
    the file itself is re-uploaded, a single early failure (e.g. from
    before PyMuPDF was installed) got cached permanently — every later
    request just replayed that same empty string forever, even after the
    extractor chain was fixed and would have succeeded. Now only a
    genuinely non-empty extraction gets cached; an empty/failed result is
    never stored, so the next request always retries extraction fresh
    until it actually succeeds.
    """
    safe_book = book.replace("..", "").strip("/")
    safe_chapter = chapter.replace("..", "").strip("/")
    cache_key = f"{safe_book}/{safe_chapter}"
    entries = _github_list_dir(f"data/education/{safe_book}")
    match = next((e for e in entries if e.get("name") == safe_chapter), None)
    if not match:
        print(f"[EDU][FETCH][FAULT] chapter file not found: 'data/education/{safe_book}/{safe_chapter}' "
              f"— available files in that folder: {[e.get('name') for e in entries]}")
        return ""
    sha = match.get("sha")
    cached = _education_chapter_text_cache.get(cache_key)
    if cached and cached.get("sha") == sha and cached.get("text"):
        return cached.get("text", "")
    raw = _github_fetch_file_bytes(match.get("download_url"))
    if raw is None:
        print(f"[EDU][FETCH][FAULT] GitHub download_url fetch returned None for {cache_key}")
        return cached.get("text", "") if cached else ""
    if not (_PDF_READ_SUPPORTED or _FITZ_SUPPORTED or _PDFPLUMBER_SUPPORTED):
        print(f"[EDU][FETCH][FAULT] no PDF extractor installed at all (pypdf/PyMuPDF/pdfplumber all "
              f"missing) — add at least one to requirements.txt. Skipping extraction for {cache_key}.")
        return ""
    text = _extract_pdf_text(raw)
    if not text:
        print(f"[EDU][FETCH][FAULT] extractor chain ran but returned empty text for {cache_key} "
              f"(pypdf={_PDF_READ_SUPPORTED}, fitz={_FITZ_SUPPORTED}, pdfplumber={_PDFPLUMBER_SUPPORTED}) "
              f"— likely a font/encoding issue in this specific PDF, not a missing package. "
              f"Trying remote OCR fallback via executor (configured={EXECUTOR_CONFIGURED})...")
        if EXECUTOR_CONFIGURED:
            text = _extract_pdf_text_via_remote_ocr(raw)
            if text:
                print(f"[EDU][FETCH] remote OCR fallback succeeded for {cache_key} ({len(text)} chars)")
            else:
                print(f"[EDU][FETCH][FAULT] remote OCR fallback also returned nothing for {cache_key} "
                      f"— check the executor box has tesseract-ocr + tesseract-ocr-hin + PyMuPDF + "
                      f"pytesseract + Pillow installed, and check its /ocr endpoint logs directly.")
        else:
            print(f"[EDU][FETCH][FAULT] EXECUTOR_URL/EXECUTOR_SECRET not set — OCR fallback needs your "
                  f"Ubuntu Railway executor configured (see earlier setup) since Vercel can't run "
                  f"tesseract itself.")
    if text:
        _education_chapter_text_cache[cache_key] = {"sha": sha, "text": text}
    return text
_EDU_TAG_RE = re.compile(r"\[\[EDU_BOOK:(.*?)\]\]\[\[EDU_CHAPTER:(.*?)\]\]")
_NO_WEB_SEARCH_TAG_RE = re.compile(r"\[\[NO_WEB_SEARCH\]\]")
_CURRENT_EVENTS_INTENT_RE = re.compile(
    r"\b(today'?s?\s+news|current\s+(news|affairs|events)|latest\s+news|breaking\s+news|"
    r"what'?s\s+(happening|going\s+on)|news\s+today|headlines)\b",
    re.IGNORECASE
)
GOOGLE_CSE_KEY = os.environ.get("GOOGLE_CSE_KEY", "").strip()
GOOGLE_CSE_CX = os.environ.get("GOOGLE_CSE_CX", "").strip()
GOOGLE_CSE_CONFIGURED = bool(GOOGLE_CSE_KEY and GOOGLE_CSE_CX)
def _google_cse_snippets(query: str, max_results: int = 4):
    try:
        params = urllib.parse.urlencode({
            "key": GOOGLE_CSE_KEY, "cx": GOOGLE_CSE_CX, "q": query, "num": max_results
        })
        req = urllib.request.Request(f"https://www.googleapis.com/customsearch/v1?{params}")
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        results = []
        for item in data.get("items", [])[:max_results]:
            title = item.get("title", "").strip()
            snippet = item.get("snippet", "").strip()
            link = item.get("link", "")
            if title:
                results.append(f"- {title}: {snippet} ({link})")
        return results
    except Exception as exc:
        print(f"[WEB][GOOGLE CSE FAULT] {exc}")
        return []
def _web_search_snippets(query: str, max_results: int = 5, _retries: int = 2):
    """Enhanced web search with retry logic, multiple parsing strategies,
    and DuckDuckGo lite fallback. Tries Google CSE first (if configured),
    then DuckDuckGo HTML, then DuckDuckGo Lite as a final fallback.
    Retries on transient failures before giving up and returning []."""
    if GOOGLE_CSE_CONFIGURED:
        results = _google_cse_snippets(query, max_results)
        if results:
            return results
    clean = lambda s: re.sub('<[^<]+?>', '', s).replace('&', '&').replace('"', '"').replace('&#x27;', "'").strip()
    for attempt in range(_retries + 1):
        try:
            encoded = urllib.parse.quote(query)
            req = urllib.request.Request(
                f"https://html.duckduckgo.com/html/?q={encoded}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                html_body = resp.read().decode('utf-8', errors='ignore')
            results = []
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html_body, re.DOTALL)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div|span)', html_body, re.DOTALL)
            for i in range(min(max_results, len(titles))):
                title = clean(titles[i])
                snippet = clean(snippets[i]) if i < len(snippets) else ""
                if title:
                    results.append(f"- {title}: {snippet}")
            if not results:
                title_matches = re.findall(r'data-title="([^"]+)"', html_body)
                snippet_matches = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:td|div)', html_body, re.DOTALL)
                for i in range(min(max_results, len(title_matches))):
                    title = clean(title_matches[i])
                    snippet = clean(snippet_matches[i]) if i < len(snippet_matches) else ""
                    if title:
                        results.append(f"- {title}: {snippet}")
            if not results:
                link_blocks = re.findall(r'<a[^>]+class="result-link"[^>]*>(.*?)</a>.*?<td[^>]*class="result-snippet"[^>]*>(.*?)</td>', html_body, re.DOTALL)
                for i in range(min(max_results, len(link_blocks))):
                    title = clean(link_blocks[i][0])
                    snippet = clean(link_blocks[i][1])
                    if title:
                        results.append(f"- {title}: {snippet}")
            if results:
                return results
        except Exception as exc:
            print(f"[WEB][DDG HTML attempt {attempt+1} FAULT] {exc}")
        try:
            encoded = urllib.parse.quote(query)
            req = urllib.request.Request(
                f"https://lite.duckduckgo.com/lite/?q={encoded}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html",
                }
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                html_body = resp.read().decode('utf-8', errors='ignore')
            results = []
            link_matches = re.findall(r'<a[^>]+class="result-link"[^>]*>(.*?)</a>', html_body, re.DOTALL)
            snippet_matches = re.findall(r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>', html_body, re.DOTALL)
            for i in range(min(max_results, len(link_matches))):
                title = clean(link_matches[i])
                snippet = clean(snippet_matches[i]) if i < len(snippet_matches) else ""
                if title:
                    results.append(f"- {title}: {snippet}")
            if results:
                return results
        except Exception as exc:
            print(f"[WEB][DDG Lite attempt {attempt+1} FAULT] {exc}")
        if attempt < _retries:
            time.sleep(0.5)                            
    print(f"[WEB] All search strategies failed for query: {query[:80]}")
    return []
def _get_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None
def _decode_google_claims(token: str):
    """Best-effort decode used only for local parsing; not a trust boundary."""
    try:
        payload=token.split('.')[1]; payload += '=' * (-len(payload)%4)
        return json.loads(base64.b64decode(payload).decode('utf-8'))
    except Exception: return None

def _verify_google_id_token(token: str):
    if not token or len(token.split('.')) != 3: return None
    try:
        q=urllib.parse.urlencode({"id_token":token})
        req=urllib.request.Request(f"https://oauth2.googleapis.com/tokeninfo?{q}", method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp: data=json.loads(resp.read().decode('utf-8',errors='replace'))
        if str(data.get('aud','')) != GOOGLE_OAUTH_CLIENT_ID: return None
        if str(data.get('iss','')) not in {'accounts.google.com','https://accounts.google.com'}: return None
        email=str(data.get('email','')).strip().lower()
        if not email: return None
        return {"sub":data.get('sub'),"email":email,"role":"standard","user_metadata":{"full_name":data.get('name'),"picture":data.get('picture')},"email_verified":str(data.get('email_verified','true')).lower()=='true'}
    except Exception as exc:
        print(f"[AUTH][GOOGLE VERIFY] {exc}")
        return None

_SESSION_TOKEN_PREFIX = "PAI1"
def _issue_session_token(user: dict) -> str:
    payload = {
        "sub": user.get("sub"),
        "email": user.get("email"),
        "role": user.get("role", "standard"),
        "full_name": (user.get("user_metadata") or {}).get("full_name"),
        "picture": (user.get("user_metadata") or {}).get("picture"),
        "exp": int(time.time()) + (SESSION_TOKEN_TTL_DAYS * 86400)
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8').rstrip('=')
    signature = hmac.new(SESSION_SECRET.encode('utf-8'), payload_b64.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{_SESSION_TOKEN_PREFIX}.{payload_b64}.{signature}"
def _verify_session_token(token: str):
    try:
        prefix, payload_b64, signature = token.split('.')
        if prefix != _SESSION_TOKEN_PREFIX:
            return None
        expected_sig = hmac.new(SESSION_SECRET.encode('utf-8'), payload_b64.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            return None
        padded = payload_b64 + '=' * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))
        if payload.get("exp", 0) < time.time():
            return None
        return {
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("role", "standard"),
            "user_metadata": {"full_name": payload.get("full_name"), "picture": payload.get("picture")}
        }
    except Exception:
        return None
def _verify_token(token: str):
    if ALLOW_INSECURE_DEV_AUTH and token == "dev-session-active-token":
        return {
            "sub": "dev-user",
            "email": "pratham31sinha@gmail.com",
            "role": "creator",
            "user_metadata": {"full_name": "Dev Master Creator"}
        }
    if not token:
        return None
    if token.startswith(f"{_SESSION_TOKEN_PREFIX}."):
        session_user = _verify_session_token(token)
        return session_user if session_user else None
    if len(token.split('.')) == 3:
        verified = _verify_google_id_token(token)
        if verified:
            return verified
    if not SUPABASE_CONFIGURED or _supabase is None:
        return None
    try:
        resp = _supabase.auth.get_user(token)
        if resp and resp.user:
            return {
                "sub": resp.user.id,
                "email": resp.user.email.lower(),
                "role": "standard",
                "user_metadata": resp.user.user_metadata or {}
            }
    except Exception:
        pass
    return None
def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return _cors_preflight()
        token = _get_token()
        user = _verify_token(token)
        if not user:
            return jsonify({"error": "Session expired or invalid. Please sign in again."}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper
@app.route("/api/agent/jobs/<job_id>", methods=["GET", "OPTIONS"])
@app.route("/api/app/agent/jobs/<job_id>", methods=["GET", "OPTIONS"])
@require_auth
def agent_job_status(job_id):
    if request.method == "OPTIONS":
        return _cors_preflight()
    with _PRATHAM_AGENT_LOCK:
        job = _PRATHAM_AGENT_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job."}), 404
        if job["userId"] != _user_id():
            return jsonify({"error": "Forbidden."}), 403
        return jsonify({"ok": True, "jobId": job_id, "status": job["status"], "result": job.get("result")})

def _clean_token(val: str) -> str:
    if not val:
        return ""
    val = val.strip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1].strip()
    return val
def _get_expected_worker_token() -> str:
    raw = os.environ.get("PRATHAM_WORKER_TOKEN") or PRATHAM_WORKER_TOKEN or ""
    return _clean_token(raw)
def _get_auth_header() -> str:
    h = request.headers.get("Authorization", "")
    if not h:
        h = request.environ.get("HTTP_AUTHORIZATION", "")
    return h.strip() if h else ""
def require_worker_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return _cors_preflight()
        expected = _get_expected_worker_token()
        env_present = bool(expected)
        auth_header = _get_auth_header()
        header_present = bool(auth_header)
        scheme = "missing"
        presented = ""
        if header_present:
            if auth_header.lower().startswith("bearer "):
                scheme = "Bearer"
                presented = _clean_token(auth_header[7:])
            else:
                scheme = "other"
                presented = _clean_token(auth_header)
        token_match = False
        if env_present and presented:
            token_match = hmac.compare_digest(presented, expected)
        print(f"[WORKER AUTH] env_present={str(env_present).lower()}")
        print(f"[WORKER AUTH] header_present={str(header_present).lower()}")
        print(f"[WORKER AUTH] scheme={scheme}")
        print(f"[WORKER AUTH] token_match={str(token_match).lower()}")
        if not env_present:
            return jsonify({"ok": False, "error": {"code": "UNAUTHORIZED",
                "message": "No PRATHAM_WORKER_TOKEN configured on this backend; worker auth is disabled."}}), 401
        if not token_match:
            return jsonify({"ok": False, "error": {"code": "UNAUTHORIZED",
                "message": "Invalid or missing worker token."}}), 401
        return f(*args, **kwargs)
    return wrapper
def _worker_is_online(entry: dict) -> bool:
    if not entry:
        return False
    if entry.get("worker_id") == "static-worker":
        return True
    age = time.time() - entry.get("last_seen_epoch", 0)
    return age <= WORKER_ONLINE_TIMEOUT_SECONDS
@app.route("/worker/status", methods=["GET", "OPTIONS"], strict_slashes=False)
@app.route("/app/worker/status", methods=["GET", "OPTIONS"], strict_slashes=False)
@app.route("/api/worker/status", methods=["GET", "OPTIONS"], strict_slashes=False)
@app.route("/api/app/worker/status", methods=["GET", "OPTIONS"], strict_slashes=False)
def worker_status():
    if request.method == "OPTIONS":
        return _cors_preflight()
    best = _worker_get_latest()
    online = _worker_is_online(best)
    if online:
        _qwen_entry_warmup_async()
    return jsonify({
        "ok": True,
        "online": online,
        "worker": {
            "worker_id": (best or {}).get("worker_id", "none"),
            "model": (best or {}).get("model", "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"),
            "gpu": (best or {}).get("gpu", "Tesla T4"),
            "vram_gb": (best or {}).get("vram_gb", 14.56),
            "status": "online" if online else "offline",
            "last_seen": (best or {}).get("last_seen", ""),
            "latency_ms": (best or {}).get("latency_ms"),
        } if best else None,
        "checked_at": datetime.now(timezone.utc).isoformat()
    })
@app.route("/worker/debug", methods=["GET", "OPTIONS"], strict_slashes=False)
@app.route("/app/worker/debug", methods=["GET", "OPTIONS"], strict_slashes=False)
@app.route("/api/worker/debug", methods=["GET", "OPTIONS"], strict_slashes=False)
@app.route("/api/app/worker/debug", methods=["GET", "OPTIONS"], strict_slashes=False)
def worker_debug():
    if request.method == "OPTIONS":
        return _cors_preflight()
    best = _worker_get_latest()
    token = _get_expected_worker_token()
    resolved_url = (best or {}).get("endpoint_url", "").strip().rstrip("/") or os.environ.get("QWEN_WORKER_URL", "").strip().rstrip("/")
    is_online = _worker_is_online(best)
    return jsonify({
        "ok": True,
        "registry_has_worker": bool(best),
        "worker_id": (best or {}).get("worker_id", "none") if best else "none",
        "online": is_online,
        "url_configured": bool(resolved_url),
        "token_configured": bool(token),
        "endpoint_url": resolved_url,
        "repo_slug": _github_repo_slug(),
        "model": (best or {}).get("model", "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ") if best else "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
        "github_token_configured": bool(GITHUB_TOKEN),
        "supabase_configured": bool(SUPABASE_CONFIGURED),
        "last_seen_epoch": (best or {}).get("last_seen_epoch") if best else None,
        "age_seconds": int(time.time() - (best or {}).get("last_seen_epoch", 0)) if best and best.get("last_seen_epoch") else None,
    })
@app.route("/worker/auth-debug", methods=["GET", "OPTIONS"], strict_slashes=False)
@app.route("/app/worker/auth-debug", methods=["GET", "OPTIONS"], strict_slashes=False)
@app.route("/api/worker/auth-debug", methods=["GET", "OPTIONS"], strict_slashes=False)
@app.route("/api/app/worker/auth-debug", methods=["GET", "OPTIONS"], strict_slashes=False)
def worker_auth_debug():
    if request.method == "OPTIONS":
        return _cors_preflight()
    expected = _get_expected_worker_token()
    env_present = bool(expected)
    env_length = len(expected)
    auth_header = _get_auth_header()
    header_received = bool(auth_header)
    scheme = "missing"
    presented = ""
    if header_received:
        if auth_header.lower().startswith("bearer "):
            scheme = "Bearer"
            presented = _clean_token(auth_header[7:])
        else:
            scheme = "other"
            presented = _clean_token(auth_header)
    token_match = False
    if env_present and presented:
        token_match = hmac.compare_digest(presented, expected)
    print(f"[WORKER AUTH] env_present={str(env_present).lower()}")
    print(f"[WORKER AUTH] header_present={str(header_received).lower()}")
    print(f"[WORKER AUTH] scheme={scheme}")
    print(f"[WORKER AUTH] token_match={str(token_match).lower()}")
    return jsonify({
        "env_present": env_present,
        "env_length": env_length,
        "header_received": header_received,
        "auth_scheme": scheme,
        "expected_env_name": "PRATHAM_WORKER_TOKEN"
    })
@app.route("/worker/heartbeat", methods=["POST", "OPTIONS"], strict_slashes=False)
@app.route("/app/worker/heartbeat", methods=["POST", "OPTIONS"], strict_slashes=False)
@app.route("/api/worker/heartbeat", methods=["POST", "OPTIONS"], strict_slashes=False)
@app.route("/api/app/worker/heartbeat", methods=["POST", "OPTIONS"], strict_slashes=False)
@require_worker_auth
def worker_heartbeat():
    body = request.get_json(silent=True) or {}
    worker_id = (body.get("worker_id") or "").strip()
    if not worker_id:
        return jsonify({"ok": False, "error": {"code": "INVALID_REQUEST", "message": "worker_id is required"}}), 400
    now = time.time()
    with _worker_registry_lock:
        prev = _worker_registry.get(worker_id, {})
    new_endpoint = (body.get("endpoint_url") or "").strip().rstrip("/")
    entry = {
        "worker_id": worker_id,
        "status": body.get("status", "online"),
        "model": body.get("model", prev.get("model", "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ")),
        "gpu": body.get("gpu", prev.get("gpu", "Tesla T4")),
        "vram_gb": body.get("vram_gb", prev.get("vram_gb", 14.56)),
        "version": body.get("version", prev.get("version", "1.0")),
        "endpoint_url": new_endpoint or prev.get("endpoint_url", ""),
        "last_seen": datetime.now(timezone.utc).isoformat(),
        "last_seen_epoch": now,
        "latency_ms": prev.get("latency_ms"),
    }
    _worker_upsert(entry)
    print(f"[WORKER] heartbeat from '{worker_id}' — status={body.get('status')} model={body.get('model')} endpoint={'updated' if new_endpoint else 'unchanged'}")
    return jsonify({"ok": True, "received_at": datetime.now(timezone.utc).isoformat()})
@app.route("/worker/register", methods=["POST", "OPTIONS"], strict_slashes=False)
@app.route("/app/worker/register", methods=["POST", "OPTIONS"], strict_slashes=False)
@app.route("/api/worker/register", methods=["POST", "OPTIONS"], strict_slashes=False)
@app.route("/api/app/worker/register", methods=["POST", "OPTIONS"], strict_slashes=False)
@require_worker_auth
def worker_register():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    worker_id = (body.get("worker_id") or "").strip()
    endpoint_url = (body.get("endpoint_url") or "").strip().rstrip("/")
    if not worker_id:
        return jsonify({"ok": False, "error": {"code": "INVALID_REQUEST", "message": "worker_id is required"}}), 400
    if not endpoint_url:
        return jsonify({"ok": False, "error": {"code": "INVALID_REQUEST", "message": "endpoint_url is required"}}), 400
    now = time.time()
    with _worker_registry_lock:
        prev = _worker_registry.get(worker_id, {})
    entry = {
        "worker_id": worker_id,
        "status": "online",
        "endpoint_url": endpoint_url,
        "model": body.get("model", prev.get("model", "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ")),
        "gpu": body.get("gpu", prev.get("gpu", "Tesla T4")),
        "vram_gb": body.get("vram_gb", prev.get("vram_gb", 14.56)),
        "version": body.get("version", prev.get("version", "1.0")),
        "last_seen": datetime.now(timezone.utc).isoformat(),
        "last_seen_epoch": now,
        "latency_ms": prev.get("latency_ms"),
    }
    _worker_upsert(entry)
    print(f"[WORKER][REGISTER] '{worker_id}' registered endpoint={endpoint_url} model={entry['model']} gpu={entry['gpu']}")
    return jsonify({
        "ok": True,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "routing": "active",
    })
_BLOCKED_PATTERNS = [
    r"\bmake\s+a\s+bomb\b", r"\bbuild\s+a\s+bomb\b", r"\bhow\s+to\s+hack\b",
    r"\bchild\s+(sexual|porn|abuse)\b", r"\bkill\s+(myself|someone|him|her|them)\b",
    r"\bsynthesi[sz]e\s+(meth|drug|explosive)\b", r"\bmake\s+a\s+weapon\b",
    r"\bcredit\s+card\s+(number|dump|generator)\b", r"\bddos\b", r"\bransomware\b",
]
_BLOCKED_REGEX = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)
def _is_flagged_message(message: str) -> bool:
    return bool(_BLOCKED_REGEX.search(message or ""))
_TEACHING_INTENT_RE = re.compile(
    r"\b(remember (that|this|to)|note (this|that)|save this|learn this|keep in mind|"
    r"for future reference|always do|always use|from now on|don't forget|never forget|"
    r"for (every|all) user|public memory|shared memory|for everyone|store this|"
    r"always remember)\b",
    re.IGNORECASE
)
_EXPLICIT_MEMORY_COMMAND_RE = re.compile(
    r"^\s*(?:add(?:\s+this)?\s+to\s+(?:your\s+)?memory|save\s+to\s+memory|remember\s+this\s+forever|"
    r"/remember|hey\s+ai,?\s+save\s+this|store\s+this)"
    r"\s*[:\-]?\s*(.*)$",
    re.IGNORECASE | re.DOTALL
)
_PUBLIC_MEMORY_PATH = "data/public_data.txt"
_public_teachings_cache = {"text": "", "t": 0}
_PUBLIC_TEACHINGS_CHAR_BUDGET = 12000                                                                
def _maybe_capture_public_teaching(user_email: str, message: str):
    """
    If a message looks like the person is teaching/instructing the assistant
    something worth remembering, it gets appended to the shared
    data/public_data.txt file. Checks the explicit deterministic command
    forms first, then falls back to the looser natural-language phrase
    detector.
    """
    explicit_match = _EXPLICIT_MEMORY_COMMAND_RE.match(message)
    if explicit_match:
        content_to_save = explicit_match.group(1).strip() or message
        entry = (
            f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"
            f"Taught by: {user_email} (explicit /memory command)\n"
            f"Content: {content_to_save}\n"
            f"{'=' * 80}\n"
        )
        _write_to_github_repository(_PUBLIC_MEMORY_PATH, entry)
        _public_teachings_cache["t"] = 0
        return
    if not _TEACHING_INTENT_RE.search(message):
        return
    entry = (
        f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"
        f"Taught by: {user_email}\n"
        f"Content: {message}\n"
        f"{'=' * 80}\n"
    )
    _write_to_github_repository(_PUBLIC_MEMORY_PATH, entry)
    _public_teachings_cache["t"] = 0                                              
def _auto_extract_and_save_knowledge(assistant_response: str):
    """
    NOT called automatically anywhere in this file, on purpose. This would
    scrape lines out of EVERY assistant reply and save them into the shared,
    all-users-visible data/public_data.txt — but that file gets injected
    into every other user's conversations, so silently auto-saving fragments
    of any one person's private chat (which could include personal details,
    account info, anything) into that shared file is a real data-leak risk,
    not just noise. Left defined and available in case you want to wire it
    up deliberately (e.g. behind an explicit opt-in), but it is intentionally
    dormant by default.
    """
    clean_text = assistant_response.strip()
    if len(clean_text) < 20:
        return
    phrases_to_skip = ["i'd be happy to", "your file is", "here is the", "something went wrong"]
    if any(p in clean_text.lower() for p in phrases_to_skip):
        return
    extracted_nodes = []
    for line in clean_text.split("\n"):
        line_strip = line.strip()
        if not line_strip:
            continue
        if line_strip.startswith("if ") or "function" in line_strip or "const" in line_strip or line_strip.startswith("-") or len(line_strip) > 40:
            extracted_nodes.append(re.sub(r"\*\*?", "", line_strip))
    if extracted_nodes:
        compiled_knowledge = " | ".join(extracted_nodes[:8])
        entry = f"[AUTO FACT — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}] {compiled_knowledge}\n"
        _write_to_github_repository(_PUBLIC_MEMORY_PATH, entry)
        _public_teachings_cache["t"] = 0
def _fetch_full_public_data_text() -> str:
    """Reads the FULL data/public_data.txt file directly from GitHub on
    every call (no stale cache window) — falls back to the last known-good
    copy only if the live fetch itself fails.
    Same fix as _write_to_github_repository: GitHub's Contents API stops
    inlining `content` once a file grows past ~1MB (which a file this long
    — 5500+ lines — can genuinely hit). Previously that meant this function
    silently returned an empty string once the file crossed that size, so
    "always read public_data.txt before responding" was quietly reading
    nothing. Now it falls back to the item's own `download_url`, which has
    no such inline-size limit, whenever `content` isn't present but the
    file's reported `size` shows it isn't actually empty.
    """
    text = ""
    if GITHUB_TOKEN:
        repo_clean = _github_repo_slug()
        endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{_PUBLIC_MEMORY_PATH}"
        req_lookup = urllib.request.Request(
            endpoint_target_url,
            headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        )
        try:
            with urllib.request.urlopen(req_lookup, timeout=10) as lookup_response:
                meta_data = json.loads(lookup_response.read().decode('utf-8'))
                if meta_data.get("content"):
                    text = base64.b64decode(meta_data["content"].replace("\n", "")).decode('utf-8')
                elif meta_data.get("size", 0) > 0 and meta_data.get("download_url"):
                    raw_req = urllib.request.Request(
                        meta_data["download_url"],
                        headers={"Authorization": f"token {GITHUB_TOKEN}"}
                    )
                    with urllib.request.urlopen(raw_req, timeout=20) as raw_resp:
                        text = raw_resp.read().decode('utf-8', errors='replace')
        except Exception as exc:
            print(f"[PUBLIC MEMORY][FETCH FAULT] {exc}")
            return _public_teachings_cache["text"]                                     
    _public_teachings_cache["text"] = text
    _public_teachings_cache["t"] = time.time()
    return text
def _search_intelligent_memory_excerpts(user_query: str) -> str:
    """
    Scores each non-blank line of data/public_data.txt against the current
    message's keywords (simple multi-keyword intersection) and returns the
    best-matching lines — smarter than just grabbing the tail of the file,
    since a relevant fact from early in the file won't get crowded out by
    unrelated recent entries. Falls back to the plain tail of the file if
    nothing scores a match, so the model still gets *some* shared context.
    """
    full_corpus = _fetch_full_public_data_text()
    if not full_corpus.strip():
        return ""
    query_tokens = set(re.findall(r"[a-zA-Z]{3,}", user_query.lower()))
    matched_lines = []
    if query_tokens:
        for line in full_corpus.splitlines():
            line_clean = line.strip()
            if not line_clean:
                continue
            line_tokens = set(re.findall(r"[a-zA-Z]{3,}", line_clean.lower()))
            score = len(query_tokens & line_tokens)
            if score > 0:
                matched_lines.append((score, line_clean))
        matched_lines.sort(key=lambda item: item[0], reverse=True)
    if matched_lines:
        top_excerpts = [line for _score, line in matched_lines[:10]]
        joined = "\n".join(top_excerpts)
        return joined[:_PUBLIC_TEACHINGS_CHAR_BUDGET]
    return full_corpus[-_PUBLIC_TEACHINGS_CHAR_BUDGET:]
_provider_cooldowns: dict = {}
COOLDOWN_SECONDS = 60
def _is_cooling(name: str) -> bool:
    return time.time() < _provider_cooldowns.get(name, 0)
def _cool(name: str):
    _provider_cooldowns[name] = time.time() + COOLDOWN_SECONDS
SYSTEM_PROMPT = (
    "You are Pratham AI, a general-purpose AI assistant created by Pratham Sinha. "
    "You help with anything: everyday questions, writing, math, code, analysis, and learning. "
    "Mention your creator only if explicitly asked.\n\n"
    "=== ACCURACY RULES (HIGHEST PRIORITY) ===\n"
    "1. ALWAYS check the web search results provided in your context before answering factual questions. "
    "Cite web sources when you use them. If web results are present but don\'t answer the question, say so.\n"
    "2. NEVER fabricate facts, dates, names, numbers, or quotes. If you\'re not certain, say \"I\'m not sure\" "
    "or check the web results. Uncertainty is better than wrong information.\n"
    "3. For math: always wrap expressions in LaTeX delimiters ($x^2$ or $$\\frac{a}{b}$$). "
    "Write each expression exactly ONCE — never duplicate it in both plain text and LaTeX. "
    "NEVER write powers as x^2 or fractions as a/b in plain text outside LaTeX delimiters.\n"
    "4. For code: use fenced blocks with explicit language tags (```python, ```html, ```javascript). "
    "Ensure your code is syntactically valid — if you\'re unsure, run it in a ```python block to verify.\n\n"
    "=== RESPONSE STYLE ===\n"
    "Default to SHORT, dense replies for non-coding questions. No filler intros (\"Great question!\"), "
    "no restating the question. Expand length only when the task genuinely needs it.\n"
    "Stay strictly on the asked topic. Don\'t add unrequested extra sections, tangents, or bonus tips. "
    "If something extra is genuinely useful, offer it in ONE short line at the end.\n"
    "Use markdown formatting: ## / ### headings, **bold** for key terms, numbered/bulleted lists, "
    "and real markdown tables for tabular data. Never fake tables with dashes or spaces.\n\n"
    "=== TERMINAL & FILE CREATION ===\n"
    "You have a REAL background terminal. When you write a ```python, ```py, ```bash, ```sh, or ```shell "
    "fenced block, the backend executes it for real and feeds you the actual stdout/stderr. Use this to: "
    "run calculations, process data, test code, create files, and chain multi-step tasks.\n"
    "To create a file directly: use ```createfile:<filename.ext>\\n<content>\\n``` — this writes a real "
    "downloadable file. Use ```editfile:<filename> with SEARCH/REPLACE blocks for incremental edits.\n"
    "For multi-file bundles (e.g. .mcaddon, .zip): write intermediate files via python open()/write() "
    "inside ```python/```bash blocks, then build the final archive with a real command. The backend "
    "auto-detects new files and makes them downloadable.\n"
    "NEVER create duplicate files (app2.py, fixed.py) — use ```editfile: to modify existing files.\n"
    "NEVER hand-type UUIDs — generate them with python\'s uuid module.\n"
    "This sandbox has only the Python stdlib. NEVER run pip/npm/apt install — write stdlib-only Python.\n\n"
    "=== FILE EXPORTS ===\n"
    "When asked to export as zip/pdf/csv/etc: put ONLY the clean deliverable in a ```finaldoc block. "
    "Say one short line outside it (\"Your file is being generated.\"). The backend handles packaging. "
    "Do NOT run zip/unzip/pandoc commands manually for simple exports — the backend does it. "
    "Only produce a file export when explicitly asked.\n\n"
    "=== CHARTS & DIAGRAMS ===\n"
    "For DATA graphs (bar/line/pie/scatter): use a ```chart block with Chart.js config JSON.\n"
    "For GEOMETRY diagrams (triangles, circles, constructions): use ```createfile:<name>.html with "
    "self-contained SVG. Compute real coordinates from given measurements — don\'t draw generic shapes. "
    "If a diagram is needed inside a PDF export, place [DIAGRAM: filename.html] at the right position.\n"
    "Each diagram marker MUST have a matching createfile block in the same reply — never one without the other.\n\n"
    "=== IMAGES ===\n"
    "Image generation is handled by Google Gemini Nano Banana 2 through the connected Google OAuth session. When asked for an image, "
    "describe what you\'ll generate in one sentence — the backend renders it. Always enrich vague prompts "
    "('a dog' → detailed description with lighting, style, composition).\n"
    "When someone uploads an image, you receive real technical metadata (EXIF, dimensions, palette). "
    "Use that data confidently — never say you cannot see images.\n\n"
    "=== WORKFLOW FOR COMPLEX TASKS ===\n"
    "For multi-step builds: (1) write a visible checklist (- [ ] Step name), (2) implement each step, "
    "(3) after each step, re-print the checklist with that box checked (- [x]), (4) review for errors.\n"
    "For ambiguous requests, ask one clarifying question before acting. For clear requests, just do it.\n"
    "Keep file names short and descriptive (invoice.py, not python_script_v1.py).\n"
    "No artificial length limit on files — write the full content even if thousands of lines.\n\n"
    "=== WEB SEARCH (MANDATORY) ===\n"
    "Live web search results are injected into your context before EVERY reply. You are ALWAYS connected "
    "to the web. NEVER say \"my training cutoff is [date]\" or \"I don\'t have recent information\". "
    "If web results are present, use them and cite them. If a topic isn\'t in the results, say \"the search "
    "didn\'t return results for that\" — never blame a training cutoff. NEVER invent specific headlines, "
    "dates, or events from memory and present them as current.\n\n"
    "=== SAFETY ===\n"
    "Never help with illegal activity, weapons, malware, or content that could seriously harm someone. "
    "Politely refuse such requests.\n\n"
    "=== HTML QUALITY ===\n"
    "When building websites: use Google Fonts, CSS custom properties, dark mode by default, "
    "glassmorphism cards, gradient accents, smooth transitions, responsive layouts. "
    "Professional SaaS quality is the minimum bar.\n"
    "=== TONE ===\n"
    "Be clear, direct, and helpful. Match the level of detail to the question. "
    "Keep the same voice across the conversation. Act with confidence when you\'re sure, "
    "but always say when you\'re not certain."
)
_IMAGE_INTENT_RE = re.compile(
    r"^/image\s+(.+)$|"
    r"\b(?:generate|create|draw|make|paint|design|render)\b.{0,25}\b(?:image|img|picture|pic|photo|art|artwork|illustration|drawing|wallpaper|poster|graphic|graphics)s?\b"
    r"(?:\s+(?:of|showing|depicting|with))?\s*(.*)$",
    re.IGNORECASE
)
_IMAGE_FOLLOWUP_RE = re.compile(
    r"^\s*(?:also\s+)?(?:add|change|make it|now|remove|replace|turn it|put|give it|make the|instead)\b.{0,120}$",
    re.IGNORECASE
)
def _enhance_image_prompt_via_llm(raw_prompt: str) -> str:
    raw=str(raw_prompt or '').strip()
    if len(raw)>=180: return raw
    return f"{raw}. Create a polished production-quality image with strong subject clarity, intentional composition, natural lighting, coherent perspective, controlled detail, clean edges, accurate materials, and a professional visual finish."

def _extract_first_image_part(payload):
    for candidate in payload.get('candidates') or []:
        for part in ((candidate.get('content') or {}).get('parts') or []):
            inline=part.get('inlineData') or part.get('inline_data')
            if inline and inline.get('data'): return {'mime_type':inline.get('mimeType') or inline.get('mime_type') or 'image/png','data':inline['data']}
    return None

def _extract_interaction_image(payload):
    """Extract an image block from the current Interactions API response."""
    for step in payload.get("steps") or []:
        content = step.get("content") or []
        if isinstance(content, dict):
            content = [content]
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image" and part.get("data"):
                return {
                    "mime_type": part.get("mime_type") or part.get("mimeType") or "image/png",
                    "data": part["data"],
                }
    # Defensive compatibility for other JSON response shapes.
    output_image = payload.get("output_image") or payload.get("outputImage")
    if isinstance(output_image, dict) and output_image.get("data"):
        return {
            "mime_type": output_image.get("mime_type") or output_image.get("mimeType") or "image/png",
            "data": output_image["data"],
        }
    return None

def _gemini_generate_image(access_token,prompt_text,reference_image_data_url=None):
    interaction_input=[{"type":"text","text":prompt_text}]
    if isinstance(reference_image_data_url,str) and reference_image_data_url.startswith("data:image/"):
        try:
            header,encoded=reference_image_data_url.split(",",1)
            mime_type=header.split(";",1)[0][5:] or "image/png"
            if len(encoded) <= 8_000_000:
                interaction_input.append({"type":"image","mime_type":mime_type,"data":encoded})
        except Exception:
            pass

    # Nano Banana 2 is the stable Gemini 3.1 Flash Image model. Google’s
    # current image-generation docs use the Interactions API for this model.
    body={
        "model": GEMINI_IMAGE_MODEL,
        "input": interaction_input,
        "response_format": {
            "type":"image",
            "mime_type":"image/png",
            "aspect_ratio":"1:1",
            "image_size":"1K",
        },
    }
    url="https://generativelanguage.googleapis.com/v1beta/interactions"
    req=urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-goog-user-project": GOOGLE_CLOUD_PROJECT_ID,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req,timeout=120) as resp:
            payload=json.loads(resp.read().decode("utf-8",errors="replace"))
    except urllib.error.HTTPError as exc:
        raw=exc.read().decode("utf-8",errors="replace")
        try:
            msg=(json.loads(raw).get("error") or {}).get("message") or raw[:1000]
        except Exception:
            msg=raw[:1000]
        # 401 means the OAuth token is invalid/expired. Do not misclassify
        # project permissions or billing errors (commonly 402/403) as a
        # reconnect problem.
        if exc.code == 401:
            raise RuntimeError(f"GEMINI_RECONNECT_REQUIRED: {msg}")
        raise RuntimeError(f"HTTP {exc.code}: {msg}")
    except Exception as exc:
        raise RuntimeError(f"Gemini image request failed: {exc}")

    image=_extract_interaction_image(payload)
    if not image:
        raise RuntimeError("Nano Banana 2 returned no image data.")

    text=[]
    for step in payload.get("steps") or []:
        content=step.get("content") or []
        if isinstance(content,dict): content=[content]
        for part in content:
            if isinstance(part,dict) and part.get("type") == "text" and part.get("text"):
                text.append(part["text"])
    return image,"\n".join(text).strip()

def _stream_google_oauth_gemini(messages,state=None):
    access_token,err=_require_gemini_connection()
    if err: raise RuntimeError('GEMINI_AUTH_REQUIRED')
    system_parts=[]; contents=[]
    for item in messages or []:
        text=str(item.get('content','') or '')
        if not text: continue
        role=item.get('role','user')
        if role=='system': system_parts.append(text)
        else: contents.append({'role':'model' if role=='assistant' else 'user','parts':[{'text':text}]})
    if not contents: raise RuntimeError('No user content was supplied to Gemini.')
    temp=(state or {}).pop('temperature',0.4) if state is not None else 0.4
    body={'contents':contents,'generationConfig':{'temperature':float(temp),'maxOutputTokens':32768}}
    if system_parts: body['systemInstruction']={'parts':[{'text':'\n\n'.join(system_parts)}]}
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(GEMINI_CHAT_MODEL,safe='-_.')}:streamGenerateContent?alt=sse"
    req=urllib.request.Request(url,data=json.dumps(body).encode(),method='POST',headers={'Authorization':f'Bearer {access_token}','x-goog-user-project':GOOGLE_CLOUD_PROJECT_ID,'Content-Type':'application/json','Accept':'text/event-stream','Cache-Control':'no-cache'})
    try:
        with urllib.request.urlopen(req,timeout=120) as resp:
            for raw_line in resp:
                line=raw_line.decode('utf-8',errors='replace').strip()
                if not line.startswith('data:'): continue
                raw=line[5:].strip()
                if not raw: continue
                try: payload=json.loads(raw)
                except Exception: continue
                if payload.get('error'): raise RuntimeError((payload.get('error') or {}).get('message') or 'Gemini API request failed.')
                for candidate in payload.get('candidates') or []:
                    finish=candidate.get('finishReason') or candidate.get('finish_reason')
                    if finish and state is not None: state['finish_reason']='length' if str(finish).upper() in {'MAX_TOKENS','LENGTH'} else 'stop'
                    for part in ((candidate.get('content') or {}).get('parts') or []):
                        if part.get('text'): yield _sse({'type':'token','text':part['text']})
    except urllib.error.HTTPError as exc:
        try:
            raw=exc.read().decode('utf-8',errors='replace'); msg=(json.loads(raw).get('error') or {}).get('message') or raw[:500]
        except Exception: msg=str(exc)
        if exc.code == 401: raise RuntimeError(f'GEMINI_RECONNECT_REQUIRED: {msg}')
        raise RuntimeError(f'HTTP {exc.code}: {msg}')

_MULTITASK_VERB_RE = re.compile(
    r'\b(zip|pdf|csv|svg|python|bash|compute|calculate|create|build|write|make|then|also|plus|and then|export|generate.*and)\b',
    re.IGNORECASE
)
def _is_complex_multitask_message(msg: str) -> bool:
    """Returns True when the message is too complex for the image short-circuit."""
    stripped = msg.strip()
    if len(stripped) > 130:
        return True
    if len(_MULTITASK_VERB_RE.findall(stripped)) >= 2:
        return True
    return False
def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
def _extract_math_expressions(text: str) -> list:
    """Extract arithmetic expressions from LaTeX-delimited math in the text,
    and from plain-text 'X = Y' patterns, so we can verify them with Python."""
    expressions = []
    for m in re.finditer(r'\\\((.+?)\\\)|\\\[(.+?)\\\]|\$\$(.+?)\$\$|\$(.+?)\$', text, re.DOTALL):
        expr = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        if expr:
            expr = expr.strip()
            cleaned = re.sub(r'\\(?:frac|sqrt|text|mathrm|mathbf|left|right|times|cdot|div|pm|mp)', '', expr)
            cleaned = re.sub(r'[{}^_]', '', cleaned)
            if re.match(r'^[\d\s+\-*/().,]+$', cleaned) and any(c in cleaned for c in '+-*/'):
                expressions.append((expr, cleaned))
    for m in re.finditer(r'(?:=|equals|is)\s*[:]?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE):
        val = m.group(1)
        before = text[:m.start()].rstrip()
        expr_match = re.search(r'([\d\s+\-*/().,]+)\s*$', before)
        if expr_match:
            raw_expr = expr_match.group(1).strip()
            if any(c in raw_expr for c in '+-*/') and len(raw_expr) > 2:
                expressions.append((f"{raw_expr} = {val}", f"{raw_expr}"))
    return expressions
def _verify_math_expressions(text: str) -> list:
    """Check if math expressions in the text are arithmetically correct.
    Returns a list of (expression, claimed_result, actual_result, is_correct)."""
    results = []
    for original, expr in _extract_math_expressions(text):
        try:
            actual = eval(expr, {"__builtins__": {}}, {})
            claimed_match = re.search(r'=\s*(\d+(?:\.\d+)?)', original)
            if claimed_match:
                claimed = float(claimed_match.group(1))
                actual_rounded = round(float(actual), 6)
                is_correct = abs(claimed - actual_rounded) < 0.001
                results.append((original, claimed, actual_rounded, is_correct))
        except Exception:
            continue                                      
    return results
def _build_verification_feedback(assistant_text: str, web_results: list) -> str:
    """Runs all verification checks and returns a feedback string for the model
    if errors are found, or None if everything checks out."""
    issues = []
    source_urls = re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)', assistant_text)
    for label, url in source_urls:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.strip('/')
        if not path or path in ('news', 'home'):
            issues.append(
                f"FABRICATED SOURCE: The link '{label}' ({url}) points to a domain root with no "
                f"article path — this looks fabricated. Remove it unless you have the real URL."
            )
    suspicious = re.findall(
        r'\b([A-Z][a-z]+ (?:Janata Party|Party|Congress|Alliance|Front|League|Movement))\b',
        assistant_text
    )
    known = ['bjp', 'congress', 'inc', 'bsp', 'cpi', 'cpm', 'tmc', 'dmk', 'aiadmk', 'aap',
             'shiv sena', 'ncp', 'sp', 'jdu', 'rjd', 'janata party', 'janata dal',
             'bharatiya janata', 'indian national congress']
    for name in suspicious:
        if not any(k in name.lower() for k in known):
            issues.append(
                f"SUSPICIOUS NAME: '{name}' doesn't match any known Indian political party. "
                f"If not in web results, REMOVE it — do not invent party names."
            )
    math_results = _verify_math_expressions(assistant_text)
    for expr, claimed, actual, is_correct in math_results:
        if not is_correct:
            issues.append(
                f"MATH ERROR: You wrote '{expr}' but {expr.split('=')[0].strip()} = {actual}, "
                f"not {claimed}. Please correct this."
            )
    if web_results:
        specific_claims = re.findall(
            r'\b(?:born|died|founded|established|created|invented|discovered|published|released)\s+(?:in|on|by)\s+([A-Z][a-z]+\s+\d{1,4}(?:,?\s+\d{4})?)',
            assistant_text
        )
        if specific_claims:
            web_text = " ".join(web_results).lower()
            for claim in specific_claims[:3]:                        
                claim_words = claim.lower().split()
                match_score = sum(1 for w in claim_words if w in web_text) / max(len(claim_words), 1)
                if match_score < 0.3:
                    issues.append(
                        f"FACT CHECK: The claim '{claim}' doesn't appear in the web search results. "
                        f"Verify this is accurate or remove it if you're not sure."
                    )
    fence_count = assistant_text.count('```')
    if fence_count % 2 != 0:
        issues.append(
            "FORMATTING ERROR: You have an unbalanced number of ``` code fences. "
            "Make sure every opening ``` has a matching closing ```."
        )
    if issues:
        return "\n".join(issues)
    return None
_MATH_QUERY_RE = re.compile(
    r'\b(calculate|solve|compute|evaluate|simplify|factor|expand|derivative|integral|'
    r'equation|matrix|determinant|theorem|prove|proof|sum of|product of|'
    r'\d+\s*[+\-*/]\s*\d+|what is.*\d|find.*value of|factorial|'
    r'permutation|combination|probability|logarithm|exponent)'
, re.IGNORECASE)
_CODE_QUERY_RE = re.compile(
    r'\b(write|create|build|fix|debug|refactor|optimize|implement|function|'
    r'method|class|script|program|algorithm|sort|search|regex|sql|html|css|'
    r'javascript|python|java|react|node|api|endpoint|bug|error|stack trace|'
    r'compile|syntax)'
, re.IGNORECASE)
_FACTUAL_QUERY_RE = re.compile(
    r'\b(who is|what is|when did|where is|how many|how much|capital of|'
    r'population of|definition of|meaning of|history of|cause of|effect of|'
    r'difference between|compare|versus|vs|definition|explain|describe|'
    r'tell me about|what are|list of|types of|examples of)'
, re.IGNORECASE)
_CREATIVE_QUERY_RE = re.compile(
    r'\b(write a story|write a poem|creative|imagine|invent|come up with|'
    r'brainstorm|suggest ideas|generate names|tagline|slogan|'
    r'song lyrics|rap|haiku|essay about|narrative|fiction|'
    r'character|plot|dialogue|screenplay|script for)'
, re.IGNORECASE)
def _classify_query_temperature(message: str) -> float:
    """Analyzes the user's message and returns the optimal temperature.
    - Math/factual/code queries: 0.1-0.3 (precision-critical)
    - General questions: 0.4 (balanced)
    - Creative tasks: 0.7 (variety helps)
    - Default: 0.4"""
    msg_lower = message.lower()
    if _CREATIVE_QUERY_RE.search(msg_lower):
        return 0.7
    if _MATH_QUERY_RE.search(msg_lower):
        return 0.15
    if _CODE_QUERY_RE.search(msg_lower):
        return 0.2
    if _FACTUAL_QUERY_RE.search(msg_lower):
        return 0.3
    if len(message.strip()) < 30:
        return 0.5
    return 0.4
    return 0.4
_FACT_CHECK_QUERY_RE = re.compile(
    r'\b(did|does|has|have|is|was|were|are|who|what|when|where|why|how)\b'
    r'.{0,60}\b(resign|resigned|die|died|appointed|elected|fired|arrested|'
    r'killed|married|divorced|born|founded|launched|released|announced|'
    r'happened|occur|ocurred|started|ended|cancelled|banned|'
    r'prime minister|president|minister|ceo|chief|director|'
    r'government|parliament|supreme court|election|'
    r'party|protest|march|strike|scam|scandal|verdict|'
    r'latest|current|today|yesterday|this week|this month|this year)'
, re.IGNORECASE)
def _is_fact_check_question(message: str) -> bool:
    """Returns True if this question asks about a specific factual claim
    that MUST be verified via web search, not guessed from training data."""
    return bool(_FACT_CHECK_QUERY_RE.search(message))
def _stream_openai_compatible(url, api_key, model, messages, state=None, temperature=0.4):
    """`state`, if provided, is a plain dict this function writes
    state['finish_reason'] into once the stream's final chunk reports one
    (e.g. 'length' when the provider cut the response short because it hit
    the token limit, vs 'stop' for a normal completion). Callers use this to
    detect truncation and automatically continue generation — see
    _do_stream's continuation loop below, which is what fixes "it stops
    HTML/file generation in the middle."""
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": 32768,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            payload_str = line[6:]
            if payload_str == "[DONE]":
                break
            try:
                payload = json.loads(payload_str)
                choice = payload["choices"][0]
                token = choice.get("delta", {}).get("content", "")
                if token:
                    yield _sse({"type": "token", "text": token})
                finish_reason = choice.get("finish_reason")
                if finish_reason and state is not None:
                    state["finish_reason"] = finish_reason
            except Exception:
                continue
def _generate_ai_chat_title(message: str) -> str:
    """Uses the model itself to write a short, clean chat title (like
    ChatGPT/Claude do), instead of just truncating the raw first message.
    Falls back to plain truncation on any failure (missing keys, rate
    limit, network error) so title generation never blocks sending the
    actual chat message."""
    keys = GROQ_API_KEYS or ([GROQ_API_KEY] if GROQ_API_KEY else [])
    if not keys:
        return message[:60]
    prompt = (
        "Write a short chat title (3-6 words, no quotes, no punctuation at the end, "
        "no emoji) summarizing what this message is about. Reply with ONLY the title, "
        f"nothing else.\n\nMessage: \"{message[:400]}\""
    )
    for idx, key in enumerate(keys):
        cooldown_name = f"groq_{idx}"
        if _is_cooling(cooldown_name):
            continue
        try:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=json.dumps({
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 20, "temperature": 0.3,
                }).encode(),
                method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            title = data["choices"][0]["message"]["content"].strip().strip('"').strip("'")
            if title:
                return title[:60]
        except Exception as exc:
            print(f"[TITLE][AI FAULT] key {idx}: {exc}")
            continue
    return message[:60]
def _stream_groq(messages, state=None):
    keys = GROQ_API_KEYS or ([GROQ_API_KEY] if GROQ_API_KEY else [])
    if not keys:
        raise RuntimeError("Groq unavailable (no API keys configured).")
    last_error = None
    any_key_tried = False
    for idx, key in enumerate(keys):
        cooldown_name = f"groq_{idx}"
        if _is_cooling(cooldown_name):
            continue
        any_key_tried = True
        try:
            yield from _stream_openai_compatible(
                "https://api.groq.com/openai/v1/chat/completions",
                key, "llama-3.3-70b-versatile", messages, state=state,
                temperature=state.pop("temperature", 0.4) if state else 0.4
            )
            return
        except Exception as exc:
            last_error = exc
            _cool(cooldown_name)
            continue
    if not any_key_tried:
        raise RuntimeError("All Groq keys are currently cooling down.")
    raise RuntimeError(f"All Groq keys failed. Last error: {last_error}")
def _stream_openrouter(messages, state=None):
    if not OPENROUTER_API_KEY or _is_cooling("openrouter"):
        raise RuntimeError("OpenRouter unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://openrouter.ai/api/v1/chat/completions",
        OPENROUTER_API_KEY, "meta-llama/llama-3.3-70b-instruct", messages, state=state
    )
def _stream_cerebras(messages, state=None):
    if not CEREBRAS_API_KEY or _is_cooling("cerebras"):
        raise RuntimeError("Cerebras unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://api.cerebras.ai/v1/chat/completions",
        CEREBRAS_API_KEY, "llama3.3-70b", messages, state=state
    )
def _stream_mistral(messages, state=None):
    if not MISTRAL_API_KEY or _is_cooling("mistral"):
        raise RuntimeError("Mistral unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://api.mistral.ai/v1/chat/completions",
        MISTRAL_API_KEY, "mistral-large-latest", messages, state=state
    )
_QWEN_FAST_CHAT_PROMPT = (
    "You are Pratham AI. Answer the user's message directly, naturally, and accurately. "
    "Be concise by default. For coding requests, provide practical runnable code. "
    "Do not invent execution results or claim to have changed files unless the system reports it."
)
_QWEN_CODE_CHAT_PROMPT = (
    "You are Pratham AI, a coding-capable assistant. Follow the user's implementation request precisely. "
    "Preserve relevant filenames, interfaces, constraints, and recent task context. "
    "Return complete syntactically valid code when code is requested. "
    "Do not invent tests, execution results, file writes, or deployments."
)
_QWEN_SIMPLE_HINT_RE = re.compile(
    r"^(hi|hello|hey|yo|thanks|thank you|ok|okay|yes|no|good|cool|nice|who are you|what(?:'|’)s your name|your name)\s*[!?.]*$",
    re.IGNORECASE,
)
_QWEN_CODE_HINT_RE = re.compile(
    r"\b(code|coding|python|javascript|typescript|html|css|sql|json|bash|shell|program|script|function|class|api|endpoint|bug|debug|fix|error|compile|deploy|build|implement|create|edit|modify|website|game|app|file|zip|pdf)\b",
    re.IGNORECASE,
)
_QWEN_SPECIAL_CONTEXT_MARKERS = (
    "EDU_BOOK", "EDU_CHAPTER", "chapter/source material", "uploaded file",
    "file contents", "shared memory", "SEARCH RESULT", "LIVE WEB",
)
def _qwen_last_user_message(messages: list) -> str:
    for item in reversed(messages or []):
        if item.get("role") == "user":
            return str(item.get("content", "") or "")
    return ""
def _qwen_is_simple_request(user_message: str) -> bool:
    text = (user_message or "").strip()
    if not text:
        return True
    if _QWEN_SIMPLE_HINT_RE.match(text):
        return True
    return len(text) <= 48 and not _QWEN_CODE_HINT_RE.search(text)
def _qwen_is_code_request(user_message: str, messages: list) -> bool:
    probe = [user_message or ""]
    for item in (messages or [])[-4:]:
        if item.get("role") in ("user", "assistant"):
            probe.append(str(item.get("content", "") or "")[:800])
    return bool(_QWEN_CODE_HINT_RE.search("\n".join(probe)))
def _qwen_trim_text(text: str, max_chars: int) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    if max_chars <= 260:
        return value[:max_chars]
    head = max(120, max_chars // 2)
    tail = max(80, max_chars - head - 70)
    return value[:head] + "\n...[context compacted]...\n" + value[-tail:]
def _qwen_extract_special_context(system_text: str, limit: int) -> str:
    text = str(system_text or "")
    if not text:
        return ""
    lowered = text.lower()
    found = []
    for marker in _QWEN_SPECIAL_CONTEXT_MARKERS:
        pos = lowered.find(marker.lower())
        if pos >= 0:
            snippet = text[max(0, pos - 160): min(len(text), pos + 800)].strip()
            if snippet:
                found.append(snippet)
    if not found:
        return ""
    unique = []
    seen = set()
    for item in found:
        key = item[:350]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return _qwen_trim_text("\n\n[RELEVANT CONTEXT]\n" + "\n\n".join(unique), limit)
def _qwen_worker_messages(messages: list) -> tuple[list, dict]:
    original = list(messages or [])
    current = _qwen_last_user_message(original)
    simple = _qwen_is_simple_request(current)
    code_request = _qwen_is_code_request(current, original)
    fast = simple and not code_request
    if fast:
        system = _QWEN_FAST_CHAT_PROMPT
        history_limit = QWEN_WORKER_SIMPLE_HISTORY_MESSAGES
        char_budget = QWEN_WORKER_SIMPLE_MAX_CHARS
        system_limit = QWEN_WORKER_SIMPLE_SYSTEM_CHARS
        context_tokens = QWEN_WORKER_SIMPLE_CONTEXT_TOKENS
        max_new_tokens = QWEN_WORKER_SIMPLE_MAX_NEW_TOKENS
    else:
        system = _QWEN_CODE_CHAT_PROMPT if code_request else _QWEN_FAST_CHAT_PROMPT
        history_limit = QWEN_WORKER_CODE_HISTORY_MESSAGES
        char_budget = QWEN_WORKER_CODE_MAX_CHARS
        system_limit = QWEN_WORKER_CODE_SYSTEM_CHARS
        context_tokens = QWEN_WORKER_CODE_CONTEXT_TOKENS
        max_new_tokens = QWEN_WORKER_CODE_MAX_NEW_TOKENS
    original_system = ""
    dialogue = []
    for item in original:
        role = item.get("role", "")
        content = str(item.get("content", "") or "")
        if role == "system" and not original_system:
            original_system = content
        elif role in ("user", "assistant"):
            dialogue.append({"role": role, "content": content})
    if not fast:
        special = _qwen_extract_special_context(original_system, QWEN_WORKER_SPECIAL_CONTEXT_CHAR_LIMIT)
        if special:
            system += "\n" + special
    compact = [{"role": "system", "content": _qwen_trim_text(system, system_limit)}]
    for item in dialogue[-max(1, history_limit):]:
        content = _qwen_trim_text(item["content"], QWEN_WORKER_RECENT_MESSAGE_CHAR_LIMIT)
        if content:
            compact.append({"role": item["role"], "content": content})
    if current.strip():
        if compact[-1].get("role") == "user":
            compact[-1]["content"] = _qwen_trim_text(current, QWEN_WORKER_RECENT_MESSAGE_CHAR_LIMIT)
        else:
            compact.append({"role": "user", "content": _qwen_trim_text(current, QWEN_WORKER_RECENT_MESSAGE_CHAR_LIMIT)})
    def total_chars(items):
        return sum(len(str(x.get("content", "") or "")) for x in items)
    while len(compact) > 2 and total_chars(compact) > char_budget:
        del compact[1]
    return compact, {
        "simple": fast,
        "code_request": code_request,
        "context_tokens": context_tokens,
        "max_new_tokens": max_new_tokens,
        "original_messages": len(original),
        "worker_messages": len(compact),
        "original_chars": total_chars(original),
        "worker_chars": total_chars(compact),
    }
_qwen_user_request_active = 0
_qwen_user_request_lock = threading.Lock()
def _qwen_mark_user_request_active(delta: int) -> None:
    global _qwen_user_request_active
    with _qwen_user_request_lock:
        _qwen_user_request_active = max(0, _qwen_user_request_active + delta)
def _qwen_user_request_is_active() -> bool:
    with _qwen_user_request_lock:
        return _qwen_user_request_active > 0
def _stream_qwen_worker(messages, state=None):
    """Stream from Daytona Qwen with minimal CPU-prefill context and immediate SSE relays."""
    _qwen_mark_user_request_active(1)
    token = _get_expected_worker_token()
    best = _worker_get_latest()
    worker_id = (best or {}).get("worker_id", "none")
    online = _worker_is_online(best)
    live_url = ((best or {}).get("endpoint_url", "").strip().rstrip("/")
                or os.environ.get("QWEN_WORKER_URL", "").strip().rstrip("/"))
    print(
        f"[QWEN] route worker={worker_id} online={online} "
        f"url={'set' if live_url else 'missing'} token={'set' if token else 'missing'}"
    )
    if not live_url or not token or not online:
        age = int(time.time() - (best or {}).get("last_seen_epoch", 0)) if best and best.get("last_seen_epoch") else "N/A"
        raise RuntimeError(
            f"Qwen worker unavailable (url={'set' if live_url else 'missing'}, "
            f"token={'set' if token else 'missing'}, online={online}, worker={worker_id}, age={age}s)"
        )
    worker_messages, meta = _qwen_worker_messages(messages)
    temperature = (state or {}).pop("temperature", 0.1) if state is not None else 0.1
    print(
        "[QWEN] compact -> "
        f"simple={meta['simple']} code={meta['code_request']} "
        f"chars={meta['original_chars']}->{meta['worker_chars']} "
        f"messages={meta['original_messages']}->{meta['worker_messages']} "
        f"ctx={meta['context_tokens']} max_new={meta['max_new_tokens']}"
    )
    target_url = f"{live_url}/v1/chat/stream"
    body = json.dumps({
        "messages": worker_messages,
        "conversation_id": (state or {}).get("conversation_id", ""),
        "max_new_tokens": meta["max_new_tokens"],
        "temperature": temperature,
        "stream": True,
        "keep_alive": -1,
        "num_ctx": meta["context_tokens"],
    }).encode("utf-8")
    req = urllib.request.Request(
        target_url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    started = time.time()
    got_delta = False
    explicit_end = False
    delta_count = 0
    try:
        with urllib.request.urlopen(req, timeout=WORKER_REQUEST_TIMEOUT_SECONDS) as resp:
            print(f"[QWEN] worker HTTP {resp.status}")
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                try:
                    payload = json.loads(line[6:])
                except Exception:
                    continue
                etype = payload.get("type")
                if etype == "thinking":
                    yield _sse({"type": "agent_step", "step_type": "thinking", "label": payload.get("message", "Thinking...")})
                elif etype == "answer_delta":
                    text = payload.get("text", "")
                    if text:
                        got_delta = True
                        delta_count += 1
                        yield _sse({"type": "token", "text": text})
                elif etype == "answer_end":
                    explicit_end = True
                    if state is not None:
                        state["finish_reason"] = payload.get("finish_reason", "stop")
                    break
                elif etype == "error":
                    raise RuntimeError(payload.get("message", "Worker reported an error."))
        if state is not None and got_delta and not state.get("finish_reason"):
            state["finish_reason"] = "stop"
        print(
            f"[QWEN] finished deltas={delta_count} explicit_end={explicit_end} "
            f"elapsed_ms={int((time.time()-started)*1000)}"
        )
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[QWEN] transport error: {exc}")
        if not got_delta:
            raise RuntimeError(f"Pratham AI worker request failed: {exc}")
        if state is not None:
            state["finish_reason"] = "stop"
        return
    finally:
        _worker_touch_latency(worker_id, int((time.time() - started) * 1000))
        _qwen_mark_user_request_active(-1)
def _validate_fenced_blocks(text: str) -> list:
    """Scans the text for createfile/editfile blocks and returns a list of
    (block_type, filename, issues) for any blocks with problems."""
    issues = []
    for m in re.finditer(r'```createfile:(\S+)\n([\s\S]*?)```', text):
        filename = m.group(1).strip()
        content = m.group(2)
        block_issues = []
        if not content.strip():
            block_issues.append("empty file content")
        if _CONFLICT_MARKER_RE.search(content):
            block_issues.append("contains SEARCH/REPLACE markers — use editfile: instead")
        if filename.endswith('.json'):
            try:
                json.loads(content)
            except json.JSONDecodeError as e:
                block_issues.append(f"invalid JSON: {str(e)[:100]}")
        if filename.endswith(('.html', '.htm')):
            open_tags = re.findall(r'<(?!/)(\w+)[^>]*>', content)
            close_tags = re.findall(r'</(\w+)>', content)
            self_closing = {'br', 'img', 'input', 'meta', 'link', 'hr', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}
            open_tags = [t for t in open_tags if t.lower() not in self_closing]
            if len(open_tags) != len(close_tags):
                block_issues.append(f"unbalanced HTML tags: {len(open_tags)} opening, {len(close_tags)} closing")
        if filename.endswith('.py'):
            try:
                import ast as _ast
                _ast.parse(content)
            except SyntaxError as e:
                block_issues.append(f"Python syntax error: {str(e)[:100]}")
        if block_issues:
            issues.append(("createfile", filename, block_issues))
    for m in re.finditer(r'```editfile:(\S+)\n([\s\S]*?)```', text):
        filename = m.group(1).strip()
        content = m.group(2)
        block_issues = []
        if not _EDIT_BLOCK_RE.search(content):
            block_issues.append("no SEARCH/REPLACE pairs found")
        if block_issues:
            issues.append(("editfile", filename, block_issues))
    return issues
def _build_block_validation_feedback(text: str) -> str:
    """Validates fenced blocks in the text and returns a feedback string
    for the model if issues are found, or None if everything is clean."""
    issues = _validate_fenced_blocks(text)
    if not issues:
        return None
    feedback_parts = ["[BLOCK VALIDATION ISSUES — fix these before finishing:]"]
    for block_type, filename, block_issues in issues:
        for issue in block_issues:
            feedback_parts.append(f"- {block_type} {filename}: {issue}")
    return "\n".join(feedback_parts)
_SUMMARY_TRIGGER_COUNT = 20                                               
_SUMMARY_KEEP_RECENT = 12                                             
_conversation_summaries: dict = {}                                             
def _summarize_old_messages(messages: list, conv_id: str = None) -> list:
    """If the message history is too long, summarize older messages and
    prepend the summary. Returns a new message list with manageable length."""
    if len(messages) <= _SUMMARY_TRIGGER_COUNT:
        return messages
    old_msgs = messages[:-_SUMMARY_KEEP_RECENT]
    recent_msgs = messages[-_SUMMARY_KEEP_RECENT:]
    cached = _conversation_summaries.get(conv_id) if conv_id else None
    if cached:
        summary_text = cached
    else:
        summary_parts = ["[CONVERSATION HISTORY SUMMARY — earlier messages condensed to preserve context:]"]
        for m in old_msgs:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if len(content) > 300:
                content = content[:300] + "... [truncated]"
            summary_parts.append(f"[{role}]: {content}")
        summary_parts.append("[END SUMMARY — recent messages follow:]")
        summary_text = "\n".join(summary_parts)
        if conv_id:
            _conversation_summaries[conv_id] = summary_text
    return [{"role": "system", "content": summary_text}] + recent_msgs
_PROVIDER_CHAIN = [("google_gemini_oauth", _stream_google_oauth_gemini)]
_MAX_AUTO_CONTINUATIONS = 6                                                                     
def _do_stream(messages):
    """Streams a reply from the first available provider, then — this is
    the fix for "it stops making the HTML in the middle" — automatically
    detects when the provider cut the response short purely because it hit
    its token limit (finish_reason == 'length', NOT a real stop) and keeps
    requesting continuations from the SAME provider, feeding back exactly
    what's been generated so far and asking it to continue seamlessly with
    no repetition, until the response actually finishes normally or the
    continuation cap is hit. The continued tokens are streamed to the
    frontend exactly like the original ones, so a file that would have been
    cut off mid-file now keeps going until it's actually complete."""
    _failure_log = []                                                                                
    for name, fn in _PROVIDER_CHAIN:
        state = {"temperature": getattr(_do_stream, '_current_temperature', 0.4)}
        accumulated_text = []
        any_token_yielded = False
        working_messages = list(messages)
        continuation_count = 0
        try:
            while True:
                state.clear()
                got_tokens_this_round = False
                for chunk in fn(working_messages, state=state):
                    any_token_yielded = True
                    got_tokens_this_round = True
                    try:
                        payload = json.loads(chunk[6:]) if chunk.startswith("data: ") else None
                        if payload and payload.get("type") == "token":
                            accumulated_text.append(payload["text"])
                    except Exception:
                        pass
                    yield chunk
                if not got_tokens_this_round:
                    break
                if state.get("finish_reason") != "length":
                    break
                if continuation_count >= _MAX_AUTO_CONTINUATIONS:
                    break
                continuation_count += 1
                working_messages = list(messages) + [
                    {"role": "assistant", "content": "".join(accumulated_text)},
                    {"role": "user", "content": (
                        "Continue exactly where you left off. Do not repeat any earlier text, do not "
                        "restart the file/answer, and do not add any preamble like 'continuing...' — "
                        "just keep producing the remaining content seamlessly as if it were never "
                        "interrupted. If you were mid-file inside a fenced code/createfile block, "
                        "resume inside that same block."
                    )}
                ]
            if any_token_yielded:
                yield _sse({"type": "complete"})
                return
        except Exception as exc:
            err_str = str(exc) or exc.__class__.__name__
            print(f"[FAILOVER] {name} dropped: {err_str}")
            _failure_log.append((name, err_str))
            if any_token_yielded:
                yield _sse({"type": "complete"})
                return
            _cool(name)
            continue
    print(f"[FAILOVER] ALL PROVIDERS FAILED: {_failure_log}")
    last_err = _failure_log[0][1] if _failure_log else "Gemini unavailable"
    if str(last_err).startswith("GEMINI_RECONNECT_REQUIRED") or str(last_err) == "GEMINI_AUTH_REQUIRED":
        code = "GEMINI_RECONNECT_REQUIRED"
        friendly = "Gemini is not connected to this PrathamAI session. Open Settings → Connect Gemini and authorize the Google account again."
    elif not GOOGLE_CLOUD_PROJECT_ID:
        code = "GEMINI_SERVER_CONFIG"
        friendly = "GOOGLE_CLOUD_PROJECT_ID is missing on the backend. Configure the Google Cloud project first."
    else:
        code = "GEMINI_REQUEST_FAILED"
        friendly = f"Gemini request failed: {last_err}"
    yield _sse({"type":"error","error":{"code":code,"message":friendly}})
    yield _sse({"type":"complete"})

_EXECUTABLE_LANGS = {"python", "py", "bash", "sh", "shell"}
_CODE_BLOCK_RE = re.compile(r"```(\w+)?\n([\s\S]*?)```")
_TERMINAL_MAX_ITERATIONS = 4                                                                     
_TERMINAL_BLOCK_TIMEOUT = 30                                                                            
_TERMINAL_OUTPUT_CHAR_LIMIT = 200000                                                                
_CREATEFILE_RE = re.compile(r"```createfile:([^\n`]+)\n([\s\S]*?)```")
_MULTI_STEP_INTENT_RE = re.compile(
    r"\b(build|create|make|write|develop|design|implement|set up|generate|produce)"
    r".{0,80}\b(and|with|including|that|which|also|plus|as well as)\b"
    r"|\b(full|complete|entire|whole)\b.{0,30}\b(app|website|system|project|program|application|tool|file|document)\b"
    r"|\b(step by step|step-by-step|multiple|several|many|lot of)\b",
    re.IGNORECASE
)
_TASK_CHECKBOX_RE = re.compile(r"^[-*]\s+\[[ xX]\]\s+(.+)$", re.MULTILINE)
def _extract_task_items_from_text(text: str) -> list:
    """Extracts task items from - [ ] or - [x] checkbox lines in the text.
    Returns [(task_id, label, is_done), ...]. task_id is derived from the
    normalized label text (not positional index) — this matters because the
    model is instructed to re-print the SAME checklist with boxes checked
    off as it completes each step, so the same label appears multiple times
    across the growing response. Keying by position gave each reprint a
    brand-new task_id (5 real steps -> 10 "tasks" once the model reprinted
    them all checked), which is what caused doubled/duplicate task lists."""
    tasks = []
    seen_ids = set()
    for m in _TASK_CHECKBOX_RE.finditer(text):
        label = m.group(1).strip()
        is_done = m.group(0)[3] in ('x', 'X')
        task_id = "task_" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:60]
        if task_id in seen_ids:
            tasks = [t for t in tasks if t[0] != task_id]
        seen_ids.add(task_id)
        tasks.append((task_id, label, is_done))
    return tasks
def _extract_createfile_blocks(text: str):
    """Returns [(filename, content), ...] for every ```createfile:name block
    in `text`, in the order they appear."""
    out = []
    for m in _CREATEFILE_RE.finditer(text):
        filename = m.group(1).strip().replace("..", "").lstrip("/")
        if filename:
            out.append((filename, m.group(2)))
    return out
def _write_direct_file(workdir: str, filename: str, content: str) -> dict:
    """Actually writes the file to the real scratch directory (creating any
    subfolders implied by the filename), and returns its real path/size —
    this is genuine disk I/O in the same working directory python/bash
    blocks in this request use, not a simulation."""
    full_path = os.path.join(workdir, filename)
    os.makedirs(os.path.dirname(full_path) or workdir, exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"filename": filename, "size_bytes": len(content.encode("utf-8")), "line_count": content.count("\n") + 1, "path": full_path}
_EDITFILE_RE = re.compile(r"```editfile:([^\n`]+)\n([\s\S]*?)```")
_EDIT_BLOCK_RE = re.compile(
    r"<{5,}\s*SEARCH\s*\n([\s\S]*?)\n={5,}\s*\n([\s\S]*?)\n>{5,}\s*REPLACE",
    re.IGNORECASE
)
_CONFLICT_MARKER_RE = re.compile(r"<{5,}\s*SEARCH|>{5,}\s*REPLACE", re.IGNORECASE)
def _extract_editfile_blocks(text: str):
    """Returns [(filename, [(search_text, replace_text), ...]), ...] for
    every ```editfile:name block in `text`."""
    out = []
    for m in _EDITFILE_RE.finditer(text):
        filename = m.group(1).strip().replace("..", "").lstrip("/")
        if not filename:
            continue
        body = m.group(2)
        pairs = [(sm.group(1), sm.group(2)) for sm in _EDIT_BLOCK_RE.finditer(body)]
        if pairs:
            out.append((filename, pairs))
    return out
def _find_last_file_content_in_history(history: list, filename: str):
    """Scans this conversation's own past assistant messages (most recent
    first) for the last time `filename` was created or edited, and
    reconstructs its current full content — either from a ```createfile:
    block that wrote it, or by replaying any earlier ```editfile: edits on
    top of the createfile version. Returns None if the file was never seen
    in this conversation, so the caller can tell the model to createfile it
    fresh instead."""
    base_content = None
    base_index = None
    for i in range(len(history) - 1, -1, -1):
        m = history[i]
        if m.get("role") != "assistant":
            continue
        for fname, content in _extract_createfile_blocks(m.get("content", "")):
            if fname == filename:
                base_content = content
                base_index = i
                break
        if base_content is not None:
            break
    if base_content is None:
        return None
    content = base_content
    for i in range(base_index + 1, len(history)):
        m = history[i]
        if m.get("role") != "assistant":
            continue
        for fname, pairs in _extract_editfile_blocks(m.get("content", "")):
            if fname != filename:
                continue
            for search_text, replace_text in pairs:
                if search_text in content:
                    content = content.replace(search_text, replace_text, 1)
    return content
def _apply_editfile_edits(base_content: str, pairs: list):
    """Applies each (search, replace) pair once, in order, against
    `base_content`. Returns (new_content, list_of_warnings) — a warning is
    recorded (not raised) for any search snippet that couldn't be found, so
    one bad match doesn't silently discard the rest of a multi-edit block."""
    content = base_content
    warnings = []
    for idx, (search_text, replace_text) in enumerate(pairs, start=1):
        if search_text in content:
            content = content.replace(search_text, replace_text, 1)
        else:
            warnings.append(f"Edit #{idx}: search text not found, skipped.")
    return content, warnings
def _extract_executable_blocks(text: str):
    """Returns a list of (lang, code) for every fenced block whose language
    tag is one we know how to actually execute."""
    out = []
    for m in _CODE_BLOCK_RE.finditer(text):
        lang = (m.group(1) or "").lower()
        if lang in _EXECUTABLE_LANGS:
            out.append((lang, m.group(2)))
    return out
def _compute_diff_stats(old_content: str, new_content: str) -> dict:
    """Real diff engine (stdlib difflib) for editfile operations. Returns
    added/removed line counts plus a unified-diff string, so the frontend
    activity card can show a genuine '+N -N' badge instead of a guess."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    added = removed = 0
    for line in difflib.ndiff(old_lines, new_lines):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    unified = "".join(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    return {"added": added, "removed": removed, "unified_diff": unified}
EXECUTOR_URL = os.environ.get("EXECUTOR_URL", "").strip().rstrip("/")
EXECUTOR_SECRET = os.environ.get("EXECUTOR_SECRET", "").strip()
EXECUTOR_CONFIGURED = bool(EXECUTOR_URL and EXECUTOR_SECRET)
def _extract_pdf_text_via_remote_ocr(pdf_bytes: bytes, lang: str = "hin+eng") -> str:
    """Calls your Ubuntu Railway box's /ocr endpoint (see executor_service.py)
    to OCR a PDF with no real text layer — Vercel's Python runtime has no
    tesseract binary and can't install one, so this has to run on a real
    persistent box instead. Returns "" on any failure (not configured,
    network error, OCR deps missing on that box, etc.) so callers can
    treat it the same as any other extraction miss."""
    if not EXECUTOR_CONFIGURED:
        return ""
    try:
        payload = json.dumps({
            "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "lang": lang,
        }).encode()
        req = urllib.request.Request(
            f"{EXECUTOR_URL}/ocr", data=payload, method="POST",
            headers={"Content-Type": "application/json", "X-Exec-Secret": EXECUTOR_SECRET}
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        if data.get("error"):
            print(f"[EDU][OCR][REMOTE FAULT] {data['error']}")
            return ""
        return data.get("text", "")
    except Exception as exc:
        print(f"[EDU][OCR][REMOTE FAULT] {exc}")
        return ""
def _run_code_block_remote(lang: str, code: str, cwd: str = None):
    """Sends the block to your Ubuntu box's /execute endpoint (see
    executor_service.py) instead of running it in this serverless function.
    Returns (stdout, stderr, returncode, ok) — ok=False means the remote
    call itself failed (not the command), so the caller can fall back."""
    try:
        if lang in ("python", "py"):
            command = f"{shlex.quote(sys.executable)} -u -c {shlex.quote(code)}"
        else:
            command = code
        payload = json.dumps({"command": command, "cwd": cwd or "/tmp/workdir", "timeout": 60}).encode()
        req = urllib.request.Request(
            f"{EXECUTOR_URL}/execute", data=payload, method="POST",
            headers={"Content-Type": "application/json", "X-Exec-Secret": EXECUTOR_SECRET}
        )
        with urllib.request.urlopen(req, timeout=65) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        return (
            data.get("stdout", "")[-_TERMINAL_OUTPUT_CHAR_LIMIT:],
            data.get("stderr", "")[-_TERMINAL_OUTPUT_CHAR_LIMIT:],
            data.get("returncode", -1),
            True,
        )
    except Exception as exc:
        print(f"[EXECUTOR][REMOTE FAULT] falling back to local exec: {exc}")
        return "", "", -1, False
def _run_code_block(lang: str, code: str, cwd: str = None):
    """Actually executes one code block in the background terminal and
    returns (stdout, stderr, returncode). This is real execution, not a
    simulation — whatever the code does (compute, read/write files in `cwd`,
    hit the network, etc.) really happens on the server.
    `cwd` should point at a writable scratch directory (see `_new_terminal_workdir`
    below). Without it, execution defaults to the process's own working
    directory, which is read-only on several hosting platforms (serverless
    functions, some container images) — that's what causes errors like
    "touch: cannot create file" or "Read-only file system" that the model
    would otherwise have no way to work around.
    """
    if EXECUTOR_CONFIGURED:
        stdout, stderr, rc, ok = _run_code_block_remote(lang, code, cwd)
        if ok:
            return stdout, stderr, rc
    try:
        if lang in ("python", "py"):
            cmd = [sys.executable, "-u", "-c", code]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_TERMINAL_BLOCK_TIMEOUT, cwd=cwd
            )
        else:                     
            shell_bin = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
            cmd = [shell_bin, "-c", code]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_TERMINAL_BLOCK_TIMEOUT, cwd=cwd
            )
        return (
            result.stdout[-_TERMINAL_OUTPUT_CHAR_LIMIT:],
            result.stderr[-_TERMINAL_OUTPUT_CHAR_LIMIT:],
            result.returncode,
        )
    except subprocess.TimeoutExpired:
        return "", f"Execution timed out after {_TERMINAL_BLOCK_TIMEOUT} seconds.", -1
    except FileNotFoundError as exc:
        return "", f"Execution failed: required interpreter not found ({exc}).", -1
    except Exception as exc:
        return "", f"Execution failed: {exc}", -1
def _new_terminal_workdir() -> str:
    """Creates a fresh, guaranteed-writable scratch directory for one
    chat-stream request's terminal session. All executed blocks AND all
    ```createfile: blocks within that same request share this directory, so
    a file written in one block (e.g. step 1 generates data.csv, or a
    createfile block writes config.json) can be read by a later block (step
    2 processes data.csv) within the same multi-step agent loop."""
    return tempfile.mkdtemp(prefix="pratham_ai_terminal_")
def _cleanup_terminal_workdir(path: str):
    if path:
        shutil.rmtree(path, ignore_errors=True)
_DIAGNOSTIC_INTENT_RE = re.compile(
    r"\b(system status|diagnostic|terminal (status|working)|is (the )?terminal working|"
    r"memory status|is memory working|check status|health check|status check)\b",
    re.IGNORECASE
)
_MEMORY_QUERY_INTENT_RE = re.compile(
    r"\b(what'?s\s+in\s+memory|what\s+do\s+you\s+know|search\s+memory\s+for|list\s+memory\s+about|"
    r"show\s+saved\s+facts|search\s+memory|list\s+memory)\b",
    re.IGNORECASE
)
def _run_system_diagnostics() -> str:
    lines = ["**Pratham AI — live system diagnostics** (creator-only, just measured)\n"]
    workdir = _new_terminal_workdir()
    try:
        out, err, rc = _run_code_block("python", "print(2 + 2)", cwd=workdir)
        python_ok = (rc == 0 and out.strip() == "4")
    except Exception as exc:
        python_ok, out, err = False, "", str(exc)
    lines.append(f"- Python terminal: {'✅ working' if python_ok else '❌ NOT working'} (exit handling verified: `print(2+2)` -> `{out.strip()}`{f', stderr: {err.strip()[:150]}' if err.strip() else ''})")
    try:
        probe_path = os.path.join(workdir, "probe.txt")
        out, err, rc = _run_code_block("bash", f"echo hello > {probe_path} && cat {probe_path}", cwd=workdir)
        shell_ok = (rc == 0 and "hello" in out)
    except Exception as exc:
        shell_ok, err = False, str(exc)
    lines.append(f"- Shell terminal + writable scratch dir: {'✅ working' if shell_ok else '❌ NOT working'}{f' ({err.strip()[:150]})' if not shell_ok and err else ''}")
    try:
        written = _write_direct_file(workdir, "diagnostic_probe.txt", "createfile channel test")
        createfile_ok = os.path.isfile(written["path"]) and written["size_bytes"] > 0
    except Exception as exc:
        createfile_ok = False
    lines.append(f"- Direct createfile channel: {'✅ working' if createfile_ok else '❌ NOT working'}")
    _cleanup_terminal_workdir(workdir)
    lines.append(f"- GITHUB_TOKEN configured: {'✅ yes' if bool(GITHUB_TOKEN) else '❌ no (memory + logs cannot persist without this)'}")
    shared_text = _fetch_full_public_data_text()
    lines.append(f"- Shared memory (public_data.txt) readable: {'✅ yes' if shared_text else '⚠️ empty or unreachable'} ({len(shared_text)} chars cached)")
    try:
        test_pdf = _write_minimal_pdf("diagnostic test")
        pdf_ok = test_pdf[:4] == b"%PDF"
    except Exception:
        pdf_ok = False
    lines.append(f"- PDF generation (built-in, no fpdf2/pandoc needed): {'✅ working' if pdf_ok else '❌ NOT working'}")
    extractor_list = []
    if _FITZ_SUPPORTED: extractor_list.append("PyMuPDF/fitz (best for Devanagari)")
    if _PDFPLUMBER_SUPPORTED: extractor_list.append("pdfplumber")
    if _PDF_READ_SUPPORTED: extractor_list.append("pypdf/PyPDF2 (weak on Devanagari)")
    lines.append(f"- PDF text extractors installed: {', '.join(extractor_list) if extractor_list else '❌ none — @education PDF reading will not work'}")
    provider_flags = {
        "Groq": bool(GROQ_API_KEYS), "OpenRouter": bool(OPENROUTER_API_KEY),
        "Cerebras": bool(CEREBRAS_API_KEY), "Mistral": bool(MISTRAL_API_KEY)
    }
    configured = [name for name, ok in provider_flags.items() if ok]
    lines.append(f"- LLM providers configured: {', '.join(configured) if configured else '❌ none — chat will not work'}")
    lines.append(f"- Groq keys configured: {len(GROQ_API_KEYS)} (each rotates independently on rate-limit/cooldown)")
    lines.append(f"- Supabase persistent storage: {'✅ connected' if SUPABASE_CONFIGURED else '⚠️ not configured (falling back to in-memory, wiped on restart)'}")
    return "\n".join(lines)
def _analyze_code_error(lang: str, code: str, stderr: str, returncode: int) -> str:
    """Analyzes a code execution error and returns targeted debugging hints
    to help the model fix it correctly on the next try, instead of just
    feeding back raw stderr and hoping the model figures it out."""
    if returncode == 0:
        return ""
    hints = []
    stderr_lower = stderr.lower()
    if lang in ("python", "py"):
        if "namerror" in stderr_lower or "nameerror" in stderr_lower:
            name_match = re.search(r"""name ['"](.+?)['"] is not defined""", stderr, re.IGNORECASE)
            if name_match:
                hints.append(f"HINT: '{name_match.group(1)}' is not defined — you need to import it or define it before using it.")
            else:
                hints.append("HINT: You referenced a name that isn\'t defined. Check for typos or missing imports.")
        elif "modulenotfounderror" in stderr_lower or "nomodule" in stderr_lower:
            hints.append("HINT: A required module is not installed. This sandbox only has the Python stdlib — rewrite your code to use only stdlib modules (os, sys, json, re, math, etc.).")
        elif "syntaxerror" in stderr_lower:
            hints.append("HINT: Syntax error. Check for: missing colons, unbalanced parentheses/brackets, incorrect indentation, or string quote issues.")
        elif "typeerror" in stderr_lower:
            hints.append("HINT: Type error. Check that you\'re not mixing incompatible types (e.g. str + int). Consider using str() or int() to convert.")
        elif "indexerror" in stderr_lower:
            hints.append("HINT: Index out of range. Check your list/string indices — the index is larger than the container length minus 1.")
        elif "keyerror" in stderr_lower:
            key_match = re.search(r"""['"](.+?)['"]""", stderr)
            if key_match:
                hints.append(f"HINT: Key '{key_match.group(1)}' not found in dict. Check the actual keys with list(your_dict.keys()).")
        elif "zerodivisionerror" in stderr_lower:
            hints.append("HINT: Division by zero. Add a check before dividing.")
        elif "filenotfounderror" in stderr_lower:
            hints.append("HINT: File not found. Check the file path — use os.path.exists() to verify before opening. The working directory is the terminal scratch dir.")
        elif "permissionerror" in stderr_lower:
            hints.append("HINT: Permission denied. The file or directory may not be writable. Try writing to the current working directory instead.")
        elif "indentationerror" in stderr_lower:
            hints.append("HINT: Indentation error. Python uses consistent indentation (4 spaces recommended). Check for mixed tabs and spaces.")
        elif "attributeerror" in stderr_lower:
            attr_match = re.search(r"""has no attribute ['"](.+?)['"]""", stderr, re.IGNORECASE)
            if attr_match:
                hints.append(f"HINT: Attribute '{attr_match.group(1)}' doesn\'t exist. Check the object type and its available methods.")
        elif "timeout" in stderr_lower:
            hints.append("HINT: Execution timed out (30s limit). Your code may have an infinite loop or is waiting for input. Avoid input() calls and infinite loops.")
        elif "urlopen" in stderr_lower or "urlerror" in stderr_lower or "connection" in stderr_lower:
            hints.append("HINT: Network error. This sandbox may not have internet access. Avoid network calls — use local data or stdlib alternatives.")
    elif lang in ("bash", "sh", "shell"):
        if "command not found" in stderr_lower:
            cmd_match = re.search(r"([\w.-]+): command not found", stderr)
            if cmd_match:
                hints.append(f"HINT: '{cmd_match.group(1)}' command not found. This sandbox is minimal — use Python instead of external CLI tools.")
        elif "no such file or directory" in stderr_lower:
            hints.append("HINT: File or directory not found. Check paths with ls or pwd. The working directory is the terminal scratch dir.")
        elif "permission denied" in stderr_lower:
            hints.append("HINT: Permission denied. Try chmod or use a different path in the working directory.")
        elif "syntax error" in stderr_lower:
            hints.append("HINT: Shell syntax error. Check for unbalanced quotes, missing semicolons, or incorrect variable syntax ($var vs ${var}).")
    if not hints:
        last_lines = [l for l in stderr.strip().split("\n") if l.strip()][-3:]
        if last_lines:
            hints.append(f"HINT: The error appears to be: {' | '.join(last_lines)}. Read the stderr above carefully and fix the specific issue.")
    return "\n".join(hints)
def _format_terminal_results_for_model(results):
    """Turns a list of {lang, code, stdout, stderr, returncode} dicts into a
    plain-text block the model can read, with targeted debugging hints when
    execution fails, so the model can fix errors correctly on the next try."""
    lines = ["[BACKGROUND TERMINAL RESULTS]"]
    for i, r in enumerate(results, start=1):
        status = "SUCCESS (exit 0)" if r["returncode"] == 0 else f"FAILED (exit code {r['returncode']})"
        lines.append(f"\n--- Block {i} ({r['lang']}) | {status} ---")
        if r["code"]:
            code_preview = r["code"][:500] + ("..." if len(r["code"]) > 500 else "")
            lines.append(f"code:\n{code_preview}")
        if r["stdout"]:
            lines.append(f"stdout:\n{r['stdout']}")
        if r["stderr"]:
            lines.append(f"stderr (check for errors):\n{r['stderr']}")
        if not r["stdout"] and not r["stderr"]:
            lines.append("(no output — command ran silently)")
        if r["returncode"] != 0:
            hints = _analyze_code_error(r["lang"], r["code"], r["stderr"], r["returncode"])
            if hints:
                lines.append(f"\n[DEBUGGING HINTS]\n{hints}")
    lines.append(
        "\n[/BACKGROUND TERMINAL RESULTS]\n"
        "IMPORTANT: These are the REAL execution results from your code — not simulated. "
        "If exit code is 0 and the output looks correct, the task succeeded. "
        "If there were errors (non-zero exit, error in stderr), READ THE DEBUGGING HINTS above "
        "and fix the specific issue in your next code block — don\'t just retry the same code. "
        "Once everything needed is complete, give a clear final plain-language answer instead of running more code."
    )
    return "\n".join(lines)
def _user_id():
    return getattr(request, "current_user", {}).get("sub", "anonymous")
def _user_email():
    return getattr(request, "current_user", {}).get("email", "anonymous_user@local.domain")
def _get_convo(conv_id):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            r = _supabase.table("conversations").select("*").eq("id", conv_id).single().execute()
            return r.data
        except Exception:
            pass
    return _mem_convos.get(conv_id)
def _save_convo(conv):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            _supabase.table("conversations").upsert(conv).execute()
            return
        except Exception:
            pass
    _mem_convos[conv["id"]] = conv
def _list_convos(user_id):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            r = _supabase.table("conversations").select("id,title,pinned,created_at,updated_at").eq("user_id", user_id).order("updated_at", desc=True).execute()
            return r.data or []
        except Exception:
            pass
    return [
        {"id": v["id"], "title": v.get("title", "Untitled"), "pinned": v.get("pinned", False),
         "created_at": v.get("created_at"), "updated_at": v.get("updated_at")}
        for v in _mem_convos.values() if v.get("user_id") == user_id
    ]
def _get_messages(conv_id):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            r = _supabase.table("messages").select("role,content,created_at").eq("conversation_id", conv_id).order("created_at").execute()
            return r.data or []
        except Exception:
            pass
    return _mem_convos.get(conv_id, {}).get("messages", [])
def _append_message(conv_id, role, content):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            _supabase.table("messages").insert({
                "id": str(uuid.uuid4()), "conversation_id": conv_id, "role": role,
                "content": content, "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()
        except Exception:
            pass
    conv = _mem_convos.get(conv_id)
    if conv:
        conv.setdefault("messages", []).append({"role": role, "content": content})
        conv["updated_at"] = datetime.now(timezone.utc).isoformat()
@app.route("/", methods=["GET"])
@app.route("/api", methods=["GET"])
@app.route("/api/app", methods=["GET"])
def index_root():
    return jsonify({"message": "Pratham AI backend active"})
def _gemini_access_token_from_request():
    token=request.headers.get(GEMINI_ACCESS_TOKEN_HEADER, "").strip()
    return token[7:].strip() if token.lower().startswith("bearer ") else token

def _gemini_token_fingerprint(token,email):
    return hmac.new(SESSION_SECRET.encode(), f"{str(email).lower()}\n{token}".encode(), hashlib.sha256).hexdigest()

def _gemini_tokeninfo(token):
    if not token: return None
    try:
        q=urllib.parse.urlencode({"access_token":token})
        req=urllib.request.Request(f"https://oauth2.googleapis.com/tokeninfo?{q}", method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp: return json.loads(resp.read().decode('utf-8',errors='replace'))
    except Exception as exc:
        print(f"[GEMINI][TOKENINFO] {exc}")
        return None

def _require_gemini_connection():
    token=_gemini_access_token_from_request(); user=getattr(request,'current_user',{}) or {}
    if not token: return None,(jsonify({"error":{"code":"GEMINI_AUTH_REQUIRED","message":"Connect Gemini in Settings before using Gemini."}}),401)
    binding=request.cookies.get('pratham_gemini_binding','')
    expected=_gemini_token_fingerprint(token,user.get('email',''))
    if not binding or not hmac.compare_digest(binding,expected):
        return None,(jsonify({"error":{"code":"GEMINI_RECONNECT_REQUIRED","message":"Reconnect Gemini in Settings so this Google OAuth session is bound to your PrathamAI account."}}),401)
    return token,None

@app.route('/auth/gemini/config',methods=['GET','OPTIONS'])
@app.route('/api/auth/gemini/config',methods=['GET','OPTIONS'])
@app.route('/api/app/auth/gemini/config',methods=['GET','OPTIONS'])
def gemini_oauth_config():
    if request.method=='OPTIONS': return _cors_preflight()
    return jsonify({"ok":True,"client_id":GOOGLE_GEMINI_OAUTH_CLIENT_ID,"scopes":GEMINI_OAUTH_SCOPES,"project_configured":bool(GOOGLE_CLOUD_PROJECT_ID),"chat_model":GEMINI_CHAT_MODEL,"image_model":GEMINI_IMAGE_MODEL})

@app.route('/auth/gemini/connect',methods=['POST','OPTIONS'])
@app.route('/api/auth/gemini/connect',methods=['POST','OPTIONS'])
@app.route('/api/app/auth/gemini/connect',methods=['POST','OPTIONS'])
@require_auth
def gemini_oauth_connect():
    if request.method=='OPTIONS': return _cors_preflight()
    if not GOOGLE_CLOUD_PROJECT_ID: return jsonify({"error":{"code":"GEMINI_SERVER_CONFIG","message":"GOOGLE_CLOUD_PROJECT_ID is not configured on the backend."}}),503
    token=_gemini_access_token_from_request(); info=_gemini_tokeninfo(token)
    if not info: return jsonify({"error":{"code":"GEMINI_INVALID_TOKEN","message":"Google rejected the Gemini OAuth access token."}}),401
    app_email=_user_email().lower(); token_email=str(info.get('email','')).lower()
    if token_email and token_email!=app_email: return jsonify({"error":{"code":"GEMINI_ACCOUNT_MISMATCH","message":"The Gemini Google account must match the account signed into PrathamAI."}}),403
    scopes=str(info.get('scope',''))
    if not ('https://www.googleapis.com/auth/cloud-platform' in scopes or 'https://www.googleapis.com/auth/generative-language.retriever' in scopes): return jsonify({"error":{"code":"GEMINI_SCOPE_MISSING","message":"The Google authorization did not grant a Gemini/Cloud scope."}}),403
    response=jsonify({"ok":True,"connected":True,"account_email":token_email or app_email,"expires_in":int(info.get('expires_in',3600) or 3600),"project_id":GOOGLE_CLOUD_PROJECT_ID})
    response.set_cookie('pratham_gemini_binding',_gemini_token_fingerprint(token,app_email),max_age=min(3600,max(300,int(info.get('expires_in',3600) or 3600))),secure=True,httponly=True,samesite='Lax',path='/')
    return response

@app.route('/auth/gemini/status',methods=['GET','OPTIONS'])
@app.route('/api/auth/gemini/status',methods=['GET','OPTIONS'])
@app.route('/api/app/auth/gemini/status',methods=['GET','OPTIONS'])
@require_auth
def gemini_oauth_status():
    if request.method=='OPTIONS': return _cors_preflight()
    token=_gemini_access_token_from_request()
    if not token: return jsonify({"ok":True,"connected":False,"configured":bool(GOOGLE_CLOUD_PROJECT_ID)})
    info=_gemini_tokeninfo(token)
    if not info: return jsonify({"ok":True,"connected":False,"configured":bool(GOOGLE_CLOUD_PROJECT_ID)})
    binding=request.cookies.get('pratham_gemini_binding',''); expected=_gemini_token_fingerprint(token,_user_email())
    return jsonify({"ok":True,"connected":bool(binding and hmac.compare_digest(binding,expected)),"configured":bool(GOOGLE_CLOUD_PROJECT_ID),"account_email":info.get('email'),"expires_in":int(info.get('expires_in',0) or 0)})

@app.route('/auth/gemini/disconnect',methods=['POST','OPTIONS'])
@app.route('/api/auth/gemini/disconnect',methods=['POST','OPTIONS'])
@app.route('/api/app/auth/gemini/disconnect',methods=['POST','OPTIONS'])
@require_auth
def gemini_oauth_disconnect():
    if request.method=='OPTIONS': return _cors_preflight()
    response=jsonify({"ok":True,"connected":False})
    response.set_cookie('pratham_gemini_binding','',max_age=0,secure=True,httponly=True,samesite='Lax',path='/')
    return response

@app.route("/auth/exchange", methods=["POST", "OPTIONS"])
@app.route("/api/auth/exchange", methods=["POST", "OPTIONS"])
@app.route("/api/app/auth/exchange", methods=["POST", "OPTIONS"])
def auth_exchange():
    """
    Takes the Authorization header (expected to be the raw Google ID token
    from the just-completed sign-in) and exchanges it for a long-lived
    backend session token. This is the real fix for "signed out again after
    closing the browser": Google's own ID token only lasts about an hour,
    but the token this returns lasts SESSION_TOKEN_TTL_DAYS days.
    """
    if request.method == "OPTIONS":
        return _cors_preflight()
    token = _get_token()
    user = _verify_token(token)
    if not user:
        return jsonify({"error": "Could not verify the provided sign-in token."}), 401
    session_token = _issue_session_token(user)
    return jsonify({"ok": True, "session_token": session_token, "user": user, "expires_in_days": SESSION_TOKEN_TTL_DAYS})
@app.route("/auth/refresh-check", methods=["POST", "OPTIONS"])
@app.route("/api/auth/refresh-check", methods=["POST", "OPTIONS"])
@app.route("/api/app/auth/refresh-check", methods=["POST", "OPTIONS"])
def refresh_check():
    """
    Lets the frontend silently verify a token it kept in localStorage after
    a page refresh, WITHOUT forcing the user through the Google popup again.
    Returns the same user profile shape the frontend already knows how to
    render, or 401 if the stored token has actually expired.
    """
    if request.method == "OPTIONS":
        return _cors_preflight()
    token = _get_token()
    user = _verify_token(token)
    if not user:
        return jsonify({"error": "Stored session expired."}), 401
    return jsonify({"ok": True, "user": user})
@app.route("/auth/vip-status", methods=["GET", "OPTIONS"])
@app.route("/api/auth/vip-status", methods=["GET", "OPTIONS"])
@app.route("/api/app/auth/vip-status", methods=["GET", "OPTIONS"])
@require_auth
def vip_status():
    if request.method == "OPTIONS":
        return _cors_preflight()
    record = _lookup_vip(_user_email())
    if record:
        return jsonify({"is_vip": True, "name": record.get("name", ""), "relationship": record.get("relationship", "")})
    return jsonify({"is_vip": False})
@app.route("/auth/vip-register", methods=["POST", "OPTIONS"])
@app.route("/api/auth/vip-register", methods=["POST", "OPTIONS"])
@app.route("/api/app/auth/vip-register", methods=["POST", "OPTIONS"])
@require_auth
def register_vip_profile():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    relationship = body.get("relationship", "").strip()
    email = body.get("email", _user_email()).strip()
    if not name or not relationship:
        return jsonify({"error": "Missing required fields."}), 400
    registration_row = f"Timestamp: {datetime.now(timezone.utc).isoformat()} | Email: {email} | Name: {name} | Relation: {relationship}\n"
    success = _write_to_github_repository("data/vip.txt", registration_row)
    if success:
        _vip_cache["t"] = 0                                                
    return jsonify({"ok": success, "status": "committed" if success else "local fallback"})
@app.route("/chat", methods=["POST", "OPTIONS"])
@app.route("/api/chat", methods=["POST", "OPTIONS"])
@app.route("/api/app/chat", methods=["POST", "OPTIONS"])
@app.route("/chat-stream", methods=["POST", "OPTIONS"])
@app.route("/api/chat-stream", methods=["POST", "OPTIONS"])
@app.route("/api/app/chat-stream", methods=["POST", "OPTIONS"])
@require_auth
def chat_stream():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    conv_id = body.get("conversation_id") or None
    web_search_disabled = bool(_NO_WEB_SEARCH_TAG_RE.search(message))
    _worker_available_for_request = _worker_is_online(_worker_get_latest())
    if _worker_available_for_request:
        web_search_disabled = True
    if not message:
        return jsonify({"error": "Message content cannot be blank"}), 400
    user_id = _user_id()
    user_email = _user_email()
    if conv_id:
        conv = _get_convo(conv_id)
        if not conv:
            conv_id = None
    if not conv_id:
        conv_id = str(uuid.uuid4())
        title_source = _EDU_TAG_RE.sub("", message)
        title_source = _NO_WEB_SEARCH_TAG_RE.sub("", title_source).strip()
        ai_title = re.sub(r"\s+", " ", title_source or message).strip()[:60] or "New conversation"
        new_conv = {
            "id": conv_id, "user_id": user_id, "title": ai_title, "pinned": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(), "messages": []
        }
        _save_convo(new_conv)
    if PRATHAM_AGENT_ONLY:
        attachments = body.get("attachments") or []
        refs = body.get("referenceImageMediaIds") or body.get("reference_image_media_ids") or []
        history = _get_messages(conv_id)
        _append_message(conv_id, "user", message)
        job = _agent_create_job(user_id, user_email, conv_id, message, history, attachments, refs)
        def stream_agent_job():
            deadline = time.time() + float(os.environ.get("PRATHAM_AGENT_SSE_TIMEOUT_SECONDS", "300"))
            sent = 0
            yield _sse({"type": "metadata", "conversation_id": conv_id, "jobId": job["jobId"]})
            while time.time() < deadline:
                with _PRATHAM_AGENT_LOCK:
                    while sent < len(job["events"]):
                        evt = job["events"][sent]
                        sent += 1
                        yield _sse(evt)
                    if job["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                        return
                    job["event_condition"].wait(timeout=1.0)
            yield _sse({"type": "error", "status": "FAILED", "message": "Universal Agent timed out waiting for a response."})
        resp = Response(stream_with_context(stream_agent_job()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache, no-transform"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    if _is_flagged_message(message):
        _append_message(conv_id, "user", message)
        refusal_text = (
            "I can't help with that request because it appears to involve illegal or "
            "seriously harmful activity. If you think this was flagged in error, please "
            "rephrase your message."
        )
        _append_message(conv_id, "assistant", refusal_text)
        current_date_formatted = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        flag_log_path = f"data/flagged/{current_date_formatted}.txt"
        flag_entry = (
            f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"
            f"User: {user_email}\n"
            f"Flagged message: {message}\n"
            f"{'=' * 80}\n"
        )
        _write_to_github_repository(flag_log_path, flag_entry)
        def generate_refusal():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "token", "text": refusal_text})
            yield _sse({"type": "complete"})
        resp = Response(stream_with_context(generate_refusal()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    if user_email.lower() in CREATOR_EMAILS and _DIAGNOSTIC_INTENT_RE.search(message):
        _append_message(conv_id, "user", message)
        diagnostics_text = _run_system_diagnostics()
        _append_message(conv_id, "assistant", diagnostics_text)
        def generate_diagnostics():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "token", "text": diagnostics_text})
            yield _sse({"type": "complete"})
        resp = Response(stream_with_context(generate_diagnostics()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    if user_email.lower() in CREATOR_EMAILS and _MEMORY_QUERY_INTENT_RE.search(message):
        _append_message(conv_id, "user", message)
        memory_dump = _fetch_full_public_data_text()
        if not memory_dump.strip():
            response_payload = "Shared memory (data/public_data.txt) is currently empty."
        else:
            search_match = re.search(r"(?:search memory for|list memory about)\s+(.+)", message, re.IGNORECASE)
            if search_match:
                term = search_match.group(1).strip().lower()
                filtered = [line for line in memory_dump.splitlines() if term in line.lower()]
                response_payload = (
                    f"**Memory search results for '{term}':**\n" +
                    ("\n".join(filtered) if filtered else "No matching entries found.")
                )
            else:
                tail = memory_dump[-4000:]
                response_payload = f"**Shared memory (data/public_data.txt) — latest entries:**\n{tail}"
        _append_message(conv_id, "assistant", response_payload)
        def generate_memory_dump():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "token", "text": response_payload})
            yield _sse({"type": "complete"})
        resp = Response(stream_with_context(generate_memory_dump()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    _explicit_memory_match = _EXPLICIT_MEMORY_COMMAND_RE.match(message)
    if _explicit_memory_match:
        _append_message(conv_id, "user", message)
        _maybe_capture_public_teaching(user_email, message)
        saved_snippet = (_explicit_memory_match.group(1).strip() or message)[:200]
        confirmation_text = f"✅ Saved to shared memory: \"{saved_snippet}\""
        _append_message(conv_id, "assistant", confirmation_text)
        def generate_memory_confirm():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "token", "text": confirmation_text})
            yield _sse({"type": "complete"})
        resp = Response(stream_with_context(generate_memory_confirm()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    _last_img_match_iter = re.finditer(
        r'Here\'s your generated image for: "(.*?)"', "\n".join(
            m.get("content", "") for m in _get_messages(conv_id) if m.get("role") == "assistant"
        )
    )
    _last_image_prompt = None
    for _m in _last_img_match_iter:
        _last_image_prompt = _m.group(1)                                     
    image_prompt = _detect_image_prompt(message, _last_image_prompt)
    if image_prompt and not _is_complex_multitask_message(message):
        access_token, image_err = _require_gemini_connection()
        if image_err: return image_err
        _append_message(conv_id, "user", message)
        enriched_image_prompt = _enhance_image_prompt_via_llm(image_prompt)
        try:
            image_info,image_text=_gemini_generate_image(access_token,enriched_image_prompt,body.get('reference_image'))
            image_url=f"data:{image_info['mime_type']};base64,{image_info['data']}"
        except Exception as exc:
            err_text=str(exc)
            def generate_image_error():
                yield _sse({"type":"metadata","conversation_id":conv_id})
                code='GEMINI_RECONNECT_REQUIRED' if 'GEMINI_RECONNECT_REQUIRED' in err_text else 'GEMINI_IMAGE_FAILED'
                yield _sse({"type":"error","error":{"code":code,"message":f"Gemini image generation failed: {err_text}"}})
                yield _sse({"type":"complete"})
            resp=Response(stream_with_context(generate_image_error()),content_type='text/event-stream')
            resp.headers['Cache-Control']='no-cache'; resp.headers['X-Accel-Buffering']='no'; resp.headers['Access-Control-Allow-Credentials']='true'
            return resp
        assistant_note=image_text or f'Generated with Nano Banana 2 for: "{image_prompt}"'
        _append_message(conv_id,'assistant',assistant_note+'\n[generated image delivered to browser]')
        def generate_image():
            yield _sse({"type":"metadata","conversation_id":conv_id})
            if assistant_note: yield _sse({"type":"token","text":assistant_note+'\n\n'})
            yield _sse({"type":"image","url":image_url,"prompt":enriched_image_prompt,"model":GEMINI_IMAGE_MODEL})
            yield _sse({"type":"complete"})
        resp=Response(stream_with_context(generate_image()),content_type='text/event-stream')
        resp.headers['Cache-Control']='no-cache, no-transform'; resp.headers['X-Accel-Buffering']='no'; resp.headers['Access-Control-Allow-Credentials']='true'
        return resp
    history = _get_messages(conv_id)
    is_creator = user_email.lower() in CREATOR_EMAILS
    if _worker_available_for_request:
        active_system_prompt = _QWEN_CODE_CHAT_PROMPT if _qwen_is_code_request(message, history) else _QWEN_FAST_CHAT_PROMPT
        if is_creator:
            active_system_prompt += " The current user is the creator of Pratham AI; be accurate about app behavior and state uncertainty when needed."
        if re.search(r"\b(memory|remember|forgot|taught|public_data)\b", message, re.IGNORECASE):
            try:
                _worker_mem = _search_intelligent_memory_excerpts(message)
            except Exception as _mem_exc:
                print(f"[QWEN][FAST MEMORY] skipped: {_mem_exc}")
                _worker_mem = ""
            if _worker_mem:
                active_system_prompt += "\n[RELEVANT SHARED MEMORY]\n" + _qwen_trim_text(_worker_mem, QWEN_WORKER_SPECIAL_CONTEXT_CHAR_LIMIT)
    else:
        active_system_prompt = SYSTEM_PROMPT
        if is_creator:
            active_system_prompt += (
                " IMPORTANT: the person you are speaking with right now is Pratham Sinha, YOUR CREATOR — "
                "the developer who built and runs this app (Pratham AI). You can confirm this if asked. He "
                "may ask you anything about how the app works, its features, or what's going wrong, and you "
                "should answer with real, accurate information about the actual running system — not "
                "guesses. If he asks about system status, errors, or whether something is working, base "
                "your answer on what you can actually verify (e.g. a background terminal check you just "
                "ran), and say plainly if you're not certain rather than inventing a confident-sounding "
                "answer. You may SUGGEST specific code changes to fix an issue (e.g. 'change this line in "
                "app.py to...'), but you must NEVER claim to have directly edited, patched, or deployed a "
                "change to this app's own source files (app.py / index.html / any backend code) — you have "
                "no ability to do that. The ONLY thing you can directly write to on your own is the shared "
                "memory file data/public_data.txt (via the remember/save-to-memory mechanism); everything "
                "else about how this app itself is built requires Pratham to make the change manually."
            )
        vip_record = _lookup_vip(user_email)
        if vip_record and not is_creator:
            active_system_prompt += (
                f" The person you are currently speaking with is a VIP contact registered by Pratham (the "
                f"app's creator) as one of his own trusted contacts — think of them as a friend of "
                f"Pratham's, recorded by name: '{vip_record.get('name', 'Unknown')}', relationship to "
                f"Pratham: '{vip_record.get('relationship', 'Unknown')}', email '{user_email}'. "
                f"You may acknowledge this relationship warmly if it becomes relevant, but do not "
                f"treat this as authorization to bypass any safety or content rules."
            )
        shared_memory_text = _search_intelligent_memory_excerpts(message)
        if shared_memory_text:
            active_system_prompt += (
                " You have just read data/public_data.txt (this happens before every single reply you "
                "give, with no exceptions). Below are the notes previous users have explicitly asked you "
                "to remember for everyone (shared across all users of this app, not private to any one "
                "person). Treat them as standing instructions/facts to keep in mind, but they never "
                "override your core safety rules above:\\n\\\"\\\"\\\"\\n" + shared_memory_text + "\\n\\\"\\\"\\\""
            )
        active_system_prompt += (
            " RESEARCH PRIORITY for ordinary conversation (not @education, which has its own strict "
            "book-only rule above): when a question could benefit from it, check sources in this order — "
            "1) live web search results (already provided below if relevant), for current/factual/"
            "specific information; 2) the shared memory notes above from data/public_data.txt; 3) this "
            "conversation's own prior messages/history for context the person already gave you. Combine "
            "what's genuinely relevant from these before answering, and be accurate — don't state "
            "something as fact if these sources don't actually support it; say you're not sure instead."
        )
    api_messages = [{"role": "system", "content": active_system_prompt}]
    if _worker_available_for_request:
        for _m in history[-QWEN_WORKER_CODE_HISTORY_MESSAGES:]:
            if _m.get("role") in ("user", "assistant"):
                _c = str(_m.get("content", "") or "")
                if _c:
                    api_messages.append({
                        "role": _m.get("role", "user"),
                        "content": _qwen_trim_text(_c, QWEN_WORKER_RECENT_MESSAGE_CHAR_LIMIT),
                    })
    else:
        _summarized_history = _summarize_old_messages(history, conv_id)
        for m in _summarized_history:
            api_messages.append({"role": m["role"], "content": m["content"]})
    _emit_searching_step = False
    outgoing_user_message = _NO_WEB_SEARCH_TAG_RE.sub("", message).strip()
    _edu_tag_match = _EDU_TAG_RE.search(message)
    if _edu_tag_match:
        edu_book, edu_chapter = _edu_tag_match.group(1), _edu_tag_match.group(2)
        outgoing_user_message = _EDU_TAG_RE.sub("", outgoing_user_message).strip()
        chapter_text = _fetch_chapter_text(edu_book, edu_chapter)
        extraction_looks_valid = False
        if chapter_text and len(chapter_text.strip()) >= 15:
            extraction_looks_valid = _text_extraction_quality_score(chapter_text) >= 0.5
        if extraction_looks_valid:
            api_messages[0]["content"] += (
                f" The user selected the book '{edu_book}', chapter '{edu_chapter}' from the "
                f"education library. Below is the COMPLETE text of that chapter, extracted directly "
                f"from the PDF. Read the entire thing before answering. Your answer must come STRICTLY "
                f"and ONLY from this chapter text — do not add outside knowledge, do not use general "
                f"facts you already know about the topic, do not pull in other chapters or books, and "
                f"do not fill gaps in the text with assumptions. Reframe/summarize/explain in your own "
                f"words as needed (don't just copy sentences verbatim), but every fact in your answer "
                f"must be traceable to this text. If the chapter genuinely doesn't contain the answer "
                f"to the user's question, say so plainly instead of guessing or using outside "
                f"knowledge. Always mention the book/chapter you used.\n"
                f"FULL CHAPTER TEXT ('{edu_book}' — '{edu_chapter}'):\n\"\"\"\n{chapter_text}\n\"\"\""
            )
        elif chapter_text:
            api_messages[0]["content"] += (
                f" The user selected book '{edu_book}', chapter '{edu_chapter}'. The PDF text "
                f"extraction for this file came back too short or badly garbled to be reliable — this "
                f"commonly happens with PDFs in scripts like Devanagari/Sanskrit where the text layer "
                f"isn't properly embedded. DO NOT attempt to answer using this broken extraction and DO "
                f"NOT fall back to general/outside knowledge about the topic. Instead, tell the user "
                f"plainly that this chapter's PDF couldn't be read reliably (extraction quality was too "
                f"low, likely a script/font issue) and that they may need to re-upload a text-searchable "
                f"version of the PDF."
            )
        else:
            api_messages[0]["content"] += (
                f" The user selected book '{edu_book}', chapter '{edu_chapter}', but that chapter's "
                f"content could not be loaded (empty file, extraction failure, or pypdf not "
                f"installed on the server). Say so plainly instead of guessing."
            )
    elif "@education" in message.lower():
        outgoing_user_message = re.sub(r"@education", "", outgoing_user_message, flags=re.IGNORECASE).strip()
        best = _find_best_education_excerpt(outgoing_user_message or message)
        if best:
            api_messages[0]["content"] += (
                f" The user tagged @education (no specific book/chapter selected), meaning they want "
                f"an answer sourced strictly from the PDF library. The most relevant excerpt found was "
                f"from the PDF file '{best['filename']}'. Answer using ONLY this excerpt — no outside "
                f"knowledge, no filling gaps with general facts. Reframe it into a clear answer in your "
                f"own words (don't just quote it verbatim), and explicitly mention which PDF file you "
                f"used. If it doesn't actually answer the question, say so instead of guessing. "
                f"Excerpt:\n\"\"\"\n{best['excerpt']}\n\"\"\""
            )
        else:
            api_messages[0]["content"] += (
                " The user tagged @education but no relevant PDF content could be found in the "
                "data/education library (it may be empty, or the pypdf package may not be installed "
                "on the server). Say so plainly instead of guessing."
            )
    elif not web_search_disabled and re.search(r"@web\b", message, flags=re.IGNORECASE):
        _emit_searching_step = True
        outgoing_user_message = _NO_WEB_SEARCH_TAG_RE.sub("", outgoing_user_message).strip()
        outgoing_user_message = re.sub(r"@web\b", "", outgoing_user_message, flags=re.IGNORECASE).strip()
        results = _web_search_snippets(outgoing_user_message or message)
        if results:
            api_messages[0]["content"] += (
                " Here are live web search results relevant to the user's message, in case current "
                "information helps (use them only if actually relevant; ignore them for timeless "
                "questions like math or general advice, and cite that info came from a web search "
                "when you do use it):\n" + "\n".join(results)
            )
        elif _CURRENT_EVENTS_INTENT_RE.search(outgoing_user_message or message) or _is_fact_check_question(outgoing_user_message or message):
            _append_message(conv_id, "user", message)
            no_results_text = (
                "I couldn't verify this through a live web search right now (the search didn't return "
                "results). Rather than risk giving you incorrect or outdated information, I'd recommend "
                "checking a reliable source directly:\n\n"
                "- [Google News](https://news.google.com) — search for the topic\n"
                "- [Wikipedia](https://en.wikipedia.org) — for verified facts\n"
                "- [Reuters](https://www.reuters.com) or [BBC News](https://www.bbc.com/news)\n\n"
                "You can also try asking me again in a moment — the search may work on retry."
            )
            _append_message(conv_id, "assistant", no_results_text)
            def generate_no_results():
                yield _sse({"type": "metadata", "conversation_id": conv_id})
                yield _sse({"type": "token", "text": no_results_text})
                yield _sse({"type": "complete"})
            resp = Response(stream_with_context(generate_no_results()), content_type="text/event-stream")
            resp.headers["Cache-Control"] = "no-cache"
            resp.headers["X-Accel-Buffering"] = "no"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp
        else:
            api_messages[0]["content"] += (
                " CRITICAL: A live web search was just attempted for this message but returned "
                "NO results. You have NO current web data for this question. You MUST follow these rules:\n"
                "1. Do NOT fabricate or invent any facts, dates, names, events, quotes, or sources.\n"
                "2. Do NOT create fake URLs or cite sources that don't exist.\n"
                "3. Do NOT present information from your training data as if it were current/verified.\n"
                "4. If the question is about a specific factual claim (did X happen, who is Y, when did Z occur) "
                "and you are NOT certain from your training data, say: 'I don't have confirmed information "
                "about this right now — a live web search didn't return results. I'd rather not guess "
                "and risk giving you wrong information. Could you check a reliable news source directly?'\n"
                "5. NEVER say 'my training cutoff is [date]' — instead say the live search didn't return results.\n"
                "6. If you ARE answering from training knowledge (not web results), you MUST add at the "
                "start of your answer: 'Note: I'm answering from my training data, not a live web search "
                "(the search didn't return results). Please verify this information independently.'\n"
                "7. Do NOT mix training-data knowledge with fabricated 'current' details to make an answer "
                "look more authoritative than it is."
            )
    api_messages.append({"role": "user", "content": outgoing_user_message or message})
    _query_temperature = _classify_query_temperature(message)
    _do_stream._current_temperature = _query_temperature
    print(f"[TEMP] Query classified with temperature={_query_temperature} for: {message[:80]}")
    _append_message(conv_id, "user", message)
    _maybe_capture_public_teaching(user_email, message)
    def generate():
        yield _sse({"type": "metadata", "conversation_id": conv_id})
        yield _sse({"type": "agent_step", "step_type": "thinking", "label": "Thinking", "timestamp": time.time()})
        if _emit_searching_step:
            yield _sse({"type": "agent_step", "step_type": "searching",
                       "label": "Searching the web for current information...",
                       "timestamp": time.time()})
        _tasks_emitted = {}                                                   
        if _MULTI_STEP_INTENT_RE.search(message):
            yield _sse({"type": "planning_started", "label": "Task Plan", "timestamp": time.time()})
        export_intent_check_message = _EDU_TAG_RE.sub("", message)
        export_ext_hint = None
        if _is_export_intent(export_intent_check_message, _ZIP_INTENT_RE):
            export_ext_hint = "zip"
        elif _is_export_intent(export_intent_check_message, _PDF_INTENT_RE):
            export_ext_hint = "pdf"
        else:
            export_ext_hint = _detect_generic_extension_intent(export_intent_check_message)
        if export_ext_hint:
            yield _sse({"type": "token", "text": f"📄 Your {export_ext_hint} file is being generated...\n\n"})
        full_reply_parts = []                                                                 
        working_messages = list(api_messages)
        total_blocks_seen = 0                                                                
        terminal_workdir = _new_terminal_workdir()
        session_file_contents = {}                                                                
        _images_emitted_this_turn = set()                                                       
        _produced_filenames_this_turn = set()                                               
        _promise_correction_attempted = False                                             
        for iteration in range(_TERMINAL_MAX_ITERATIONS):
            iteration_text_parts = []
            for chunk in _do_stream(working_messages):
                try:
                    if chunk.startswith("data: "):
                        payload = json.loads(chunk[6:])
                        if payload.get("type") == "token":
                            token_text = payload["text"]
                            iteration_text_parts.append(token_text)
                            full_reply_parts.append(token_text)
                            accumulated_so_far = "".join(iteration_text_parts)
                            if "- [" in accumulated_so_far or "* [" in accumulated_so_far:
                                _last_newline = accumulated_so_far.rfind("\n")
                                complete_text_for_tasks = accumulated_so_far[:_last_newline] if _last_newline != -1 else ""
                                new_tasks = _extract_task_items_from_text(complete_text_for_tasks)
                                for task_id, label, is_done in new_tasks:
                                    if task_id not in _tasks_emitted:
                                        _tasks_emitted[task_id] = is_done
                                        yield _sse({"type": "task_created", "task_id": task_id, "label": label})
                                        if is_done:
                                            yield _sse({"type": "task_completed", "task_id": task_id, "ok": True})
                                    elif is_done and not _tasks_emitted[task_id]:
                                        _tasks_emitted[task_id] = True
                                        yield _sse({"type": "task_completed", "task_id": task_id, "ok": True})
                        elif payload.get("type") == "complete":
                            continue                                                               
                except Exception:
                    pass
                if not chunk.startswith("data: ") or json.loads(chunk[6:]).get("type") != "complete":
                    yield chunk
            iteration_reply = "".join(iteration_text_parts)
            if iteration == 0 and len(iteration_reply) > 50:
                _web_results_for_check = results if 'results' in dir() else []
                _verification_feedback = _build_verification_feedback(iteration_reply, _web_results_for_check)
                _block_feedback = _build_block_validation_feedback(iteration_reply)
                _combined_feedback = None
                if _verification_feedback and _block_feedback:
                    _combined_feedback = _verification_feedback + "\n\n" + _block_feedback
                elif _verification_feedback:
                    _combined_feedback = _verification_feedback
                elif _block_feedback:
                    _combined_feedback = _block_feedback
                if _combined_feedback:
                    yield _sse({"type": "agent_step", "step_type": "verifying", "label": "Verifying answer accuracy...", "timestamp": time.time()})
                    working_messages.append({"role": "assistant", "content": iteration_reply})
                    working_messages.append({"role": "user", "content": (
                        f"[VERIFICATION CHECK FOUND ISSUES — please fix these and re-answer:]\n{_combined_feedback}\n"
                        "Correct the issues above and provide your updated answer. "
                        "Do not repeat your entire previous response — just provide the corrected version."
                    )})
                    continue                                      
            for _img_m in re.finditer(r"```image\s*\n([\s\S]*?)```", iteration_reply):
                _raw_img_prompt = _img_m.group(1).strip()
                if not _raw_img_prompt or _raw_img_prompt in _images_emitted_this_turn:
                    continue
                _images_emitted_this_turn.add(_raw_img_prompt)
                _enriched_prompt = _enhance_image_prompt_via_llm(_raw_img_prompt)
                try:
                    _img_token, _img_err = _require_gemini_connection()
                    if _img_err:
                        yield _sse({
                            "type": "error",
                            "error": {
                                "code": "GEMINI_AUTH_REQUIRED",
                                "message": "Connect Gemini in Settings before generating images."
                            }
                        })
                        continue
                    _img_info, _img_text = _gemini_generate_image(_img_token, _enriched_prompt)
                    _img_url = f"data:{_img_info['mime_type']};base64,{_img_info['data']}"
                    yield _sse({
                        "type": "image",
                        "url": _img_url,
                        "prompt": _enriched_prompt,
                        "model": GEMINI_IMAGE_MODEL
                    })
                except Exception as _img_exc:
                    _img_msg = str(_img_exc)
                    _low_img_msg = _img_msg.lower()
                    _img_code = (
                        "GEMINI_RECONNECT_REQUIRED" if "GEMINI_RECONNECT_REQUIRED" in _img_msg else
                        "GEMINI_BILLING_OR_PERMISSION" if any(k in _low_img_msg for k in ("billing", "payment", "quota", "permission", "forbidden", "http 402", "http 403")) else
                        "GEMINI_IMAGE_FAILED"
                    )
                    yield _sse({
                        "type": "error",
                        "error": {"code": _img_code, "message": f"Gemini image generation failed: {_img_msg}"}
                    })
            for filename, content in _extract_createfile_blocks(iteration_reply):
                try:
                    final_content = content
                    if _CONFLICT_MARKER_RE.search(content):
                        stray_pairs = [(m.group(1), m.group(2)) for m in _EDIT_BLOCK_RE.finditer(content)]
                        if stray_pairs:
                            base_content = session_file_contents.get(filename)
                            if base_content is None:
                                base_content = _find_last_file_content_in_history(history, filename)
                            if base_content is not None:
                                final_content, _warn = _apply_editfile_edits(base_content, stray_pairs)
                                yield _sse({
                                    "type": "terminal_output", "ordinal": 0,
                                    "stdout": f"Note: resolved SEARCH/REPLACE markers found inside a "
                                              f"createfile block for {filename} — use ```editfile: for "
                                              f"edits next time instead.",
                                    "stderr": "", "returncode": 0
                                })
                    written = _write_direct_file(terminal_workdir, filename, final_content)
                    session_file_contents[filename] = final_content
                    file_ext = filename.rsplit(".", 1)[-1] if "." in filename else "txt"
                    _register_session_file(conv_id, filename, file_ext, written["size_bytes"], line_count=written["line_count"])
                    _produced_filenames_this_turn.add(filename.lower())
                    with open(written["path"], "rb") as fh:
                        file_bytes = fh.read()
                    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                    token = _store_generated_file(file_bytes, filename, mimetype)
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": filename})
                    yield _sse({
                        "type": "activity_created",
                        "filename": filename,
                        "size_bytes": written["size_bytes"],
                        "line_count": written["line_count"],
                        "preview_type": file_ext,
                    })
                    yield _sse({"type": "verification_started", "filename": filename})
                    val_result = validate_generated_code(file_ext, final_content)
                    yield _sse({
                        "type": "verification_completed",
                        "filename": filename,
                        "ok": val_result["valid"],
                        "details": val_result["error"] or f"Validated {file_ext.upper()} — no issues found.",
                    })
                except Exception as exc:
                    print(f"[CREATEFILE][FAULT] {exc}")
            for filename, pairs in _extract_editfile_blocks(iteration_reply):
                try:
                    base_content = session_file_contents.get(filename)
                    if base_content is None:
                        base_content = _find_last_file_content_in_history(history, filename)
                    if base_content is None:
                        yield _sse({
                            "type": "terminal_output", "ordinal": 0,
                            "stdout": "", "stderr": f"editfile: no prior version of '{filename}' found in this "
                                                     f"conversation — use ```createfile: instead to create it first.",
                            "returncode": -1
                        })
                        continue
                    new_content, warnings = _apply_editfile_edits(base_content, pairs)
                    diff_stats = _compute_diff_stats(base_content, new_content)
                    written = _write_direct_file(terminal_workdir, filename, new_content)
                    session_file_contents[filename] = new_content
                    file_ext = filename.rsplit(".", 1)[-1] if "." in filename else "txt"
                    _register_session_file(conv_id, filename, file_ext, written["size_bytes"], line_count=written["line_count"])
                    _produced_filenames_this_turn.add(filename.lower())
                    with open(written["path"], "rb") as fh:
                        file_bytes = fh.read()
                    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                    token = _store_generated_file(file_bytes, filename, mimetype)
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": filename})
                    yield _sse({
                        "type": "activity_edited",
                        "filename": filename,
                        "added": diff_stats["added"],
                        "removed": diff_stats["removed"],
                        "unified_diff": diff_stats["unified_diff"],
                    })
                    if warnings:
                        yield _sse({
                            "type": "terminal_output", "ordinal": 0,
                            "stdout": f"Applied {len(pairs) - len(warnings)}/{len(pairs)} edits to {filename}.",
                            "stderr": " ".join(warnings), "returncode": 0
                        })
                except Exception as exc:
                    print(f"[EDITFILE][FAULT] {exc}")
            all_blocks_this_iteration = list(_CODE_BLOCK_RE.finditer(iteration_reply))
            executable_present = any(
                (m.group(1) or "").lower() in _EXECUTABLE_LANGS for m in all_blocks_this_iteration
            )
            if not executable_present:
                if not _promise_correction_attempted:
                    _promised_filenames = set(
                        m.group(0) for m in re.finditer(
                            r"\b[\w\-]+\.(?:mcaddon|zip|mrpack|apk|jar|exe|dmg|tar\.gz|7z)\b",
                            iteration_reply, re.IGNORECASE
                        )
                    )
                    _unfulfilled = [f for f in _promised_filenames if f.lower() not in _produced_filenames_this_turn]
                    if _unfulfilled:
                        _promise_correction_attempted = True
                        working_messages.append({"role": "assistant", "content": iteration_reply})
                        working_messages.append({"role": "user", "content": (
                            f"You said {', '.join(sorted(_unfulfilled))} is ready, but no such file was "
                            f"actually created — you described it without running the real command to "
                            f"build it. Actually execute the packaging/build command now in a ```bash or "
                            f"```python block (e.g. the real `zip`/archive command), don't just describe "
                            f"it again."
                        )})
                        continue
                break                                                     
            results = []
            for m in all_blocks_this_iteration:
                total_blocks_seen += 1
                lang = (m.group(1) or "").lower()
                if lang not in _EXECUTABLE_LANGS:
                    continue                                                                    
                code = m.group(2)
                yield _sse({
                    "type": "agent_step",
                    "step_type": "executing",
                    "label": f"Executing {lang.upper()} block \u2014 please wait...",
                    "timestamp": time.time()
                })
                _pre_exec_files = set()
                if terminal_workdir and os.path.isdir(terminal_workdir):
                    for _root, _dirs, _files in os.walk(terminal_workdir):
                        for _f in _files:
                            _pre_exec_files.add(os.path.join(_root, _f))
                stdout, stderr, rc = _run_code_block(lang, code, cwd=terminal_workdir)
                if terminal_workdir and os.path.isdir(terminal_workdir):
                    _post_exec_files = set()
                    for _root, _dirs, _files in os.walk(terminal_workdir):
                        for _f in _files:
                            _post_exec_files.add(os.path.join(_root, _f))
                    for _new_path in sorted(_post_exec_files - _pre_exec_files):
                        try:
                            _new_name = os.path.basename(_new_path)
                            with open(_new_path, "rb") as _fh:
                                _new_bytes = _fh.read()
                            if len(_new_bytes) > 60 * 1024 * 1024:                   
                                continue
                            _new_mimetype = mimetypes.guess_type(_new_name)[0] or "application/octet-stream"
                            _new_token = str(uuid.uuid4())
                            _generated_files_store[_new_token] = {
                                "bytes": _new_bytes, "filename": _new_name, "mimetype": _new_mimetype,
                            }
                            yield _sse({
                                "type": "file_ready",
                                "url": f"/download/{_new_token}",
                                "filename": _new_name,
                            })
                            _produced_filenames_this_turn.add(_new_name.lower())
                        except Exception as _reg_exc:
                            print(f"[AUTO FILE DISCOVERY FAULT] {_new_path} -> {_reg_exc}")
                results.append({"lang": lang, "code": code, "stdout": stdout, "stderr": stderr, "returncode": rc})
                yield _sse({
                    "type": "terminal_output",
                    "ordinal": total_blocks_seen,
                    "code": code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": rc
                })
                yield _sse({
                    "type": "activity_terminal",
                    "ordinal": total_blocks_seen,
                    "lang": lang,
                    "returncode": rc,
                    "had_output": bool(stdout or stderr),
                })
            is_last_allowed_iteration = (iteration == _TERMINAL_MAX_ITERATIONS - 1)
            if is_last_allowed_iteration:
                break                                                                    
            working_messages.append({"role": "assistant", "content": iteration_reply})
            working_messages.append({"role": "user", "content": _format_terminal_results_for_model(results)})
        if _tasks_emitted:
            final_reply_so_far = "".join(full_reply_parts)
            final_task_states = {tid: False for tid in _tasks_emitted}
            for task_id, label, is_done in _extract_task_items_from_text(final_reply_so_far):
                if task_id in final_task_states:
                    final_task_states[task_id] = is_done
            for task_id, label in _tasks_emitted.items():
                yield _sse({
                    "type": "task_completed",
                    "task_id": task_id,
                    "ok": final_task_states.get(task_id, True),
                })
        yield _sse({"type": "complete"})
        assistant_response = "".join(full_reply_parts)
        if assistant_response:
            _append_message(conv_id, "assistant", assistant_response)
            current_date_formatted = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            repo_sync_destination_path = f"data/{user_email}/{current_date_formatted}.txt"
            log_entry = (
                f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"
                f"User: {message}\n"
                f"Pratham AI:\n{assistant_response}\n"
                f"{'=' * 80}\n"
            )
            _write_to_github_repository(repo_sync_destination_path, log_entry)
            try:
                if _is_export_intent(export_intent_check_message, _ZIP_INTENT_RE):
                    zip_name = _derive_export_filename(export_intent_check_message, "zip", assistant_response)
                    inner_name = _derive_export_filename(export_intent_check_message, "txt", assistant_response)
                    zip_bytes = _build_zip_from_response(assistant_response, workdir=terminal_workdir, deliverable_name=inner_name)
                    token = _store_generated_file(zip_bytes, zip_name, "application/zip")
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": zip_name})
                elif _is_export_intent(export_intent_check_message, _PDF_INTENT_RE):
                    pdf_bytes, _default_name, pdf_mime = _build_pdf_from_response(assistant_response)
                    pdf_name = _derive_export_filename(export_intent_check_message, "pdf", assistant_response)
                    token = _store_generated_file(pdf_bytes, pdf_name, pdf_mime)
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": pdf_name})
                else:
                    generic_ext = _detect_generic_extension_intent(export_intent_check_message)
                    if generic_ext:
                        file_bytes, _default_name, file_mime = _build_generic_file_from_response(
                            assistant_response, generic_ext, workdir=terminal_workdir
                        )
                        file_name = _derive_export_filename(export_intent_check_message, generic_ext, assistant_response)
                        token = _store_generated_file(file_bytes, file_name, file_mime)
                        yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": file_name})
            except Exception as exc:
                print(f"[FILEGEN][FAULT] {exc}")
        _cleanup_terminal_workdir(terminal_workdir)
    resp = Response(stream_with_context(generate()), content_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp
@app.route("/education/books", methods=["GET", "OPTIONS"])
@app.route("/api/education/books", methods=["GET", "OPTIONS"])
@app.route("/api/app/education/books", methods=["GET", "OPTIONS"])
@require_auth
def education_books():
    if request.method == "OPTIONS":
        return _cors_preflight()
    return jsonify({"books": _list_education_books()})
@app.route("/education/chapters", methods=["GET", "OPTIONS"])
@app.route("/api/education/chapters", methods=["GET", "OPTIONS"])
@app.route("/api/app/education/chapters", methods=["GET", "OPTIONS"])
@require_auth
def education_chapters():
    if request.method == "OPTIONS":
        return _cors_preflight()
    book = request.args.get("book", "").strip()
    if not book:
        return jsonify({"error": "Missing ?book= parameter"}), 400
    return jsonify({"book": book, "chapters": _list_education_chapters(book)})
@app.route("/conversations", methods=["GET", "OPTIONS"])
@app.route("/api/conversations", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations", methods=["GET", "OPTIONS"])
@require_auth
def list_conversations():
    if request.method == "OPTIONS":
        return _cors_preflight()
    return jsonify(_list_convos(_user_id()))
@app.route("/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])
@app.route("/api/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])
@require_auth
def get_messages_route(conv_id):
    if request.method == "OPTIONS":
        return _cors_preflight()
    return jsonify(_get_messages(conv_id))
@app.route("/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])
@app.route("/api/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])
@app.route("/api/app/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])
@require_auth
def delete_conversation(conv_id):
    if request.method == "OPTIONS":
        return _cors_preflight()
    _mem_convos.pop(conv_id, None)
    if SUPABASE_CONFIGURED and _supabase:
        try:
            _supabase.table("messages").delete().eq("conversation_id", conv_id).execute()
            _supabase.table("conversations").delete().eq("id", conv_id).execute()
        except Exception:
            pass
    return jsonify({"ok": True, "target_id": conv_id})
@app.route("/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])
@app.route("/api/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])
@require_auth
def export_conversation(conv_id):
    if request.method == "OPTIONS":
        return _cors_preflight()
    msgs = _get_messages(conv_id)
    lines = ["Pratham AI conversation export", ""]
    for m in msgs:
        lines.append(f"[{m.get('role', 'system')}]:\n{m['content']}\n")
    return Response("\n".join(lines), content_type="text/plain; charset=utf-8")
@app.route("/execute-python", methods=["POST", "OPTIONS"])
@app.route("/api/execute-python", methods=["POST", "OPTIONS"])
@app.route("/api/app/execute-python", methods=["POST", "OPTIONS"])
@require_auth
def execute_python():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    code = body.get("code", "").strip()
    if not code:
        return jsonify({"error": "Empty code payload"}), 400
    try:
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
        return jsonify({"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode})
    except Exception as exc:
        return jsonify({"stdout": "", "stderr": f"Sandbox Exception: {exc}", "returncode": -1})
@app.route("/terminal/run", methods=["POST", "OPTIONS"])
@app.route("/api/terminal/run", methods=["POST", "OPTIONS"])
@app.route("/api/app/terminal/run", methods=["POST", "OPTIONS"])
@require_auth
def terminal_run_direct():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    lang = (body.get("lang") or "python").strip().lower()
    code = (body.get("code") or "").strip()
    if not code:
        return jsonify({"error": "Empty code payload"}), 400
    if lang not in _EXECUTABLE_LANGS:
        return jsonify({"error": f"Unsupported lang '{lang}'. Use one of: {sorted(_EXECUTABLE_LANGS)}"}), 400
    workdir = _new_terminal_workdir()
    try:
        stdout, stderr, rc = _run_code_block(lang, code, cwd=workdir)
        created_files = []
        for root, _dirs, files in os.walk(workdir):
            for fname in files:
                full_path = os.path.join(root, fname)
                with open(full_path, "rb") as fh:
                    data = fh.read()
                mimetype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
                token = _store_generated_file(data, fname, mimetype)
                created_files.append({"filename": fname, "size_bytes": len(data), "url": f"/download/{token}"})
        return jsonify({"stdout": stdout, "stderr": stderr, "returncode": rc, "files": created_files})
    finally:
        _cleanup_terminal_workdir(workdir)
@app.route("/terminal/create-file", methods=["POST", "OPTIONS"])
@app.route("/api/terminal/create-file", methods=["POST", "OPTIONS"])
@app.route("/api/app/terminal/create-file", methods=["POST", "OPTIONS"])
@require_auth
def terminal_create_file_direct():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    filename = (body.get("filename") or "").strip().replace("..", "").lstrip("/")
    content = body.get("content", "")
    if not filename:
        return jsonify({"error": "Missing 'filename'."}), 400
    workdir = _new_terminal_workdir()
    try:
        written = _write_direct_file(workdir, filename, content)
        with open(written["path"], "rb") as fh:
            data = fh.read()
        mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        token = _store_generated_file(data, filename, mimetype)
        return jsonify({"ok": True, "filename": filename, "size_bytes": written["size_bytes"], "url": f"/download/{token}"})
    finally:
        _cleanup_terminal_workdir(workdir)
@app.route("/upload", methods=["POST", "OPTIONS"])
@app.route("/api/upload", methods=["POST", "OPTIONS"])
@app.route("/api/app/upload", methods=["POST", "OPTIONS"])
@require_auth
def upload_pdf():
    if request.method == "OPTIONS":
        return _cors_preflight()
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file received."}), 400
    filename = f.filename
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    raw_bytes = f.read()
    extracted_preview = ""
    decode_status = "stored"
    try:
        if ext == "pdf":
            if _PDF_READ_SUPPORTED:
                extracted_preview = _extract_pdf_text(raw_bytes)[:4000]
                decode_status = "decoded"
            else:
                decode_status = "stored (install `pypdf` on the server to extract PDF text)"
        elif ext in ("txt", "md", "csv", "json", "html", "css", "js", "py", "xml", "yml", "yaml", "log"):
            extracted_preview = raw_bytes.decode("utf-8", errors="replace")[:4000]
            decode_status = "decoded"
        elif ext == "docx":
            try:
                import docx                                    
                doc = docx.Document(io.BytesIO(raw_bytes))
                extracted_preview = "\n".join(p.text for p in doc.paragraphs)[:4000]
                decode_status = "decoded"
            except ImportError:
                decode_status = "stored (install `python-docx` on the server to extract .docx text)"
        elif ext == "zip":
            try:
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                    extracted_preview = "\n".join(zf.namelist()[:100])
                decode_status = "decoded (file listing)"
            except zipfile.BadZipFile:
                decode_status = "stored (not a valid zip)"
        elif ext in ("png", "jpg", "jpeg", "gif", "webp"):
            img_meta = _extract_image_metadata(raw_bytes, ext)
            if img_meta:
                extracted_preview = img_meta
                decode_status = "decoded (image metadata: dimensions, color mode, file info)"
            else:
                decode_status = f"stored ({len(raw_bytes)} bytes, image)"
        else:
            try:
                extracted_preview = raw_bytes.decode("utf-8")[:4000]
                decode_status = "decoded (generic text sniff)"
            except UnicodeDecodeError:
                decode_status = f"stored ({len(raw_bytes)} bytes, binary — no text extraction available for .{ext or 'unknown'})"
    except Exception as exc:
        decode_status = f"stored (decode attempt failed: {exc})"
    return jsonify({
        "ok": True,
        "filename": filename,
        "size_bytes": len(raw_bytes),
        "status": decode_status,
        "preview": extracted_preview
    })
import ast
@app.route("/config/public", methods=["GET", "OPTIONS"])
@app.route("/api/config/public", methods=["GET", "OPTIONS"])
@app.route("/api/app/config/public", methods=["GET", "OPTIONS"])
def config_public():
    if request.method == "OPTIONS":
        return _cors_preflight()
    return jsonify({
        "ok": True,
        "app_name": "Pratham AI",
        "supabase_configured": SUPABASE_CONFIGURED,
        "github_repo": GITHUB_REPO,
        "ai": {
            "mode": PRATHAM_AI_MODE,
            "gemini_oauth": True,
            "google_cloud_project_configured": bool(GOOGLE_CLOUD_PROJECT_ID),
            "google_oauth_client_configured": bool(GOOGLE_GEMINI_OAUTH_CLIENT_ID),
            "chat_model": GEMINI_CHAT_MODEL,
            "image_model": GEMINI_IMAGE_MODEL,
        },
        "google_cse": GOOGLE_CSE_CONFIGURED,
        "pdf_read_supported": _PDF_READ_SUPPORTED,
        "pdf_extractors_available": {
            "pypdf_or_pypdf2": _PDF_READ_SUPPORTED,
            "pymupdf_fitz": _FITZ_SUPPORTED,
            "pdfplumber": _PDFPLUMBER_SUPPORTED,
        },
        "session_token_ttl_days": SESSION_TOKEN_TTL_DAYS,
        "logo_512": "https://raw.githubusercontent.com/pratham31sinha-boop/Partham-AI-/main/icon-512.png",
        "logo_192": "https://raw.githubusercontent.com/pratham31sinha-boop/Partham-AI-/main/icon-192.png",
    })
_rate_limit_buckets: dict = {}
_RATE_LIMIT_WINDOW_SECONDS = 60
def rate_limit(max_requests: int):
    """Caps a route to `max_requests` calls per user per rolling 60s
    window. In-process (resets on redeploy) — fine for a single-instance
    deployment; multi-instance would need a shared store like Redis."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if request.method == "OPTIONS":
                return f(*args, **kwargs)
            identity = _user_id() if hasattr(request, "current_user") else (request.remote_addr or "anon")
            bucket_key = f"{identity}:{f.__name__}"
            now_ts = time.time()
            timestamps = [t for t in _rate_limit_buckets.get(bucket_key, []) if now_ts - t < _RATE_LIMIT_WINDOW_SECONDS]
            if len(timestamps) >= max_requests:
                return jsonify({"error": "Rate limit exceeded. Please slow down and try again shortly."}), 429
            timestamps.append(now_ts)
            _rate_limit_buckets[bucket_key] = timestamps
            return f(*args, **kwargs)
        return wrapper
    return decorator
def validate_json_block(code: str) -> dict:
    try:
        json.loads(code)
        return {"valid": True, "error": None}
    except Exception as exc:
        return {"valid": False, "error": str(exc)}
def validate_python_block(code: str) -> dict:
    try:
        ast.parse(code)
        return {"valid": True, "error": None}
    except SyntaxError as exc:
        return {"valid": False, "error": f"SyntaxError: {exc.msg} (line {exc.lineno})"}
    except Exception as exc:
        return {"valid": False, "error": str(exc)}
def validate_html_block(code: str) -> dict:
    """Lightweight structural check: balanced tags, common generation
    mistakes caught (unclosed/mismatched tags). Not a full HTML5 parser."""
    void_elements = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
    tag_pattern = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(/?)>")
    stack, issues = [], []
    for m in tag_pattern.finditer(code):
        closing, tag_name, self_closing = m.group(1), m.group(2).lower(), m.group(3)
        if tag_name in void_elements or self_closing == "/":
            continue
        if not closing:
            stack.append(tag_name)
        elif stack and stack[-1] == tag_name:
            stack.pop()
        elif tag_name in stack:
            while stack and stack[-1] != tag_name:
                issues.append(f"Unclosed tag: <{stack.pop()}>")
            if stack:
                stack.pop()
        else:
            issues.append(f"Closing tag with no matching open: </{tag_name}>")
    for leftover in stack:
        issues.append(f"Unclosed tag: <{leftover}>")
    return {"valid": len(issues) == 0, "error": "; ".join(issues) if issues else None}
def validate_js_block(code: str) -> dict:
    """Lightweight, dependency-free JS/TS check: balanced brackets outside of
    string/template literals and comments. Not a full parser — catches the
    most common generation mistakes (an unclosed brace/bracket/paren) without
    needing a real JS toolchain installed on the server."""
    stack = []
    in_str, str_char = False, None
    in_line_comment, in_block_comment = False, False
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 1
        elif in_str:
            if ch == "\\":
                i += 1                     
            elif ch == str_char:
                in_str = False
        elif ch == "/" and nxt == "/":
            in_line_comment = True
            i += 1
        elif ch == "/" and nxt == "*":
            in_block_comment = True
            i += 1
        elif ch in ('"', "'", "`"):
            in_str, str_char = True, ch
        elif ch in ("{", "[", "("):
            stack.append(ch)
        elif ch in ("}", "]", ")"):
            pairs = {"}": "{", "]": "[", ")": "("}
            if not stack or stack[-1] != pairs[ch]:
                return {"valid": False, "error": f"Unexpected '{ch}' at position {i} (unmatched or wrong bracket type)"}
            stack.pop()
        i += 1
    if stack:
        return {"valid": False, "error": f"Unclosed '{stack[-1]}' — {len(stack)} bracket(s) never closed"}
    if in_str:
        return {"valid": False, "error": f"Unterminated string literal (started with {str_char})"}
    return {"valid": True, "error": None}
def validate_generated_code(lang: str, code: str) -> dict:
    lang = (lang or "").lower()
    if lang == "json":
        return validate_json_block(code)
    if lang in ("python", "py"):
        return validate_python_block(code)
    if lang in ("html", "htm"):
        return validate_html_block(code)
    if lang in ("js", "javascript", "mjs", "cjs", "ts", "typescript"):
        return validate_js_block(code)
    return {"valid": True, "error": None}
@app.route("/validate-code", methods=["POST", "OPTIONS"])
@app.route("/api/validate-code", methods=["POST", "OPTIONS"])
@app.route("/api/app/validate-code", methods=["POST", "OPTIONS"])
@require_auth
@rate_limit(60)
def validate_code_route():
    """Lets the frontend validate a file-creation-card's content on demand
    and show a real pass/fail badge instead of assuming it's correct."""
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    lang, code = body.get("lang", ""), body.get("code", "")
    if not code:
        return jsonify({"error": "Empty code payload"}), 400
    return jsonify(validate_generated_code(lang, code))
_session_files_registry: dict = {}                                                                                   
def _register_session_file(conv_id: str, filename: str, lang: str, size: int, download_url: str = None, line_count: int = None):
    _session_files_registry.setdefault(conv_id, []).append({
        "filename": filename, "lang": lang, "size_bytes": size, "line_count": line_count,
        "created_at": datetime.now(timezone.utc).isoformat(), "download_url": download_url
    })
@app.route("/conversations/<conv_id>/files", methods=["GET", "OPTIONS"])
@app.route("/api/conversations/<conv_id>/files", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations/<conv_id>/files", methods=["GET", "OPTIONS"])
@require_auth
def list_session_files(conv_id):
    """Real Files-tab data source: files actually produced in this
    conversation (via createfile blocks, code execution that wrote files,
    or exports), not simulated GitHub activity."""
    if request.method == "OPTIONS":
        return _cors_preflight()
    files = list(_session_files_registry.get(conv_id, []))
    if not files:
        ordinal = 0
        for m in _get_messages(conv_id):
            if m.get("role") != "assistant":
                continue
            for lang_match, code_match in _CODE_BLOCK_RE.findall(m.get("content", "")):
                if (lang_match or "").lower() == "finaldoc":
                    continue
                if (lang_match or "").lower().startswith("createfile:"):
                    filename = lang_match.split(":", 1)[1].strip()
                    files.append({
                        "filename": filename, "lang": filename.rsplit(".", 1)[-1] if "." in filename else "txt",
                        "size_bytes": len(code_match.encode("utf-8")), "line_count": code_match.count("\n") + 1,
                        "created_at": m.get("created_at"),
                        "download_url": None
                    })
                    continue
                ordinal += 1
                ext = {"html": "html", "javascript": "js", "js": "js", "python": "py", "py": "py",
                       "css": "css", "json": "json", "bash": "sh", "text": "txt"}.get((lang_match or "text").lower(), "txt")
                files.append({
                    "filename": f"generated_{ordinal}.{ext}", "lang": lang_match or "text",
                    "size_bytes": len(code_match.encode("utf-8")), "line_count": code_match.count("\n") + 1,
                    "created_at": m.get("created_at"),
                    "download_url": None
                })
    return jsonify({"conversation_id": conv_id, "files": files})
def _cors_preflight():
    resp = Response("", status=204)
    origin = request.headers.get("Origin", "*")
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept, X-Requested-With"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp
QWEN_APP_HEARTBEAT_ENABLED = os.environ.get("QWEN_APP_HEARTBEAT_ENABLED", "0").strip().lower() not in {"0", "false", "no", "off"}
QWEN_APP_HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("QWEN_APP_HEARTBEAT_INTERVAL_SECONDS", "120"))
QWEN_APP_HEARTBEAT_TIMEOUT_SECONDS = int(os.environ.get("QWEN_APP_HEARTBEAT_TIMEOUT_SECONDS", "20"))
QWEN_APP_HEARTBEAT_MAX_NEW_TOKENS = 1
QWEN_ENTRY_WARMUP_ENABLED = os.environ.get("QWEN_ENTRY_WARMUP_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
QWEN_ENTRY_WARMUP_MIN_INTERVAL_SECONDS = int(os.environ.get("QWEN_ENTRY_WARMUP_MIN_INTERVAL_SECONDS", "60"))
_qwen_app_heartbeat_started = False
_qwen_app_heartbeat_lock = threading.Lock()
_qwen_entry_warm_lock = threading.Lock()
_qwen_entry_warm_last_started = 0.0
def _qwen_app_resolve_worker() -> tuple[str, str]:
    """Resolve the current worker endpoint/token without doing a blocking chat request."""
    try:
        best = _worker_get_latest()
    except Exception:
        best = None
    url = ((best or {}).get("endpoint_url", "").strip().rstrip("/")
           or os.environ.get("QWEN_WORKER_URL", "").strip().rstrip("/"))
    token = _get_expected_worker_token()
    if not url or not token or not _worker_is_online(best):
        return "", ""
    return url, token
def _qwen_app_send_keepwarm_once() -> bool:
    """Ask the worker to touch qwen-local and keep its model resident."""
    url, token = _qwen_app_resolve_worker()
    if not url or not token:
        return False
    target_url = f"{url}/v1/chat/stream"
    payload = json.dumps({
        "messages": [{"role": "user", "content": " "}],
        "conversation_id": "__app_keepwarm__",
        "max_new_tokens": QWEN_APP_HEARTBEAT_MAX_NEW_TOKENS,
        "temperature": 0.0,
        "stream": True,
        "keep_alive": -1,
        "num_ctx": QWEN_WORKER_SIMPLE_CONTEXT_TOKENS,
    }).encode("utf-8")
    req = urllib.request.Request(
        target_url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=QWEN_APP_HEARTBEAT_TIMEOUT_SECONDS) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except Exception:
                    continue
                if event.get("type") in {"answer_end", "error"}:
                    return event.get("type") == "answer_end"
            return resp.status == 200
    except Exception as exc:
        print(f"[QWEN HEARTBEAT] keep-warm attempt failed: {exc}")
        return False
def _qwen_entry_warmup_async() -> None:
    """Best-effort warmup triggered by the website's worker-status request.
    The frontend already polls /worker/status once when the page opens, so this
    gives each fresh app visit a chance to wake/touch qwen-local before the user
    sends their second message. It never blocks the status HTTP response.
    """
    global _qwen_entry_warm_last_started
    if not QWEN_ENTRY_WARMUP_ENABLED or _qwen_user_request_is_active():
        return
    now = time.time()
    with _qwen_entry_warm_lock:
        if now - _qwen_entry_warm_last_started < max(10, QWEN_ENTRY_WARMUP_MIN_INTERVAL_SECONDS):
            return
        _qwen_entry_warm_last_started = now
    def _safe_entry_warmup():
        if _qwen_user_request_is_active():
            return
        _qwen_app_send_keepwarm_once()
    threading.Thread(
        target=_safe_entry_warmup,
        name="pratham-qwen-entry-warm",
        daemon=True,
    ).start()
def _qwen_app_heartbeat_loop() -> None:
    """Optional periodic warmup. Disabled by default because CPU warmup can compete with real chats."""
    global _qwen_app_heartbeat_started
    while True:
        try:
            ok = _qwen_app_send_keepwarm_once()
            if ok:
                print("[QWEN HEARTBEAT] model keep-warm OK")
        except Exception as exc:
            print(f"[QWEN HEARTBEAT] loop error: {exc}")
        time.sleep(max(30, QWEN_APP_HEARTBEAT_INTERVAL_SECONDS))
def _start_qwen_app_heartbeat() -> None:
    """Start one daemon heartbeat thread per long-lived app process."""
    global _qwen_app_heartbeat_started
    if not QWEN_APP_HEARTBEAT_ENABLED:
        return
    with _qwen_app_heartbeat_lock:
        if _qwen_app_heartbeat_started:
            return
        _qwen_app_heartbeat_started = True
        t = threading.Thread(
            target=_qwen_app_heartbeat_loop,
            name="pratham-qwen-keepwarm",
            daemon=True,
        )
        t.start()
        print(
            f"[QWEN HEARTBEAT] app-level keep-warm started "
            f"(interval={QWEN_APP_HEARTBEAT_INTERVAL_SECONDS}s)"
        )
_start_qwen_app_heartbeat()
PRATHAM_FAST_WORKER_BUILD = "2026-09-13-fast-worker-v4"
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
