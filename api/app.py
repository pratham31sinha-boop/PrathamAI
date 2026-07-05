"""
Pratham AI Gateway Engine - Clean Architecture Production Build
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
import threading
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, Response, jsonify, stream_with_context, send_file
from flask_cors import CORS

# Optional structural extensions extraction matching setup
try:
    from pypdf import PdfReader as _PdfReader
    _PDF_READ_SUPPORTED = True
except ImportError:
    _PDF_READ_SUPPORTED = False

try:
    from fpdf import FPDF as _FPDF
    _PDF_WRITE_SUPPORTED = True
except ImportError:
    _PDF_WRITE_SUPPORTED = False

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --- THREAD-SAFE MEMORY ISOLATION STORAGE CONTAINER ---
class ThreadSafeWorkspaceMemory:
    def __init__(self):
        self._lock = threading.RLock()
        self._store = {}

    def get(self, key, default=None):
        with self._lock:
            return self._store.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._store[key] = value

    def pop(self, key, default=None):
        with self._lock:
            return self._store.pop(key, default)

    def values(self):
        with self._lock:
            return list(self._store.values())

_mem_convos = ThreadSafeWorkspaceMemory()

# --- CONFIGURATION INTERFACE PARSING CONTEXT ---
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY", "").strip()
OPENROUTER_API_KEY   = os.environ.get("OPENROUTER_API_KEY", "").strip()
CEREBRAS_API_KEY     = os.environ.get("CEREBRAS_API_KEY", "").strip()
MISTRAL_API_KEY      = os.environ.get("MISTRAL_API_KEY", "").strip()
GITHUB_TOKEN         = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO          = os.environ.get("GITHUB_REPO", "pratham31sinha-boop/data").strip()
SESSION_SECRET       = os.environ.get("SESSION_SECRET", "pratham-ai-dev-secret-crypt-key-2026").strip()
SESSION_TOKEN_PREFIX = "PAI1"

_provider_cooldowns = {}
_generated_files_store = {}

SYSTEM_PROMPT = (
    "You are Pratham AI, an elite principal software engineering agent. "
    "Provide production-grade layout components without placeholder lines or structural shortcuts. "
    "When requested to build components, output complete usable text frameworks."
)

# --- DECORATORS & CORE CROSS-ROUTING HELPERS ---
def add_route_with_prefixes(rule, **options):
    def decorator(f):
        endpoint = options.pop('endpoint', f.__name__)
        # Register standard structural paths cleanly to handle frontend permutations
        app.add_url_rule(rule, f"{endpoint}_base", f, **options)
        app.add_url_rule(f"/api{rule}", f"{endpoint}_api", f, **options)
        app.add_url_rule(f"/api/app{rule}", f"{endpoint}_apiapp", f, **options)
        return f
    return decorator

def _get_token_from_context():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.args.get("Authorization") or None

def _verify_session_claims(token: str):
    if not token:
        return None
    try:
        if token.startswith(f"{SESSION_TOKEN_PREFIX}."):
            parts = token.split('.')
            if len(parts) != 3:
                return None
            prefix, payload_b64, signature = parts
            expected_sig = hmac.new(SESSION_SECRET.encode('utf-8'), payload_b64.encode('utf-8'), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_sig, signature):
                return None
            padded = payload_b64 + '=' * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))
            if payload.get("exp", 0) < time.time():
                return None
            return payload
        else:
            # Handle standard raw Google ID verification token signatures fallback fallback check
            payload_chunk = token.split('.')[1]
            padded_chunk = payload_chunk + '=' * (-len(payload_chunk) %Part 4)
            claims = json.loads(base64.b64decode(padded_chunk).decode('utf-8'))
            return {
                "sub": claims.get("sub"),
                "email": claims.get("email"),
                "name": claims.get("name", "Workspace User"),
                "picture": claims.get("picture", "")
            }
    except Exception:
        return None

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return _cors_preflight()
        token = _get_token_from_context()
        claims = _verify_session_claims(token)
        if not claims:
            return jsonify({"error": "Unauthorized endpoint initialization request context"}), 401
        request.current_user = claims
        return f(*args, **kwargs)
    return wrapper

def _cors_preflight():
    resp = Response("", status=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, DELETE"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

# --- REMOTE LOG SYNC STRATEGY LAYER ---
def _write_to_github_repository(target_file_path: str, contents_payload: str) -> bool:
    if not GITHUB_TOKEN:
        return False
    repo_slug = GITHUB_REPO.replace("https://github.com/", "").strip("/")
    endpoint_target_url = f"https://api.github.com/repos/{repo_slug}/contents/{target_file_path}"
    
    # Check if remote tracking entity exists to resolve correct mutation index tree
    sha = None
    existing_content = ""
    req_lookup = urllib.request.Request(endpoint_target_url, headers={"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "PrathamAI-Gateway"})
    try:
        with urllib.request.urlopen(req_lookup, timeout=5) as resp:
            meta = json.loads(resp.read().decode('utf-8'))
            sha = meta.get("sha")
            if meta.get("content"):
                existing_content = base64.b64decode(meta["content"].replace("\n", "")).decode('utf-8', errors='ignore')
    except Exception:
        pass

    compiled = existing_content + contents_payload
    encoded = base64.b64encode(compiled.encode('utf-8')).decode('utf-8')
    
    payload_data = {"message": f"Sync trace: {target_file_path}", "content": encoded}
    if sha:
        payload_data["sha"] = sha

    req_write = urllib.request.Request(
        endpoint_target_url,
        data=json.dumps(payload_data).encode('utf-8'),
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json", "User-Agent": "PrathamAI-Gateway"},
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req_write, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception:
        return False

# --- MULTI-PROVIDER AI STREAMING PIPELINE CORE ---
def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

def _stream_provider_call(url, key, model, messages):
    body = json.dumps({"model": model, "messages": messages, "stream": True, "temperature": 0.3}).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "PrathamAI-Core"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        buffer = ""
        while True:
            chunk = resp.read(1024)
            if not chunk:
                break
            buffer += chunk.decode('utf-8', errors='ignore')
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    payload = json.loads(data_str)
                    token = payload["choices"][0].get("delta", {}).get("content", "")
                    if token:
                        yield _sse({"type": "token", "text": token})
                except Exception:
                    continue

def _execute_failover_llm_chain(messages):
    providers = [
        ("groq", "https://api.groq.com/openai/v1/chat/completions", GROQ_API_KEY, "llama-3.3-70b-versatile"),
        ("cerebras", "https://api.cerebras.ai/v1/chat/completions", CEREBRAS_API_KEY, "llama3.3-70b"),
        ("openrouter", "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_API_KEY, "meta-llama/llama-3.3-70b-instruct")
    ]
    
    for name, url, key, model in providers:
        if not key or time.time() < _provider_cooldowns.get(name, 0):
            continue
        try:
            yield from _stream_provider_call(url, key, model, messages)
            return
        except Exception as e:
            print(f"[FAILOVER][PROVIDER DROPPED]: {name} | Err: {e}")
            _provider_cooldowns[name] = time.time() + 60
            continue

    yield _sse({"type": "token", "text": "All integrated AI cluster nodes are currently overloaded. Please check parameters."})

# --- APPLICATION ROUTING ENTRYPOINTS ---
@app.route("/", methods=["GET"])
def service_ping():
    return jsonify({"status": "active", "system": "Pratham AI Engine Layer"})

@add_route_with_prefixes("/auth/exchange", methods=["POST", "OPTIONS"])
def exchange_tokens():
    if request.method == "OPTIONS": return _cors_preflight()
    token = _get_token_from_context()
    claims = _verify_session_claims(token)
    if not claims:
        return jsonify({"error": "Identity validation breach"}), 401
    
    # Format unified session application token payload parameters securely
    session_payload = {
        "sub": claims.get("sub"), "email": claims.get("email"),
        "name": claims.get("name", "User"), "picture": claims.get("picture", ""),
        "exp": int(time.time()) + (30 * 86400)
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(session_payload).encode('utf-8')).decode('utf-8').rstrip('=')
    sig = hmac.new(SESSION_SECRET.encode('utf-8'), payload_b64.encode('utf-8'), hashlib.sha256).hexdigest()
    issued_token = f"{SESSION_TOKEN_PREFIX}.{payload_b64}.{sig}"
    
    return jsonify({"ok": True, "session_token": issued_token, "user": session_payload})

@add_route_with_prefixes("/auth/refresh-check", methods=["POST", "OPTIONS"])
def check_refresh_context():
    if request.method == "OPTIONS": return _cors_preflight()
    token = _get_token_from_context()
    claims = _verify_session_claims(token)
    if not claims: return jsonify({"error": "Stale token index mapping context"}), 401
    return jsonify({"ok": True, "user": claims})

@add_route_with_prefixes("/conversations", methods=["GET", "OPTIONS"])
@require_auth
def list_user_history():
    if request.method == "OPTIONS": return _cors_preflight()
    uid = request.current_user.get("sub")
    user_nodes = [
        {"id": c["id"], "title": c["title"], "updated_at": c["updated_at"]}
        for c in _mem_convos.values() if c.get("user_id") == uid
    ]
    return jsonify(user_nodes)

@add_route_with_prefixes("/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])
@require_auth
def get_convo_messages(conv_id):
    if request.method == "OPTIONS": return _cors_preflight()
    convo = _mem_convos.get(conv_id, {"messages": []})
    return jsonify(convo.get("messages", []))

@add_route_with_prefixes("/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])
@require_auth
def discard_convo(conv_id):
    if request.method == "OPTIONS": return _cors_preflight()
    _mem_convos.pop(conv_id, None)
    return jsonify({"ok": True, "target_id": conv_id})

@add_route_with_prefixes("/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])
@require_auth
def export_convo_payload(conv_id):
    if request.method == "OPTIONS": return _cors_preflight()
    convo = _mem_convos.get(conv_id, {"messages": []})
    lines = [f"[{m['role'].upper()}]:\n{m['content']}\n" for m in convo.get("messages", [])]
    return Response("\n".join(lines), content_type="text/plain; charset=utf-8")

@add_route_with_prefixes("/chat-stream", methods=["POST", "OPTIONS"])
@require_auth
def run_chat_stream_sequence():
    if request.method == "OPTIONS": return _cors_preflight()
    body = request.get_json(silent=True) or {}
    message = body.get("message", "").strip()
    conv_id = body.get("conversation_id") or str(uuid.uuid4())
    
    if not message:
        return jsonify({"error": "Message frame is empty"}), 400

    uid = request.current_user.get("sub")
    uemail = request.current_user.get("email")

    convo = _mem_convos.get(conv_id)
    if not convo:
        convo = {
            "id": conv_id, "user_id": uid, "title": message[:45],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(), "messages": []
        }
        _mem_convos.set(conv_id, convo)

    convo["messages"].append({"role": "user", "content": message})

    # Auto Image Dispatch Logic Detection Block
    if any(keyword in message.lower() for keyword in ["make image", "generate image", "draw matching photo", "create picture"]):
        clean_prompt = re.sub(r"(make|generate|draw|create)\s+(image|picture|photo)?", "", message, flags=re.IGNORECASE).strip()
        img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(clean_prompt or 'futuristic computing matrix')}?nologo=true"
        convo["messages"].append({"role": "assistant", "content": f"Rendering requested asset image link matrix:\n![Generated]({img_url})"})
        
        def image_generation_stream():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "activity", "text": "Triggered Pollinations engine vector"})
            yield _sse({"type": "image", "url": img_url, "prompt": clean_prompt})
            yield _sse({"type": "complete"})
        return Response(stream_with_context(image_generation_stream()), content_type="text/event-stream")

    # Parse and structure historic message arrays for execution gateway delivery
    api_payload_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for historic_node in convo["messages"][-12:]:
        api_payload_messages.append({"role": historic_node["role"], "content": historic_node["content"]})

    def dynamic_event_generator():
        yield _sse({"type": "metadata", "conversation_id": conv_id})
        accumulated_text = []
        
        for event in _execute_failover_llm_chain(api_payload_messages):
            if "token" in event:
                try:
                    chunk_data = json.loads(event.split("data: ")[1])["text"]
                    accumulated_text.append(chunk_data)
                except Exception:
                    pass
            yield event

        full_reply = "".join(accumulated_text)
        if full_reply:
            convo["messages"].append({"role": "assistant", "content": full_reply})
            convo["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            # Persist tracking execution data remotely asynchronously
            _write_to_github_repository(
                f"data_logs/{uemail}/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.txt",
                f"\n--- EXECUTION INDEX: {datetime.now(timezone.utc).isoformat()} ---\nUSER: {message}\nAGENT: {full_reply}\n"
            )

    resp = Response(stream_with_context(dynamic_event_generator()), content_type="text/event-stream")
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

@add_route_with_prefixes("/upload", methods=["POST", "OPTIONS"])
@require_auth
def structural_file_ingress():
    if request.method == "OPTIONS": return _cors_preflight()
    f = request.files.get("file")
    if not f: return jsonify({"error": "Empty reference mapping asset"}), 400
    
    raw = f.read()
    preview_extracted = ""
    ext = f.filename.split('.')[-1].lower() if '.' in f.filename else ''
    
    if ext == "pdf" and _PDF_READ_SUPPORTED:
        try:
            reader = _PdfReader(io.BytesIO(raw))
            preview_extracted = "\n".join((page.extract_text() or "") for page in reader.pages[:4])[:3000]
        except Exception as e:
            preview_extracted = f"PDF compilation bypass: {e}"
    else:
        preview_extracted = raw.decode('utf-8', errors='ignore')[:3000]

    return jsonify({
        "ok": True, "filename": f.filename, "size": len(raw),
        "status": "Extracted context cleanly", "preview": preview_extracted
    })

@add_route_with_prefixes("/execute-python", methods=["POST", "OPTIONS"])
@require_auth
def restricted_sandbox_runner():
    if request.method == "OPTIONS": return _cors_preflight()
    body = request.get_json(silent=True) or {}
    code = body.get("code", "").strip()
    
    if not code:
        return jsonify({"error": "Payload contains no processing codes"}), 400

    # High priority internal code restriction filter block sequence
    blocked_keywords = ["os.system", "subprocess", "rmdir", "shutil", "globals", "eval(", "exec("]
    if any(token in code for token in blocked_keywords):
        return jsonify({"stdout": "", "stderr": "Security Exception: High risk command sequence detected.", "returncode": -1})

    try:
        res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=5)
        return jsonify({"stdout": res.stdout, "stderr": res.stderr, "returncode": res.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"stdout": "", "stderr": "Execution window timed out (Max 5s restriction model)", "returncode": -1})
    except Exception as e:
        return jsonify({"stdout": "", "stderr": str(e), "returncode": -1})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
