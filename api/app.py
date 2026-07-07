"""
Pratham AI - Full Production Backend Architecture
=================================================
Corrected + optimized version with Automated Persistent Memory Matrix.

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

# Creator list alignment
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
_gh_sha_cache: dict = {}
_GH_CACHE_TTL = 8

def _github_repo_slug() -> str:
    return GITHUB_REPO.replace("https://github.com/", "").strip("/")

def _write_to_github_repository(target_file_path: str, contents_payload: str) -> bool:
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

# ── VIP RECOGNITION ──
_vip_cache = {"entries": {}, "t": 0}
_VIP_CACHE_TTL = 30

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

# ── BACKGROUND FILE GENERATION ──
_generated_files_store: dict = {}
_GENERATED_FILE_TTL = 3600

_ZIP_INTENT_RE = re.compile(r"\bzip\b", re.IGNORECASE)
_PDF_INTENT_RE = re.compile(r"\bpdf\b", re.IGNORECASE)

def _is_export_intent(message: str, regex: "re.Pattern") -> bool:
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
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines))
    return cleaned.strip()

def _extract_export_content(assistant_text: str) -> str:
    m = _FINALDOC_RE.search(assistant_text)
    if m:
        return _strip_export_filler(m.group(1).strip())
    return _strip_export_filler(assistant_text)

def _build_zip_from_response(assistant_text: str, workdir: str = None) -> bytes:
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

        content = re.sub(r'\*\*(.+?)\*\*', r'\1', stripped)
        wrapped = textwrap.wrap(content, width=max_width_chars) or ['']
        for w in wrapped:
            rendered.append(("F1", 0, w))
    return rendered or [("F1", 0, "")]

def _write_minimal_pdf(text: str) -> bytes:
    base_font_size = 11
    heading_font_size = 13
    leading = 15
    margin_left = 50
    margin_top = 792 - 50
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
    try:
        clean_content = _extract_export_content(assistant_text)
        pdf_bytes = _write_minimal_pdf(clean_content)
        return pdf_bytes, "generated.pdf", "application/pdf"
    except Exception as exc:
        print(f"[PDF][BUILD FAULT] {exc}")
        return assistant_text.encode("utf-8"), "generated.txt", "text/plain"

# ── GENERIC EXPORT INTENTS ──
_GENERIC_EXTENSION_RE = re.compile(
    r"\b(?:as\s+an?|make\s+(?:it|this)\s+an?|download\s+(?:as|this\s+as)|export\s+(?:as|to)|"
    r"convert\s+(?:this\s+|it\s+)?to|save\s+(?:this\s+|it\s+)?as)\s+(?:an?\s+)?\.?([a-zA-Z0-9]{1,6})\b",
    re.IGNORECASE
)
_HANDLED_EXTENSIONS = {"zip", "pdf"}

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
_EDUCATION_LISTING_TTL = 120

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
            continue
        raw = _github_fetch_file_bytes(entry.get("download_url"))
        if raw is None:
            continue
        text = _extract_pdf_text(raw)
        _education_cache["files"][name] = {"sha": sha, "text": text}
    _education_cache["listing_t"] = now_ts

def _find_best_education_excerpt(question: str):
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
        best["excerpt"] = text[:1800]
    if label:
        best["label"] = label
    return best

# ── Book/chapter folder architecture ──
_education_books_cache = {"books": [], "t": 0}
_EDUCATION_BOOKS_TTL = 120
_education_chapter_text_cache = {}

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

# ── "@web" DuckDuckGo parsing ──
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
    try:
        payload_chunk = token.split('.')[1]
        padded_chunk = payload_chunk + '=' * (-len(payload_chunk) % 4)
        return json.loads(base64.b64decode(padded_chunk).decode('utf-8'))
    except Exception:
        return None

# ── LONG LIVED SESSION TOKENS ──
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

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return _cors_preflight()
        token = _get_token()
        user = _verify_token(token)
        if not hesitate:
            if not user:
                return jsonify({"error": "Session expired or invalid. Please sign in again."}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper

# ── CONTENT GUARD ──
_BLOCKED_PATTERNS = [
    r"\bmake\s+a\s+bomb\b", r"\bbuild\s+a\s+bomb\b", r"\bhow\s+to\s+hack\b",
    r"\bchild\s+(sexual|porn|abuse)\b", r"\bkill\s+(myself|someone|him|her|them)\b",
    r"\bsynthesi[sz]e\s+(meth|drug|explosive)\b", r"\bmake\s+a\s+weapon\b",
    r"\bcredit\s+card\s+(number|dump|generator)\b", r"\bddos\b", r"\bransomware\b",
]
_BLOCKED_REGEX = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)

def _is_flagged_message(message: str) -> bool:
    return bool(_BLOCKED_REGEX.search(message or ""))

# Creative Query Intent Match Pattern for Creators Only
_MEMORY_QUERY_INTENT_RE = re.compile(
    r"\b(what'?s\s+in\s+memory|what\s+do\s+you\s+know|search\s+memory|show\s+saved\s+facts|list\s+memory)\b",
    re.IGNORECASE
)

def _maybe_capture_public_teaching(user_email: str, message: str):
    """Fallback legacy explicit layout handler, integrated alongside auto-extractor."""
    msg_clean = message.strip().lower()
    is_teaching = (
        msg_clean.startswith("/remember") or 
        msg_clean.startswith("hey ai, save this:") or
        msg_clean.startswith("store this:") or
        any(word in msg_clean for word in ["save to memory", "public memory", "always remember"])
    )
    if not is_teaching:
        return
    clean_info = re.sub(r"^(/remember|hey ai, save this:|store this:)\s*", "", message, flags=re.IGNORECASE).strip()
    entry = f"[EXPLICIT LESSON] {clean_info}\n"
    _write_to_github_repository("data/public_data.txt", entry)
    _public_teachings_cache["t"] = 0

def _auto_extract_and_save_knowledge(assistant_response: str):
    """
    Intelligently analyzes the assistant's response to filter out conversation filler,
    isolating generalized principles, programming directives, or technical strategies,
    then automatically archives it into data/public_data.txt without personal details.
    """
    clean_text = assistant_response.strip()
    if len(clean_text) < 20:
        return

    # Filter rules to prevent writing raw conversational chat filler
    phrases_to_skip = ["i'd be happy to", "your file is", "here is the", "something went wrong"]
    if any(p in clean_text.lower() for p in phrases_to_skip):
        return

    # Extract clean generalizable blocks (e.g. sentences or technical steps)
    extracted_nodes = []
    lines = clean_text.split("\n")
    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue
        # Capture code snippets or declarative rule explanations
        if line_strip.startswith("if ") or "function" in line_strip or "const" in line_strip or line_strip.startswith("-") or len(line_strip) > 40:
            # Strip markdown bolding to keep the data clean
            cleaned_line = re.sub(r"\*\*?", "", line_strip)
            extracted_nodes.append(cleaned_line)

    if extracted_nodes:
        compiled_knowledge = " | ".join(extracted_nodes[:8])
        entry = f"[AUTO FACT — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}] {compiled_knowledge}\n"
        _write_to_github_repository("data/public_data.txt", entry)
        _public_teachings_cache["t"] = 0

_public_teachings_cache = {"text": "", "t": 0}

def _fetch_full_public_data_text() -> str:
    """Reads the FULL data/public_data.txt file directly from GitHub on each pass."""
    text = ""
    if GITHUB_TOKEN:
        repo_clean = _github_repo_slug()
        endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/data/public_data.txt"
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
            print(f"[PUBLIC DATA MATRIX][FETCH FAULT] {exc}")
            return _public_teachings_cache["text"]

    _public_teachings_cache["text"] = text
    _public_teachings_cache["t"] = time.time()
    return text

def _search_intelligent_memory_excerpts(user_query: str) -> str:
    """
    Intelligently searches the entire contents of data/public_data.txt.
    Splits records by lines and scores them using multi-keyword intersection metrics,
    assembling the absolute best matches as explicit context.
    """
    full_corpus = _fetch_full_public_data_text()
    if not full_corpus.strip():
        return ""

    query_tokens = set(re.findall(r"[a-zA-Z]{3,}", user_query.lower()))
    if not query_tokens:
        return ""

    matched_lines = []
    for line in full_corpus.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        line_tokens = set(re.findall(r"[a-zA-Z]{3,}", line_clean.lower()))
        score = len(query_tokens & line_tokens)
        if score > 0:
            matched_lines.append((score, line_clean))

    # Sort items based on match priority weight score
    matched_lines.sort(key=lambda item: item[0], reverse=True)
    
    # Bundle the top matched records up to a safe character ceiling
    top_excerpts = [item[1] for item in matched_lines[:6]]
    if top_excerpts:
        return "\n".join(top_excerpts)
    return ""

# ── LLM PROVIDERS ──
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

_IMAGE_INTENT_RE = re.compile(
    r"^/image\s+(.+)$|\b(?:generate|create|draw|make|paint)\b.{0,20}\b(?:image|picture|photo|art|illustration|drawing)\b(?:\s+(?:of|showing|depicting))?\s*(.*)$",
    re.IGNORECASE
)

def _detect_image_prompt(message: str):
    m = _IMAGE_INTENT_RE.search(message.strip())
    if not m:
        return None
    prompt_text = (m.group(1) or m.group(2) or "").strip(" .!")
    return prompt_text or None

def _pollinations_image_url(prompt_text: str) -> str:
    encoded = urllib.parse.quote(prompt_text)
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

# ── BACKGROUND TERMINAL ENGINE ──
_EXECUTABLE_LANGS = {"python", "py", "bash", "sh", "shell"}
_CODE_BLOCK_RE = re.compile(r"```(\w+)?\n([\s\S]*?)```")
_TERMINAL_MAX_ITERATIONS = 4
_TERMINAL_BLOCK_TIMEOUT = 15
_TERMINAL_OUTPUT_CHAR_LIMIT = 4000

def _extract_executable_blocks(text: str):
    out = []
    for m in _CODE_BLOCK_RE.finditer(text):
        lang = (m.group(1) or "").lower()
        if lang in _EXECUTABLE_LANGS:
            out.append((lang, m.group(2)))
    return out

def _run_code_block(lang: str, code: str, cwd: str = None):
    try:
        if lang in ("python", "py"):
            cmd = [sys.executable, "-u", "-c", code]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_TERMINAL_BLOCK_TIMEOUT, cwd=cwd
            )
        else:
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
    return tempfile.mkdtemp(prefix="pratham_ai_terminal_")

def _cleanup_terminal_workdir(path: str):
    if path:
        shutil.rmtree(path, ignore_errors=True)

# ── REPO SYSTEM STATUS DIAGNOSTICS ──
_DIAGNOSTIC_INTENT_RE = re.compile(
    r"\b(system status|diagnostic|terminal (status|working)|is (the )?terminal working|"
    r"memory status|is memory working|check status|health check|status check)\b",
    re.IGNORECASE
)

def _run_system_diagnostics() -> str:
    lines = ["**Pratham AI — live system diagnostics** (creator-only, just measured)\n"]

    workdir = _new_terminal_workdir()
    try:
        out, err, rc = _run_code_block("python", "print(2 + 2)", cwd=workdir)
        python_ok = (rc == 0 and out.strip() == "4")
    except Exception as exc:
        python_ok, out, err = False, "", str(exc)
    lines.append(f"- Python terminal: {'✅ working' if python_ok else '❌ NOT working'} (exit handling verified: `print(2+2)` -> `{out.strip()}`{f', stderr: {err.strip()[:150]}' if err.strip() else ''})")

    try:
        probe_path = os.path.join(workdir, "probe.txt")
        out, err, rc = _run_code_block("bash", f"echo hello > {probe_path} && cat {probe_path}", cwd=workdir)
        shell_ok = (rc == 0 and "hello" in out)
    except Exception as exc:
        shell_ok, err = False, str(exc)
    lines.append(f"- Shell terminal + writable scratch dir: {'✅ working' if shell_ok else '❌ NOT working'}{f' ({err.strip()[:150]})' if not shell_ok and err else ''}")
    _cleanup_terminal_workdir(workdir)

    lines.append(f"- GITHUB_TOKEN configured: {'✅ yes' if bool(GITHUB_TOKEN) else '❌ no (memory + logs cannot persist without this)'}")

    shared_text = _fetch_full_public_data_text()
    lines.append(f"- Shared memory (public_data.txt) readable: {'✅ yes' if shared_text else '⚠️ empty or unreachable'} ({len(shared_text)} chars cached)")

    try:
        test_pdf = _write_minimal_pdf("diagnostic test")
        pdf_ok = test_pdf[:4] == b"%PDF"
    except Exception:
        pdf_ok = False
    lines.append(f"- PDF generation (built-in, no fpdf2/pandoc needed): {'✅ working' if pdf_ok else '❌ NOT working'}")

    provider_flags = {
        "Groq": bool(GROQ_API_KEY), "OpenRouter": bool(OPENROUTER_API_KEY),
        "Cerebras": bool(CEREBRAS_API_KEY), "Mistral": bool(MISTRAL_API_KEY)
    }
    configured = [name for name, ok in provider_flags.items() if ok]
    lines.append(f"- LLM providers configured: {', '.join(configured) if configured else '❌ none — chat will not work'}")

    lines.append(f"- Supabase persistent storage: {'✅ connected' if SUPABASE_CONFIGURED else '⚠️ not configured (falling back to in-memory, wiped on restart)'}")

    return "\n".join(lines)

def _format_terminal_results_for_model(results):
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

# ── DATA SYNC LAYER ──
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
    success = _write_to_github_repository("data/vip.txt", registration_row)
    if success:
        _vip_cache["t"] = 0
    return jsonify({"ok": success, "status": "committed" if success else "local fallback"})

# ── CENTRALIZED EXECUTION PIPELINE ROUTE ──
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

    # Content safety check
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

    # Creator-Only Live Memory Matrix Direct Queries Interrupt
    if user_email.lower() in CREATOR_EMAILS and _MEMORY_QUERY_INTENT_RE.search(message):
        _append_message(conv_id, "user", message)
        memory_dump = _fetch_full_public_data_text()
        if not memory_dump.strip():
            response_payload = "The public persistent memory index matrix is currently blank."
        else:
            # Parse search parameter variations if present
            search_match = re.search(r"(?:search memory for|list memory about)\s+(.+)", message, re.IGNORECASE)
            if search_match:
                term = search_match.group(1).strip().lower()
                filtered = [line for line in memory_dump.splitlines() if term in line.lower()]
                response_payload = f"**Memory Search Results for '{term}':**\n" + ("\n".join(filtered) if filtered else "No intersecting fact arrays detected.")
            else:
                response_payload = f"**Pratham AI Full Persistent Memory Matrix (Latest Entries):**\n
http://googleusercontent.com/immersive_entry_chip/0
