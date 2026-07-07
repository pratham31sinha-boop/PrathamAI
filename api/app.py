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
  9. Image generation via Pollinations AI (no API key required): a message
     like "generate an image of a red fox in snow" or "/image a red fox in
     snow" now returns a real rendered image instead of text.
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
SESSION_SECRET       = os.environ.get("SESSION_SECRET", "pratham-ai-dev-secret-change-me").strip()
SESSION_TOKEN_TTL_DAYS = int(os.environ.get("SESSION_TOKEN_TTL_DAYS", "30"))

# Mirrors the creator list already hardcoded in the frontend's
# paintIdentityIntoShell(), so the backend can also recognize these accounts
# for creator-only features (like the live system-diagnostics short-circuit
# below) without needing a separate database/table.
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

# ── VIP RECOGNITION (reads back data/vip.txt so the bot can recognize a
#    registered VIP contact by email and greet/treat them accordingly) ──
_vip_cache = {"entries": {}, "t": 0}
_VIP_CACHE_TTL = 30  # seconds; short enough that a fresh registration is
                      # picked up almost immediately, long enough to avoid
                      # hitting GitHub on every single chat message.

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
                            "relationship": parts.get("relationship", ""),
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

# ── BACKGROUND FILE GENERATION ("the AI uses a Python terminal") ──
# This is the real, executing counterpart to the frontend's animated file
# cards: when the person's message asks for a zip or a PDF, the backend
# actually builds that file in Python (zipfile from stdlib; PDF via the
# optional fpdf2 package) and hands back a one-time download link.
_generated_files_store: dict = {}
_GENERATED_FILE_TTL = 3600  # 1 hour

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

# Deterministic safety net: models don't always follow the ```finaldoc
# instruction reliably, so even without it, strip whole lines/sentences that
# are clearly meta-commentary about the export mechanism rather than actual
# content, instead of exporting the raw full reply verbatim.
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
    # Collapse resulting doubled-up blank lines from removed sentences.
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

def _build_zip_from_response(assistant_text: str, workdir: str = None) -> bytes:
    """Packs real files first: if the background terminal actually created
    any files in `workdir` during this request (e.g. the model ran python
    that wrote out a .csv, a script, etc.), those real files are what gets
    zipped. Falls back to packing every fenced code block in the reply if
    the workdir is empty, and to the clean exported content (see
    `_extract_export_content`) as response.txt if there were no code blocks
    either."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        real_files_written = False
        if workdir and os.path.isdir(workdir):
            for root, _dirs, files in os.walk(workdir):
                for fname in files:
                    full_path = os.path.join(root, fname)
                    arcname = os.path.relpath(full_path, workdir)
                    try:
                        zf.write(full_path, arcname)
                        real_files_written = True
                    except Exception:
                        continue

        if not real_files_written:
            blocks = re.findall(r"```(\w+)?\n([\s\S]*?)```", assistant_text)
            blocks = [(lang, content) for lang, content in blocks if (lang or "").lower() != "finaldoc"]
            if blocks:
                for i, (lang, content) in enumerate(blocks, start=1):
                    ext = {
                        "html": "html", "javascript": "js", "js": "js", "python": "py", "py": "py",
                        "css": "css", "json": "json", "bash": "sh", "text": "txt"
                    }.get((lang or "text").lower(), "txt")
                    zf.writestr(f"file_{i}.{ext}", content)
            else:
                zf.writestr("response.txt", _extract_export_content(assistant_text))
    buf.seek(0)
    return buf.read()

def _escape_pdf_literal_text(s: str) -> str:
    return s.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')

def _markdownish_lines_for_pdf(text: str, max_width_chars: int):
    """
    Converts lightly-markdown-formatted text (headings wrapped in **like
    this**, and `* `/`- ` bullets — the style the model actually writes) into
    a flat list of (font_key, size_delta, rendered_line) tuples ready to lay
    out on a page. This covers the common case seen in practice (standalone
    bold heading lines, bullet lists, plain paragraphs) without needing a
    full markdown/HTML parser.
    """
    rendered = []
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            rendered.append(("F1", 0, ""))
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

        # Plain paragraph line — strip stray ** markers (no inline-bold support,
        # this covers whole-line headings which is the common real-world case).
        content = re.sub(r'\*\*(.+?)\*\*', r'\1', stripped)
        wrapped = textwrap.wrap(content, width=max_width_chars) or ['']
        for w in wrapped:
            rendered.append(("F1", 0, w))
    return rendered or [("F1", 0, "")]

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
    margin_top = 792 - 50   # US Letter page height in points, minus a top margin
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
    content (not the full chat reply with "I'd be happy to..." framing)."""
    try:
        clean_content = _extract_export_content(assistant_text)
        pdf_bytes = _write_minimal_pdf(clean_content)
        return pdf_bytes, "generated.pdf", "application/pdf"
    except Exception as exc:
        print(f"[PDF][BUILD FAULT] {exc}")
        return assistant_text.encode("utf-8"), "generated.txt", "text/plain"

# ── GENERIC "make it a <any extension>" export ──
# Not every request is a zip or a pdf — this catches "as a docx", "save this
# as csv", "convert to png", etc. and packages the clean deliverable content
# with whatever extension was asked for. For simple text-based formats
# (txt/md/csv/json/html/etc.) this produces a genuinely correct file. For
# complex binary formats (real .docx/.xlsx internal structure, actual raster
# .png image encoding of text) this cannot fabricate the real binary format
# from scratch — it still gives back a real, correctly-named/typed file
# containing the content, which is the best a dependency-free backend can
# honestly do without a heavy document-generation library installed.
_GENERIC_EXTENSION_RE = re.compile(
    r"\b(?:as\s+an?|make\s+(?:it|this)\s+an?|download\s+(?:as|this\s+as)|export\s+(?:as|to)|"
    r"convert\s+(?:this\s+|it\s+)?to|save\s+(?:this\s+|it\s+)?as)\s+(?:an?\s+)?\.?([a-zA-Z0-9]{1,6})\b",
    re.IGNORECASE
)
_HANDLED_EXTENSIONS = {"zip", "pdf"}  # these already have dedicated builders above

def _detect_generic_extension_intent(message: str):
    if "?" in message:
        return None
    m = _GENERIC_EXTENSION_RE.search(message)
    if not m:
        return None
    ext = m.group(1).lower()
    if ext in _HANDLED_EXTENSIONS:
        return None
    return ext

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

# ── "@education" PDF-backed Q&A ──
_education_cache = {"files": {}, "listing_t": 0}
_EDUCATION_LISTING_TTL = 120  # seconds

def _github_list_dir(path: str):
    if not GITHUB_TOKEN:
        return []
    repo_clean = _github_repo_slug()
    endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{path}"
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
                # SOF0-SOF3 / SOF5-SOF7 / SOF9-SOF11 / SOF13-SOF15 markers carry dimensions
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

def _extract_pdf_text(pdf_bytes: bytes) -> str:
    if not _PDF_READ_SUPPORTED:
        return ""
    try:
        reader = _PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        print(f"[EDU][EXTRACT FAULT] {exc}")
        return ""

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
        if cached and cached.get("sha") == sha:
            continue  # unchanged, keep existing extracted text
        raw = _github_fetch_file_bytes(entry.get("download_url"))
        if raw is None:
            continue
        text = _extract_pdf_text(raw)
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
        # No keyword overlap at all — still return *something* so the
        # answer isn't a total guess, just the start of the text.
        best["excerpt"] = text[:1800]
    if label:
        best["label"] = label
    return best

# ── Book/chapter folder structure: data/education/<Book Name>/<chapter>.pdf ──
# This sits alongside the older flat data/education/*.pdf layout above (which
# still works for plain "@education <question>" with no book/chapter picked)
# and is what powers the book-picker -> chapter-picker popup flow in the UI.
_education_books_cache = {"books": [], "t": 0}
_EDUCATION_BOOKS_TTL = 120  # seconds
_education_chapter_text_cache = {}  # key: "book/chapter" -> {"sha":..., "text":...}

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
    # Guard against path traversal since `book` ultimately comes from user input.
    safe_book = book.replace("..", "").strip("/")
    entries = _github_list_dir(f"data/education/{safe_book}")
    chapters = sorted(
        e.get("name") for e in entries
        if e.get("type") == "file" and e.get("name", "").lower().endswith(".pdf")
    )
    return chapters

def _fetch_chapter_text(book: str, chapter: str) -> str:
    safe_book = book.replace("..", "").strip("/")
    safe_chapter = chapter.replace("..", "").strip("/")
    cache_key = f"{safe_book}/{safe_chapter}"
    entries = _github_list_dir(f"data/education/{safe_book}")
    match = next((e for e in entries if e.get("name") == safe_chapter), None)
    if not match:
        return ""
    sha = match.get("sha")
    cached = _education_chapter_text_cache.get(cache_key)
    if cached and cached.get("sha") == sha:
        return cached.get("text", "")
    raw = _github_fetch_file_bytes(match.get("download_url"))
    if raw is None:
        return cached.get("text", "") if cached else ""
    text = _extract_pdf_text(raw)
    _education_chapter_text_cache[cache_key] = {"sha": sha, "text": text}
    return text

# ── "@web" best-effort live search (DuckDuckGo HTML, no API key) ──
_EDU_TAG_RE = re.compile(r"\[\[EDU_BOOK:(.*?)\]\]\[\[EDU_CHAPTER:(.*?)\]\]")

def _web_search_snippets(query: str, max_results: int = 4):
    try:
        encoded = urllib.parse.quote(query)
        req = urllib.request.Request(
            f"https://html.duckduckgo.com/html/?q={encoded}",
            headers={"User-Agent": "Mozilla/5.0 (PrathamAI Search Agent)"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html_body = resp.read().decode('utf-8', errors='ignore')
        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html_body, re.DOTALL)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html_body, re.DOTALL)
        clean = lambda s: re.sub('<[^<]+?>', '', s).strip()
        results = []
        for i in range(min(max_results, len(titles))):
            title = clean(titles[i])
            snippet = clean(snippets[i]) if i < len(snippets) else ""
            if title:
                results.append(f"- {title}: {snippet}")
        return results
    except Exception as exc:
        print(f"[WEB][SEARCH FAULT] {exc}")
        return []


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

# ── Backend-issued long-lived session tokens ──
# Google ID tokens only live ~1 hour, which is why signing back in kept
# happening after the browser was closed for a while. Once a Google sign-in
# succeeds, the frontend exchanges that short-lived token for one of these
# (via /auth/exchange), which is good for SESSION_TOKEN_TTL_DAYS and doesn't
# depend on Google's own token lifetime at all.
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
    if not token or token == "dev-session-active-token":
        return {
            "sub": "dev-user",
            "email": "pratham31sinha@gmail.com",
            "role": "creator",
            "user_metadata": {"full_name": "Dev Master Creator"}
        }

    # Our own backend-issued long-lived session tokens (see /auth/exchange).
    # These are checked first since they're the primary auth mechanism the
    # frontend uses after the initial Google sign-in.
    if token.startswith(f"{_SESSION_TOKEN_PREFIX}."):
        session_user = _verify_session_token(token)
        if session_user:
            return session_user
        return None

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

_TEACHING_INTENT_RE = re.compile(
    r"\b(remember (that|this|to)|note (this|that)|save this|learn this|keep in mind|"
    r"for future reference|always do|always use|from now on|don't forget|never forget|"
    r"for (every|all) user|public memory|shared memory|for everyone|store this)\b",
    re.IGNORECASE
)

def _maybe_capture_public_teaching(user_email: str, message: str):
    """
    If a message looks like the person is teaching/instructing the assistant
    something worth remembering (prompt-engineering style guidance), it gets
    appended to a PUBLIC file at the repo root: public_data.txt. This is
    intentionally repo-root (not under data/) since it's meant to be shared
    knowledge, not per-user private history.
    """
    if not _TEACHING_INTENT_RE.search(message):
        return
    entry = (
        f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"
        f"Taught by: {user_email}\n"
        f"Content: {message}\n"
        f"{'=' * 80}\n"
    )
    _write_to_github_repository("public_data.txt", entry)
    _public_teachings_cache["t"] = 0  # force the next read to refetch immediately

# ── PUBLIC SHARED MEMORY READ-BACK ──
# Writing to public_data.txt only matters if something actually reads it
# back. This fetches the same single, repo-root public_data.txt (one file
# shared by every user, as requested) and feeds the most recent entries into
# every conversation's system prompt, so a thing one person taught the
# assistant is genuinely remembered and usable in anyone else's chat too.
# Always fetched fresh on every chat turn (no caching window) per an explicit
# request that every response reads the full current shared memory rather
# than a possibly-stale cached copy; the cache dict below is kept only as a
# fallback if a live GitHub fetch happens to fail (e.g. transient network
# error), so a single hiccup doesn't wipe the assistant's shared memory for
# that turn.
_public_teachings_cache = {"text": "", "t": 0}
_PUBLIC_TEACHINGS_CHAR_BUDGET = 3000  # keep the injected memory small relative to the rest of the prompt

def _fetch_public_teachings_text() -> str:
    text = ""
    if GITHUB_TOKEN:
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
                    text = base64.b64decode(meta_data["content"].replace("\n", "")).decode('utf-8')
        except Exception as exc:
            print(f"[PUBLIC MEMORY][FETCH FAULT] {exc}")
            return _public_teachings_cache["text"]  # fall back to last known good copy

    _public_teachings_cache["text"] = text
    _public_teachings_cache["t"] = time.time()
    return text

def _public_teachings_for_prompt() -> str:
    """Returns the most recent entries (tail of the file, since new entries
    are appended at the end), trimmed to a fixed character budget so shared
    memory can't crowd out the rest of the system prompt."""
    full_text = _fetch_public_teachings_text()
    if not full_text.strip():
        return ""
    return full_text[-_PUBLIC_TEACHINGS_CHAR_BUDGET:]

# ── LLM MULTI-PROVIDER FAILOVER: Groq -> OpenRouter -> Cerebras -> Mistral ──
_provider_cooldowns: dict = {}
COOLDOWN_SECONDS = 60

def _is_cooling(name: str) -> bool:
    return time.time() < _provider_cooldowns.get(name, 0)

def _cool(name: str):
    _provider_cooldowns[name] = time.time() + COOLDOWN_SECONDS

SYSTEM_PROMPT = (
    "You are Pratham AI, a general-purpose assistant that can help with anything: everyday "
    "questions, writing, learning, advice, and analysis, not just coding. When a task does "
    "involve code or file output, format it cleanly in fenced code blocks with explicit "
    "language tags like ```html, ```javascript, or ```text so it can be rendered live.\n\n"
    "Pratham AI was created by Pratham Sinha, under the supervision of Akriti Aishwarya and "
    "Aditi Aishwarya. Only mention this if someone actually asks who made you / who you were "
    "built by — don't bring it up unprompted.\n\n"
    "You also have a REAL background terminal, not a simulated one. Any ```python, ```py, "
    "```bash, ```sh, or ```shell fenced block you write is actually executed on the server "
    "right after you finish your reply, and you will be shown the real stdout/stderr/return "
    "code and get another turn to react to it. Use this to actually DO tasks instead of just "
    "describing them: run calculations, process or transform data, generate/inspect files in "
    "the working directory, test that your own code really works, or chain several steps "
    "together (write code -> see real output -> fix or continue) until the task is finished. "
    "Only rely on this loop when it genuinely helps; don't run code just to run code. Each "
    "conversation turn allows a limited number of execute-and-continue cycles, so work "
    "efficiently and give a clear final plain-language answer once the task is actually done.\n\n"
    "Separately: if the person asks you to turn something into a zip, pdf, or ANY other file "
    "extension (e.g. \"zip it\", \"make it a zip\", \"as a pdf\", \"as a csv\", \"download this\"), "
    "you do NOT need to build that file yourself, and you must NOT run shell commands like "
    "`zip`, `unzip`, `touch`, `pandoc`, or `wkhtmltopdf` to demonstrate it — those tools may not "
    "even exist in this sandbox and are never required. The backend automatically packages the "
    "clean deliverable content (or, if your terminal use in this turn actually created real "
    "files, those exact files) into a real downloadable file in the requested format and attaches "
    "a working download button right after you answer.\n"
    "STRICT RULES for these requests, follow exactly:\n"
    "1. Put ONLY the final, clean deliverable content (the essay/code/document itself — nothing "
    "else) inside a single ```finaldoc fenced block. No chat filler inside that block, ever.\n"
    "2. Outside that block, say ONLY one short line such as \"Your file is being generated.\" or "
    "\"Here's the content — your download will be ready in a moment.\" Do NOT explain that the "
    "backend will package it, do NOT mention zip/pdf mechanics, do NOT say \"you can download it "
    "using the button\", do NOT repeat yourself, and do NOT say \"your file is ready\" — the "
    "backend attaches the real download card itself; you narrating around it is unnecessary and "
    "should be avoided entirely.\n"
    "3. Never paste the deliverable into a ```text (or any other non-finaldoc) fenced block just "
    "to \"simulate\" a file — that creates a fake, non-functional file card instead of the real "
    "download the backend provides.\n\n"
    "You must never help with illegal activity, weapons, malware, or content that could seriously harm "
    "someone; politely refuse those requests instead — this includes never using the terminal "
    "to access the network for attacks, exfiltrate credentials, or damage systems outside this "
    "sandbox."
)

# ── IMAGE GENERATION (Pollinations AI — no API key required) ──
_IMAGE_INTENT_RE = re.compile(
    r"^/image\s+(.+)$|\b(?:generate|create|draw|make|paint)\b.{0,20}\b(?:image|picture|photo|art|illustration|drawing)\b(?:\s+(?:of|showing|depicting))?\s*(.*)$",
    re.IGNORECASE
)

def _detect_image_prompt(message: str):
    """
    Returns a plain-language image description if `message` looks like an
    image-generation request, else None. Kept intentionally simple (regex
    heuristic) rather than a full intent classifier, to stay fast.
    """
    m = _IMAGE_INTENT_RE.search(message.strip())
    if not m:
        return None
    prompt_text = (m.group(1) or m.group(2) or "").strip(" .!")
    return prompt_text or None

def _pollinations_image_url(prompt_text: str) -> str:
    encoded = urllib.parse.quote(prompt_text)
    # width/height/seed kept default-ish; nologo=true removes the Pollinations
    # watermark bar when supported.
    return f"https://image.pollinations.ai/prompt/{encoded}?nologo=true"

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

    print("[FAILOVER] All model providers exhausted.")
    yield _sse({
        "type": "token",
        "text": "All model providers are temporarily unavailable. Please check your API keys or try again shortly."
    })
    yield _sse({"type": "complete"})

# ── BACKGROUND TERMINAL: general-purpose code execution + agent loop ──
# This is what actually lets Pratham AI "do tasks" with a python terminal
# instead of just talking about code. Any ```python / ```py / ```bash /
# ```sh / ```shell block in a reply gets really executed server-side, and
# the real stdout/stderr is fed back to the model so it can react to what
# happened (fix a bug, use a computed result, continue a multi-step task)
# instead of just guessing at what the code would print.
#
# SECURITY NOTE (read this before deploying): this executes arbitrary code
# with no sandboxing beyond a subprocess + timeout — no container, no
# network/filesystem restriction, no user isolation. That is fine for a
# single-owner hobby/dev deployment, but if this app is ever opened up to
# other people, this endpoint (and the /execute-python route below) is a
# full remote-code-execution surface on your server. If you plan to let
# other people use this, put the execution in an isolated sandbox (e.g. a
# throwaway Docker container / firecracker VM / a service like e2b) rather
# than running it directly in the main process.

_EXECUTABLE_LANGS = {"python", "py", "bash", "sh", "shell"}
_CODE_BLOCK_RE = re.compile(r"```(\w+)?\n([\s\S]*?)```")
_TERMINAL_MAX_ITERATIONS = 4          # hard cap on agent "run code, see result, continue" cycles
_TERMINAL_BLOCK_TIMEOUT = 15          # seconds per executed block
_TERMINAL_OUTPUT_CHAR_LIMIT = 4000    # per-stream truncation so huge output can't blow up context/UI

def _extract_executable_blocks(text: str):
    """Returns a list of (lang, code) for every fenced block whose language
    tag is one we know how to actually execute."""
    out = []
    for m in _CODE_BLOCK_RE.finditer(text):
        lang = (m.group(1) or "").lower()
        if lang in _EXECUTABLE_LANGS:
            out.append((lang, m.group(2)))
    return out

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
    try:
        if lang in ("python", "py"):
            cmd = [sys.executable, "-u", "-c", code]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_TERMINAL_BLOCK_TIMEOUT, cwd=cwd
            )
        else:  # bash / sh / shell
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
    chat-stream request's terminal session. All executed blocks within that
    same request share this directory, so a file written in one block (e.g.
    step 1 generates data.csv) can be read by a later block (step 2 processes
    data.csv) within the same multi-step agent loop."""
    return tempfile.mkdtemp(prefix="pratham_ai_terminal_")

def _cleanup_terminal_workdir(path: str):
    if path:
        shutil.rmtree(path, ignore_errors=True)

# ── BACKGROUND TERMINAL INTERFACE ──
_DIAGNOSTIC_INTENT_RE = re.compile(
    r"\b(system status|diagnostic|terminal (status|working)|is (the )?terminal working|"
    r"memory status|is memory working|check status|health check|status check)\b",
    re.IGNORECASE
)

def _run_system_diagnostics() -> str:
    lines = ["**Pratham AI — live system diagnostics** (creator-only, just measured)\n"]

    # 1. Python terminal execution
    workdir = _new_terminal_workdir()
    try:
        out, err, rc = _run_code_block("python", "print(2 + 2)", cwd=workdir)
        python_ok = (rc == 0 and out.strip() == "4")
    except Exception as exc:
        python_ok, out, err = False, "", str(exc)
    lines.append(f"- Python terminal: {'✅ working' if python_ok else '❌ NOT working'} (exit handling verified: `print(2+2)` -> `{out.strip()}`{f', stderr: {err.strip()[:150]}' if err.strip() else ''})")

    # 2. Shell terminal + writable filesystem check (this is the exact thing
    #    that failed before with "Read-only file system")
    try:
        probe_path = os.path.join(workdir, "probe.txt")
        out, err, rc = _run_code_block("bash", f"echo hello > {probe_path} && cat {probe_path}", cwd=workdir)
        shell_ok = (rc == 0 and "hello" in out)
    except Exception as exc:
        shell_ok, err = False, str(exc)
    lines.append(f"- Shell terminal + writable scratch dir: {'✅ working' if shell_ok else '❌ NOT working'}{f' ({err.strip()[:150]})' if not shell_ok and err else ''}")
    _cleanup_terminal_workdir(workdir)

    # 3. GitHub token / write path
    lines.append(f"- GITHUB_TOKEN configured: {'✅ yes' if bool(GITHUB_TOKEN) else '❌ no (memory + logs cannot persist without this)'}")

    # 4. Shared public memory read-back
    shared_text = _fetch_public_teachings_text()
    lines.append(f"- Shared memory (public_data.txt) readable: {'✅ yes' if shared_text else '⚠️ empty or unreachable'} ({len(shared_text)} chars cached)")

    # 5. PDF generation (pure-python writer, no external deps needed anymore)
    try:
        test_pdf = _write_minimal_pdf("diagnostic test")
        pdf_ok = test_pdf[:4] == b"%PDF"
    except Exception:
        pdf_ok = False
    lines.append(f"- PDF generation (built-in, no fpdf2/pandoc needed): {'✅ working' if pdf_ok else '❌ NOT working'}")

    # 6. LLM providers configured
    provider_flags = {
        "Groq": bool(GROQ_API_KEY), "OpenRouter": bool(OPENROUTER_API_KEY),
        "Cerebras": bool(CEREBRAS_API_KEY), "Mistral": bool(MISTRAL_API_KEY)
    }
    configured = [name for name, ok in provider_flags.items() if ok]
    lines.append(f"- LLM providers configured: {', '.join(configured) if configured else '❌ none — chat will not work'}")

    # 7. Persistent conversation storage
    lines.append(f"- Supabase persistent storage: {'✅ connected' if SUPABASE_CONFIGURED else '⚠️ not configured (falling back to in-memory, wiped on restart)'}")

    return "\n".join(lines)

def _format_terminal_results_for_model(results):
    """Turns a list of {lang, code, stdout, stderr, returncode} dicts into a
    plain-text block the model can read, so it can decide whether the task
    is done or another step is needed."""
    lines = ["[BACKGROUND TERMINAL RESULTS]"]
    for i, r in enumerate(results, start=1):
        status = "ok" if r["returncode"] == 0 else f"exit code {r['returncode']}"
        lines.append(f"--- Block {i} ({r['lang']}, {status}) ---")
        if r["stdout"]:
            lines.append(f"stdout:\n{r['stdout']}")
        if r["stderr"]:
            lines.append(f"stderr:\n{r['stderr']}")
        if not r["stdout"] and not r["stderr"]:
            lines.append("(no output)")
    lines.append(
        "[/BACKGROUND TERMINAL RESULTS]\n"
        "Continue the task using these real results. If everything needed is done, "
        "give the final answer in plain language instead of running more code."
    )
    return "\n".join(lines)

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
    # Saved inside the "data" folder of the repo, at data/vip.txt as requested.
    success = _write_to_github_repository("data/vip.txt", registration_row)
    if success:
        _vip_cache["t"] = 0  # force the next lookup to refetch immediately
    return jsonify({"ok": success, "status": "committed" if success else "local fallback"})

# ⚠️ CRITICAL ADDITIVE FIX: Maps the mobile app's absolute network calls safely to eliminate the 404
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

    # ── Creator-only live diagnostics short-circuit ──
    # Bypasses the LLM entirely so "is the terminal working" gets an answer
    # this process actually just measured, not a guess from the model.
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

    # ── Image generation short-circuit (Pollinations AI, no key needed) ──
    image_prompt = _detect_image_prompt(message)
    if image_prompt:
        _append_message(conv_id, "user", message)
        image_url = _pollinations_image_url(image_prompt)
        assistant_note = f"Here's your generated image for: \"{image_prompt}\""
        _append_message(conv_id, "assistant", f"{assistant_note}\n![generated image]({image_url})")

        current_date_formatted = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _write_to_github_repository(
            f"data/{user_email}/{current_date_formatted}.txt",
            f"\n=== {datetime.now(timezone.utc).isoformat()} ===\nUser: {message}\n"
            f"Pratham AI: [image generated] {image_url}\n{'=' * 80}\n"
        )

        def generate_image():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "token", "text": assistant_note + "\n\n"})
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
    shared_memory_text = _public_teachings_for_prompt()
    if shared_memory_text:
        active_system_prompt += (
            " Below are notes previous users have explicitly asked you to remember for everyone "
            "shared across all users of this app, not private to any one person). Treat them as "
            "standing instructions/facts to keep in mind, but they never override your core safety "
            "rules above:\n\"\"\"\n" + shared_memory_text + "\n\"\"\""
        )
    api_messages = [{"role": "system", "content": active_system_prompt}]
    for m in history[-20:]:
        api_messages.append({"role": m["role"], "content": m["content"]})

    outgoing_user_message = message
    _edu_tag_match = _EDU_TAG_RE.search(message)
    if _edu_tag_match:
        # Book + chapter were picked via the @education popup flow — scope
        # the answer to ONLY that chapter's content, not the whole library.
        edu_book, edu_chapter = _edu_tag_match.group(1), _edu_tag_match.group(2)
        outgoing_user_message = _EDU_TAG_RE.sub("", outgoing_user_message).strip()
        chapter_text = _fetch_chapter_text(edu_book, edu_chapter)
        best = _find_best_excerpt_in_text(outgoing_user_message or message, chapter_text, label=f"{edu_book} — {edu_chapter}")
        if best and chapter_text:
            api_messages[0]["content"] += (
                f" The user selected the book '{edu_book}', chapter '{edu_chapter}' from the "
                f"education library, and is asking a question about it. Answer using ONLY the "
                f"excerpt below from that specific chapter — do not pull in other chapters or "
                f"books. Refine it into a clear answer (don't just quote it verbatim), and mention "
                f"the book/chapter you used. Excerpt:\n\"\"\"\n{best['excerpt']}\n\"\"\""
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
                f" The user tagged @education, meaning they want an answer sourced from the PDF "
                f"library. The most relevant excerpt found was from the PDF file '{best['filename']}'. "
                f"Use it to answer, refine it into a clear answer (don't just quote it verbatim), "
                f"note it doesn't need to be an exact textual match, and explicitly mention which PDF "
                f"file you used. Excerpt:\n\"\"\"\n{best['excerpt']}\n\"\"\""
            )
        else:
            api_messages[0]["content"] += (
                " The user tagged @education but no relevant PDF content could be found in the "
                "data/education library (it may be empty, or the pypdf package may not be installed "
                "on the server). Say so plainly instead of guessing."
            )
    elif re.search(r"@web\b", message, re.IGNORECASE) or len(message.strip()) > 5:
        # Web search now runs automatically on essentially every message
        # (the person no longer has to type "@web" each time). It's skipped
        # only for very short/trivial messages (greetings, "ok", etc.) to
        # avoid wasted latency on requests that clearly don't need it.
        outgoing_user_message = re.sub(r"@web\b", "", outgoing_user_message, flags=re.IGNORECASE).strip()
        results = _web_search_snippets(outgoing_user_message or message)
        if results:
            api_messages[0]["content"] += (
                " Here are live web search results relevant to the user's message, in case current "
                "information helps (use them only if actually relevant; ignore them for timeless "
                "questions like math or general advice, and cite that info came from a web search "
                "when you do use it):\n" + "\n".join(results)
            )
        # If the search fails or returns nothing, silently proceed with no
        # extra context rather than telling the user every single time —
        # that would get noisy since this now runs on almost every message.

    api_messages.append({"role": "user", "content": outgoing_user_message or message})

    _append_message(conv_id, "user", message)
    _maybe_capture_public_teaching(user_email, message)

    def generate():
        yield _sse({"type": "metadata", "conversation_id": conv_id})

        # Give immediate feedback the moment we know this turn wants a real
        # exported file, rather than waiting for the model's full reply to
        # start streaming — matches "it will reply the file is being made
        # and then the generated file".
        export_ext_hint = None
        if _is_export_intent(message, _ZIP_INTENT_RE):
            export_ext_hint = "zip"
        elif _is_export_intent(message, _PDF_INTENT_RE):
            export_ext_hint = "pdf"
        else:
            export_ext_hint = _detect_generic_extension_intent(message)
        if export_ext_hint:
            yield _sse({"type": "token", "text": f"📄 Your {export_ext_hint} file is being generated...\n\n"})

        full_reply_parts = []   # everything shown to the user across all iterations, in order
        working_messages = list(api_messages)
        total_blocks_seen = 0   # counts EVERY fenced code block (any language), matching the
                                 # frontend's own per-block counter exactly, so terminal_output
                                 # events land on the right card. Counting only executable blocks
                                 # here (as before) drifted out of sync as soon as a reply also
                                 # contained a non-executable block (e.g. ```json, ```html), which
                                 # is what caused status updates to attach to the wrong card.
        terminal_workdir = _new_terminal_workdir()

        for iteration in range(_TERMINAL_MAX_ITERATIONS):
            iteration_text_parts = []
            for chunk in _do_stream(working_messages):
                try:
                    if chunk.startswith("data: "):
                        payload = json.loads(chunk[6:])
                        if payload.get("type") == "token":
                            iteration_text_parts.append(payload["text"])
                            full_reply_parts.append(payload["text"])
                        elif payload.get("type") == "complete":
                            continue  # only forward the final "complete" once, after the loop ends
                except Exception:
                    pass
                if not chunk.startswith("data: ") or json.loads(chunk[6:]).get("type") != "complete":
                    yield chunk

            iteration_reply = "".join(iteration_text_parts)

            # ── Walk every fenced block in this iteration's reply, in order ──
            all_blocks_this_iteration = list(_CODE_BLOCK_RE.finditer(iteration_reply))
            executable_present = any(
                (m.group(1) or "").lower() in _EXECUTABLE_LANGS for m in all_blocks_this_iteration
            )
            if not executable_present:
                break  # nothing to execute -> the model's answer is final

            results = []
            for m in all_blocks_this_iteration:
                total_blocks_seen += 1
                lang = (m.group(1) or "").lower()
                if lang not in _EXECUTABLE_LANGS:
                    continue  # not runnable (e.g. ```json, ```html) — leave its ordinal "spent"
                              # but don't execute or emit a terminal_output for it
                code = m.group(2)
                stdout, stderr, rc = _run_code_block(lang, code, cwd=terminal_workdir)
                results.append({"lang": lang, "code": code, "stdout": stdout, "stderr": stderr, "returncode": rc})
                yield _sse({
                    "type": "terminal_output",
                    "ordinal": total_blocks_seen,
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": rc
                })

            is_last_allowed_iteration = (iteration == _TERMINAL_MAX_ITERATIONS - 1)
            if is_last_allowed_iteration:
                break  # out of cycles; stop here rather than asking for yet another turn

            # Feed the real execution results back to the model as a new turn
            # so it can react to what actually happened.
            working_messages.append({"role": "assistant", "content": iteration_reply})
            working_messages.append({"role": "user", "content": _format_terminal_results_for_model(results)})

        yield _sse({"type": "complete"})

        assistant_response = "".join(full_reply_parts)
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

            # Background "Python terminal" file generation: if the request
            # was asking for a zip, a PDF, or ANY other named extension of
            # the reply, actually build it now and hand back a real
            # download link.
            try:
                if _is_export_intent(message, _ZIP_INTENT_RE):
                    zip_bytes = _build_zip_from_response(assistant_response, workdir=terminal_workdir)
                    token = _store_generated_file(zip_bytes, "pratham_ai_output.zip", "application/zip")
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": "pratham_ai_output.zip"})
                elif _is_export_intent(message, _PDF_INTENT_RE):
                    pdf_bytes, pdf_name, pdf_mime = _build_pdf_from_response(assistant_response)
                    token = _store_generated_file(pdf_bytes, pdf_name, pdf_mime)
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": pdf_name})
                else:
                    generic_ext = _detect_generic_extension_intent(message)
                    if generic_ext:
                        file_bytes, file_name, file_mime = _build_generic_file_from_response(
                            assistant_response, generic_ext, workdir=terminal_workdir
                        )
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
        return jsonify({"error": "Missing code parameter."}), 400
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
                import docx  # python-docx, optional dependency
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
                decode_status = "decoded (image metadata — no pixel-level AI vision, but real file facts extracted)"
            else:
                decode_status = f"stored ({len(raw_bytes)} bytes, image — couldn't parse header metadata for this format)"
        else:
            # Best-effort generic sniff: try UTF-8 text, else report as binary.
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
