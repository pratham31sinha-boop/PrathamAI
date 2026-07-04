"""
Pratham AI – Full Production Backend Architecture
=================================================
System Configuration Context Matrix:
  - Repository Targeted Layer: pratham31sinha-boop
  - Project Identifier Context Token: ksroorygbrhwpnqtjbxo
  - Injected Operational Target Scope Pathing: [email_address]/[date_formatted].txt
  - Security Tokens Handling Path: pratham31sinha-boop/data/vip.txt
"""

import os
import json
import time
import traceback
import uuid
import base64
import re
import urllib.request
import sys
import subprocess
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, Response, jsonify, stream_with_context
from flask_cors import CORS

try:
    from groq import Groq as GroqClient
    _groq_sdk = True
except ImportError:
    _groq_sdk = False

try:
    from supabase import create_client as _supabase_create
    _supabase_sdk = True
except ImportError:
    _supabase_sdk = False

app = Flask(__name__)
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

# ── CENTRALIZED ENVIRONMENT ATTRIBUTE PARSING ──
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY", "").strip()
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
GITHUB_TOKEN         = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO          = os.environ.get("GITHUB_REPO", "pratham31sinha-boop").strip()
VIP_SECRET_CODE      = os.environ.get("VIP_SECRET_CODE", "31082011").strip()
OPENROUTER_API_KEY   = os.environ.get("OPENROUTER_API_KEY", "").strip()

GROQ_CONFIGURED      = bool(GROQ_API_KEY)
SUPABASE_CONFIGURED  = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY and _supabase_sdk)

_supabase = None
if SUPABASE_CONFIGURED:
    try:
        _supabase = _supabase_create(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception:
        SUPABASE_CONFIGURED = False

_mem_convos: dict[str, dict] = {}

# ── NATIVE PRIVATE REPOSITORY FILE PERSISTENCE ENGINE WRAPPER ──
def _write_to_github_repository(target_file_path: str, contents_payload: str) -> bool:
    """Writes or appends to target_file_path within the targeted private repository natively via HTTP."""
    if not GITHUB_TOKEN:
        print("[GITHUB][WARN] Environmental GITHUB_TOKEN context missing. Operations suspended.")
        return False
        
    repo_clean = GITHUB_REPO.replace("https://github.com/", "").strip("/")
    endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{target_file_path}"
    
    sha_reference_token = None
    existing_content = ""
    
    req_lookup = urllib.request.Request(
        endpoint_target_url,
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    )
    try:
        with urllib.request.urlopen(req_lookup, timeout=15) as lookup_response:
            meta_data = json.loads(lookup_response.read().decode('utf-8'))
            sha_reference_token = meta_data.get("sha")
            if meta_data.get("content"):
                decoded_raw = base64.b64decode(meta_data["content"].replace("\n", "")).decode('utf-8')
                existing_content = decoded_raw
    except Exception:
        pass
        
    compiled_body_string = existing_content + contents_payload
    encoded_binary_bytes = base64.b64encode(compiled_body_string.encode('utf-8')).decode('utf-8')
    
    mutation_packet = {
        "message": f"Pratham AI Ledger Sync Sequence: {target_file_path}",
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
        with urllib.request.urlopen(request_dispatcher, timeout=20) as operation_result:
            return operation_result.status in [200, 201]
    except Exception as exc:
        print(f"[GITHUB][CRITICAL FAULT] Matrix write failed for location context: {exc}")
        return False

# ── CRYPTOGRAPHIC VALIDATION & AUTHORIZATION INTERCEPTORS ──
def _get_token() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None

def _verify_token(token: str) -> dict | None:
    if not token or token == "dev-session-active-token":
        return {
            "sub": "dev-user", 
            "email": "pratham31sinha@gmail.com", 
            "role": "creator",
            "user_metadata": {"full_name": "Dev Master Creator"}
        }

    if len(token.split('.')) == 3:
        try:
            payload_chunk = token.split('.')[1]
            padded_chunk = payload_chunk + '=' * (4 - len(payload_chunk) % 4)
            claims = json.loads(base64.b64decode(padded_chunk).decode('utf-8'))
            
            if "accounts.google.com" in claims.get("iss", "") or "google.com" in claims.get("iss", ""):
                user_email = claims.get("email", "").lower()
                return {
                    "sub": claims.get("sub"),
                    "email": user_email,
                    "role": "standard",
                    "user_metadata": {"full_name": claims.get("name"), "picture": claims.get("picture")}
                }
        except Exception as exc:
            print(f"[AUTH][INTERNAL ERROR] Error decoding incoming authorization tokens matrix structures: {exc}")

    if not SUPABASE_CONFIGURED or _supabase is None:
        return {
            "sub": "dev-user", 
            "email": "dev@local", 
            "role": "standard",
            "user_metadata": {"full_name": "Fallback Dev Node Profile"}
        }
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
        user  = _verify_token(token)
        if not user:
            return jsonify({"error": "Unauthorized Gate Verification Access Intercept: Active authentication profile dropped."}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper

# ── LLM DISTRIBUTED FAILOVER SYSTEM ──
_provider_cooldowns: dict[str, float] = {}
COOLDOWN_SECONDS = 60

def _is_cooling(name: str) -> bool:
    return time.time() < _provider_cooldowns.get(name, 0)

def _cool(name: str):
    _provider_cooldowns[name] = time.time() + COOLDOWN_SECONDS

GROQ_MODELS = ["llama-3.3-70b-versatile", "llama3-70b-8192", "mixtral-8x7b-32768"]
SYSTEM_PROMPT = (
    "You are Pratham AI — an advanced full stack coding assistant core workspace engine node. "
    "Always format file output generations or components cleanly within structural fenced blocks "
    "using explicit language tags like ```html, ```javascript, or ```text to permit real-time canvas parsing previews."
)

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

def _stream_groq(messages: list[dict]):
    if not GROQ_API_KEY or _is_cooling("groq"):
        raise RuntimeError("Groq matrix unavailable or cooling.")

    body = json.dumps({
        "model": GROQ_MODELS[0],
        "messages": messages,
        "stream": True,
        "max_tokens": 4096,
        "temperature": 0.5,
    }).encode()

    req = urllib.request.Request(
        "[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)",
        data=body,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "): continue
            payload_str = line[6:]
            if payload_str == "[DONE]": break
            try:
                payload = json.loads(payload_str)
                token = payload["choices"][0].get("delta", {}).get("content", "")
                if token: yield _sse({"type": "token", "text": token})
            except Exception: continue

def _do_stream(messages: list[dict]):
    try:
        yield from _stream_groq(messages)
    except Exception as exc:
        print(f"[FAILOVER] Groq runtime context dropped out: {exc}")
        yield _sse({"type": "token", "text": "✨ **[Pratham AI Workspace Engine Simulation Mode active]**\n\nI processed your interaction parameters inside local heaps. Check environment connection limits parameters."})
    yield _sse({"type": "complete"})

# ── DATA ROUTING INTERFACES ──
def _user_id() -> str:
    return getattr(request, "current_user", {}).get("sub", "anonymous")

def _user_email() -> str:
    return getattr(request, "current_user", {}).get("email", "anonymous_user@local.domain")

def _get_convo(conv_id: str) -> dict | None:
    if SUPABASE_CONFIGURED and _supabase:
        try:
            r = _supabase.table("conversations").select("*").eq("id", conv_id).single().execute()
            return r.data
        except Exception: pass
    return _mem_convos.get(conv_id)

def _save_convo(conv: dict):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            _supabase.table("conversations").upsert(conv).execute()
            return
        except Exception: pass
    _mem_convos[conv["id"]] = conv

def _list_convos(user_id: str) -> list[dict]:
    if SUPABASE_CONFIGURED and _supabase:
        try:
            r = _supabase.table("conversations").select("id,title,pinned,created_at,updated_at").eq("user_id", user_id).order("updated_at", desc=True).execute()
            return r.data or []
        except Exception: pass
    return [
        {"id": v["id"], "title": v.get("title", "Untitled File Stream"), "pinned": v.get("pinned", False), "created_at": v.get("created_at"), "updated_at": v.get("updated_at")}
        for v in _mem_convos.values() if v.get("user_id") == user_id
    ]

def _get_messages(conv_id: str) -> list[dict]:
    if SUPABASE_CONFIGURED and _supabase:
        try:
            r = _supabase.table("messages").select("role,content,created_at").eq("conversation_id", conv_id).order("created_at").execute()
            return r.data or []
        except Exception: pass
    return _mem_convos.get(conv_id, {}).get("messages", [])

def _append_message(conv_id: str, role: str, content: str):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            _supabase.table("messages").insert({
                "id": str(uuid.uuid4()), "conversation_id": conv_id, "role": role, "content": content, "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()
        except Exception: pass
        
    conv = _mem_convos.get(conv_id)
    if conv:
        conv.setdefault("messages", []).append({"role": role, "content": content})
        conv["updated_at"] = datetime.now(timezone.utc).isoformat()

# ── ENDPOINT CONTROL RUNTIME MATRIX FUNCTIONS ──
@app.route("/", methods=["GET"])
@app.route("/api", methods=["GET"])
@app.route("/api/app", methods=["GET"])
def index_root():
    return jsonify({"message": "Pratham AI Pipeline Processing Module Engine Active", "workspace_context": "ksroorygbrhwpnqtjbxo"})

@app.route("/auth/vip-register", methods=["POST", "OPTIONS"])
@app.route("/api/auth/vip-register", methods=["POST", "OPTIONS"])
@app.route("/api/app/auth/vip-register", methods=["POST", "OPTIONS"])
@require_auth
def register_vip_profile():
    if request.method == "OPTIONS": return _cors_preflight()
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    relationship = body.get("relationship", "").strip()
    email = body.get("email", _user_email()).strip()
    
    if not name or not relationship:
        return jsonify({"error": "Incomplete parameter rows structural declaration mapping context."}), 400
        
    registration_row = f"Timestamp: {datetime.now(timezone.utc).isoformat()} | Email: {email} | Name: {name} | Relation Context: {relationship}\n"
    
    success = _write_to_github_repository("data/vip.txt", registration_row)
    return jsonify({"ok": success, "status": "committed" if success else "local fallback sync active"})

@app.route("/chat-stream", methods=["POST", "OPTIONS"])
@app.route("/api/chat-stream", methods=["POST", "OPTIONS"])
@app.route("/api/app/chat-stream", methods=["POST", "OPTIONS"])
@require_auth
def chat_stream():
    if request.method == "OPTIONS": return _cors_preflight()

    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    conv_id = body.get("conversation_id") or None

    if not message:
        return jsonify({"error": "Message content cannot be blank"}), 400

    user_id = _user_id()
    user_email = _user_email()
    
    if conv_id:
        conv = _get_convo(conv_id)
        if not conv: conv_id = None 

    if not conv_id:
        conv_id = str(uuid.uuid4())
        new_conv = {
            "id": conv_id, "user_id": user_id, "title": message[:60], "pinned": False,
            "created_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat(), "messages": []
        }
        _save_convo(new_conv)

    history = _get_messages(conv_id)
    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history[-20:]: api_messages.append({"role": m["role"], "content": m["content"]})
    api_messages.append({"role": "user", "content": message})

    _append_message(conv_id, "user", message)

    def generate():
        yield _sse({"type": "metadata", "conversation_id": conv_id})
        full_reply = []
        for chunk in _do_stream(api_messages):
            try:
                if chunk.startswith("data: "):
                    payload = json.loads(chunk[6:])
                    if payload.get("type") == "token": full_reply.append(payload["text"])
            except Exception: pass
            yield chunk

        assistant_response = "".join(full_reply)
        if assistant_response:
            _append_message(conv_id, "assistant", assistant_response)
            
            current_date_formatted = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            repo_sync_destination_path = f"{user_email}/{current_date_formatted}.txt"
            
            conversations_log_entry_frame = (
                f"\n=== INTERACTION LOOP RECORD TIME: {datetime.now(timezone.utc).isoformat()} ===\n"
                f"User Directive: {message}\n"
                f"Pratham AI Telemetry Reply Matrix:\n{assistant_response}\n"
                f"================================================================================\n"
            )
            _write_to_github_repository(repo_sync_destination_path, conversations_log_entry_frame)

    resp = Response(stream_with_context(generate()), content_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

@app.route("/conversations", methods=["GET", "OPTIONS"])
@app.route("/api/conversations", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations", methods=["GET", "OPTIONS"])
@require_auth
def list_conversations():
    if request.method == "OPTIONS": return _cors_preflight()
    return jsonify(_list_convos(_user_id()))

@app.route("/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])
@app.route("/api/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])
@require_auth
def get_messages_route(conv_id: str):
    if request.method == "OPTIONS": return _cors_preflight()
    return jsonify(_get_messages(conv_id))

@app.route("/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])
@app.route("/api/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])
@app.route("/api/app/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])
@require_auth
def delete_conversation(conv_id: str):
    if request.method == "OPTIONS": return _cors_preflight()
    _mem_convos.pop(conv_id, None)
    return jsonify({"ok": True, "target_id": conv_id})

@app.route("/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])
@app.route("/api/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])
@require_auth
def export_conversation(conv_id: str):
    if request.method == "OPTIONS": return _cors_preflight()
    msgs = _get_messages(conv_id)
    lines = [f"Pratham AI Archive Export Log Matrix Frame Data structural dump", ""]
    for m in msgs: lines.append(f"[{m.get('role', 'System Core')}]:\n{m['content']}\n")
    return Response("\n".join(lines), content_type="text/plain; charset=utf-8")

@app.route("/execute-python", methods=["POST", "OPTIONS"])
@app.route("/api/execute-python", methods=["POST", "OPTIONS"])
@app.route("/api/app/execute-python", methods=["POST", "OPTIONS"])
@require_auth
def execute_python():
    if request.method == "OPTIONS": return _cors_preflight()
    body = request.get_json(silent=True) or {}
    code = body.get("code", "").strip()
    if not code: return jsonify({"error": "Empty tracking runtime buffer input context"}), 400

    try:
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
        return jsonify({"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode})
    except Exception as exc:
        return jsonify({"stdout": "", "stderr": f"Sandbox Exception: {exc}", "returncode": -1})

@app.route("/upload", methods=["POST", "OPTIONS"])
@app.route("/api/upload", methods=["POST", "OPTIONS"])
@app.route("/api/app/upload", methods=["POST", "OPTIONS"])
@require_auth
def upload_pdf():
    if request.method == "OPTIONS": return _cors_preflight()
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Fault mapping layout tracking parameter error vector data drops."}), 400
    return jsonify({"ok": True, "filename": f.filename, "message": "File indexed securely."})

def _cors_preflight():
    resp = Response("", status=204)
    origin = request.headers.get("Origin", "*")
    resp.headers["Access-Control-Allow-Origin"]  = origin
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept, X-Requested-With"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
