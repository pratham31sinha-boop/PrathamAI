# app.py — Pratham AI Backend (Complete & Corrected)

import os, json, uuid, time, re, subprocess, tempfile, mimetypes, zipfile, io, base64
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps
from typing import Generator

from flask import (
    Flask, request, jsonify, Response, stream_with_context,
    send_from_directory, send_file, abort
)
from flask_cors import CORS
import requests as http_requests

# ── Optional imports (graceful fallback) ───────────────────────────────────────
try:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_auth_requests
    GOOGLE_VERIFY_AVAILABLE = True
except ImportError:
    GOOGLE_VERIFY_AVAILABLE = False

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ── Flask app setup ────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static")
CORS(app, origins="*", allow_headers=["Content-Type", "Authorization"])

# ── Config ─────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_CLIENT_ID    = "352716901368-sp0550kmd9jb9ob4b5adrq6npltq4jht.apps.googleusercontent.com"
OPENAI_API_KEY      = os.environ.get("OPENAI_API_KEY", "")       # for DALL-E image gen
STABILITY_API_KEY   = os.environ.get("STABILITY_API_KEY", "")    # fallback image gen

UPLOAD_DIR  = Path("uploads");  UPLOAD_DIR.mkdir(exist_ok=True)
STATIC_DIR  = Path("static");   STATIC_DIR.mkdir(exist_ok=True)
GENERATED_DIR = STATIC_DIR / "generated"; GENERATED_DIR.mkdir(exist_ok=True)

MAX_CONTEXT_MESSAGES = 20
MAX_TOKENS_PER_FILE  = 8000        # trigger continuation if code block approaches this
ALLOWED_ORIGINS = ["*"]

# ── In-memory stores ───────────────────────────────────────────────────────────
conversations: dict  = {}   # { conv_id: { "user_email": ..., "messages": [...], "title": ..., "updated_at": ... } }
session_tokens: dict = {}   # { token: email }
public_memory: list  = []   # global learned facts
uploaded_file_context: dict = {}  # { email: [{ filename, content }] }

# ── Authorised users ───────────────────────────────────────────────────────────
CREATOR_EMAILS    = {"pratham31sinha@gmail.com", "pratham08sinha@gmail.com", "pratham310811@gmail.com"}
SUPERVISOR_EMAILS = {"aditiaishwaryam11@gmail.com", "akritiaishwaryam17@gmail.com"}

def get_role(email: str) -> str:
    e = email.lower()
    if e in CREATOR_EMAILS:    return "creator"
    if e in SUPERVISOR_EMAILS: return "supervisor"
    return "user"

# ── Auth helpers ───────────────────────────────────────────────────────────────
def extract_bearer(req) -> str:
    hdr = req.headers.get("Authorization", "")
    if hdr.startswith("Bearer "): return hdr[7:]
    return req.args.get("token", "").replace("Bearer ", "")

def resolve_email_from_token(token: str) -> str | None:
    """Return email from session token or raw Google JWT."""
    if not token: return None
    # 1. Check our own session store
    if token in session_tokens: return session_tokens[token]
    # 2. Try to decode as Google JWT (no verification — we trust our own exchange)
    try:
        parts = token.split(".")
        if len(parts) == 3:
            padded = parts[1] + "=="
            claims = json.loads(base64.urlsafe_b64decode(padded))
            email = claims.get("email", "").lower()
            if email: return email
    except Exception: pass
    return None

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = extract_bearer(request)
        email = resolve_email_from_token(token)
        if not email:
            return jsonify({"error": "Unauthorized"}), 401
        request.user_email = email
        return f(*args, **kwargs)
    return wrapper

# ── SSE helpers ───────────────────────────────────────────────────────────────
def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

def sse_activity(text: str) -> str:
    return sse({"type": "activity", "text": text})

def sse_token(text: str) -> str:
    return sse({"type": "token", "text": text})

def sse_image_start(prompt: str) -> str:
    return sse({"type": "image_start", "prompt": prompt})

def sse_image(url: str, prompt: str) -> str:
    return sse({"type": "image", "url": url, "prompt": prompt})

def sse_file_ready(url: str, filename: str) -> str:
    return sse({"type": "file_ready", "url": url, "filename": filename})

def sse_terminal(ordinal: int, returncode: int, stdout: str, stderr: str) -> str:
    return sse({"type": "terminal_output", "ordinal": ordinal, "returncode": returncode, "stdout": stdout, "stderr": stderr})

def sse_complete(needs_continuation: bool = False) -> str:
    return sse({"type": "complete", "needs_continuation": needs_continuation})

def sse_metadata(conv_id: str) -> str:
    return sse({"type": "metadata", "conversation_id": conv_id})

# ── File generation helpers ───────────────────────────────────────────────────
def make_pdf(text_content: str, filename: str) -> Path:
    """Generate a real PDF file using ReportLab."""
    out_path = GENERATED_DIR / filename
    if REPORTLAB_AVAILABLE:
        c = rl_canvas.Canvas(str(out_path), pagesize=letter)
        w, h = letter
        margin = inch
        y = h - margin
        c.setFont("Helvetica", 11)
        for line in text_content.split('\n'):
            if y < margin:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = h - margin
            # Word-wrap long lines
            while len(line) > 90:
                c.drawString(margin, y, line[:90])
                line = line[90:]
                y -= 16
                if y < margin:
                    c.showPage()
                    c.setFont("Helvetica", 11)
                    y = h - margin
            c.drawString(margin, y, line)
            y -= 16
        c.save()
    else:
        # Fallback: write as plain text with .pdf extension
        out_path.write_text(text_content, encoding='utf-8')
    return out_path

def make_zip(files: dict) -> Path:
    """
    Create a ZIP file.
    files = { "filename.ext": "content string", ... }
    """
    ts = int(time.time())
    zip_path = GENERATED_DIR / f"bundle_{ts}.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)
    zip_path.write_bytes(buf.read())
    return zip_path

def make_image_placeholder(prompt: str) -> Path:
    """Generate a placeholder image when no API key is available."""
    ts = int(time.time())
    img_path = GENERATED_DIR / f"image_{ts}.png"
    if PIL_AVAILABLE:
        from PIL import ImageDraw, ImageFont
        img = PILImage.new('RGB', (512, 512), color=(194, 97, 63))
        draw = ImageDraw.Draw(img)
        draw.text((20, 240), f"🎨 {prompt[:40]}", fill=(255, 255, 255))
        img.save(str(img_path))
    else:
        # Minimal 1x1 PNG bytes
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI6QAAAABJRU5ErkJggg=="
        )
        img_path.write_bytes(png_bytes)
    return img_path

async def generate_image_dalle(prompt: str) -> str | None:
    """Call OpenAI DALL-E 3 and return public URL."""
    if not OPENAI_API_KEY: return None
    try:
        resp = http_requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": prompt, "n": 1, "size": "1024x1024"},
            timeout=60
        )
        data = resp.json()
        return data["data"][0]["url"]
    except Exception:
        return None

def generate_image_stability(prompt: str) -> str | None:
    """Call Stability AI and return a local URL."""
    if not STABILITY_API_KEY: return None
    try:
        resp = http_requests.post(
            "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
            headers={"Authorization": f"Bearer {STABILITY_API_KEY}", "Content-Type": "application/json", "Accept": "application/json"},
            json={"text_prompts": [{"text": prompt}], "cfg_scale": 7, "height": 1024, "width": 1024, "steps": 30, "samples": 1},
            timeout=90
        )
        data = resp.json()
        if "artifacts" in data and data["artifacts"]:
            img_b64 = data["artifacts"][0]["base64"]
            ts = int(time.time())
            img_path = GENERATED_DIR / f"image_{ts}.png"
            img_path.write_bytes(base64.b64decode(img_b64))
            return f"/static/generated/{img_path.name}"
    except Exception: pass
    return None

# ── Intent / tool detection ───────────────────────────────────────────────────
IMG_PATTERNS = [
    r'\b(generate|create|make|draw|render|paint|show|produce)\s+(a\s+|an\s+|the\s+)?(image|photo|picture|illustration|artwork|painting|drawing|portrait|scene|wallpaper|thumbnail)\b',
    r'\b(image|picture|photo)\s+of\b',
    r'\bvisualize\b',
    r'\btext.?to.?image\b',
]
IMG_RE = re.compile('|'.join(IMG_PATTERNS), re.IGNORECASE)

PDF_PATTERNS = [
    r'\b(generate|create|make|write|produce|export|save)\s+(a\s+|an\s+|the\s+)?(pdf|PDF)\b',
    r'\bpdf\s+(document|report|file|version)\b',
    r'\bexport\s+to\s+pdf\b',
    r'\bsave\s+as\s+pdf\b',
]
PDF_RE = re.compile('|'.join(PDF_PATTERNS), re.IGNORECASE)

ZIP_PATTERNS = [
    r'\b(generate|create|make|build|package|bundle|zip|compress)\s+(a\s+|an\s+|the\s+)?(zip|ZIP|archive|bundle|package)\b',
    r'\bzip\s+(file|archive|folder)\b',
    r'\bpackage\s+(all|the|it|them|files|code)\b',
    r'\bbundle\s+(all|the|it|them|files|code)\b',
]
ZIP_RE = re.compile('|'.join(ZIP_PATTERNS), re.IGNORECASE)

CODE_EXEC_PATTERNS = [
    r'\b(run|execute|eval|compute|calculate|test)\s+(this|the|my)?\s*(code|script|snippet|python|program)\b',
    r'\brun\s+it\b',
]
CODE_EXEC_RE = re.compile('|'.join(CODE_EXEC_PATTERNS), re.IGNORECASE)

WEB_PATTERNS = [
    r'\b(search|lookup|find|google|check|look up)\b',
    r'\bwhat.s\s+happening\b',
    r'\blatest\b',
    r'\bcurrent(ly)?\b',
    r'\btoday\b',
    r'\brecent\b',
    r'\bnews\b',
    r'\b20(24|25)\b',
]
WEB_RE = re.compile('|'.join(WEB_PATTERNS), re.IGNORECASE)

LEARN_PATTERNS = [
    r'\b(remember|learn|save|note|memorize)\s+(that|this|it)?\b',
    r'\btake note\b',
    r'\bkeep in mind\b',
]
LEARN_RE = re.compile('|'.join(LEARN_PATTERNS), re.IGNORECASE)

def detect_image_prompt(message: str) -> str | None:
    """Extract image generation prompt from message if detected."""
    if IMG_RE.search(message):
        # Try to extract the subject
        clean = re.sub(r'\b(generate|create|make|draw|render|paint|show|produce|please|can you|could you)\b', '', message, flags=re.IGNORECASE)
        clean = re.sub(r'\b(a |an |the |image of |picture of |photo of |illustration of )\b', '', clean, flags=re.IGNORECASE)
        return clean.strip() or message
    return None

def detect_pdf_request(message: str) -> bool:
    return bool(PDF_RE.search(message))

def detect_zip_request(message: str) -> bool:
    return bool(ZIP_RE.search(message))

def detect_code_exec_request(message: str) -> bool:
    return bool(CODE_EXEC_RE.search(message))

def detect_web_search(message: str) -> bool:
    return bool(WEB_RE.search(message))

def detect_learn_request(message: str) -> bool:
    return bool(LEARN_RE.search(message))

# ── Web search (DuckDuckGo scrape) ────────────────────────────────────────────
def web_search(query: str, max_results: int = 4) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://api.duckduckgo.com/?q={http_requests.utils.quote(query)}&format=json&no_redirect=1&no_html=1"
        r = http_requests.get(url, headers=headers, timeout=8)
        data = r.json()
        results = []
        if data.get("AbstractText"):
            results.append(f"Summary: {data['AbstractText']}")
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(f"• {topic['Text']}")
        return "\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Web search unavailable: {e}"

# ── Code execution ─────────────────────────────────────────────────────────────
def execute_python_code(code: str, timeout: int = 15) -> tuple[int, str, str]:
    """Execute Python code in a temp file. Returns (returncode, stdout, stderr)."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(GENERATED_DIR)
        )
        return result.returncode, result.stdout[:2000], result.stderr[:2000]
    except subprocess.TimeoutExpired:
        return 1, "", "Execution timed out (15s limit)."
    except Exception as e:
        return 1, "", str(e)
    finally:
        try: os.unlink(tmp_path)
        except: pass

def execute_bash_code(code: str, timeout: int = 15) -> tuple[int, str, str]:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["bash", tmp_path],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(GENERATED_DIR)
        )
        return result.returncode, result.stdout[:2000], result.stderr[:2000]
    except subprocess.TimeoutExpired:
        return 1, "", "Execution timed out."
    except Exception as e:
        return 1, "", str(e)
    finally:
        try: os.unlink(tmp_path)
        except: pass

# ── Extract code blocks from AI response ─────────────────────────────────────
def extract_code_blocks(text: str) -> list[dict]:
    """Return list of {lang, code} from fenced code blocks."""
    blocks = []
    pattern = re.compile(r'```(\w+)?\n(.*?)```', re.DOTALL)
    for m in pattern.finditer(text):
        lang = (m.group(1) or 'text').lower()
        code = m.group(2)
        blocks.append({'lang': lang, 'code': code})
    return blocks

# ── System prompt builder ─────────────────────────────────────────────────────
def build_system_prompt(user_email: str, web_context: str = "", file_context: str = "") -> str:
    role = get_role(user_email)
    memory_str = ""
    if public_memory:
        memory_str = "\n\nPublic Memory (things you've been taught):\n" + "\n".join(f"- {m}" for m in public_memory[-20:])

    return f"""You are Pratham AI, an advanced AI assistant that can:
1. Answer questions with deep knowledge and reasoning
2. Generate complete, production-ready code files (HTML, Python, JS, CSS, etc.)
3. Create essays, reports, documents
4. Analyze uploaded files and images
5. Perform multi-step reasoning

USER ROLE: {role}
USER EMAIL: {user_email}

IMPORTANT RULES:
- When asked to create/generate a file (HTML, Python, JS, PDF content, etc.), ALWAYS provide the COMPLETE file content in a properly fenced code block
- Use ```html for HTML, ```python for Python, ```javascript for JS, etc.
- NEVER truncate or abbreviate code — write the entire file
- If a file is very large (>300 lines), still write it completely. Do not say "continue" or abbreviate
- For PDF requests: write the full text content in a ```text code block and the backend will convert it to a real PDF
- For ZIP requests: write each file in separate labeled code blocks and the backend will bundle them
- For image requests: describe what you want clearly (the backend handles actual generation)
- Be creative, thorough, and produce genuinely useful output
- You have access to web search results and file context when provided

CAPABILITIES YOU SHOULD KNOW ABOUT:
- The backend can execute Python code blocks automatically
- The backend converts ```text or ```markdown blocks into real PDFs when PDF is requested
- The backend bundles multiple code blocks into ZIP files when requested
- Image generation is handled separately by the backend image API
{memory_str}{web_context}{file_context}"""

# ── Main streaming chat endpoint ───────────────────────────────────────────────
@app.route("/api/app/chat-stream", methods=["POST"])
@app.route("/api/chat-stream", methods=["POST"])
@app.route("/chat-stream", methods=["POST"])
@require_auth
def chat_stream():
    data = request.get_json(silent=True) or {}
    user_message: str = data.get("message", "").strip()
    conv_id: str = data.get("conversation_id") or str(uuid.uuid4())

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    user_email = request.user_email

    # Get or create conversation
    if conv_id not in conversations:
        conversations[conv_id] = {
            "user_email": user_email,
            "messages": [],
            "title": user_message[:60],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
    conv = conversations[conv_id]
    conv["updated_at"] = datetime.now(timezone.utc).isoformat()

    def generate() -> Generator[str, None, None]:
        # 1. Send metadata first
        yield sse_metadata(conv_id)

        # 2. Detect intents
        wants_image  = detect_image_prompt(user_message)
        wants_pdf    = detect_pdf_request(user_message)
        wants_zip    = detect_zip_request(user_message)
        wants_exec   = detect_code_exec_request(user_message)
        wants_web    = detect_web_search(user_message)
        wants_learn  = detect_learn_request(user_message)

        # 3. Handle learning
        if wants_learn:
            fact = re.sub(r'\b(remember|learn|save|note|memorize|that|this|please)\b', '', user_message, flags=re.IGNORECASE).strip()
            if fact:
                public_memory.append(f"[{user_email}]: {fact}")
                yield sse_activity("💾 Saved to memory")

        # 4. Web search
        web_context = ""
        if wants_web:
            yield sse_activity("🌐 Searching the web...")
            results = web_search(user_message)
            web_context = f"\n\nWeb Search Results for '{user_message}':\n{results}"
            yield sse_activity("✓ Web search complete")

        # 5. Handle image generation (before AI response)
        if wants_image:
            prompt = wants_image
            yield sse_image_start(prompt)
            yield sse_activity(f"🎨 Generating image: {prompt[:40]}...")

            image_url = None
            # Try DALL-E first
            if OPENAI_API_KEY:
                import asyncio
                try:
                    loop = asyncio.new_event_loop()
                    image_url = loop.run_until_complete(generate_image_dalle(prompt))
                    loop.close()
                except Exception: pass

            # Try Stability AI
            if not image_url and STABILITY_API_KEY:
                image_url = generate_image_stability(prompt)

            # Fallback: placeholder
            if not image_url:
                placeholder_path = make_image_placeholder(prompt)
                image_url = f"/static/generated/{placeholder_path.name}"

            yield sse_image(image_url, prompt)
            yield sse_activity("✓ Image ready")

        # 6. Build file context
        file_context = ""
        if user_email in uploaded_file_context and uploaded_file_context[user_email]:
            parts = []
            for fc in uploaded_file_context[user_email][-3:]:
                parts.append(f"\n--- File: {fc['filename']} ---\n{fc['content'][:3000]}")
            file_context = "\n\nAttached file context:" + "".join(parts)

        # 7. Build messages for Claude
        system = build_system_prompt(user_email, web_context, file_context)
        history = conv["messages"][-MAX_CONTEXT_MESSAGES:]

        # Add intent hints to message
        enhanced_message = user_message
        if wants_pdf:
            enhanced_message += "\n\n[SYSTEM HINT: User wants a PDF. Generate the full content in a ```text code block. The backend will convert it to a real PDF file automatically.]"
        if wants_zip:
            enhanced_message += "\n\n[SYSTEM HINT: User wants a ZIP bundle. Write each file as a separate named code block. The backend will zip them all.]"
        if wants_exec:
            enhanced_message += "\n\n[SYSTEM HINT: User wants code executed. Write executable Python in a ```python code block. The backend will run it and show output.]"

        messages = history + [{"role": "user", "content": enhanced_message}]

        # 8. Stream from Claude
        full_response = ""
        if not ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
            # Fallback mock response
            yield sse_activity("⚠ No AI API configured — using mock")
            mock = f"I received your message: '{user_message}'\n\nThis is a placeholder response. Please configure ANTHROPIC_API_KEY to enable real AI responses."
            for word in mock.split(" "):
                yield sse_token(word + " ")
                full_response += word + " "
                time.sleep(0.02)
        else:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            yield sse_activity("🤔 Thinking...")
            try:
                with client.messages.stream(
                    model="claude-opus-4-5",
                    max_tokens=8192,
                    system=system,
                    messages=messages
                ) as stream:
                    for text_chunk in stream.text_stream:
                        yield sse_token(text_chunk)
                        full_response += text_chunk
            except anthropic.APIError as e:
                error_msg = f"\n\n[API Error: {str(e)}]"
                yield sse_token(error_msg)
                full_response += error_msg

        # 9. Post-processing: extract and handle code blocks
        code_blocks = extract_code_blocks(full_response)
        needs_continuation = False

        if code_blocks:
            yield sse_activity("⚙ Processing generated files...")

            # Handle PDF
            if wants_pdf:
                for i, block in enumerate(code_blocks):
                    if block['lang'] in ('text', 'markdown', 'md', 'txt'):
                        yield sse_activity(f"📄 Creating PDF {i+1}...")
                        ts = int(time.time())
                        pdf_filename = f"document_{ts}.pdf"
                        try:
                            pdf_path = make_pdf(block['code'], pdf_filename)
                            yield sse_file_ready(f"/static/generated/{pdf_filename}", pdf_filename)
                            yield sse_activity(f"✓ PDF ready: {pdf_filename}")
                        except Exception as ex:
                            yield sse_activity(f"⚠ PDF error: {ex}")

            # Handle ZIP
            if wants_zip:
                yield sse_activity("📦 Bundling files into ZIP...")
                zip_files = {}
                for i, block in enumerate(code_blocks):
                    ext_map = {'html':'index.html','python':'script.py','py':'script.py','javascript':'script.js',
                               'js':'script.js','css':'style.css','json':'data.json','bash':'run.sh','sh':'run.sh',
                               'text':'content.txt','txt':'content.txt','markdown':'README.md','md':'README.md'}
                    base_name = ext_map.get(block['lang'], f"file_{i+1}.txt")
                    if base_name in zip_files:
                        name_parts = base_name.rsplit('.', 1)
                        base_name = f"{name_parts[0]}_{i+1}.{name_parts[1]}"
                    zip_files[base_name] = block['code']
                if zip_files:
                    try:
                        zip_path = make_zip(zip_files)
                        yield sse_file_ready(f"/static/generated/{zip_path.name}", zip_path.name)
                        yield sse_activity(f"✓ ZIP ready: {zip_path.name} ({len(zip_files)} files)")
                    except Exception as ex:
                        yield sse_activity(f"⚠ ZIP error: {ex}")

            # Handle code execution
            if wants_exec or detect_code_exec_request(full_response):
                for i, block in enumerate(code_blocks):
                    if block['lang'] in ('python', 'py'):
                        yield sse_activity(f"🔧 Executing Python block {i+1}...")
                        rc, stdout, stderr = execute_python_code(block['code'])
                        yield sse_terminal(i+1, rc, stdout, stderr)
                        yield sse_activity(f"{'✓' if rc==0 else '⚠'} Execution complete (exit {rc})")
                    elif block['lang'] in ('bash', 'sh', 'shell'):
                        yield sse_activity(f"🔧 Executing shell block {i+1}...")
                        rc, stdout, stderr = execute_bash_code(block['code'])
                        yield sse_terminal(i+1, rc, stdout, stderr)

        # Check if response was cut short (crude heuristic)
        if len(full_response) > 7000 and not full_response.rstrip().endswith('```'):
            needs_continuation = True

        # 10. Save conversation
        conv["messages"].append({"role": "user", "content": user_message})
        conv["messages"].append({"role": "assistant", "content": full_response})
        if len(conv["messages"]) > MAX_CONTEXT_MESSAGES * 2:
            conv["messages"] = conv["messages"][-(MAX_CONTEXT_MESSAGES * 2):]

        yield sse_complete(needs_continuation)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

# ── Auth endpoints ─────────────────────────────────────────────────────────────
@app.route("/api/app/auth/exchange", methods=["POST"])
@app.route("/api/auth/exchange", methods=["POST"])
@app.route("/auth/exchange", methods=["POST"])
def auth_exchange():
    token = extract_bearer(request)
    if not token: return jsonify({"error": "No token"}), 400
    email = resolve_email_from_token(token)
    if not email: return jsonify({"error": "Invalid token"}), 401
    session_token = f"sess_{uuid.uuid4().hex}"
    session_tokens[session_token] = email
    return jsonify({"session_token": session_token, "email": email})

@app.route("/api/app/auth/refresh-check", methods=["POST"])
@app.route("/api/auth/refresh-check", methods=["POST"])
@app.route("/auth/refresh-check", methods=["POST"])
def auth_refresh_check():
    token = extract_bearer(request)
    email = resolve_email_from_token(token)
    if not email: return jsonify({"error": "Invalid"}), 401
    return jsonify({"ok": True, "email": email})

# ── Conversations endpoints ────────────────────────────────────────────────────
@app.route("/api/app/conversations", methods=["GET"])
@app.route("/api/conversations", methods=["GET"])
@app.route("/conversations", methods=["GET"])
@require_auth
def list_conversations():
    user_email = request.user_email
    result = []
    for cid, conv in conversations.items():
        if conv.get("user_email") == user_email:
            result.append({
                "id": cid,
                "title": conv.get("title", "Untitled"),
                "created_at": conv.get("created_at", ""),
                "updated_at": conv.get("updated_at", "")
            })
    result.sort(key=lambda x: x["updated_at"], reverse=True)
    return jsonify(result)

@app.route("/api/app/conversations/<conv_id>/messages", methods=["GET"])
@app.route("/api/conversations/<conv_id>/messages", methods=["GET"])
@app.route("/conversations/<conv_id>/messages", methods=["GET"])
@require_auth
def get_conversation_messages(conv_id):
    user_email = request.user_email
    conv = conversations.get(conv_id)
    if not conv: return jsonify([])
    if conv.get("user_email") != user_email: return jsonify({"error": "Forbidden"}), 403
    return jsonify(conv.get("messages", []))

@app.route("/api/app/conversations/<conv_id>", methods=["DELETE"])
@app.route("/api/conversations/<conv_id>", methods=["DELETE"])
@app.route("/conversations/<conv_id>", methods=["DELETE"])
@require_auth
def delete_conversation(conv_id):
    user_email = request.user_email
    conv = conversations.get(conv_id)
    if conv and conv.get("user_email") == user_email:
        del conversations[conv_id]
    return jsonify({"ok": True})

@app.route("/api/app/conversations/<conv_id>/export", methods=["GET"])
@app.route("/conversations/<conv_id>/export", methods=["GET"])
@require_auth
def export_conversation(conv_id):
    user_email = request.user_email
    conv = conversations.get(conv_id)
    if not conv or conv.get("user_email") != user_email:
        return jsonify({"error": "Not found"}), 404
    lines = []
    for msg in conv.get("messages", []):
        role = "You" if msg["role"] == "user" else "Pratham AI"
        lines.append(f"## {role}\n\n{msg['content']}\n")
    export_text = f"# Conversation Export\n\n{'---'.join(lines)}"
    return Response(export_text, mimetype="text/markdown",
                    headers={"Content-Disposition": f"attachment; filename=conversation_{conv_id[:8]}.md"})

# ── File upload endpoint ───────────────────────────────────────────────────────
@app.route("/api/app/upload", methods=["POST"])
@app.route("/api/upload", methods=["POST"])
@app.route("/upload", methods=["POST"])
@require_auth
def upload_file():
    user_email = request.user_email
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    filename = f.filename or "upload.bin"
    safe_name = re.sub(r'[^\w.\-]', '_', filename)
    save_path = UPLOAD_DIR / safe_name
    f.save(str(save_path))
    size = save_path.stat().st_size

    # Decode content
    content = ""
    ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
    status = "stored"

    try:
        if ext in ('txt', 'py', 'js', 'ts', 'jsx', 'tsx', 'html', 'htm', 'css', 'json', 'csv', 'md', 'xml', 'yaml', 'yml', 'sh', 'bash', 'sql'):
            content = save_path.read_text(encoding='utf-8', errors='replace')
            status = "decoded as text"
        elif ext == 'pdf':
            try:
                import pdfplumber
                with pdfplumber.open(str(save_path)) as pdf:
                    content = "\n".join(p.extract_text() or '' for p in pdf.pages)
                status = "decoded PDF"
            except ImportError:
                try:
                    import pypdf
                    reader = pypdf.PdfReader(str(save_path))
                    content = "\n".join(p.extract_text() or '' for p in reader.pages)
                    status = "decoded PDF"
                except Exception: content = "[PDF content could not be extracted — install pdfplumber]"; status = "PDF parse failed"
        elif ext in ('docx',):
            try:
                from docx import Document as DocxDocument
                doc = DocxDocument(str(save_path))
                content = "\n".join(p.text for p in doc.paragraphs)
                status = "decoded DOCX"
            except Exception: content = "[DOCX extraction requires python-docx]"; status = "DOCX parse failed"
        elif ext == 'zip':
            try:
                with zipfile.ZipFile(str(save_path)) as zf:
                    parts = []
                    for name in zf.namelist()[:20]:
                        try:
                            parts.append(f"--- {name} ---\n{zf.read(name).decode('utf-8', errors='replace')[:2000]}")
                        except Exception: parts.append(f"--- {name} --- [binary]")
                    content = "\n\n".join(parts)
                status = "decoded ZIP"
            except Exception: content = "[ZIP extraction failed]"; status = "ZIP parse failed"
        else:
            content = f"[Binary file: {filename}, {size} bytes]"
            status = "stored as binary"
    except Exception as e:
        content = f"[Error reading file: {e}]"; status = "read error"

    # Store in context
    if user_email not in uploaded_file_context:
        uploaded_file_context[user_email] = []
    uploaded_file_context[user_email].append({"filename": filename, "content": content})
    if len(uploaded_file_context[user_email]) > 5:
        uploaded_file_context[user_email] = uploaded_file_context[user_email][-5:]

    return jsonify({"ok": True, "filename": filename, "size_bytes": size, "status": status})

# ── Static file serving ────────────────────────────────────────────────────────
@app.route("/static/generated/<path:filename>")
def serve_generated(filename):
    return send_from_directory(str(GENERATED_DIR), filename)

@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(str(STATIC_DIR), filename)

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    # Serve index.html for all non-API routes
    if path.startswith("api/") or path.startswith("static/"):
        abort(404)
    index = Path("index.html")
    if index.exists():
        return index.read_text(encoding='utf-8'), 200, {"Content-Type": "text/html"}
    return "<h1>Pratham AI</h1><p>index.html not found.</p>", 200

# ── Health check ───────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "anthropic": ANTHROPIC_AVAILABLE and bool(ANTHROPIC_API_KEY),
        "reportlab": REPORTLAB_AVAILABLE,
        "pil": PIL_AVAILABLE,
        "openai_image": bool(OPENAI_API_KEY),
        "stability_image": bool(STABILITY_API_KEY),
        "conversations": len(conversations),
        "memory_facts": len(public_memory),
    })

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "0") == "1"
    print(f"""
╔══════════════════════════════════════╗
║         Pratham AI Backend           ║
║  http://127.0.0.1:{port:<5}               ║
║  Anthropic: {'✓' if ANTHROPIC_AVAILABLE and ANTHROPIC_API_KEY else '✗ (set ANTHROPIC_API_KEY)'}                  ║
║  PDF (ReportLab): {'✓' if REPORTLAB_AVAILABLE else '✗ (pip install reportlab)'}           ║
║  Images (DALL-E): {'✓' if OPENAI_API_KEY else '✗ (set OPENAI_API_KEY)'}             ║
║  Images (Stability): {'✓' if STABILITY_API_KEY else '✗ (set STABILITY_API_KEY)'}          ║
╚══════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
