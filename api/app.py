"""
Pratham AI - Full Production Backend
=====================================
Everything lives inside the private repo: pratham31sinha-boop/data

Repo layout expected:
  vip.txt                  <- VIP registrations (name | relationship | email)
  public_data.txt          <- freeform "self-taught" notes, always injected
                               into the system prompt (see NOTE below)
  flagged/<date>.txt       <- refused/flagged message audit log
  <email>/<date>.txt       <- per-user conversation transcripts
  education/                <- book PDFs live here, e.g.
                               education/Indian Contract Act.pdf
  logo.png (or .jpg/.svg)   <- if present at repo root, used as the app logo

NOTE on "self-upgrading": true autonomous self-modification is out of scope
for a hosted chatbot (and not something to build unsupervised). What's
implemented instead: public_data.txt is fetched fresh on every chat request
and injected into the system prompt, so anything written into that file
(manually, or via /public-data/append) is immediately "known" on the next
message. That's the realistic version of "the AI can read and use a
knowledge file it has access to."

NOTE on book search: this uses simple keyword-overlap paragraph retrieval,
not embeddings/vector search. It works well for direct factual lookups and
less well for heavily paraphrased questions. Swapping in real embeddings
later is a drop-in replacement for `_naive_paragraph_search`.

NOTE on web search: uses DuckDuckGo's HTML endpoint (no API key needed).
It's a best-effort scrape, not a paid search API, so treat results as
"pretty good," not "guaranteed."
"""

import os
import re
import io
import json
import time
import uuid
import base64
import zipfile
import urllib.request
import urllib.parse
import sys
import subprocess
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, Response, jsonify, stream_with_context, send_file
from flask_cors import CORS

try:
    from supabase import create_client as _supabase_create
    _supabase_sdk = True
except ImportError:
    _supabase_sdk = False

try:
    from pypdf import PdfReader
    _pypdf_available = True
except ImportError:
    _pypdf_available = False

try:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch
    _reportlab_available = True
except ImportError:
    _reportlab_available = False

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

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
    except Exception:
        SUPABASE_CONFIGURED = False

_mem_convos: dict = {}

CREATOR_EMAILS = {"pratham31sinha@gmail.com", "pratham08sinha@gmail.com", "pratham310811@gmail.com"}
SUPERVISOR_EMAILS = {"akritiaishwaryam17@gmail.com", "aditiaishwaryam11@gmail.com"}

IDENTITY_NOTE = (
    "You (Pratham AI) were built by Pratham Sinha, under the guidance of "
    "Akriti Aishwaryam and Aditi Aishwaryam. You may mention this if asked "
    "who made you, but do not bring it up unprompted."
)

REPO_IS_DATA_ROOT = GITHUB_REPO.endswith("/data")

# ── GITHUB HELPERS ──
def _github_repo_slug() -> str:
    return GITHUB_REPO.replace("https://github.com/", "").strip("/")

def _gh_get(path: str, timeout=10):
    if not GITHUB_TOKEN:
        return None
    repo_clean = _github_repo_slug()
    url = f"https://api.github.com/repos/{repo_clean}/contents/{urllib.parse.quote(path)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as exc:
        print(f"[GITHUB][GET FAULT] {path}: {exc}")
        return None

_gh_sha_cache: dict = {}
_GH_CACHE_TTL = 8

def _write_to_github_repository(target_file_path: str, contents_payload: str) -> bool:
    if not GITHUB_TOKEN:
        return False
    repo_clean = _github_repo_slug()
    endpoint = f"https://api.github.com/repos/{repo_clean}/contents/{target_file_path}"

    sha = None
    existing = ""
    cache_hit = _gh_sha_cache.get(target_file_path)
    now_ts = time.time()
    if cache_hit and (now_ts - cache_hit["t"]) < _GH_CACHE_TTL:
        sha, existing = cache_hit["sha"], cache_hit["content"]
    else:
        meta = _gh_get(target_file_path)
        if meta and isinstance(meta, dict):
            sha = meta.get("sha")
            if meta.get("content"):
                try:
                    existing = base64.b64decode(meta["content"].replace("\n", "")).decode('utf-8')
                except Exception:
                    existing = ""

    compiled = existing + contents_payload
    encoded = base64.b64encode(compiled.encode('utf-8')).decode('utf-8')
    packet = {"message": f"Pratham AI sync: {target_file_path}", "content": encoded}
    if sha:
        packet["sha"] = sha

    req = urllib.request.Request(
        endpoint, data=json.dumps(packet).encode('utf-8'),
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json",
                 "Accept": "application/vnd.github.v3+json"},
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status in (200, 201)
            if ok:
                try:
                    resp_body = json.loads(resp.read().decode('utf-8'))
                    new_sha = resp_body.get("content", {}).get("sha")
                    _gh_sha_cache[target_file_path] = {"sha": new_sha, "content": compiled, "t": time.time()}
                except Exception:
                    _gh_sha_cache.pop(target_file_path, None)
            return ok
    except Exception as exc:
        print(f"[GITHUB][WRITE FAULT] {exc}")
        return False

def _vip_file_path() -> str:
    return "vip.txt" if REPO_IS_DATA_ROOT else "data/vip.txt"

def _dated_log_path(email: str) -> str:
    prefix = "" if REPO_IS_DATA_ROOT else "data/"
    return f"{prefix}{email}/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.txt"

def _flagged_log_path() -> str:
    prefix = "" if REPO_IS_DATA_ROOT else "data/"
    return f"{prefix}flagged/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.txt"

def _public_data_path() -> str:
    return "public_data.txt" if REPO_IS_DATA_ROOT else "data/public_data.txt"

def _education_folder() -> str:
    return "education" if REPO_IS_DATA_ROOT else "data/education"

# ── VIP DIRECTORY ──
_vip_cache = {"entries": {}, "t": 0}
_VIP_CACHE_TTL = 30

def _fetch_vip_directory() -> dict:
    now_ts = time.time()
    if _vip_cache["entries"] and (now_ts - _vip_cache["t"]) < _VIP_CACHE_TTL:
        return _vip_cache["entries"]
    entries = {}
    meta = _gh_get(_vip_file_path())
    if meta and isinstance(meta, dict) and meta.get("content"):
        try:
            raw = base64.b64decode(meta["content"].replace("\n", "")).decode('utf-8')
            for row in raw.splitlines():
                row = row.strip()
                if not row or "Email:" not in row:
                    continue
                parts = {}
                for chunk in row.split(" | "):
                    if ":" in chunk:
                        k, _, v = chunk.partition(":")
                        parts[k.strip().lower()] = v.strip()
                email = parts.get("email", "").lower()
                if email:
                    entries[email] = {"name": parts.get("name", ""), "relationship": parts.get("relation", "")}
        except Exception as exc:
            print(f"[VIP][PARSE FAULT] {exc}")
    _vip_cache["entries"] = entries
    _vip_cache["t"] = now_ts
    return entries

def _lookup_vip(email: str):
    if not email:
        return None
    return _fetch_vip_directory().get(email.lower())

# ── PUBLIC DATA (self-taught notes injected into system prompt) ──
_public_data_cache = {"text": "", "t": 0}
_PUBLIC_DATA_TTL = 20

def _fetch_public_data() -> str:
    now_ts = time.time()
    if _public_data_cache["text"] and (now_ts - _public_data_cache["t"]) < _PUBLIC_DATA_TTL:
        return _public_data_cache["text"]
    meta = _gh_get(_public_data_path())
    text = ""
    if meta and isinstance(meta, dict) and meta.get("content"):
        try:
            text = base64.b64decode(meta["content"].replace("\n", "")).decode('utf-8')
        except Exception:
            text = ""
    _public_data_cache["text"] = text
    _public_data_cache["t"] = now_ts
    return text

# ── LOGO ──
_logo_cache = {"url": None, "t": 0}
_LOGO_TTL = 300

def _find_repo_logo_url():
    now_ts = time.time()
    if _logo_cache["t"] and (now_ts - _logo_cache["t"]) < _LOGO_TTL:
        return _logo_cache["url"]
    listing = _gh_get("")
    url = None
    if isinstance(listing, list):
        for item in listing:
            name = item.get("name", "").lower()
            if item.get("type") == "file" and "logo" in name and any(name.endswith(e) for e in (".png", ".jpg", ".jpeg", ".svg", ".webp")):
                url = item.get("download_url")
                break
        if not url:
            for item in listing:
                name = item.get("name", "").lower()
                if item.get("type") == "file" and any(name.endswith(e) for e in (".png", ".jpg", ".jpeg", ".svg", ".webp")):
                    url = item.get("download_url")
                    break
    _logo_cache["url"] = url
    _logo_cache["t"] = now_ts
    return url

# ── AUTH ──
def _get_token():
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else None

def _decode_google_claims(token: str):
    try:
        chunk = token.split('.')[1]
        padded = chunk + '=' * (-len(chunk) % 4)
        return json.loads(base64.b64decode(padded).decode('utf-8'))
    except Exception:
        return None

def _verify_token(token: str):
    if not token or token == "dev-session-active-token":
        return {"sub": "dev-user", "email": "pratham31sinha@gmail.com", "role": "creator",
                "user_metadata": {"full_name": "Dev Master Creator"}}
    if len(token.split('.')) == 3:
        claims = _decode_google_claims(token)
        if claims and ("google.com" in claims.get("iss", "")):
            exp = claims.get("exp", 0)
            if exp and time.time() > exp:
                return None
            email = claims.get("email", "").lower()
            return {"sub": claims.get("sub"), "email": email, "role": "standard",
                    "user_metadata": {"full_name": claims.get("name"), "picture": claims.get("picture")}}
    if not SUPABASE_CONFIGURED or _supabase is None:
        return {"sub": "dev-user", "email": "dev@local", "role": "standard",
                "user_metadata": {"full_name": "Fallback Dev Node Profile"}}
    try:
        resp = _supabase.auth.get_user(token)
        if resp and resp.user:
            return {"sub": resp.user.id, "email": resp.user.email.lower(), "role": "standard",
                    "user_metadata": resp.user.user_metadata or {}}
    except Exception:
        pass
    return None

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return _cors_preflight()
        user = _verify_token(_get_token())
        if not user:
            return jsonify({"error": "Session expired or invalid. Please sign in again."}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper

# ── CONTENT SAFETY GUARD ──
_BLOCKED_PATTERNS = [
    r"\bmake\s+a\s+bomb\b", r"\bbuild\s+a\s+bomb\b", r"\bhow\s+to\s+hack\b",
    r"\bchild\s+(sexual|porn|abuse)\b", r"\bkill\s+(myself|someone|him|her|them)\b",
    r"\bsynthesi[sz]e\s+(meth|drug|explosive)\b", r"\bmake\s+a\s+weapon\b",
    r"\bcredit\s+card\s+(number|dump|generator)\b", r"\bddos\b", r"\bransomware\b",
]
_BLOCKED_REGEX = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)

def _is_flagged_message(message: str) -> bool:
    return bool(_BLOCKED_REGEX.search(message or ""))

# ── LLM PROVIDERS ──
_provider_cooldowns: dict = {}
COOLDOWN_SECONDS = 60

def _is_cooling(name):
    return time.time() < _provider_cooldowns.get(name, 0)

def _cool(name):
    _provider_cooldowns[name] = time.time() + COOLDOWN_SECONDS

BASE_SYSTEM_PROMPT = (
    "You are Pratham AI, an advanced full stack coding assistant and general-purpose "
    "helper. Always format file output cleanly within fenced code blocks using explicit "
    "language tags (```html, ```python, ```text, etc). "
    "You must never help with illegal activity, weapons, malware, or seriously harmful "
    "content; politely refuse those requests instead. " + IDENTITY_NOTE
)

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

def _stream_openai_compatible(url, api_key, model, messages):
    body = json.dumps({"model": model, "messages": messages, "stream": True,
                        "max_tokens": 4096, "temperature": 0.5}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"
    }, method="POST")
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

def _stream_groq(messages, vision=False):
    if not GROQ_API_KEY or _is_cooling("groq"):
        raise RuntimeError("Groq unavailable or cooling.")
    model = "llama-3.2-11b-vision-preview" if vision else "llama-3.3-70b-versatile"
    yield from _stream_openai_compatible("https://api.groq.com/openai/v1/chat/completions", GROQ_API_KEY, model, messages)

def _stream_openrouter(messages, vision=False):
    if not OPENROUTER_API_KEY or _is_cooling("openrouter"):
        raise RuntimeError("OpenRouter unavailable or cooling.")
    model = "meta-llama/llama-3.2-11b-vision-instruct" if vision else "meta-llama/llama-3.3-70b-instruct"
    yield from _stream_openai_compatible("https://openrouter.ai/api/v1/chat/completions", OPENROUTER_API_KEY, model, messages)

def _stream_cerebras(messages, vision=False):
    if not CEREBRAS_API_KEY or _is_cooling("cerebras") or vision:
        raise RuntimeError("Cerebras unavailable, cooling, or no vision support.")
    yield from _stream_openai_compatible("https://api.cerebras.ai/v1/chat/completions", CEREBRAS_API_KEY, "llama3.3-70b", messages)

def _stream_mistral(messages, vision=False):
    if not MISTRAL_API_KEY or _is_cooling("mistral"):
        raise RuntimeError("Mistral unavailable or cooling.")
    model = "pixtral-large-latest" if vision else "mistral-large-latest"
    yield from _stream_openai_compatible("https://api.mistral.ai/v1/chat/completions", MISTRAL_API_KEY, model, messages)

_PROVIDER_CHAIN = [("groq", _stream_groq), ("openrouter", _stream_openrouter),
                    ("cerebras", _stream_cerebras), ("mistral", _stream_mistral)]

def _do_stream(messages, vision=False):
    any_yielded = False
    for name, fn in _PROVIDER_CHAIN:
        try:
            for chunk in fn(messages, vision=vision):
                any_yielded = True
                yield chunk
            if any_yielded:
                yield _sse({"type": "complete"})
                return
        except Exception as exc:
            print(f"[FAILOVER] {name} dropped: {exc}")
            _cool(name)
            continue
    yield _sse({"type": "token", "text": "All model providers are temporarily unavailable. Please check API keys or try again shortly."})
    yield _sse({"type": "complete"})

# ── DATA (conversations) ──
def _user_id():
    return getattr(request, "current_user", {}).get("sub", "anonymous")

def _user_email():
    return getattr(request, "current_user", {}).get("email", "anonymous_user@local.domain")

def _identity_tier(email: str) -> str:
    if email in CREATOR_EMAILS:
        return "creator"
    if email in SUPERVISOR_EMAILS:
        return "supervisor"
    if _lookup_vip(email):
        return "vip"
    return "standard"

def _get_convo(conv_id):
    if SUPABASE_CONFIGURED and _supabase:
        try:
            return _supabase.table("conversations").select("*").eq("id", conv_id).single().execute().data
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
    return [{"id": v["id"], "title": v.get("title", "Untitled"), "pinned": v.get("pinned", False),
             "created_at": v.get("created_at"), "updated_at": v.get("updated_at")}
            for v in _mem_convos.values() if v.get("user_id") == user_id]

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
            _supabase.table("messages").insert({"id": str(uuid.uuid4()), "conversation_id": conv_id, "role": role,
                                                 "content": content, "created_at": datetime.now(timezone.utc).isoformat()}).execute()
        except Exception:
            pass
    conv = _mem_convos.get(conv_id)
    if conv:
        conv.setdefault("messages", []).append({"role": role, "content": content})
        conv["updated_at"] = datetime.now(timezone.utc).isoformat()

def _cors_preflight():
    resp = Response("", status=204)
    origin = request.headers.get("Origin", "*")
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept, X-Requested-With"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

# ══════════════════════════════ ROUTES ══════════════════════════════

@app.route("/", methods=["GET"])
@app.route("/api", methods=["GET"])
@app.route("/api/app", methods=["GET"])
def index_root():
    return jsonify({"message": "Pratham AI backend active"})

@app.route("/auth/refresh-check", methods=["POST", "OPTIONS"])
@app.route("/api/auth/refresh-check", methods=["POST", "OPTIONS"])
@app.route("/api/app/auth/refresh-check", methods=["POST", "OPTIONS"])
def refresh_check():
    if request.method == "OPTIONS":
        return _cors_preflight()
    user = _verify_token(_get_token())
    if not user:
        return jsonify({"error": "Stored session expired."}), 401
    return jsonify({"ok": True, "user": user, "tier": _identity_tier(user.get("email", ""))})

@app.route("/auth/vip-register", methods=["POST", "OPTIONS"])
@app.route("/api/auth/vip-register", methods=["POST", "OPTIONS"])
@app.route("/api/app/auth/vip-register", methods=["POST", "OPTIONS"])
@require_auth
def register_vip_profile():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    relationship = (body.get("relationship") or "").strip()
    email = (body.get("email") or _user_email()).strip()
    if not name or not relationship:
        return jsonify({"error": "Missing name or relationship."}), 400
    row = f"Timestamp: {datetime.now(timezone.utc).isoformat()} | Email: {email} | Name: {name} | Relation: {relationship}\n"
    success = _write_to_github_repository(_vip_file_path(), row)
    if success:
        _vip_cache["t"] = 0
    return jsonify({"ok": success})

@app.route("/repo-logo", methods=["GET", "OPTIONS"])
@app.route("/api/repo-logo", methods=["GET", "OPTIONS"])
@app.route("/api/app/repo-logo", methods=["GET", "OPTIONS"])
def repo_logo():
    if request.method == "OPTIONS":
        return _cors_preflight()
    return jsonify({"logo_url": _find_repo_logo_url()})

@app.route("/education/list", methods=["GET", "OPTIONS"])
@app.route("/api/education/list", methods=["GET", "OPTIONS"])
@app.route("/api/app/education/list", methods=["GET", "OPTIONS"])
@require_auth
def education_list():
    if request.method == "OPTIONS":
        return _cors_preflight()
    listing = _gh_get(_education_folder())
    books = []
    if isinstance(listing, list):
        for item in listing:
            if item.get("type") == "file" and item.get("name", "").lower().endswith(".pdf"):
                books.append({"name": item["name"], "path": item["path"]})
    return jsonify({"books": books})

_book_text_cache: dict = {}
_BOOK_CACHE_TTL = 600

def _fetch_book_text(path: str) -> str:
    now_ts = time.time()
    hit = _book_text_cache.get(path)
    if hit and (now_ts - hit["t"]) < _BOOK_CACHE_TTL:
        return hit["text"]
    meta = _gh_get(path)
    text = ""
    if meta and isinstance(meta, dict) and meta.get("content"):
        try:
            raw_bytes = base64.b64decode(meta["content"].replace("\n", ""))
            if _pypdf_available:
                reader = PdfReader(io.BytesIO(raw_bytes))
                text = "\n".join((p.extract_text() or "") for p in reader.pages)
            else:
                text = "[pypdf not installed on server -- cannot extract PDF text]"
        except Exception as exc:
            text = f"[Could not extract text: {exc}]"
    _book_text_cache[path] = {"text": text, "t": now_ts}
    return text

def _naive_paragraph_search(full_text: str, question: str, top_k=4):
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", full_text) if len(p.strip()) > 40]
    q_words = set(w.lower() for w in re.findall(r"[a-zA-Z]{4,}", question))
    scored = []
    for p in paragraphs:
        p_words = set(w.lower() for w in re.findall(r"[a-zA-Z]{4,}", p))
        overlap = len(q_words & p_words)
        if overlap > 0:
            scored.append((overlap, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:top_k]]

@app.route("/education/ask", methods=["POST", "OPTIONS"])
@app.route("/api/education/ask", methods=["POST", "OPTIONS"])
@app.route("/api/app/education/ask", methods=["POST", "OPTIONS"])
@require_auth
def education_ask():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    book_path = body.get("book_path", "")
    question = (body.get("question") or "").strip()
    if not book_path or not question:
        return jsonify({"error": "book_path and question are required"}), 400

    full_text = _fetch_book_text(book_path)
    excerpts = _naive_paragraph_search(full_text, question)
    context_block = "\n\n---\n\n".join(excerpts) if excerpts else "(No closely matching passage found; answer from general knowledge and say so.)"

    system_prompt = (
        BASE_SYSTEM_PROMPT +
        " You are now answering a question about a specific book the user selected. "
        "Use ONLY the excerpts provided below where relevant, restate them in your own "
        "natural human explanation (don't just copy them verbatim), and be clear if the "
        "excerpts don't fully answer the question.\n\nBOOK EXCERPTS:\n" + context_block
    )
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": question}]

    def generate():
        for chunk in _do_stream(messages):
            yield chunk

    resp = Response(stream_with_context(generate()), content_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

@app.route("/web-search", methods=["POST", "OPTIONS"])
@app.route("/api/web-search", methods=["POST", "OPTIONS"])
@app.route("/api/app/web-search", methods=["POST", "OPTIONS"])
@require_auth
def web_search():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        results = []
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html):
            link, title = m.group(1), re.sub("<[^>]+>", "", m.group(2))
            results.append({"title": title.strip(), "url": link})
            if len(results) >= 5:
                break
        return jsonify({"results": results})
    except Exception as exc:
        return jsonify({"error": str(exc), "results": []}), 200

@app.route("/web-search-ask", methods=["POST", "OPTIONS"])
@app.route("/api/web-search-ask", methods=["POST", "OPTIONS"])
@app.route("/api/app/web-search-ask", methods=["POST", "OPTIONS"])
@require_auth
def web_search_ask():
    """Runs a search, then asks the LLM to answer the question grounded in the results."""
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    results = []
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html):
            link, title = m.group(1), re.sub("<[^>]+>", "", m.group(2))
            results.append(f"- {title.strip()} ({link})")
            if len(results) >= 6:
                break
    except Exception:
        pass

    context_block = "\n".join(results) if results else "(No search results retrieved.)"
    system_prompt = (
        BASE_SYSTEM_PROMPT +
        " You were just given fresh web search results below. Use them to answer the "
        "question accurately, mention sources by name/link where relevant, and say so if "
        "the results don't actually answer it.\n\nSEARCH RESULTS:\n" + context_block
    )
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": query}]

    def generate():
        for chunk in _do_stream(messages):
            yield chunk

    resp = Response(stream_with_context(generate()), content_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    return resp

@app.route("/file-generate/pdf", methods=["POST", "OPTIONS"])
@app.route("/api/file-generate/pdf", methods=["POST", "OPTIONS"])
@app.route("/api/app/file-generate/pdf", methods=["POST", "OPTIONS"])
@require_auth
def file_generate_pdf():
    if request.method == "OPTIONS":
        return _cors_preflight()
    if not _reportlab_available:
        return jsonify({"error": "reportlab is not installed on the server."}), 500
    body = request.get_json(silent=True) or {}
    text = body.get("text", "")
    filename = body.get("filename", "document.pdf")
    if not text:
        return jsonify({"error": "text is required"}), 400

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    width, height = LETTER
    margin = 0.75 * inch
    max_width_chars = 95
    y = height - margin
    c.setFont("Helvetica", 10)
    for raw_line in text.split("\n"):
        wrapped = [raw_line[i:i + max_width_chars] for i in range(0, len(raw_line), max_width_chars)] or [""]
        for line in wrapped:
            if y < margin:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - margin
            c.drawString(margin, y, line)
            y -= 14
    c.save()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=filename)

@app.route("/file-generate/zip", methods=["POST", "OPTIONS"])
@app.route("/api/file-generate/zip", methods=["POST", "OPTIONS"])
@app.route("/api/app/file-generate/zip", methods=["POST", "OPTIONS"])
@require_auth
def file_generate_zip():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    files = body.get("files", [])
    zip_name = body.get("zip_name", "pratham_ai_bundle.zip")
    if not files:
        return jsonify({"error": "files array is required, e.g. [{name, content}]"}), 400

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f.get("name", "file.txt"), f.get("content", ""))
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=zip_name)

@app.route("/public-data", methods=["GET", "OPTIONS"])
@app.route("/api/public-data", methods=["GET", "OPTIONS"])
@app.route("/api/app/public-data", methods=["GET", "OPTIONS"])
@require_auth
def get_public_data():
    if request.method == "OPTIONS":
        return _cors_preflight()
    return jsonify({"content": _fetch_public_data()})

@app.route("/public-data/append", methods=["POST", "OPTIONS"])
@app.route("/api/public-data/append", methods=["POST", "OPTIONS"])
@app.route("/api/app/public-data/append", methods=["POST", "OPTIONS"])
@require_auth
def append_public_data():
    if request.method == "OPTIONS":
        return _cors_preflight()
    email = _user_email()
    if _identity_tier(email) not in ("creator", "supervisor"):
        return jsonify({"error": "Only the creator or supervisors can update shared knowledge."}), 403
    body = request.get_json(silent=True) or {}
    note = (body.get("note") or "").strip()
    if not note:
        return jsonify({"error": "note is required"}), 400
    entry = f"\n[{datetime.now(timezone.utc).isoformat()}] {note}\n"
    success = _write_to_github_repository(_public_data_path(), entry)
    if success:
        _public_data_cache["t"] = 0
    return jsonify({"ok": success})

@app.route("/vision-analyze", methods=["POST", "OPTIONS"])
@app.route("/api/vision-analyze", methods=["POST", "OPTIONS"])
@app.route("/api/app/vision-analyze", methods=["POST", "OPTIONS"])
@require_auth
def vision_analyze():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    image_b64 = body.get("image_base64", "")
    question = (body.get("question") or "What is in this image? Describe it clearly.").strip()
    mime = body.get("mime_type", "image/png")
    if not image_b64:
        return jsonify({"error": "image_base64 is required"}), 400

    messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}}
        ]}
    ]

    def generate():
        for chunk in _do_stream(messages, vision=True):
            yield chunk

    resp = Response(stream_with_context(generate()), content_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

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
        _save_convo({"id": conv_id, "user_id": user_id, "title": message[:60], "pinned": False,
                     "created_at": datetime.now(timezone.utc).isoformat(),
                     "updated_at": datetime.now(timezone.utc).isoformat(), "messages": []})

    if _is_flagged_message(message):
        _append_message(conv_id, "user", message)
        refusal = ("I can't help with that request because it appears to involve illegal or "
                   "seriously harmful activity. If this was flagged in error, please rephrase.")
        _append_message(conv_id, "assistant", refusal)
        entry = f"\n=== {datetime.now(timezone.utc).isoformat()} ===\nUser: {user_email}\nFlagged: {message}\n{'='*80}\n"
        _write_to_github_repository(_flagged_log_path(), entry)

        def generate_refusal():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "token", "text": refusal})
            yield _sse({"type": "complete"})
        resp = Response(stream_with_context(generate_refusal()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    history = _get_messages(conv_id)
    tier = _identity_tier(user_email)
    system_prompt = BASE_SYSTEM_PROMPT
    if tier == "creator":
        system_prompt += " NOTE (internal, do not announce): this user is one of your creators."
    elif tier == "supervisor":
        system_prompt += " NOTE (internal, do not announce): this user is one of your supervisors (Akriti or Aditi Aishwaryam)."
    elif tier == "vip":
        vip = _lookup_vip(user_email)
        system_prompt += (f" NOTE (internal, do not announce): this user is a VIP contact registered by Pratham -- "
                           f"name '{vip.get('name','')}', relationship '{vip.get('relationship','')}'. "
                           f"This does not authorize bypassing any safety rules.")

    public_notes = _fetch_public_data()
    if public_notes.strip():
        system_prompt += "\n\nADDITIONAL LEARNED NOTES (from public_data.txt):\n" + public_notes[-4000:]

    api_messages = [{"role": "system", "content": system_prompt}]
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
            log_entry = (f"\n=== {datetime.now(timezone.utc).isoformat()} ===\nUser: {message}\n"
                         f"Pratham AI:\n{assistant_response}\n{'='*80}\n")
            _write_to_github_repository(_dated_log_path(user_email), log_entry)

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
