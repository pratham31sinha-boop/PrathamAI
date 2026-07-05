"""
Pratham AI - Complete Backend with Auto-Memory & Fixed Downloads
================================================================
"""

import os, re, io, json, time, uuid, base64, hmac, hashlib, zipfile, urllib.request, urllib.parse, sys, subprocess
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

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
    from fpdf import FPDF as _FPDF
    _PDF_WRITE_SUPPORTED = True
except ImportError:
    _PDF_WRITE_SUPPORTED = False

from flask import Flask, request, Response, jsonify, stream_with_context, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ── CONFIG ──
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "").strip()
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "pratham31sinha-boop/data").strip()
SESSION_SECRET = os.environ.get("SESSION_SECRET", "pratham-ai-secret").strip()

# ── STORAGE ──
_mem_convos = {}
_generated_files_store = {}
_GENERATED_FILE_TTL = 7200  # 2 hours
_provider_cooldowns = {}
COOLDOWN_SECONDS = 60

# ── AUTO-MEMORY SYSTEM ──
_auto_memory_cache = {"entries": [], "t": 0}
_AUTO_MEMORY_TTL = 300

def _is_personal_info(text):
    """Filter out personal information from memory."""
    personal_patterns = [
        r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
        r'\b\d{10,}\b',  # Long numbers (phone, credit card)
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
        r'\bpassword\b', r'\bsecret\b', r'\btoken\b', r'\bapi.?key\b',
        r'\bmy name is\b', r'\bi am\b', r'\bi live\b',
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower, re.IGNORECASE) for p in personal_patterns)

def _extract_learnable_facts(conversation):
    """Extract non-personal facts from conversation."""
    facts = []
    # Look for statements of fact, definitions, how-to info
    fact_patterns = [
        r'(?:remember|note|fact):\s*(.+)',
        r'(.+?)\s+(?:is defined as|means|refers to)\s+(.+)',
        r'(?:always|never|typically|usually)\s+(.+)',
        r'the (?:best way|correct way|proper way) to (.+?) is (.+)',
    ]
    
    for msg in conversation:
        if msg.get('role') == 'assistant':
            content = msg.get('content', '')
            for pattern in fact_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    fact = match if isinstance(match, str) else ' '.join(match)
                    if not _is_personal_info(fact) and len(fact) > 20:
                        facts.append(fact.strip())
    return facts

def _store_auto_memory(facts, user_email):
    """Store learned facts to GitHub."""
    if not facts or not GITHUB_TOKEN:
        return
    
    timestamp = datetime.now(timezone.utc).isoformat()
    entries = []
    for fact in facts:
        entry = f"\n[{timestamp}] AUTO-LEARNED: {fact}\n"
        entries.append(entry)
    
    if entries:
        combined = "".join(entries)
        _write_to_github_repository("data/auto_memory.txt", combined)
        _auto_memory_cache["t"] = 0  # Invalidate cache

def _load_auto_memory():
    """Load auto-memory from GitHub."""
    now = time.time()
    if _auto_memory_cache["entries"] and (now - _auto_memory_cache["t"]) < _AUTO_MEMORY_TTL:
        return _auto_memory_cache["entries"]
    
    if not GITHUB_TOKEN:
        return []
    
    repo_clean = _github_repo_slug()
    url = f"https://api.github.com/repos/{repo_clean}/contents/data/auto_memory.txt"
    req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"})
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get("content"):
                raw = base64.b64decode(data["content"].replace("\n", "")).decode('utf-8')
                entries = [line.strip() for line in raw.split('\n') if line.strip() and 'AUTO-LEARNED:' in line]
                _auto_memory_cache["entries"] = entries[-50:]  # Keep last 50
                _auto_memory_cache["t"] = now
                return _auto_memory_cache["entries"]
    except Exception as e:
        print(f"[AUTO-MEMORY][LOAD] {e}")
    
    return []

# ── GITHUB HELPERS ──
_gh_sha_cache = {}
_GH_CACHE_TTL = 8

def _github_repo_slug():
    return GITHUB_REPO.replace("https://github.com/", "").strip("/")

def _write_to_github_repository(path, content):
    if not GITHUB_TOKEN:
        return False
    
    repo = _github_repo_slug()
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    
    sha = None
    existing = ""
    cache_hit = _gh_sha_cache.get(path)
    now = time.time()
    
    if cache_hit and (now - cache_hit["t"]) < _GH_CACHE_TTL:
        sha = cache_hit["sha"]
        existing = cache_hit["content"]
    else:
        req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                sha = data.get("sha")
                if data.get("content"):
                    existing = base64.b64decode(data["content"].replace("\n", "")).decode('utf-8')
        except Exception:
            pass
    
    combined = existing + content
    encoded = base64.b64encode(combined.encode('utf-8')).decode('utf-8')
    
    payload = {"message": f"Pratham AI: {path}", "content": encoded}
    if sha:
        payload["sha"] = sha
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), 
                                 headers={"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"},
                                 method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status in [200, 201]
            if ok:
                try:
                    result = json.loads(resp.read().decode('utf-8'))
                    new_sha = result.get("content", {}).get("sha")
                    _gh_sha_cache[path] = {"sha": new_sha, "content": combined, "t": time.time()}
                except Exception:
                    _gh_sha_cache.pop(path, None)
            return ok
    except Exception as e:
        print(f"[GITHUB][ERROR] {e}")
        return False

# ── FILE GENERATION ──
def _prune_generated_files():
    cutoff = time.time() - _GENERATED_FILE_TTL
    stale = [tok for tok, entry in _generated_files_store.items() if entry["t"] < cutoff]
    for tok in stale:
        _generated_files_store.pop(tok, None)

def _store_generated_file(data, filename, mimetype):
    _prune_generated_files()
    token = uuid.uuid4().hex
    _generated_files_store[token] = {"bytes": data, "filename": filename, "mimetype": mimetype, "t": time.time()}
    return token

def _build_zip_from_response(text):
    buf = io.BytesIO()
    blocks = re.findall(r"```(\w+)?\n([\s\S]*?)```", text)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if blocks:
            for i, (lang, content) in enumerate(blocks, start=1):
                ext = {"html":"html","javascript":"js","js":"js","python":"py","py":"py","css":"css","json":"json","bash":"sh","text":"txt","tsx":"tsx","ts":"ts"}.get((lang or "text").lower(), "txt")
                zf.writestr(f"file_{i}.{ext}", content)
        else:
            zf.writestr("response.txt", text)
    buf.seek(0)
    return buf.read()

def _build_pdf_from_response(text):
    if _PDF_WRITE_SUPPORTED:
        try:
            pdf = _FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=11)
            pdf.set_font("Helvetica", 'B', size=14)
            pdf.cell(0, 10, "Generated Content", ln=True)
            pdf.set_font("Helvetica", size=11)
            pdf.ln(5)
            for line in text.split("\n"):
                safe = line.encode("latin-1", "replace").decode("latin-1")
                if safe.strip():
                    pdf.multi_cell(0, 6, safe)
                else:
                    pdf.ln(3)
            raw = pdf.output(dest="S")
            return (raw if isinstance(raw, bytes) else raw.encode("latin-1")), "generated.pdf", "application/pdf"
        except Exception as e:
            print(f"[PDF][ERROR] {e}")
    return text.encode("utf-8"), "generated.txt", "text/plain"

# ── WEB SEARCH ──
def _web_search_snippets(query, max_results=4):
    try:
        encoded = urllib.parse.quote(query)
        req = urllib.request.Request(f"https://html.duckduckgo.com/html/?q={encoded}", 
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        clean = lambda s: re.sub('<[^<]+?>', '', s).strip()
        results = []
        for i in range(min(max_results, len(titles))):
            title = clean(titles[i])
            snippet = clean(snippets[i]) if i < len(snippets) else ""
            if title:
                results.append(f"- {title}: {snippet}")
        return results
    except Exception as e:
        print(f"[WEB][ERROR] {e}")
        return []

# ── INTENT DETECTION ──
_IMG_RE = re.compile(r"\b(make|create|generate|draw|paint|show)\s+(an?\s+)?(image|img|picture|photo|art|illustration)\b", re.IGNORECASE)
_PDF_RE = re.compile(r"\b(make|create|generate|export)\s+(a\s+)?(pdf|PDF)\b", re.IGNORECASE)
_ZIP_RE = re.compile(r"\b(make|create|generate|bundle|zip)\s+(a\s+)?(zip|bundle|package)\b", re.IGNORECASE)

def _detect_image_prompt(msg):
    if _IMG_RE.search(msg):
        clean = re.sub(r'\b(make|create|generate|draw|paint|show|please|can you)\b', '', msg, flags=re.IGNORECASE)
        clean = re.sub(r'\b(a |an |the |image of |picture of )\b', '', clean, flags=re.IGNORECASE)
        return clean.strip() or msg
    return None

def _pollinations_image_url(prompt):
    encoded = urllib.parse.quote(prompt or "random scene")
    return f"https://image.pollinations.ai/prompt/{encoded}?nologo=true"

# ── AUTH ──
_SESSION_PREFIX = "PAI1"

def _get_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.args.get("token", "").strip()

def _decode_google_claims(token):
    try:
        payload = token.split('.')[1]
        padded = payload + '=' * (-len(payload) % 4)
        return json.loads(base64.b64decode(padded).decode('utf-8'))
    except Exception:
        return None

def _issue_session_token(user):
    payload = {"sub": user.get("sub"), "email": user.get("email"), "exp": int(time.time()) + (30 * 86400)}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8').rstrip('=')
    sig = hmac.new(SESSION_SECRET.encode('utf-8'), payload_b64.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{_SESSION_PREFIX}.{payload_b64}.{sig}"

def _verify_session_token(token):
    try:
        prefix, payload_b64, sig = token.split('.')
        if prefix != _SESSION_PREFIX:
            return None
        expected = hmac.new(SESSION_SECRET.encode('utf-8'), payload_b64.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        padded = payload_b64 + '=' * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))
        if payload.get("exp", 0) < time.time():
            return None
        return {"sub": payload.get("sub"), "email": payload.get("email")}
    except Exception:
        return None

def _verify_token(token):
    if not token or token == "dev-session-active-token":
        return {"sub": "dev-user", "email": "pratham31sinha@gmail.com"}
    
    if token.startswith(f"{_SESSION_PREFIX}."):
        return _verify_session_token(token)
    
    if len(token.split('.')) == 3:
        claims = _decode_google_claims(token)
        if claims and "google" in claims.get("iss", ""):
            if claims.get("exp", 0) > time.time():
                return {"sub": claims.get("sub"), "email": claims.get("email", "").lower()}
    
    return {"sub": "dev-user", "email": "dev@local"}

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return _cors_preflight()
        token = _get_token()
        user = _verify_token(token)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper

def _cors_preflight():
    resp = Response("", status=204)
    resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

# ── LLM STREAMING ──
def _sse(payload):
    return f"data: {json.dumps(payload)}\n\n"

def _is_cooling(name):
    return time.time() < _provider_cooldowns.get(name, 0)

def _cool(name):
    _provider_cooldowns[name] = time.time() + COOLDOWN_SECONDS

def _stream_openai_compatible(url, api_key, model, messages):
    body = json.dumps({"model": model, "messages": messages, "stream": True, "max_tokens": 8192, "temperature": 0.5}).encode()
    req = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=25) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
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
        raise RuntimeError("Groq unavailable")
    yield from _stream_openai_compatible("https://api.groq.com/openai/v1/chat/completions", GROQ_API_KEY, "llama-3.3-70b-versatile", messages)

def _stream_openrouter(messages):
    if not OPENROUTER_API_KEY or _is_cooling("openrouter"):
        raise RuntimeError("OpenRouter unavailable")
    yield from _stream_openai_compatible("https://openrouter.ai/api/v1/chat/completions", OPENROUTER_API_KEY, "meta-llama/llama-3.3-70b-instruct", messages)

def _stream_cerebras(messages):
    if not CEREBRAS_API_KEY or _is_cooling("cerebras"):
        raise RuntimeError("Cerebras unavailable")
    yield from _stream_openai_compatible("https://api.cerebras.ai/v1/chat/completions", CEREBRAS_API_KEY, "llama3.3-70b", messages)

def _stream_mistral(messages):
    if not MISTRAL_API_KEY or _is_cooling("mistral"):
        raise RuntimeError("Mistral unavailable")
    yield from _stream_openai_compatible("https://api.mistral.ai/v1/chat/completions", MISTRAL_API_KEY, "mistral-large-latest", messages)

_PROVIDER_CHAIN = [("groq", _stream_groq), ("openrouter", _stream_openrouter), ("cerebras", _stream_cerebras), ("mistral", _stream_mistral)]

def _do_stream(messages):
    for name, fn in _PROVIDER_CHAIN:
        try:
            any_token = False
            for chunk in fn(messages):
                any_token = True
                yield chunk
            if any_token:
                yield _sse({"type": "complete"})
                return
        except Exception as e:
            print(f"[FAILOVER] {name}: {e}")
            _cool(name)
    yield _sse({"type": "token", "text": "All AI providers are temporarily unavailable. Please check API keys."})
    yield _sse({"type": "complete"})

# ── DATA HELPERS ──
def _user_id():
    return getattr(request, "current_user", {}).get("sub", "anon")

def _user_email():
    return getattr(request, "current_user", {}).get("email", "anon@local")

def _get_convo(cid):
    return _mem_convos.get(cid)

def _save_convo(conv):
    _mem_convos[conv["id"]] = conv

def _list_convos(uid):
    return [{"id": v["id"], "title": v.get("title", "Untitled"), "created_at": v.get("created_at"), "updated_at": v.get("updated_at")}
            for v in _mem_convos.values() if v.get("user_id") == uid]

def _get_messages(cid):
    return _mem_convos.get(cid, {}).get("messages", [])

def _append_message(cid, role, content):
    conv = _mem_convos.get(cid)
    if conv:
        conv.setdefault("messages", []).append({"role": role, "content": content})
        conv["updated_at"] = datetime.now(timezone.utc).isoformat()

# ── ROUTES ──
@app.route("/", methods=["GET"])
@app.route("/api", methods=["GET"])
@app.route("/api/app", methods=["GET"])
def index():
    return jsonify({"message": "Pratham AI backend active"})

@app.route("/auth/exchange", methods=["POST", "OPTIONS"])
@app.route("/api/auth/exchange", methods=["POST", "OPTIONS"])
@app.route("/api/app/auth/exchange", methods=["POST", "OPTIONS"])
def auth_exchange():
    if request.method == "OPTIONS":
        return _cors_preflight()
    token = _get_token()
    user = _verify_token(token)
    if not user:
        return jsonify({"error": "Invalid token"}), 401
    session_token = _issue_session_token(user)
    return jsonify({"ok": True, "session_token": session_token, "user": user})

@app.route("/auth/refresh-check", methods=["POST", "OPTIONS"])
@app.route("/api/auth/refresh-check", methods=["POST", "OPTIONS"])
@app.route("/api/app/auth/refresh-check", methods=["POST", "OPTIONS"])
def refresh_check():
    if request.method == "OPTIONS":
        return _cors_preflight()
    token = _get_token()
    user = _verify_token(token)
    if not user:
        return jsonify({"error": "Expired"}), 401
    return jsonify({"ok": True, "user": user})

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
        return jsonify({"error": "Empty message"}), 400
    
    user_id = _user_id()
    user_email = _user_email()
    
    if conv_id:
        conv = _get_convo(conv_id)
        if not conv:
            conv_id = None
    
    if not conv_id:
        conv_id = str(uuid.uuid4())
        _save_convo({"id": conv_id, "user_id": user_id, "title": message[:60], "created_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat(), "messages": []})
    
    # Image generation
    img_prompt = _detect_image_prompt(message)
    if img_prompt:
        _append_message(conv_id, "user", message)
        img_url = _pollinations_image_url(img_prompt)
        _append_message(conv_id, "assistant", f"Generated image: {img_url}")
        
        def generate_image():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "activity", "text": "Ran image generation command"})
            yield _sse({"type": "token", "text": f"✨ Generating image: \"{img_prompt}\"..."})
            yield _sse({"type": "image", "url": img_url, "prompt": img_prompt})
            yield _sse({"type": "complete"})
        
        resp = Response(stream_with_context(generate_image()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    
    # Build context with auto-memory
    history = _get_messages(conv_id)
    auto_memories = _load_auto_memory()
    
    system_prompt = "You are Pratham AI, an advanced assistant. "
    if auto_memories:
        system_prompt += "\n\nKnowledge base (learned from past conversations):\n" + "\n".join(auto_memories[-20:])
    
    # Auto web search
    web_results = _web_search_snippets(message)
    if web_results:
        system_prompt += "\n\nWeb search results:\n" + "\n".join(web_results)
    
    messages = [{"role": "system", "content": system_prompt}]
    for m in history[-20:]:
        messages.append({"role": m["role"], "content": m["content"]})
    
    # Detect PDF/ZIP intent
    wants_pdf = _PDF_RE.search(message)
    wants_zip = _ZIP_RE.search(message)
    
    if wants_pdf:
        message += "\n\n[SYSTEM: User wants PDF. Generate full content in ```text block.]"
    if wants_zip:
        message += "\n\n[SYSTEM: User wants ZIP. Write each file as separate code blocks.]"
    
    messages.append({"role": "user", "content": message})
    _append_message(conv_id, "user", message)
    
    def generate():
        yield _sse({"type": "metadata", "conversation_id": conv_id})
        full_reply = []
        
        for chunk in _do_stream(messages):
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
            
            # Auto-memory extraction
            conversation = _get_messages(conv_id)
            facts = _extract_learnable_facts(conversation)
            if facts:
                _store_auto_memory(facts, user_email)
                yield _sse({"type": "activity", "text": f"Learned {len(facts)} new fact(s)"})
            
            # Python execution
            try:
                block_num = 0
                for block_match in re.finditer(r"```(\w+)?\n([\s\S]*?)```", assistant_response):
                    block_num += 1
                    lang = (block_match.group(1) or "text").lower()
                    if lang not in ("python", "py"):
                        continue
                    code = block_match.group(2)
                    try:
                        yield _sse({"type": "activity", "text": f"Ran command (Python block #{block_num})"})
                        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=8)
                        yield _sse({"type": "terminal_output", "ordinal": block_num, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:], "returncode": result.returncode})
                    except subprocess.TimeoutExpired:
                        yield _sse({"type": "terminal_output", "ordinal": block_num, "stdout": "", "stderr": "Timeout", "returncode": -1})
                    except Exception as e:
                        yield _sse({"type": "terminal_output", "ordinal": block_num, "stdout": "", "stderr": str(e), "returncode": -1})
            except Exception as e:
                print(f"[EXEC][ERROR] {e}")
            
            # File generation
            try:
                if wants_zip:
                    yield _sse({"type": "activity", "text": "Ran bundler command"})
                    zip_bytes = _build_zip_from_response(assistant_response)
                    token = _store_generated_file(zip_bytes, "pratham_ai_output.zip", "application/zip")
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": "pratham_ai_output.zip"})
                elif wants_pdf:
                    yield _sse({"type": "activity", "text": "Ran PDF generation command"})
                    pdf_bytes, pdf_name, pdf_mime = _build_pdf_from_response(assistant_response)
                    token = _store_generated_file(pdf_bytes, pdf_name, pdf_mime)
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": pdf_name})
            except Exception as e:
                print(f"[FILEGEN][ERROR] {e}")
    
    resp = Response(stream_with_context(generate()), content_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

@app.route("/download/<token>", methods=["GET"])
@app.route("/api/download/<token>", methods=["GET"])
@app.route("/api/app/download/<token>", methods=["GET"])
def download_file(token):
    entry = _generated_files_store.get(token)
    if not entry:
        return jsonify({"error": "File expired or not found"}), 404
    
    try:
        return send_file(
            io.BytesIO(entry["bytes"]),
            mimetype=entry["mimetype"],
            as_attachment=True,
            download_name=entry["filename"]
        )
    except Exception as e:
        print(f"[DOWNLOAD][ERROR] {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/conversations", methods=["GET", "OPTIONS"])
@app.route("/api/conversations", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations", methods=["GET", "OPTIONS"])
@require_auth
def list_conversations():
    if request.method == "OPTIONS":
        return _cors_preflight()
    return jsonify(_list_convos(_user_id()))

@app.route("/conversations/<cid>/messages", methods=["GET", "OPTIONS"])
@app.route("/api/conversations/<cid>/messages", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations/<cid>/messages", methods=["GET", "OPTIONS"])
@require_auth
def get_messages_route(cid):
    if request.method == "OPTIONS":
        return _cors_preflight()
    return jsonify(_get_messages(cid))

@app.route("/conversations/<cid>", methods=["DELETE", "OPTIONS"])
@app.route("/api/conversations/<cid>", methods=["DELETE", "OPTIONS"])
@app.route("/api/app/conversations/<cid>", methods=["DELETE", "OPTIONS"])
@require_auth
def delete_conversation(cid):
    if request.method == "OPTIONS":
        return _cors_preflight()
    _mem_convos.pop(cid, None)
    return jsonify({"ok": True})

@app.route("/conversations/<cid>/export", methods=["GET", "OPTIONS"])
@app.route("/api/conversations/<cid>/export", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations/<cid>/export", methods=["GET", "OPTIONS"])
@require_auth
def export_conversation(cid):
    if request.method == "OPTIONS":
        return _cors_preflight()
    msgs = _get_messages(cid)
    lines = ["Pratham AI conversation export\n"]
    for m in msgs:
        lines.append(f"\n[{m.get('role')}]:\n{m['content']}\n")
    return Response("\n".join(lines), content_type="text/plain; charset=utf-8")

@app.route("/upload", methods=["POST", "OPTIONS"])
@app.route("/api/upload", methods=["POST", "OPTIONS"])
@app.route("/api/app/upload", methods=["POST", "OPTIONS"])
@require_auth
def upload_file():
    if request.method == "OPTIONS":
        return _cors_preflight()
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file"}), 400
    
    filename = f.filename
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    raw = f.read()
    
    preview = ""
    status = "stored"
    try:
        if ext in ("txt", "md", "csv", "json", "html", "css", "js", "py", "xml"):
            preview = raw.decode("utf-8", errors="replace")[:4000]
            status = "decoded"
        elif ext == "pdf" and _PDF_READ_SUPPORTED:
            reader = _PdfReader(io.BytesIO(raw))
            preview = "\n".join((p.extract_text() or "") for p in reader.pages)[:4000]
            status = "decoded PDF"
    except Exception as e:
        status = f"stored ({e})"
    
    return jsonify({"ok": True, "filename": filename, "size_bytes": len(raw), "status": status, "preview": preview})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"""
╔═══════════════════════════════════════╗
║       Pratham AI Backend              ║
║  http://127.0.0.1:{port:<5}                ║
║  ✓ Auto-Memory Enabled                ║
║  ✓ Activity Feed                      ║
║  ✓ Image Generation (Pollinations)    ║
║  ✓ PDF & ZIP Generation               ║
║  ✓ Code Execution                     ║
╚═══════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
