import osimport reimport ioimport jsonimport timeimport uuidimport base64import hmacimport hashlibimport zipfileimport urllib.requestimport urllib.parseimport sysimport subprocessfrom datetime import datetime, timezonefrom functools import wraps

try:from pypdf import PdfReader as _PdfReader_PDF_READ_SUPPORTED = Trueexcept ImportError:try:from PyPDF2 import PdfReader as _PdfReader_PDF_READ_SUPPORTED = Trueexcept ImportError:_PDF_READ_SUPPORTED = False

try:from fpdf import FPDF as _FPDF_PDF_WRITE_SUPPORTED = Trueexcept ImportError:_PDF_WRITE_SUPPORTED = False

from flask import Flask, request, Response, jsonify, stream_with_context, send_filefrom flask_cors import CORS

try:from supabase import create_client as _supabase_create_supabase_sdk = Trueexcept ImportError:_supabase_sdk = False

app = Flask(name)CORS(app, resources={r"/": {"origins": ["https://prathamai.vercel.app","http://localhost:3000","http://localhost:5173","http://127.0.0.1:5173","http://localhost:5000","http://127.0.0.1:5000",""]}}, supports_credentials=True)

── ENVIRONMENT ──

GROQ_API_KEY         = os.environ.get("GROQ_API_KEY", "").strip()OPENROUTER_API_KEY   = os.environ.get("OPENROUTER_API_KEY", "").strip()CEREBRAS_API_KEY     = os.environ.get("CEREBRAS_API_KEY", "").strip()MISTRAL_API_KEY      = os.environ.get("MISTRAL_API_KEY", "").strip()SUPABASE_URL         = os.environ.get("SUPABASE_URL", "https://ksroorygbrhwpnqtjbxo.supabase.co").strip()SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()GITHUB_TOKEN         = os.environ.get("GITHUB_TOKEN", "").strip()GITHUB_REPO          = os.environ.get("GITHUB_REPO", "pratham31sinha-boop/data").strip()VIP_SECRET_CODE      = os.environ.get("VIP_SECRET_CODE", "31082011").strip()SESSION_SECRET       = os.environ.get("SESSION_SECRET", "pratham-ai-dev-secret-change-me").strip()SESSION_TOKEN_TTL_DAYS = int(os.environ.get("SESSION_TOKEN_TTL_DAYS", "30"))

SUPABASE_CONFIGURED = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY and _supabase_sdk)

_supabase = Noneif SUPABASE_CONFIGURED:try:_supabase = _supabase_create(SUPABASE_URL, SUPABASE_SERVICE_KEY)print(f"[INIT] Persistent layer connected: {SUPABASE_URL}")except Exception:SUPABASE_CONFIGURED = False

_mem_convos: dict = {}

── GITHUB LOG PERSISTENCE ──

_gh_sha_cache: dict = {}_GH_CACHE_TTL = 8

def _github_repo_slug() -> str:return GITHUB_REPO.replace("https://github.com/", "").strip("/")

def _write_to_github_repository(target_file_path: str, contents_payload: str) -> bool:if not GITHUB_TOKEN:return False

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

── VIP RECOGNITION ──

_vip_cache = {"entries": {}, "t": 0}_VIP_CACHE_TTL = 30

def _fetch_vip_directory() -> dict:now_ts = time.time()if _vip_cache["entries"] and (now_ts - _vip_cache["t"]) < _VIP_CACHE_TTL:return _vip_cache["entries"]

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

def _lookup_vip(email: str):if not email:return Nonereturn _fetch_vip_directory().get(email.lower())

── BACKGROUND FILE GENERATION ──

_generated_files_store: dict = {}_GENERATED_FILE_TTL = 3600

_ZIP_INTENT_RE = re.compile(r"\b(make|create|generate|give me|download|export|zip|bundle)\b.{0,20}\b(zip|bundle)\b", re.IGNORECASE)_PDF_INTENT_RE = re.compile(r"\b(make|create|generate|give me|download|export)\b.{0,20}\bpdf\b", re.IGNORECASE)_FILE_BUNDLE_RE = re.compile(r"(index.html|app.py|app.tsx|main.js|style.css|config.json)", re.IGNORECASE)

def _prune_generated_files():cutoff = time.time() - _GENERATED_FILE_TTLstale = [tok for tok, entry in _generated_files_store.items() if entry["t"] < cutoff]for tok in stale:_generated_files_store.pop(tok, None)

def _store_generated_file(data: bytes, filename: str, mimetype: str) -> str:_prune_generated_files()token = uuid.uuid4().hex_generated_files_store[token] = {"bytes": data, "filename": filename, "mimetype": mimetype, "t": time.time()}return token

def _parse_code_bundle(text: str) -> dict:files = {}current_filename = Nonecurrent_content = []

for line in text.split('\n'):
    if line.strip().startswith('###') or line.strip().startswith('=='):
        if current_filename:
            files[current_filename] = '\n'.join(current_content).strip()
        current_filename = line.strip().replace('###', '').replace('==', '').strip()
        current_content = []
    elif current_filename:
        current_content.append(line)

if current_filename:
    files[current_filename] = '\n'.join(current_content).strip()

return files

def _build_zip_from_files(files_dict: dict) -> bytes:buf = io.BytesIO()with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:for filename, content in files_dict.items():zf.writestr(filename, content)buf.seek(0)return buf.read()

def build_zip_from_response(assistant_text: str) -> bytes:buf = io.BytesIO()blocks = re.findall(r"(\w+)?\n([\s\S]*?)", assistant_text)with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:if blocks:for i, (lang, content) in enumerate(blocks, start=1):ext = {"html": "html", "javascript": "js", "js": "js", "python": "py", "py": "py","css": "css", "json": "json", "bash": "sh", "text": "txt", "tsx": "tsx", "ts": "ts"}.get((lang or "text").lower(), "txt")filename = f"file{i}.{ext}"zf.writestr(filename, content)else:zf.writestr("response.txt", assistant_text)buf.seek(0)return buf.read()

def _build_pdf_from_response(assistant_text: str):if _PDF_WRITE_SUPPORTED:try:pdf = _FPDF()pdf.add_page()pdf.set_font("Helvetica", size=11)

        pdf.set_font("Helvetica", 'B', size=14)
        pdf.cell(0, 10, "Generated Content", ln=True)
        pdf.set_font("Helvetica", size=11)
        pdf.ln(5)

        for line in assistant_text.split("\n"):
            safe_line = line.encode("latin-1", "replace").decode("latin-1")
            if safe_line.strip():
                pdf.multi_cell(0, 6, safe_line)
            else:
                pdf.ln(3)

        raw_output = pdf.output(dest="S")
        if isinstance(raw_output, str):
            pdf_bytes = raw_output.encode("latin-1")
        else:
            pdf_bytes = bytes(raw_output)
        return pdf_bytes, "generated.pdf", "application/pdf"
    except Exception as e:
        print(f"[PDF][ERROR] {e}")
        return assistant_text.encode("utf-8"), "generated.txt", "text/plain"

return assistant_text.encode("utf-8"), "generated.txt", "text/plain"

── DOWNLOAD ROUTES ──

@app.route("/download/<token>", methods=["GET"])@app.route("/api/download/<token>", methods=["GET"])@app.route("/api/app/download/<token>", methods=["GET"])def download_generated_file(token):entry = _generated_files_store.get(token)if not entry:return jsonify({"error": "This download has expired or does not exist."}), 404

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

@app.route("/download-direct/<token>", methods=["GET"])@app.route("/api/download-direct/<token>", methods=["GET"])@app.route("/api/app/download-direct/<token>", methods=["GET"])def download_generated_file_direct(token):entry = _generated_files_store.get(token)if not entry:return jsonify({"error": "This download has expired or does not exist."}), 404

resp = Response(entry["bytes"], mimetype=entry["mimetype"])
resp.headers["Content-Disposition"] = f'attachment; filename="{entry["filename"]}"'
resp.headers["Content-Type"] = entry["mimetype"]
resp.headers["Content-Length"] = len(entry["bytes"])
return resp

── @education PDF-backed Q&A (HIDDEN FEATURE) ──

_education_cache = {"files": {}, "listing_t": 0}_EDUCATION_LISTING_TTL = 120

def _github_list_dir(path: str):if not GITHUB_TOKEN:return []repo_clean = _github_repo_slug()endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{path}"req_lookup = urllib.request.Request(endpoint_target_url,headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"})try:with urllib.request.urlopen(req_lookup, timeout=12) as resp:data = json.loads(resp.read().decode('utf-8'))return data if isinstance(data, list) else []except Exception as exc:print(f"[EDU][LIST FAULT] {exc}")return []

def _github_fetch_file_bytes(download_url: str):try:req = urllib.request.Request(download_url, headers={"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {})with urllib.request.urlopen(req, timeout=20) as resp:return resp.read()except Exception as exc:print(f"[EDU][FETCH FAULT] {exc}")return None

def _extract_pdf_text(pdf_bytes: bytes) -> str:if not _PDF_READ_SUPPORTED:return ""try:reader = _PdfReader(io.BytesIO(pdf_bytes))return "\n".join((page.extract_text() or "") for page in reader.pages)except Exception as exc:print(f"[EDU][EXTRACT FAULT] {exc}")return ""

def _refresh_education_library():now_ts = time.time()if _education_cache["files"] and (now_ts - _education_cache["listing_t"]) < _EDUCATION_LISTING_TTL:returnentries = _github_list_dir("data/education")for entry in entries:if not entry.get("name", "").lower().endswith(".pdf"):continuesha = entry.get("sha")name = entry.get("name")cached = _education_cache["files"].get(name)if cached and cached.get("sha") == sha:continueraw = _github_fetch_file_bytes(entry.get("download_url"))if raw is None:continuetext = _extract_pdf_text(raw)_education_cache["files"][name] = {"sha": sha, "text": text}_education_cache["listing_t"] = now_ts

def _find_best_education_excerpt(question: str):_refresh_education_library()if not _education_cache["files"]:return None

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

── AUTO @web SEARCH ──

def _web_search_snippets(query: str, max_results: int = 4):try:encoded = urllib.parse.quote(query)req = urllib.request.Request(f"https://html.duckduckgo.com/html/?q={encoded}",headers={"User-Agent": "Mozilla/5.0 (PrathamAI Search Agent)"})with urllib.request.urlopen(req, timeout=6) as resp:html_body = resp.read().decode('utf-8', errors='ignore')titles = re.findall(r'class="result__a"[^>]>(.?)</a>', html_body, re.DOTALL)snippets = re.findall(r'class="result__snippet"[^>]>(.?)</a>', html_body, re.DOTALL)clean = lambda s: re.sub('<[^<]+?>', '', s).strip()results = []for i in range(min(max_results, len(titles))):title = clean(titles[i])snippet = clean(snippets[i]) if i < len(snippets) else ""if title:results.append(f"- {title}: {snippet}")return resultsexcept Exception as exc:print(f"[WEB][SEARCH FAULT] {exc}")return []

def _get_token():auth = request.headers.get("Authorization", "")if auth.startswith("Bearer "):return auth[7:].strip()return None

def _decode_google_claims(token: str):try:payload_chunk = token.split('.')[1]padded_chunk = payload_chunk + '=' * (-len(payload_chunk) % 4)return json.loads(base64.b64decode(padded_chunk).decode('utf-8'))except Exception:return None

── SESSION TOKENS ──

_SESSION_TOKEN_PREFIX = "PAI1"

def _issue_session_token(user: dict) -> str:payload = {"sub": user.get("sub"),"email": user.get("email"),"role": user.get("role", "standard"),"full_name": (user.get("user_metadata") or {}).get("full_name"),"picture": (user.get("user_metadata") or {}).get("picture"),"exp": int(time.time()) + (SESSION_TOKEN_TTL_DAYS * 86400)}payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8').rstrip('=')signature = hmac.new(SESSION_SECRET.encode('utf-8'), payload_b64.encode('utf-8'), hashlib.sha256).hexdigest()return f"{_SESSION_TOKEN_PREFIX}.{payload_b64}.{signature}"

def _verify_session_token(token: str):try:prefix, payload_b64, signature = token.split('.')if prefix != _SESSION_TOKEN_PREFIX:return Noneexpected_sig = hmac.new(SESSION_SECRET.encode('utf-8'), payload_b64.encode('utf-8'), hashlib.sha256).hexdigest()if not hmac.compare_digest(expected_sig, signature):return Nonepadded = payload_b64 + '=' * (-len(payload_b64) % 4)payload = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))if payload.get("exp", 0) < time.time():return Nonereturn {"sub": payload.get("sub"),"email": payload.get("email"),"role": payload.get("role", "standard"),"user_metadata": {"full_name": payload.get("full_name"), "picture": payload.get("picture")}}except Exception:return None

def _verify_token(token: str):if not token or token == "dev-session-active-token":return {"sub": "dev-user","email": "pratham31sinha@gmail.com","role": "creator","user_metadata": {"full_name": "Dev Master Creator"}}

if token.startswith(f"{_SESSION_TOKEN_PREFIX}."):
    session_user = _verify_session_token(token)
    if session_user:
        return session_user
    return None

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

def require_auth(f):@wraps(f)def wrapper(*args, **kwargs):if request.method == "OPTIONS":return _cors_preflight()token = _get_token()user = _verify_token(token)if not user:return jsonify({"error": "Session expired or invalid. Please sign in again."}), 401request.current_user = userreturn f(*args, **kwargs)return wrapper

── CONTENT SAFETY GUARD ──

_BLOCKED_PATTERNS = [r"\bmake\s+a\s+bomb\b", r"\bbuild\s+a\s+bomb\b", r"\bhow\s+to\s+hack\b",r"\bchild\s+(sexual|porn|abuse)\b", r"\bkill\s+(myself|someone|him|her|them)\b",r"\bsynthesi[sz]e\s+(meth|drug|explosive)\b", r"\bmake\s+a\s+weapon\b",r"\bcredit\s+card\s+(number|dump|generator)\b", r"\bddos\b", r"\bransomware\b",]_BLOCKED_REGEX = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)

def _is_flagged_message(message: str) -> bool:return bool(_BLOCKED_REGEX.search(message or ""))

── PUBLIC MEMORY ──

_TEACHING_INTENT_RE = re.compile(r"\b(remember that|remember this|note this|note that|save this|learn this|keep in mind|"r"for future reference|always do|from now on|don't forget|never forget)\b",re.IGNORECASE)

def _maybe_capture_public_teaching(user_email: str, message: str):if not _TEACHING_INTENT_RE.search(message):returnentry = (f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"f"Taught by: {user_email}\n"f"Content: {message}\n"f"{'=' * 80}\n")_write_to_github_repository("public_data.txt", entry)

def _extract_public_memories() -> str:if not GITHUB_TOKEN:return "No memories stored yet."

repo_clean = _github_repo_slug()
endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/public_data.txt"
req_lookup = urllib.request.Request(
    endpoint_target_url,
    headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
)
try:
    with urllib.request.urlopen(req_lookup, timeout=10) as lookup_response:
        meta_data = json.loads(lookup_response.read().decode('utf-8'))
        if meta_data.get("content"):
            return base64.b64decode(meta_data["content"].replace("\n", "")).decode('utf-8')
except Exception as e:
    print(f"[MEMORY][FETCH] {e}")
return "No memories stored yet."

── LLM MULTI-PROVIDER FAILOVER ──

_provider_cooldowns: dict = {}COOLDOWN_SECONDS = 60

def _is_cooling(name: str) -> bool:return time.time() < _provider_cooldowns.get(name, 0)

def _cool(name: str):_provider_cooldowns[name] = time.time() + COOLDOWN_SECONDS

SYSTEM_PROMPT = ("You are Pratham AI, an elite software engineering system designed to produce production-ready ""software, not prototypes or templates. Core principles: never return placeholder code, never ""leave empty methods or TODO comments, never generate mock implementations unless explicitly ""requested. Every feature must exist in working code. ""\n\n""IMAGE GENERATION:\n""When user asks to 'make img', 'generate image', 'draw', 'create picture', etc.:\n""- The system will automatically generate the image using Pollinations AI\n""- Just acknowledge the request briefly\n""\n""FILE GENERATION WITH ZIP/PDF:\n""When user asks to 'make zip', 'create pdf', 'generate bundle', etc.:\n""- The system will execute Python code to generate the file\n""- Just acknowledge the request briefly\n""\n""FOR ALL OTHER REQUESTS:\n""Respond normally with full explanations, code examples, and detailed answers.\n""Never help with illegal activity, weapons, malware, or seriously harmful content.\n")

── IMAGE GENERATION ──

_IMAGE_INTENT_RE = re.compile(r"^/image\s+(.+)$|mak(e|ing)?\s+(an?\s+)?(img|image|picture|photo|art|drawing|illustration|man|woman|person|character).{0,50}(?|showing|depicting|with)?\s*(.*)$|\b(generate|create|draw|make|paint|design)\b.{0,20}\b(image|picture|photo|art|illustration|img|drawing|portrait)\b",re.IGNORECASE)

def _detect_image_prompt(message: str):match = re.search(r"^/image\s+(.+)$", message.strip(), re.IGNORECASE)if match:return match.group(1).strip(" .!")

if re.search(r"\b(mak|generat|creat|draw|paint|design|illustrat)\w+.{0,30}\b(img|image|picture|photo|art|drawing|portrait|man|woman|person)\b", message, re.IGNORECASE):
    prompt_match = re.search(
        r"(?:of|showing|depicting|for|with|:)\s*(.+?)(?:\.|$|\?|!)",
        message,
        re.IGNORECASE
    )
    if prompt_match:
        return prompt_match.group(1).strip(" .!?")

    descriptive_match = re.search(
        r"\b(?:img|image|picture|photo|art|drawing|portrait|man|woman|person)\b\s+(.+?)(?:\.|$|\?|!)",
        message,
        re.IGNORECASE
    )
    if descriptive_match:
        return descriptive_match.group(1).strip(" .!?")

    words = re.findall(r"\b[a-z]+\b", message.lower())
    if words:
        filtered = [w for w in words if w not in ['make', 'img', 'image', 'of', 'a', 'an', 'the', 'in', 'with', 'picture', 'photo', 'art', 'drawing']]
        if filtered:
            return " ".join(filtered[:5])

return None

def _pollinations_image_url(prompt_text: str) -> str:if not prompt_text:prompt_text = "random beautiful scene"encoded = urllib.parse.quote(prompt_text)return f"https://image.pollinations.ai/prompt/{encoded}?nologo=true"

def _detect_file_bundle_intent(message: str) -> bool:return bool(re.search(r"###\s+\w+.|==\s+\w+.", message))

def _detect_create_files_intent(message: str) -> bool:return bool(re.search(r"\b(make|create|generate|turn|convert|zip|bundle|create files|make files)\b.{0,30}\b(files|zip|bundle|archive)\b", message, re.IGNORECASE))

def _sse(payload: dict) -> str:return f"data: {json.dumps(payload)}\n\n"

def _stream_openai_compatible(url, api_key, model, messages):body = json.dumps({"model": model,"messages": messages,"stream": True,"max_tokens": 8192,"temperature": 0.5,}).encode()

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
            token = payload["choices"][0].get("delta", {}).get("content", "")
            if token:
                yield _sse({"type": "token", "text": token})
        except Exception:
            continue

def _stream_groq(messages):if not GROQ_API_KEY or _is_cooling("groq"):raise RuntimeError("Groq unavailable or cooling.")yield from _stream_openai_compatible("https://api.groq.com/openai/v1/chat/completions",GROQ_API_KEY, "llama-3.3-70b-versatile", messages)

def _stream_openrouter(messages):if not OPENROUTER_API_KEY or _is_cooling("openrouter"):raise RuntimeError("OpenRouter unavailable or cooling.")yield from _stream_openai_compatible("https://openrouter.ai/api/v1/chat/completions",OPENROUTER_API_KEY, "meta-llama/llama-3.3-70b-instruct", messages)

def _stream_cerebras(messages):if not CEREBRAS_API_KEY or _is_cooling("cerebras"):raise RuntimeError("Cerebras unavailable or cooling.")yield from _stream_openai_compatible("https://api.cerebras.ai/v1/chat/completions",CEREBRAS_API_KEY, "llama3.3-70b", messages)

def _stream_mistral(messages):if not MISTRAL_API_KEY or _is_cooling("mistral"):raise RuntimeError("Mistral unavailable or cooling.")yield from _stream_openai_compatible("https://api.mistral.ai/v1/chat/completions",MISTRAL_API_KEY, "mistral-large-latest", messages)

_PROVIDER_CHAIN = [("groq", _stream_groq),("openrouter", _stream_openrouter),("cerebras", _stream_cerebras),("mistral", _stream_mistral),]

def _do_stream(messages):any_token_yielded = Falsefor name, fn in _PROVIDER_CHAIN:try:for chunk in fn(messages):any_token_yielded = Trueyield chunkif any_token_yielded:yield _sse({"type": "complete"})returnexcept Exception as exc:print(f"[FAILOVER] {name} dropped: {exc}")_cool(name)continue

yield _sse({
    "type": "token",
    "text": "All model providers are temporarily unavailable. Please check your API keys or try again shortly."
})
yield _sse({"type": "complete"})

── DATA ──

def _user_id():return getattr(request, "current_user", {}).get("sub", "anonymous")

def _user_email():return getattr(request, "current_user", {}).get("email", "anonymous_user@local.domain")

def _get_convo(conv_id):if SUPABASE_CONFIGURED and _supabase:try:r = _supabase.table("conversations").select("*").eq("id", conv_id).single().execute()return r.dataexcept Exception:passreturn _mem_convos.get(conv_id)

def _save_convo(conv):if SUPABASE_CONFIGURED and _supabase:try:_supabase.table("conversations").upsert(conv).execute()returnexcept Exception:pass_mem_convos[conv["id"]] = conv

def _list_convos(user_id):if SUPABASE_CONFIGURED and _supabase:try:r = _supabase.table("conversations").select("id,title,pinned,created_at,updated_at").eq("user_id", user_id).order("updated_at", desc=True).execute()return r.data or []except Exception:passreturn [{"id": v["id"], "title": v.get("title", "Untitled"), "pinned": v.get("pinned", False),"created_at": v.get("created_at"), "updated_at": v.get("updated_at")}for v in _mem_convos.values() if v.get("user_id") == user_id]

def _get_messages(conv_id):if SUPABASE_CONFIGURED and _supabase:try:r = _supabase.table("messages").select("role,content,created_at").eq("conversation_id", conv_id).order("created_at").execute()return r.data or []except Exception:passreturn _mem_convos.get(conv_id, {}).get("messages", [])

def _append_message(conv_id, role, content):if SUPABASE_CONFIGURED and _supabase:try:_supabase.table("messages").insert({"id": str(uuid.uuid4()), "conversation_id": conv_id, "role": role,"content": content, "created_at": datetime.now(timezone.utc).isoformat()}).execute()except Exception:pass

conv = _mem_convos.get(conv_id)
if conv:
    conv.setdefault("messages", []).append({"role": role, "content": content})
    conv["updated_at"] = datetime.now(timezone.utc).isoformat()

── ROUTES ──

@app.route("/", methods=["GET"])@app.route("/api", methods=["GET"])@app.route("/api/app", methods=["GET"])def index_root():return jsonify({"message": "Pratham AI backend active"})

@app.route("/auth/exchange", methods=["POST", "OPTIONS"])@app.route("/api/auth/exchange", methods=["POST", "OPTIONS"])@app.route("/api/app/auth/exchange", methods=["POST", "OPTIONS"])def auth_exchange():if request.method == "OPTIONS":return _cors_preflight()token = _get_token()user = _verify_token(token)if not user:return jsonify({"error": "Could not verify the provided sign-in token."}), 401session_token = _issue_session_token(user)return jsonify({"ok": True, "session_token": session_token, "user": user, "expires_in_days": SESSION_TOKEN_TTL_DAYS})

@app.route("/auth/refresh-check", methods=["POST", "OPTIONS"])@app.route("/api/auth/refresh-check", methods=["POST", "OPTIONS"])@app.route("/api/app/auth/refresh-check", methods=["POST", "OPTIONS"])def refresh_check():if request.method == "OPTIONS":return _cors_preflight()token = _get_token()user = _verify_token(token)if not user:return jsonify({"error": "Stored session expired."}), 401return jsonify({"ok": True, "user": user})

@app.route("/auth/vip-status", methods=["GET", "OPTIONS"])@app.route("/api/auth/vip-status", methods=["GET", "OPTIONS"])@app.route("/api/app/auth/vip-status", methods=["GET", "OPTIONS"])@require_authdef vip_status():if request.method == "OPTIONS":return _cors_preflight()record = _lookup_vip(_user_email())if record:return jsonify({"is_vip": True, "name": record.get("name", ""), "relationship": record.get("relationship", "")})return jsonify({"is_vip": False})

@app.route("/auth/vip-register", methods=["POST", "OPTIONS"])@app.route("/api/auth/vip-register", methods=["POST", "OPTIONS"])@app.route("/api/app/auth/vip-register", methods=["POST", "OPTIONS"])@require_authdef register_vip_profile():if request.method == "OPTIONS":return _cors_preflight()body = request.get_json(silent=True) or {}name = body.get("name", "").strip()relationship = body.get("relationship", "").strip()email = body.get("email", _user_email()).strip()

if not name or not relationship:
    return jsonify({"error": "Missing required fields."}), 400

registration_row = f"Timestamp: {datetime.now(timezone.utc).isoformat()} | Email: {email} | Name: {name} | Relation: {relationship}\n"
success = _write_to_github_repository("data/vip.txt", registration_row)
if success:
    _vip_cache["t"] = 0
return jsonify({"ok": success, "status": "committed" if success else "local fallback"})

@app.route("/chat-stream", methods=["POST", "OPTIONS"])@app.route("/api/chat-stream", methods=["POST", "OPTIONS"])@app.route("/api/app/chat-stream", methods=["POST", "OPTIONS"])@require_authdef chat_stream():if request.method == "OPTIONS":return _cors_preflight()

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

# ── FILE BUNDLE WITH ZIP GENERATION ──
has_file_bundle = _detect_file_bundle_intent(message)
should_create_files = _detect_create_files_intent(message)

if has_file_bundle and should_create_files:
    _append_message(conv_id, "user", message)

    files_dict = _parse_code_bundle(message)

    if files_dict:
        zip_bytes = _build_zip_from_files(files_dict)
        token = _store_generated_file(zip_bytes, "files.zip", "application/zip")

        def generate_file_bundle_zip():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            file_list = ", ".join(files_dict.keys())
            yield _sse({"type": "activity", "text": f"Edited {len(files_dict)} files"})
            yield _sse({"type": "activity", "text": "Ran a bundler"})
            yield _sse({"type": "token", "text": f"✅ Created files: {file_list}\n\nZIP package ready for download."})
            yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": "files.zip"})
            yield _sse({"type": "complete"})

        resp = Response(stream_with_context(generate_file_bundle_zip()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

# ── IMAGE GENERATION ──
image_prompt = _detect_image_prompt(message)
if image_prompt:
    _append_message(conv_id, "user", message)
    image_url = _pollinations_image_url(image_prompt)
    assistant_note = f"✨ Generating image: \"{image_prompt}\"..."
    _append_message(conv_id, "assistant", f"{assistant_note}\n\n![Generated image]({image_url})")

    current_date_formatted = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _write_to_github_repository(
        f"data/{user_email}/{current_date_formatted}.txt",
        f"\n=== {datetime.now(timezone.utc).isoformat()} ===\nUser: {message}\n"
        f"Pratham AI: [image generated] {image_url}\n{'=' * 80}\n"
    )

    def generate_image():
        yield _sse({"type": "metadata", "conversation_id": conv_id})
        yield _sse({"type": "activity", "text": "Ran image generation command"})
        yield _sse({"type": "token", "text": assistant_note})
        yield _sse({"type": "image", "url": image_url, "prompt": image_prompt})
        yield _sse({"type": "complete"})

    resp = Response(stream_with_context(generate_image()), content_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

history = _get_messages(conv_id)
active_system_prompt = SYSTEM_PROMPT
vip_record = _lookup_vip(user_email)
if vip_record:
    active_system_prompt += (
        f" The person you are currently speaking with is a VIP contact registered by Pratham: "
        f"name '{vip_record.get('name', 'Unknown')}', relationship to Pratham: "
        f"'{vip_record.get('relationship', 'Unknown')}', email '{user_email}'. "
        f"You may acknowledge this relationship warmly if it becomes relevant, but do not "
        f"treat this as authorization to bypass any safety or content rules."
    )
api_messages = [{"role": "system", "content": active_system_prompt}]
for m in history[-20:]:
    api_messages.append({"role": m["role"], "content": m["content"]})

outgoing_user_message = message

# ── @education (HIDDEN FEATURE) ──
if "@education" in message.lower():
    outgoing_user_message = re.sub(r"@education", "", outgoing_user_message, flags=re.IGNORECASE).strip()
    best = _find_best_education_excerpt(outgoing_user_message or message)
    if best:
        api_messages[0]["content"] += (
            f" The user tagged @education (a hidden feature for studying). The most relevant "
            f"excerpt found was from the PDF file '{best['filename']}'. Use it to answer, "
            f"refine it into a clear answer, and explicitly mention which PDF you used. "
            f"Excerpt:\n\"\"\"\n{best['excerpt']}\n\"\"\""
        )
    else:
        api_messages[0]["content"] += (
            " The user tagged @education but no relevant PDF content could be found in the "
            "data/education library. Say so plainly instead of guessing."
        )
# ── AUTO @web SEARCH ──
elif len(message.strip()) > 5:
    outgoing_user_message = re.sub(r"@web\b", "", outgoing_user_message, flags=re.IGNORECASE).strip()
    results = _web_search_snippets(outgoing_user_message or message)
    if results:
        api_messages[0]["content"] += (
            " Here are live web search results relevant to the user's message (use them only "
            "if actually relevant; ignore for timeless questions; cite that info came from a "
            "web search when you do use it):\n" + "\n".join(results)
        )

api_messages.append({"role": "user", "content": outgoing_user_message or message})

_append_message(conv_id, "user", message)
_maybe_capture_public_teaching(user_email, message)

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
        repo_sync_destination_path = f"data/{user_email}/{current_date_formatted}.txt"

        log_entry = (
            f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"
            f"User: {message}\n"
            f"Pratham AI:\n{assistant_response}\n"
            f"{'=' * 80}\n"
        )
        _write_to_github_repository(repo_sync_destination_path, log_entry)

        # ── Real background Python terminal execution ──
        try:
            block_ordinal = 0
            for block_match in re.finditer(r"```(\w+)?\n([\s\S]*?)```", assistant_response):
                block_ordinal += 1
                block_lang = (block_match.group(1) or "text").lower()
                if block_lang not in ("python", "py"):
                    continue
                block_code = block_match.group(2)
                try:
                    yield _sse({"type": "activity", "text": f"Ran a command (Python block #{block_ordinal})"})
                    exec_result = subprocess.run(
                        [sys.executable, "-c", block_code],
                        capture_output=True, text=True, timeout=8
                    )
                    yield _sse({
                        "type": "terminal_output",
                        "ordinal": block_ordinal,
                        "stdout": exec_result.stdout[-4000:],
                        "stderr": exec_result.stderr[-4000:],
                        "returncode": exec_result.returncode
                    })
                except subprocess.TimeoutExpired:
                    yield _sse({
                        "type": "terminal_output", "ordinal": block_ordinal,
                        "stdout": "", "stderr": "Execution timed out after 8 seconds.", "returncode": -1
                    })
                except Exception as exec_exc:
                    yield _sse({
                        "type": "terminal_output", "ordinal": block_ordinal,
                        "stdout": "", "stderr": f"Execution failed: {exec_exc}", "returncode": -1
                    })
        except Exception as exc:
            print(f"[TERMINAL][FAULT] {exc}")

        # ── Background file generation ──
        try:
            if _ZIP_INTENT_RE.search(message):
                yield _sse({"type": "activity", "text": "Ran a bundler command"})
                zip_bytes = _build_zip_from_response(assistant_response)
                token = _store_generated_file(zip_bytes, "pratham_ai_output.zip", "application/zip")
                yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": "pratham_ai_output.zip"})
            elif _PDF_INTENT_RE.search(message):
                yield _sse({"type": "activity", "text": "Ran PDF generation command"})
                pdf_bytes, pdf_name, pdf_mime = _build_pdf_from_response(assistant_response)
                token = _store_generated_file(pdf_bytes, pdf_name, pdf_mime)
                yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": pdf_name})
        except Exception as exc:
            print(f"[FILEGEN][FAULT] {exc}")

resp = Response(stream_with_context(generate()), content_type="text/event-stream")
resp.headers["Cache-Control"] = "no-cache"
resp.headers["X-Accel-Buffering"] = "no"
resp.headers["Access-Control-Allow-Credentials"] = "true"
return resp

@app.route("/conversations", methods=["GET", "OPTIONS"])@app.route("/api/conversations", methods=["GET", "OPTIONS"])@app.route("/api/app/conversations", methods=["GET", "OPTIONS"])@require_authdef list_conversations():if request.method == "OPTIONS":return _cors_preflight()return jsonify(_list_convos(_user_id()))

@app.route("/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])@app.route("/api/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])@app.route("/api/app/conversations/<conv_id>/messages", methods=["GET", "OPTIONS"])@require_authdef get_messages_route(conv_id):if request.method == "OPTIONS":return _cors_preflight()return jsonify(_get_messages(conv_id))

@app.route("/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])@app.route("/api/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])@app.route("/api/app/conversations/<conv_id>", methods=["DELETE", "OPTIONS"])@require_authdef delete_conversation(conv_id):if request.method == "OPTIONS":return _cors_preflight()_mem_convos.pop(conv_id, None)if SUPABASE_CONFIGURED and _supabase:try:_supabase.table("messages").delete().eq("conversation_id", conv_id).execute()_supabase.table("conversations").delete().eq("id", conv_id).execute()except Exception:passreturn jsonify({"ok": True, "target_id": conv_id})

@app.route("/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])@app.route("/api/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])@app.route("/api/app/conversations/<conv_id>/export", methods=["GET", "OPTIONS"])@require_authdef export_conversation(conv_id):if request.method == "OPTIONS":return _cors_preflight()msgs = _get_messages(conv_id)lines = ["Pratham AI conversation export", ""]for m in msgs:lines.append(f"[{m.get('role', 'system')}]:\n{m['content']}\n")return Response("\n".join(lines), content_type="text/plain; charset=utf-8")

@app.route("/execute-python", methods=["POST", "OPTIONS"])@app.route("/api/execute-python", methods=["POST", "OPTIONS"])@app.route("/api/app/execute-python", methods=["POST", "OPTIONS"])@require_authdef execute_python():if request.method == "OPTIONS":return _cors_preflight()body = request.get_json(silent=True) or {}code = body.get("code", "").strip()if not code:return jsonify({"error": "Empty code payload"}), 400try:result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)return jsonify({"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode})except Exception as exc:return jsonify({"stdout": "", "stderr": f"Sandbox Exception: {exc}", "returncode": -1})

@app.route("/upload", methods=["POST", "OPTIONS"])@app.route("/api/upload", methods=["POST", "OPTIONS"])@app.route("/api/app/upload", methods=["POST", "OPTIONS"])@require_authdef upload_pdf():if request.method == "OPTIONS":return _cors_preflight()f = request.files.get("file")if not f or not f.filename:return jsonify({"error": "No file received."}), 400

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
    elif ext in ("txt", "md", "csv", "json", "html", "css", "js", "py", "xml", "yml", "yaml", "log", "tsx", "ts"):
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
        decode_status = f"stored ({len(raw_bytes)} bytes, image — use chat vision features to analyze it)"
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

def _cors_preflight():resp = Response("", status=204)origin = request.headers.get("Origin", "*")resp.headers["Access-Control-Allow-Origin"] = originresp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept, X-Requested-With"resp.headers["Access-Control-Allow-Credentials"] = "true"return resp

if name == "main":port = int(os.environ.get("PORT", 5000))app.run(host="0.0.0.0", port=port, debug=False)
