import os
import re
import sys
import io
import json
import time
import uuid
import base64
import atexit
import logging
import secrets
import threading
import traceback
import contextlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
 
import requests
from flask import Flask, request, jsonify, Response, stream_with_context, g, redirect
from flask_cors import CORS
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from pypdf import PdfReader
from werkzeug.middleware.proxy_fix import ProxyFix
 
# ==============================================================================
# SECTION 1: LOGGING
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(threadName)s] in %(pathname)s:%(lineno)d: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("PrathamAIBackend")
logger.info("=" * 80)
logger.info("Initializing Pratham AI Backend Server (v3, patched)...")
logger.info("=" * 80)
 
# ==============================================================================
# SECTION 2: CONFIGURATION
# All secrets now come ONLY from environment variables. No hardcoded
# fallback keys. Set these in Railway -> Variables.
# ==============================================================================
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
 
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "pratham31sinha-boop/data")
VIP_SECRET_CODE = os.environ.get("VIP_SECRET_CODE", "")
 
# --- SUPABASE CENTRAL INFRASTRUCTURE KEYS ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
 
VIP_EMAIL_ALLOWLIST = {"pratham31sinha@gmail.com"}
VIP_EMAIL_PREFIXES = ("admin@",)
 
REQUEST_TIMEOUT_CONNECT = 8
REQUEST_TIMEOUT_STREAM = 45
MAX_CONTENT_LENGTH_BYTES = 20 * 1024 * 1024
PROVIDER_COOLDOWN_SECONDS = 90
SANDBOX_EXEC_TIMEOUT_SECONDS = 8
 
DATA_DIR = Path(os.environ.get("PRATHAM_DATA_DIR", "./pratham_data"))
STATE_FILE = DATA_DIR / "state.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)
 
if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY is not set. /chat-stream will return a config error until it is set in the environment.")
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    logger.warning("SUPABASE_URL / SUPABASE_ANON_KEY not set. Authentication will fail until these are configured.")
 
logger.info("Configuration loaded. GitHub repo target: %s", GITHUB_REPO)
 
# ==============================================================================
# SECTION 3: FLASK APP BOOTSTRAP AND CORS POLICIES
# ==============================================================================
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
 
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH_BYTES
 
CORS(app, resources={r"/*": {
    "origins": [
        "https://prathamai.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:5500"
    ],
    "allow_headers": ["Content-Type", "Authorization", "Accept", "X-Requested-With"],
    "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
}}, supports_credentials=True)
 
logger.info("CORS successfully initialized with explicit Vercel origins.")
 
# ==============================================================================
# SECTION 3.5: AUTHENTICATION TOKEN EXTRACTOR
# ==============================================================================
def get_authenticated_user():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.error("Cannot authenticate: SUPABASE_URL/SUPABASE_ANON_KEY missing from environment.")
        return None
    headers = {"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY}
    try:
        res = requests.get(f"{SUPABASE_URL}/auth/v1/user", headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        logger.error("Token authentication layer exception: %s", e)
    return None
 
# ==============================================================================
# SECTION 4: GLOBAL STATE + THREAD SAFETY + PERSISTENCE
# ==============================================================================
STATE_LOCK = threading.RLock()
 
SESSIONS = {}
CONVERSATIONS = {}
USER_FILES = {}
PROVIDER_COOLDOWN = {}
CONVO_COUNTER_BOX = {"value": 0}
GITHUB_SYNC_QUEUE = []
 
 
def load_state_from_disk():
    global CONVO_COUNTER_BOX
    if not STATE_FILE.exists():
        logger.info("No prior local state snapshot found - starting fresh.")
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            snapshot = json.load(fh)
        with STATE_LOCK:
            SESSIONS.update(snapshot.get("sessions", {}))
            CONVERSATIONS.update(snapshot.get("conversations", {}))
            USER_FILES.update(snapshot.get("user_files", {}))
            CONVO_COUNTER_BOX["value"] = snapshot.get("convo_counter", 0)
        logger.info(
            "Restored %d sessions, %d conversations, %d user file buckets from disk.",
            len(SESSIONS), len(CONVERSATIONS), len(USER_FILES),
        )
    except Exception as exc:
        logger.error("Failed to load persisted state snapshot: %s", exc)
        logger.error(traceback.format_exc())
 
 
def save_state_to_disk():
    try:
        with STATE_LOCK:
            snapshot = {
                "sessions": SESSIONS,
                "conversations": CONVERSATIONS,
                "user_files": USER_FILES,
                "convo_counter": CONVO_COUNTER_BOX["value"],
            }
        tmp_path = STATE_FILE.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh)
        tmp_path.replace(STATE_FILE)
    except Exception as exc:
        logger.error("Failed to persist state snapshot to disk: %s", exc)
 
 
load_state_from_disk()
logger.info("In-memory tracking structures and database structures successfully instantiated.")
 
# ==============================================================================
# SECTION 5: SMALL UTILITIES
# ==============================================================================
 
def now_iso():
    return datetime.now(timezone.utc).isoformat()
 
 
def new_request_id():
    return uuid.uuid4().hex[:12]
 
 
def safe_json_body():
    try:
        data = request.get_json(silent=True, force=True)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
 
 
def email_to_folder_name(email):
    if not email:
        return "unknown_user"
    local_part = email.split("@")[0]
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", local_part)
    return safe or "unknown_user"
 
 
def truncate(text, limit=4000):
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "... [truncated]"
 
 
def error_response(message, status_code, **extra):
    request_id = getattr(g, "request_id", new_request_id())
    body = {"error": message, "status": status_code, "request_id": request_id}
    body.update(extra)
    return jsonify(body), status_code
 
 
# ==============================================================================
# SECTION 6: REQUEST LIFECYCLE HOOKS
# ==============================================================================
 
@app.before_request
def _attach_request_context():
    g.request_id = new_request_id()
    g.started_at = time.time()
    logger.info("--> [%s] %s %s from %s", g.request_id, request.method, request.path, request.remote_addr)
 
 
@app.after_request
def _finalize_response(response):
    try:
        elapsed_ms = (time.time() - getattr(g, "started_at", time.time())) * 1000
        response.headers["X-Request-Id"] = getattr(g, "request_id", "n/a")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer-when-downgrade"
        logger.info(
            "<-- [%s] %s %s -> %s (%.1fms)",
            getattr(g, "request_id", "n/a"), request.method, request.path, response.status_code, elapsed_ms,
        )
    except Exception:
        pass
    return response
 
 
# ==============================================================================
# SECTION 7: GITHUB PRIVATE-REPO CLIENT
# ==============================================================================
class GithubLogClient:
    def __init__(self, token, repo):
        self.token = token
        self.repo = repo
        self.api_base = f"https://api.github.com/repos/{repo}"
 
    @property
    def enabled(self):
        return bool(self.token and self.repo)
 
    def _headers(self):
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PrathamAI-Backend",
        }
 
    def get_file(self, path):
        url = f"{self.api_base}/contents/{path}"
        res = requests.get(url, headers=self._headers(), timeout=REQUEST_TIMEOUT_CONNECT)
        if res.status_code == 200:
            payload = res.json()
            sha = payload.get("sha")
            raw = payload.get("content", "")
            try:
                content = base64.b64decode(raw).decode("utf-8", errors="ignore")
            except Exception:
                content = ""
            return content, sha
        if res.status_code == 404:
            return "", None
        logger.warning("GitHub get_file unexpected status %s for %s", res.status_code, path)
        return "", None
 
    def put_file(self, path, content, message):
        old_content, sha = self.get_file(path)
        combined = (old_content + "\n" if old_content else "") + content
        encoded = base64.b64encode(combined.encode("utf-8")).decode("utf-8")
        payload = {"message": message, "content": encoded}
        if sha:
            payload["sha"] = sha
        url = f"{self.api_base}/contents/{path}"
        res = requests.put(url, headers=self._headers(), json=payload, timeout=REQUEST_TIMEOUT_STREAM)
        if res.status_code not in (200, 201):
            logger.warning("GitHub put_file failed (%s) for %s: %s", res.status_code, path, truncate(res.text, 300))
        return res.status_code in (200, 201)
 
    def append_chat_log(self, email, log_entry):
        folder = email_to_folder_name(email)
        date_str = time.strftime("%Y-%m-%d")
        path = f"chat_logs/{folder}/{date_str}.txt"
        message = f"Sync chat transcript for {folder} ({date_str})"
        return self.put_file(path, log_entry, message)
 
 
github_client = GithubLogClient(GITHUB_TOKEN, GITHUB_REPO)
 
 
def sync_chat_log_to_github(email, log_entry):
    if not github_client.enabled:
        logger.warning("GitHub sync skipped - token/repo not configured.")
        return
 
    def _async_push():
        try:
            ok = github_client.append_chat_log(email, log_entry)
            if not ok:
                logger.warning("GitHub sync failed for %s (will remain only in local state).", email)
        except Exception as exc:
            logger.error("GitHub async push raised an exception: %s", exc)
 
    threading.Thread(target=_async_push, daemon=True, name="github-sync").start()
 
 
# ==============================================================================
# SECTION 8: PDF EXTRACTION + LIGHTWEIGHT RAG FOR @education MODE
# ==============================================================================
 
def extract_pdf_text(file_bytes, max_chars=20000):
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        parts = []
        for i, page in enumerate(reader.pages):
            try:
                parts.append(page.extract_text() or "")
            except Exception as page_exc:
                logger.warning("Failed extracting text from PDF page %d: %s", i, page_exc)
        text = "\n".join(parts).strip()
        return truncate(text, max_chars)
    except Exception as exc:
        logger.error("PDF extraction failed entirely: %s", exc)
        return ""
 
 
def build_education_context(user_id, question, max_chars=6000):
    docs = USER_FILES.get(user_id, [])
    if not docs:
        return "", []
 
    keywords = {w.lower() for w in re.findall(r"[a-zA-Z0-9]{3,}", question) if w.lower() != "education"}
    scored_chunks = []
    for doc in docs:
        text = doc.get("text", "")
        if not text:
            continue
        chunks = [c.strip() for c in re.split(r"\n{2,}", text) if c.strip()]
        for chunk in chunks:
            lower_chunk = chunk.lower()
            score = sum(1 for kw in keywords if kw in lower_chunk)
            if score > 0:
                scored_chunks.append((score, doc["filename"], chunk))
 
    scored_chunks.sort(key=lambda t: t[0], reverse=True)
    selected = scored_chunks[:6] if scored_chunks else [(0, d["filename"], d.get("text", "")[:1200]) for d in docs[:2]]
 
    context_parts = []
    used_files = []
    running_len = 0
    for _, filename, chunk in selected:
        block = f"[From {filename}]\n{chunk}"
        if running_len + len(block) > max_chars:
            continue
        context_parts.append(block)
        used_files.append(filename)
        running_len += len(block)
 
    return "\n\n".join(context_parts), sorted(set(used_files))
 
 
# ==============================================================================
# SECTION 9: APPLICATION API ROUTE DEFINITIONS
# ==============================================================================
 
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "providers": [
            {"name": "groq", "configured": bool(GROQ_API_KEY), "is_default": True, "cooling_down": False},
            {"name": "openrouter", "configured": bool(OPENROUTER_API_KEY), "is_default": False, "cooling_down": False},
            {"name": "cerebras", "configured": bool(CEREBRAS_API_KEY), "is_default": False, "cooling_down": False},
            {"name": "mistral", "configured": bool(MISTRAL_API_KEY), "is_default": False, "cooling_down": False}
        ]
    })
 
@app.route("/api/app", methods=["GET"])
def api_app_root():
    # Added for Vercel deployment: this is the endpoint the frontend's
    # test button calls (fetch('/api/app')). Vercel's Python builder
    # auto-detects the `app` Flask/WSGI object below and serves it as a
    # serverless function, so no BaseHTTPRequestHandler class is needed -
    # exporting `app` IS the Vercel-compatible "handler equivalent".
    return jsonify({
        "status": "ok",
        "message": "Pratham AI backend is reachable on Vercel.",
        "time": now_iso(),
        "groq_configured": bool(GROQ_API_KEY),
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_ANON_KEY)
    })

@app.route("/upload", methods=["POST"])
def upload():
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
    if "file" not in request.files:
        return error_response("No data file stream presented.", 400)
    file = request.files["file"]
    if not file.filename.endswith(".pdf"):
        return error_response("Invalid file formatting structure.", 400)
 
    file_bytes = file.read()
    extracted_text = extract_pdf_text(file_bytes)
 
    user_id = user["id"]
    with STATE_LOCK:
        if user_id not in USER_FILES:
            USER_FILES[user_id] = []
        USER_FILES[user_id].append({
            "filename": file.filename,
            "text": extracted_text,
            "uploaded_at": now_iso()
        })
    save_state_to_disk()
    return jsonify({"status": "success", "filename": file.filename})
 
@app.route("/conversations", methods=["GET"])
def get_conversations():
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
 
    user_id = user["id"]
    user_convos = []
    with STATE_LOCK:
        for c_id, convo in CONVERSATIONS.items():
            if convo.get("user_id") == user_id:
                user_convos.append({
                    "id": c_id,
                    "title": convo.get("title", "Untitled Chat"),
                    "pinned": convo.get("pinned", False),
                    "updated_at": convo.get("updated_at")
                })
    user_convos.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
    return jsonify(user_convos)
 
@app.route("/conversations/<convo_id>/messages", methods=["GET"])
def get_messages(convo_id):
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
 
    with STATE_LOCK:
        convo = CONVERSATIONS.get(convo_id)
        if not convo or convo.get("user_id") != user["id"]:
            return error_response("Conversation not found.", 404)
        return jsonify(convo.get("messages", []))
 
@app.route("/conversations/<convo_id>", methods=["DELETE"])
def delete_conversation(convo_id):
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
 
    with STATE_LOCK:
        if convo_id in CONVERSATIONS and CONVERSATIONS[convo_id].get("user_id") == user["id"]:
            del CONVERSATIONS[convo_id]
            save_state_to_disk()
            return jsonify({"status": "success"})
    return error_response("Conversation not found.", 404)
 
@app.route("/conversations/<convo_id>/pin", methods=["POST"])
def toggle_pin(convo_id):
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
 
    with STATE_LOCK:
        convo = CONVERSATIONS.get(convo_id)
        if convo and convo.get("user_id") == user["id"]:
            convo["pinned"] = not convo.get("pinned", False)
            save_state_to_disk()
            return jsonify({"status": "success", "pinned": convo["pinned"]})
    return error_response("Conversation not found.", 404)
 
@app.route("/conversations/<convo_id>/rename", methods=["PATCH"])
def rename_conversation(convo_id):
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
 
    body = safe_json_body()
    new_title = body.get("title", "").strip()
    if not new_title:
        return error_response("Missing title.", 400)
 
    with STATE_LOCK:
        convo = CONVERSATIONS.get(convo_id)
        if convo and convo.get("user_id") == user["id"]:
            convo["title"] = new_title
            save_state_to_disk()
            return jsonify({"status": "success"})
    return error_response("Conversation not found.", 404)
 
@app.route("/conversations/<convo_id>/export", methods=["GET"])
def export_conversation(convo_id):
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
 
    with STATE_LOCK:
        convo = CONVERSATIONS.get(convo_id)
        if not convo or convo.get("user_id") != user["id"]:
            return error_response("Conversation not found.", 404)
 
        output = io.StringIO()
        output.write(f"Chat Transcript: {convo.get('title')}\nGenerated: {now_iso()}\n\n")
        for m in convo.get("messages", []):
            output.write(f"[{m['role'].upper()}]: {m['content']}\n\n")
 
        return Response(
            output.getvalue(),
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment;filename=chat_{convo_id}.txt"}
        )
 
@app.route("/execute-python", methods=["POST"])
def execute_python():
    # NOTE: this endpoint executes arbitrary code on the server with only
    # an 8-second timeout as protection. Anyone who can sign in can run
    # arbitrary Python on your Railway instance. Left functionally as-is
    # since replacing it needs a real sandbox (e.g. a container-per-run),
    # but flagging this clearly: restrict who can log in, or disable this
    # route, if this app is public-facing.
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
 
    body = safe_json_body()
    code = body.get("code", "")
    if not code:
        return error_response("Empty code.", 400)
 
    try:
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=SANDBOX_EXEC_TIMEOUT_SECONDS
        )
        return jsonify({"stdout": res.stdout, "stderr": res.stderr})
    except subprocess.TimeoutExpired:
        return jsonify({"stdout": "", "stderr": "Execution timed out."})
    except Exception as e:
        return jsonify({"stdout": "", "stderr": str(e)})
 
@app.route("/feedback", methods=["POST"])
def feedback():
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
    return jsonify({"status": "success", "message": "Feedback recorded."})
 
@app.route("/auth/vip-upgrade", methods=["POST"])
def vip_upgrade():
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
 
    if not VIP_SECRET_CODE:
        return error_response("VIP upgrades are not configured on this server.", 503)
 
    body = safe_json_body()
    code = body.get("code", "")
    if code == VIP_SECRET_CODE or user.get("email") in VIP_EMAIL_ALLOWLIST:
        user_metadata = user.copy()
        user_metadata["role"] = "vip"
        return jsonify({"status": "success", "user": user_metadata})
    return error_response("Invalid VIP code.", 403)
 
@app.route("/chat-stream", methods=["POST"])
def chat_stream():
    user = get_authenticated_user()
    if not user:
        return error_response("Unauthorized Access Token.", 401)
 
    if not GROQ_API_KEY:
        return error_response("Server is missing GROQ_API_KEY configuration.", 503)
 
    body = safe_json_body()
    message_text = body.get("message", "").strip()
    convo_id = body.get("conversation_id")
 
    if not message_text:
        return error_response("Message cannot be empty.", 400)
 
    if not convo_id:
        convo_id = uuid.uuid4().hex[:16]
        with STATE_LOCK:
            CONVERSATIONS[convo_id] = {
                "user_id": user["id"],
                "title": message_text[:24] + ("..." if len(message_text) > 24 else ""),
                "pinned": False,
                "messages": [],
                "created_at": now_iso(),
                "updated_at": now_iso()
            }
            CONVO_COUNTER_BOX["value"] += 1
 
    @stream_with_context
    def generate():
        yield f"data: {json.dumps({'type': 'metadata', 'conversation_id': convo_id})}\n\n"
 
        context = ""
        if "@education" in message_text:
            context, _ = build_education_context(user["id"], message_text)
 
        system_prompt = "You are Pratham AI, an expert, adaptive assistant."
        if context:
            system_prompt += f"\nGround your responses using this context from the user's uploaded documents:\n{context}"
 
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text}
            ],
            "stream": True
        }
 
        try:
            # FIXED: was "openapi" (typo), must be "openai"
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload, headers=headers, stream=True, timeout=REQUEST_TIMEOUT_STREAM
            )
            if res.status_code == 200:
                full_collected_response = ""
                for line in res.iter_lines():
                    if line:
                        line_str = line.decode("utf-8").strip()
                        if line_str.startswith("data: ") and not line_str.endswith("[DONE]"):
                            try:
                                data_chunk = json.loads(line_str[6:])
                                token = data_chunk["choices"][0]["delta"].get("content", "")
                                if token:
                                    full_collected_response += token
                                    yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
                            except Exception:
                                pass
 
                with STATE_LOCK:
                    if convo_id in CONVERSATIONS:
                        CONVERSATIONS[convo_id]["messages"].append({"role": "user", "content": message_text})
                        CONVERSATIONS[convo_id]["messages"].append({"role": "assistant", "content": full_collected_response})
                        CONVERSATIONS[convo_id]["updated_at"] = now_iso()
                save_state_to_disk()
 
                sync_chat_log_to_github(user.get("email"), f"User: {message_text}\nAI: {full_collected_response}")
                yield f"data: {json.dumps({'type': 'complete', 'provider': 'groq'})}\n\n"
            else:
                logger.error("Groq returned status %s: %s", res.status_code, truncate(res.text, 500))
                yield f"data: {json.dumps({'type': 'error', 'text': 'The AI provider returned an error. Please try again.'})}\n\n"
        except Exception as ex:
            logger.error("chat-stream exception: %s", ex)
            yield f"data: {json.dumps({'type': 'error', 'text': str(ex)})}\n\n"
 
    return Response(generate(), mimetype="text/event-stream")
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# ==============================================================================
# SECTION 10: VERCEL SERVERLESS COMPATIBILITY NOTES
# ==============================================================================
# Vercel's Python runtime (@vercel/python) auto-detects a WSGI-compatible
# object named `app` in this file and wraps it as the serverless function
# entrypoint - this is the officially supported "handler equivalent" for
# Flask apps, so `app` above is left exported exactly as-is.
#
# Two things will NOT survive on Vercel the way they do on Railway, because
# serverless functions are stateless and short-lived per invocation:
#   1. SESSIONS / CONVERSATIONS / USER_FILES / STATE_FILE persistence - each
#      cold start gets a fresh in-memory dict and an ephemeral filesystem, so
#      conversation history will not reliably persist between requests. For
#      real persistence on Vercel you would need an external store (e.g.
#      Supabase Postgres, Redis) instead of the local JSON snapshot file.
#   2. SSE streaming from /chat-stream and long-running /execute-python calls
#      are subject to Vercel's per-invocation execution time limit, so very
#      long generations or long-running Python snippets may be cut off.
# Both routes are left fully intact above so behavior is unchanged when this
# same file is run on Railway/Render; the constraints above only apply once
# deployed on Vercel specifically.
application = app
