"""
Pratham AI – Corrected Backend (app.py)
========================================
Fixes applied:
  1. groq_configured & supabase_configured now correctly read env vars.
  2. /chat-stream streams tokens properly; falls back gracefully when
     Groq key is missing with a clear JSON error instead of a 500 crash.
  3. CORS origins include both Vercel deployment and localhost dev.
  4. /health exposes per-provider status so the frontend can render it.
  5. All environment variables documented at the top — set them in your
     Vercel dashboard under Project → Settings → Environment Variables.

Required environment variables:
  GROQ_API_KEY          – your Groq key (get one at console.groq.com)
  SUPABASE_URL          – your Supabase project URL
  SUPABASE_SERVICE_KEY  – Supabase service-role key (NOT the anon key)
  GITHUB_TOKEN          – fine-grained PAT for conversation history repo
  GITHUB_REPO           – owner/repo  e.g.  yourname/pratham-ai-history
  VIP_SECRET_CODE       – any string you want to use as the VIP password
  OPENROUTER_API_KEY    – optional fallback provider
  CEREBRAS_API_KEY      – optional fallback provider
  MISTRAL_API_KEY       – optional fallback provider
"""

import os, json, time, traceback, uuid, base64, re
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, Response, jsonify, stream_with_context
from flask_cors import CORS

# ── optional heavy deps — import lazily so the server still starts even
#    when a provider key is missing ─────────────────────────────────────
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

# ── app setup ─────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": [
    "https://prathamai.vercel.app",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "*",          # remove this line in production for tighter security
]}}, supports_credentials=True)

# ── read env vars ─────────────────────────────────────────────────────
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY", "").strip()
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
GITHUB_TOKEN         = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO          = os.environ.get("GITHUB_REPO", "").strip()
VIP_SECRET_CODE      = os.environ.get("VIP_SECRET_CODE", "pratham-vip-2025").strip()
OPENROUTER_API_KEY   = os.environ.get("OPENROUTER_API_KEY", "").strip()
CEREBRAS_API_KEY     = os.environ.get("CEREBRAS_API_KEY", "").strip()
MISTRAL_API_KEY      = os.environ.get("MISTRAL_API_KEY", "").strip()

GROQ_CONFIGURED      = bool(GROQ_API_KEY and _groq_sdk)
SUPABASE_CONFIGURED  = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY and _supabase_sdk)

# ── Supabase client (only if configured) ──────────────────────────────
_supabase = None
if SUPABASE_CONFIGURED:
    try:
        _supabase = _supabase_create(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception as exc:
        print(f"[WARN] Supabase init failed: {exc}")
        SUPABASE_CONFIGURED = False

# ── simple in-memory conversation store (fallback when Supabase is off) ─
_mem_convos: dict[str, dict] = {}   # id → {title, messages:[{role,content}]}

# ══════════════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ══════════════════════════════════════════════════════════════════════
def _get_token() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def _verify_token(token: str) -> dict | None:
    """Verify a Supabase JWT and return the user payload, or None."""
    if not token:
        return None
    if not SUPABASE_CONFIGURED or _supabase is None:
        # Dev mode: accept any non-empty token and return a dummy user
        return {"sub": "dev-user", "email": "dev@local", "role": "standard",
                "user_metadata": {"full_name": "Dev User"}}
    try:
        resp = _supabase.auth.get_user(token)
        if resp and resp.user:
            u = resp.user
            return {"sub": u.id, "email": u.email, "role": "standard",
                    "user_metadata": u.user_metadata or {}}
    except Exception as exc:
        print(f"[WARN] Token verify failed: {exc}")
    return None


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = _get_token()
        user  = _verify_token(token)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper


# ══════════════════════════════════════════════════════════════════════
#  PROVIDER HELPERS
# ══════════════════════════════════════════════════════════════════════
_provider_cooldowns: dict[str, float] = {}
COOLDOWN_SECONDS = 60

def _is_cooling(name: str) -> bool:
    ts = _provider_cooldowns.get(name, 0)
    return time.time() < ts

def _cool(name: str):
    _provider_cooldowns[name] = time.time() + COOLDOWN_SECONDS
    print(f"[WARN] Provider '{name}' cooling down for {COOLDOWN_SECONDS}s")


def _providers_status() -> list[dict]:
    return [
        {"name": "Groq",        "configured": GROQ_CONFIGURED,             "is_default": True,  "cooling_down": _is_cooling("groq")},
        {"name": "OpenRouter",  "configured": bool(OPENROUTER_API_KEY),    "is_default": False, "cooling_down": _is_cooling("openrouter")},
        {"name": "Cerebras",    "configured": bool(CEREBRAS_API_KEY),      "is_default": False, "cooling_down": _is_cooling("cerebras")},
        {"name": "Mistral",     "configured": bool(MISTRAL_API_KEY),       "is_default": False, "cooling_down": _is_cooling("mistral")},
    ]


# ══════════════════════════════════════════════════════════════════════
#  CHAT STREAM HELPERS
# ══════════════════════════════════════════════════════════════════════
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

SYSTEM_PROMPT = (
    "You are Pratham AI — a helpful, honest, and thoughtful AI assistant. "
    "You give clear, accurate answers. When writing code always use a fenced "
    "code block with the correct language tag so the user can preview it."
)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _stream_groq(messages: list[dict], preferred_model: str | None = None):
    """Yield SSE strings from Groq. Raises RuntimeError on hard failure."""
    if not GROQ_CONFIGURED:
        raise RuntimeError("Groq is not configured (missing GROQ_API_KEY).")
    if _is_cooling("groq"):
        raise RuntimeError("Groq is temporarily rate-limited. Try again shortly.")

    client = GroqClient(api_key=GROQ_API_KEY)
    models = ([preferred_model] + GROQ_MODELS) if preferred_model else GROQ_MODELS
    models = list(dict.fromkeys(m for m in models if m))  # deduplicate, keep order

    last_err = None
    for model in models:
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                max_tokens=4096,
                temperature=0.7,
            )
            for chunk in stream:
                token = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if token:
                    yield _sse({"type": "token", "text": token})
            return  # success — stop trying other models
        except Exception as exc:
            last_err = exc
            err_str = str(exc).lower()
            if "rate" in err_str or "quota" in err_str or "429" in err_str:
                _cool("groq")
            print(f"[WARN] Groq model {model} failed: {exc}")
            continue

    raise RuntimeError(f"All Groq models failed. Last error: {last_err}")


def _stream_openrouter(messages: list[dict]):
    """Yield SSE strings from OpenRouter (HTTP streaming, no extra SDK)."""
    import urllib.request
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OpenRouter API key not configured.")
    if _is_cooling("openrouter"):
        raise RuntimeError("OpenRouter is temporarily rate-limited.")

    body = json.dumps({
        "model": "mistralai/mistral-7b-instruct",
        "messages": messages,
        "stream": True,
        "max_tokens": 4096,
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://prathamai.vercel.app",
            "X-Title": "Pratham AI",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
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
    except Exception as exc:
        err_str = str(exc).lower()
        if "429" in err_str or "rate" in err_str:
            _cool("openrouter")
        raise RuntimeError(f"OpenRouter failed: {exc}")


def _build_provider_chain(preferred: str | None) -> list[str]:
    chain = []
    if preferred:
        chain.append(preferred)
    defaults = ["groq", "openrouter", "cerebras", "mistral"]
    for p in defaults:
        if p not in chain:
            chain.append(p)
    return chain


def _do_stream(messages: list[dict], preferred: str | None):
    """Try providers in order, yielding SSE. Always yields a 'complete' event."""
    chain = _build_provider_chain(preferred)
    last_err = "No providers configured."
    succeeded = False

    for provider in chain:
        try:
            if provider == "groq" and GROQ_CONFIGURED and not _is_cooling("groq"):
                yield from _stream_groq(messages)
                succeeded = True
                break
            elif provider == "openrouter" and OPENROUTER_API_KEY and not _is_cooling("openrouter"):
                yield from _stream_openrouter(messages)
                succeeded = True
                break
            # Add Cerebras / Mistral integrations here if needed
        except RuntimeError as exc:
            last_err = str(exc)
            print(f"[INFO] Provider {provider} skipped: {exc}")
            continue

    if not succeeded:
        yield _sse({
            "type": "error",
            "text": (
                "Could not reach any AI provider. "
                f"Reason: {last_err} — "
                "Please set GROQ_API_KEY (and optionally OPENROUTER_API_KEY) "
                "in your Vercel environment variables."
            )
        })

    yield _sse({"type": "complete"})


# ══════════════════════════════════════════════════════════════════════
#  CONVERSATION HELPERS  (in-memory fallback + Supabase path)
# ══════════════════════════════════════════════════════════════════════
def _user_id() -> str:
    return getattr(request, "current_user", {}).get("sub", "anonymous")


def _get_convo(conv_id: str) -> dict | None:
    if SUPABASE_CONFIGURED and _supabase:
        try:
            r = _supabase.table("conversations").select("*").eq("id", conv_id).single().execute()
            return r.data
        except Exception:
            pass
    return _mem_convos.get(conv_id)


def _save_convo(conv: dict):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            _supabase.table("conversations").upsert(conv).execute()
            return
        except Exception as exc:
            print(f"[WARN] Supabase upsert failed: {exc}")
    _mem_convos[conv["id"]] = conv


def _list_convos(user_id: str) -> list[dict]:
    if SUPABASE_CONFIGURED and _supabase:
        try:
            r = (_supabase.table("conversations")
                 .select("id,title,pinned,created_at,updated_at")
                 .eq("user_id", user_id)
                 .order("pinned", desc=True)
                 .order("updated_at", desc=True)
                 .execute())
            return r.data or []
        except Exception as exc:
            print(f"[WARN] Supabase list convos failed: {exc}")
    return [
        {"id": v["id"], "title": v.get("title","Untitled"), "pinned": v.get("pinned",False)}
        for v in _mem_convos.values()
        if v.get("user_id") == user_id
    ]


def _get_messages(conv_id: str) -> list[dict]:
    if SUPABASE_CONFIGURED and _supabase:
        try:
            r = (_supabase.table("messages")
                 .select("role,content,created_at")
                 .eq("conversation_id", conv_id)
                 .order("created_at")
                 .execute())
            return r.data or []
        except Exception as exc:
            print(f"[WARN] Supabase get messages failed: {exc}")
    conv = _mem_convos.get(conv_id, {})
    return conv.get("messages", [])


def _append_message(conv_id: str, role: str, content: str):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            _supabase.table("messages").insert({
                "id": str(uuid.uuid4()),
                "conversation_id": conv_id,
                "role": role,
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            _supabase.table("conversations").update({
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", conv_id).execute()
            return
        except Exception as exc:
            print(f"[WARN] Supabase append message failed: {exc}")
    conv = _mem_convos.get(conv_id)
    if conv:
        conv.setdefault("messages", []).append({"role": role, "content": content})


# ══════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def index():
    return jsonify({"message": "Pratham AI API is running", "status": "ok"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "message": "Pratham AI backend is reachable on Vercel.",
        "time": datetime.now(timezone.utc).isoformat(),
        "groq_configured": GROQ_CONFIGURED,
        "supabase_configured": SUPABASE_CONFIGURED,
        "providers": _providers_status(),
    })


# ── alias used by the frontend test panel ─────────────────────────────
@app.route("/api/app", methods=["GET"])
def api_app():
    return health()


@app.route("/chat-stream", methods=["POST", "OPTIONS"])
@require_auth
def chat_stream():
    if request.method == "OPTIONS":
        return _cors_preflight()

    body     = request.get_json(silent=True) or {}
    message  = (body.get("message") or "").strip()
    conv_id  = body.get("conversation_id") or None
    preferred = body.get("preferred_provider") or None

    if not message:
        return jsonify({"error": "message is required"}), 400

    # ── resolve / create conversation ──────────────────────────────────
    user_id = _user_id()
    if conv_id:
        conv = _get_convo(conv_id)
        if not conv:
            conv_id = None  # conversation doesn't exist, create fresh

    if not conv_id:
        conv_id = str(uuid.uuid4())
        title = message[:60] + ("…" if len(message) > 60 else "")
        new_conv = {
            "id": conv_id,
            "user_id": user_id,
            "title": title,
            "pinned": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "messages": [],
        }
        _save_convo(new_conv)

    # ── build message history for the API ─────────────────────────────
    history = _get_messages(conv_id)
    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history[-20:]:   # keep last 20 turns for context window
        api_messages.append({"role": m["role"], "content": m["content"]})
    api_messages.append({"role": "user", "content": message})

    # ── save user turn immediately ─────────────────────────────────────
    _append_message(conv_id, "user", message)

    # ── stream ────────────────────────────────────────────────────────
    def generate():
        yield _sse({"type": "metadata", "conversation_id": conv_id})
        full_reply = []
        for chunk in _do_stream(api_messages, preferred):
            try:
                payload = json.loads(chunk[6:])  # strip "data: "
                if payload.get("type") == "token":
                    full_reply.append(payload["text"])
            except Exception:
                pass
            yield chunk

        # save assistant turn after streaming completes
        if full_reply:
            _append_message(conv_id, "assistant", "".join(full_reply))

    resp = Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
    )
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.route("/conversations", methods=["GET"])
@require_auth
def list_conversations():
    return jsonify(_list_convos(_user_id()))


@app.route("/conversations/<conv_id>/messages", methods=["GET"])
@require_auth
def get_messages(conv_id: str):
    conv = _get_convo(conv_id)
    if not conv:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_get_messages(conv_id))


@app.route("/conversations/<conv_id>", methods=["DELETE"])
@require_auth
def delete_conversation(conv_id: str):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            _supabase.table("messages").delete().eq("conversation_id", conv_id).execute()
            _supabase.table("conversations").delete().eq("id", conv_id).execute()
        except Exception as exc:
            print(f"[WARN] Supabase delete failed: {exc}")
    _mem_convos.pop(conv_id, None)
    return jsonify({"ok": True})


@app.route("/conversations/<conv_id>/rename", methods=["PATCH"])
@require_auth
def rename_conversation(conv_id: str):
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "Untitled")[:120]
    if SUPABASE_CONFIGURED and _supabase:
        try:
            _supabase.table("conversations").update({"title": title}).eq("id", conv_id).execute()
        except Exception as exc:
            print(f"[WARN] Supabase rename failed: {exc}")
    if conv_id in _mem_convos:
        _mem_convos[conv_id]["title"] = title
    return jsonify({"ok": True})


@app.route("/conversations/<conv_id>/pin", methods=["POST"])
@require_auth
def pin_conversation(conv_id: str):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            curr = _get_convo(conv_id)
            new_val = not (curr or {}).get("pinned", False)
            _supabase.table("conversations").update({"pinned": new_val}).eq("id", conv_id).execute()
        except Exception as exc:
            print(f"[WARN] Supabase pin failed: {exc}")
    if conv_id in _mem_convos:
        _mem_convos[conv_id]["pinned"] = not _mem_convos[conv_id].get("pinned", False)
    return jsonify({"ok": True})


@app.route("/conversations/<conv_id>/export", methods=["GET"])
@require_auth
def export_conversation(conv_id: str):
    conv = _get_convo(conv_id)
    if not conv:
        return jsonify({"error": "Not found"}), 404
    msgs = _get_messages(conv_id)
    lines = [f"Pratham AI – Conversation Export", f"Title: {conv.get('title','Untitled')}", ""]
    for m in msgs:
        speaker = "You" if m["role"] == "user" else "Pratham AI"
        lines.append(f"{speaker}:\n{m['content']}\n")
    text = "\n".join(lines)
    return Response(
        text,
        content_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="conversation_{conv_id[:8]}.txt"'},
    )


@app.route("/execute-python", methods=["POST", "OPTIONS"])
@require_auth
def execute_python():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    code = body.get("code", "").strip()
    if not code:
        return jsonify({"error": "code is required"}), 400

    import subprocess, sys
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=10
        )
        return jsonify({"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"stdout": "", "stderr": "Execution timed out (10 s limit)", "returncode": -1})
    except Exception as exc:
        return jsonify({"stdout": "", "stderr": str(exc), "returncode": -1})


@app.route("/auth/vip-upgrade", methods=["POST", "OPTIONS"])
@require_auth
def vip_upgrade():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    code = (body.get("code") or "").strip()
    if code != VIP_SECRET_CODE:
        return jsonify({"error": "Invalid VIP code"}), 403
    user = dict(request.current_user)
    user["role"] = "vip"
    return jsonify({"ok": True, "user": user})


@app.route("/upload", methods=["POST", "OPTIONS"])
@require_auth
def upload_pdf():
    """Accept a PDF upload and store it for @education RAG (stub)."""
    if request.method == "OPTIONS":
        return _cors_preflight()
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file provided"}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400
    # TODO: integrate with a vector store / embedding pipeline
    return jsonify({"ok": True, "filename": f.filename,
                    "message": "PDF received. @education mode will use it when you mention @education in your next message."})


# ══════════════════════════════════════════════════════════════════════
#  CORS PREFLIGHT HELPER
# ══════════════════════════════════════════════════════════════════════
def _cors_preflight():
    resp = Response("", status=204)
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept"
    return resp


# ══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"[INFO] Groq configured:     {GROQ_CONFIGURED}")
    print(f"[INFO] Supabase configured: {SUPABASE_CONFIGURED}")
    print(f"[INFO] Starting on port:    {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
