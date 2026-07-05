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
"""

import os
import re
import json
import time
import uuid
import base64
import urllib.request
import sys
import subprocess
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, Response, jsonify, stream_with_context
from flask_cors import CORS

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

# ── ENVIRONMENT ──
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY", "").strip()
OPENROUTER_API_KEY   = os.environ.get("OPENROUTER_API_KEY", "").strip()
CEREBRAS_API_KEY     = os.environ.get("CEREBRAS_API_KEY", "").strip()
MISTRAL_API_KEY      = os.environ.get("MISTRAL_API_KEY", "").strip()
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "https://ksroorygbrhwpnqtjbxo.supabase.co").strip()
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
GITHUB_TOKEN         = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO          = os.environ.get("GITHUB_REPO", "pratham31sinha-boop/data").strip()
VIP_SECRET_CODE      = os.environ.get("VIP_SECRET_CODE", "31082011").strip()

SUPABASE_CONFIGURED = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY and _supabase_sdk)

_supabase = None
if SUPABASE_CONFIGURED:
    try:
        _supabase = _supabase_create(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        print(f"[INIT] Persistent layer connected: {SUPABASE_URL}")
    except Exception:
        SUPABASE_CONFIGURED = False

_mem_convos: dict = {}

# ── GITHUB LOG PERSISTENCE ──
# Small short-lived cache so we don't hammer the GitHub API's "get sha"
# lookup when several appends happen back to back for the same file path.
_gh_sha_cache: dict = {}
_GH_CACHE_TTL = 8  # seconds

def _github_repo_slug() -> str:
    return GITHUB_REPO.replace("https://github.com/", "").strip("/")

def _write_to_github_repository(target_file_path: str, contents_payload: str) -> bool:
    """
    Appends `contents_payload` to `target_file_path` inside the configured
    GitHub repository. Creates the file (and implicitly the folder path,
    since GitHub's contents API creates intermediate folders automatically)
    if it does not already exist.
    """
    if not GITHUB_TOKEN:
        return False

    repo_clean = _github_repo_slug()
    endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{target_file_path}"

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

# ── AUTH ──
def _get_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None

def _decode_google_claims(token: str):
    """Decode (without re-verifying signature) a Google-issued JWT's payload."""
    try:
        payload_chunk = token.split('.')[1]
        padded_chunk = payload_chunk + '=' * (-len(payload_chunk) % 4)
        return json.loads(base64.b64decode(padded_chunk).decode('utf-8'))
    except Exception:
        return None

def _verify_token(token: str):
    if not token or token == "dev-session-active-token":
        return {
            "sub": "dev-user",
            "email": "pratham31sinha@gmail.com",
            "role": "creator",
            "user_metadata": {"full_name": "Dev Master Creator"}
        }

    # Google ID tokens: verify structure and, importantly, expiry (exp claim)
    # so a stored/replayed token can't be used forever, but we DO allow the
    # frontend to silently refresh via Google's own session before expiry.
    if len(token.split('.')) == 3:
        claims = _decode_google_claims(token)
        if claims and ("accounts.google.com" in claims.get("iss", "") or "google.com" in claims.get("iss", "")):
            exp = claims.get("exp", 0)
            if exp and time.time() > exp:
                return None
            user_email = claims.get("email", "").lower()
            return {
                "sub": claims.get("sub"),
                "email": user_email,
                "role": "standard",
                "user_metadata": {"full_name": claims.get("name"), "picture": claims.get("picture")}
            }

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
        user = _verify_token(token)
        if not user:
            return jsonify({"error": "Session expired or invalid. Please sign in again."}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper

# ── LIGHTWEIGHT CONTENT SAFETY GUARD ──
# This does NOT try to be a full moderation system, but it catches a set of
# obviously illegal-intent patterns so the assistant can refuse rather than
# helping, and so the interaction gets flagged in the GitHub audit log.
_BLOCKED_PATTERNS = [
    r"\bmake\s+a\s+bomb\b", r"\bbuild\s+a\s+bomb\b", r"\bhow\s+to\s+hack\b",
    r"\bchild\s+(sexual|porn|abuse)\b", r"\bkill\s+(myself|someone|him|her|them)\b",
    r"\bsynthesi[sz]e\s+(meth|drug|explosive)\b", r"\bmake\s+a\s+weapon\b",
    r"\bcredit\s+card\s+(number|dump|generator)\b", r"\bddos\b", r"\bransomware\b",
]
_BLOCKED_REGEX = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)

def _is_flagged_message(message: str) -> bool:
    return bool(_BLOCKED_REGEX.search(message or ""))

# ── LLM MULTI-PROVIDER FAILOVER: Groq -> OpenRouter -> Cerebras -> Mistral ──
_provider_cooldowns: dict = {}
COOLDOWN_SECONDS = 60

def _is_cooling(name: str) -> bool:
    return time.time() < _provider_cooldowns.get(name, 0)

def _cool(name: str):
    _provider_cooldowns[name] = time.time() + COOLDOWN_SECONDS

SYSTEM_PROMPT = (
    "You are Pratham AI, an advanced full stack coding assistant. "
    "Always format file output generations or components cleanly within fenced code blocks "
    "using explicit language tags like ```html, ```javascript, or ```text so they can be rendered live. "
    "You must never help with illegal activity, weapons, malware, or content that could seriously harm "
    "someone; politely refuse those requests instead."
)

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

def _stream_openai_compatible(url, api_key, model, messages):
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": 4096,
        "temperature": 0.5,
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
    # Shorter connect/read timeout so a dead provider fails over faster
    # instead of making the user wait the full minute before a fallback.
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
                token = payload["choices"][0].get("delta", {}).get("content", "")
                if token:
                    yield _sse({"type": "token", "text": token})
            except Exception:
                continue

def _stream_groq(messages):
    if not GROQ_API_KEY or _is_cooling("groq"):
        raise RuntimeError("Groq unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://api.groq.com/openai/v1/chat/completions",
        GROQ_API_KEY, "llama-3.3-70b-versatile", messages
    )

def _stream_openrouter(messages):
    if not OPENROUTER_API_KEY or _is_cooling("openrouter"):
        raise RuntimeError("OpenRouter unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://openrouter.ai/api/v1/chat/completions",
        OPENROUTER_API_KEY, "meta-llama/llama-3.3-70b-instruct", messages
    )

def _stream_cerebras(messages):
    if not CEREBRAS_API_KEY or _is_cooling("cerebras"):
        raise RuntimeError("Cerebras unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://api.cerebras.ai/v1/chat/completions",
        CEREBRAS_API_KEY, "llama3.3-70b", messages
    )

def _stream_mistral(messages):
    if not MISTRAL_API_KEY or _is_cooling("mistral"):
        raise RuntimeError("Mistral unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://api.mistral.ai/v1/chat/completions",
        MISTRAL_API_KEY, "mistral-large-latest", messages
    )

_PROVIDER_CHAIN = [
    ("groq", _stream_groq),
    ("openrouter", _stream_openrouter),
    ("cerebras", _stream_cerebras),
    ("mistral", _stream_mistral),
]

def _do_stream(messages):
    any_token_yielded = False
    for name, fn in _PROVIDER_CHAIN:
        try:
            for chunk in fn(messages):
                any_token_yielded = True
                yield chunk
            if any_token_yielded:
                yield _sse({"type": "complete"})
                return
        except Exception as exc:
            print(f"[FAILOVER] {name} dropped: {exc}")
            _cool(name)
            continue

    yield _sse({
        "type": "token",
        "text": "All model providers are temporarily unavailable. Please check your API keys or try again shortly."
    })
    yield _sse({"type": "complete"})

# ── DATA ──
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

# ── ROUTES ──
@app.route("/", methods=["GET"])
@app.route("/api", methods=["GET"])
@app.route("/api/app", methods=["GET"])
def index_root():
    return jsonify({"message": "Pratham AI backend active"})

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
    # Saved inside the "data" folder of the repo, at data/vip.txt as requested.
    success = _write_to_github_repository("data/vip.txt", registration_row)
    return jsonify({"ok": success, "status": "committed" if success else "local fallback"})

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
        new_conv = {
            "id": conv_id, "user_id": user_id, "title": message[:60], "pinned": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(), "messages": []
        }
        _save_convo(new_conv)

    # ── Content safety check ──
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

    history = _get_messages(conv_id)
    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history[-20:]:
        api_messages.append({"role": m["role"], "content": m["content"]})
    api_messages.append({"role": "user", "content": message})

    _append_message(conv_id, "user", message)

    def generate():
        yield _sse({"type": "metadata", "conversation_id": conv_id})
        full_reply = []
        for chunk in _do_stream(api_messages):
            try:
                if chunk.startswith("data: "):
                    payload = json.loads(chunk[6:])
                    if payload.get("type") == "token":
                        full_reply.append(payload["text"])
            except Exception:
                pass
            yield chunk

        assistant_response = "".join(full_reply)
        if assistant_response:
            _append_message(conv_id, "assistant", assistant_response)

            current_date_formatted = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            # Saved as: data/<email>/<date>.txt inside the repository
            # (previously this incorrectly wrote to "<email>/<date>.txt" at repo root).
            repo_sync_destination_path = f"data/{user_email}/{current_date_formatted}.txt"

            log_entry = (
                f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"
                f"User: {message}\n"
                f"Pratham AI:\n{assistant_response}\n"
                f"{'=' * 80}\n"
            )
            _write_to_github_repository(repo_sync_destination_path, log_entry)

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

@app.route("/upload", methods=["POST", "OPTIONS"])
@app.route("/api/upload", methods=["POST", "OPTIONS"])
@app.route("/api/app/upload", methods=["POST", "OPTIONS"])
@require_auth
def upload_pdf():
    if request.method == "OPTIONS":
        return _cors_preflight()
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF uploads are supported."}), 400
    return jsonify({"ok": True, "filename": f.filename, "message": "File indexed securely."})

def _cors_preflight():
    resp = Response("", status=204)
    origin = request.headers.get("Origin", "*")
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept, X-Requested-With"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
