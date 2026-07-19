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

Third pass — direct file-creation channel (nothing above was removed):
 14. The model can now emit ```createfile:<filename.ext>\n<content>\n```
     fenced blocks to directly write a real file into the same background
     terminal working directory used for code execution — no need to write
     python/bash just to produce a file. Every such file is registered in
     the conversation's file registry (same one the Workbench "Files" tab
     already reads from) and immediately gets a real, downloadable
     file-ready card, exactly like a zip/pdf export does.
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
import difflib
import shlex
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

# ── ADDITIONAL PDF TEXT EXTRACTORS FOR COMPLEX SCRIPTS (Devanagari/Sanskrit/Hindi) ──
# pypdf/PyPDF2 use a fairly naive text-extraction algorithm that frequently
# mangles or drops text in scripts with conjuncts/ligatures (Devanagari being
# a textbook case) — this is a known, well-documented limitation of that
# library, not something fixable with a regex. PyMuPDF (fitz) and
# pdfplumber both use different, generally much more reliable extraction
# approaches for exactly this kind of PDF. Both are OPTIONAL — if neither is
# installed, extraction silently falls back to pypdf/PyPDF2 as before. To
# actually get good Sanskrit/Hindi extraction, add ONE of these to your
# requirements.txt (PyMuPDF is the strongest for Devanagari in practice):
#   PyMuPDF   (import name: fitz)
#   pdfplumber
try:
    import fitz as _fitz  # PyMuPDF
    _FITZ_SUPPORTED = True
except ImportError:
    _FITZ_SUPPORTED = False

try:
    import pdfplumber as _pdfplumber
    _PDFPLUMBER_SUPPORTED = True
except ImportError:
    _PDFPLUMBER_SUPPORTED = False

# ── OCR FALLBACK for PDFs with no real text layer (common for scanned or
# oddly-encoded Devanagari PDFs where fitz/pdfplumber/pypdf all correctly
# report "no extractable text" because there genuinely isn't any — the
# glyphs are images, not text). Both OPTIONAL: if pytesseract isn't
# installed, this fallback is simply skipped and the existing "could not
# be loaded" message still applies (no regression). Add BOTH to
# requirements.txt to enable OCR: pytesseract, and the tesseract-ocr binary
# itself needs to be present on the host (apt install tesseract-ocr
# tesseract-ocr-hin for Hindi/Devanagari) — pytesseract only wraps it.
try:
    import pytesseract as _pytesseract
    _OCR_SUPPORTED = _FITZ_SUPPORTED  # OCR path renders pages via fitz, so needs it too
except ImportError:
    _OCR_SUPPORTED = False

def _extract_pdf_text_with_ocr(pdf_bytes: bytes, lang: str = "hin+eng") -> str:
    """Last-resort extractor: rasterizes each page (via PyMuPDF) and runs
    Tesseract OCR on it. Only used when every direct text extractor above
    returned empty/near-empty — this is what actually handles scanned or
    image-only Devanagari PDFs that have no real text layer at all, which
    is a different problem than pypdf's ligature-mangling and can't be
    fixed by switching extractors, only by OCR."""
    if not _OCR_SUPPORTED:
        return ""
    try:
        doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            from PIL import Image
            img = Image.open(io.BytesIO(img_bytes))
            parts.append(_pytesseract.image_to_string(img, lang=lang))
        return "\n".join(parts).strip()
    except Exception as exc:
        print(f"[EDU][OCR FAULT] {exc}")
        return ""

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

# ── MULTIPLE GROQ API KEYS ──
# Groq supports adding several keys (e.g. GROQ_API_KEY="key1,key2,key3" or
# separate GROQ_API_KEY_2 / GROQ_API_KEY_3 / GROQ_API_KEY_4 env vars) so the
# effective rate limit is the SUM of all keys' limits, not just one. Each
# key gets its own independent cooldown, so if one key hits its per-minute
# limit the next one is tried immediately instead of failing over all the
# way down to OpenRouter/Cerebras/Mistral.
def _collect_groq_keys() -> list:
    keys = []
    primary = os.environ.get("GROQ_API_KEY", "").strip()
    if primary:
        # Support comma-separated keys in the single GROQ_API_KEY var too.
        keys.extend([k.strip() for k in primary.split(",") if k.strip()])
    for suffix in range(2, 11):  # GROQ_API_KEY_2 .. GROQ_API_KEY_10
        extra = os.environ.get(f"GROQ_API_KEY_{suffix}", "").strip()
        if extra:
            keys.append(extra)
    # De-duplicate while preserving order.
    seen = set()
    unique_keys = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            unique_keys.append(k)
    return unique_keys

GROQ_API_KEYS = _collect_groq_keys()
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

    IMPORTANT FIX (this was the cause of "saving replaces old content
    instead of appending"): GitHub's Contents API only inlines the file's
    `content` field for files under ~1MB. Once a growing file like
    data/public_data.txt crosses that size, the API keeps returning a valid
    `sha` but a null/empty `content` field — the old code treated that as
    "existing content is empty" and PUT the file with ONLY the new entry,
    silently wiping everything previously saved. Now, whenever `content` is
    missing/empty but the file's reported `size` is greater than 0 (i.e. it
    genuinely has content GitHub just didn't inline), the real content is
    fetched via the item's own `download_url` instead, so appends are always
    appends — regardless of how large the file has grown.
    """
    if not GITHUB_TOKEN:
        return False

    repo_clean = _github_repo_slug()
    encoded_target_path = "/".join(urllib.parse.quote(segment, safe="") for segment in target_file_path.split("/") if segment)
    endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{encoded_target_path}"

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
                elif meta_data.get("size", 0) > 0 and meta_data.get("download_url"):
                    # File exists and genuinely has content, but the Contents
                    # API didn't inline it (large-file case) — fetch the real
                    # bytes directly instead of silently treating it as empty.
                    try:
                        raw_req = urllib.request.Request(
                            meta_data["download_url"],
                            headers={"Authorization": f"token {GITHUB_TOKEN}"}
                        )
                        with urllib.request.urlopen(raw_req, timeout=20) as raw_resp:
                            existing_content = raw_resp.read().decode('utf-8', errors='replace')
                    except Exception as raw_exc:
                        print(f"[GITHUB][LARGE-FILE FETCH FAULT] {target_file_path}: {raw_exc}")
                        # We could not confirm the real existing content — refuse to
                        # write at all rather than risk overwriting it with a PUT
                        # that only contains the new entry.
                        return False
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
                            "relationship": parts.get("relation", ""),
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

def _build_zip_from_response(assistant_text: str, workdir: str = None, deliverable_name: str = "content.txt") -> bytes:
    """
    Fix for the "zip contains the wrong content" bug: the clean deliverable
    (the ```finaldoc block, or the filler-stripped full reply — see
    `_extract_export_content`) is ALWAYS written into the zip under
    `deliverable_name` first, since that's the thing the person actually
    asked for. Any REAL files the background terminal created in `workdir`
    during this same request (via python/bash execution or a ```createfile:
    block) are added alongside as extras, not as a silent replacement — so a
    request like "write an essay, zip it" reliably gets the essay in the
    zip, even if unrelated scratch files exist in the terminal's workdir
    from something else the model did in the same turn.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        deliverable_text = _extract_export_content(assistant_text)
        zf.writestr(deliverable_name, deliverable_text)

        if workdir and os.path.isdir(workdir):
            for root, _dirs, files in os.walk(workdir):
                for fname in files:
                    full_path = os.path.join(root, fname)
                    arcname = os.path.relpath(full_path, workdir)
                    try:
                        zf.write(full_path, arcname)
                    except Exception:
                        continue
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

# ── CONTENT-AWARE EXPORT FILENAME ──
# Fixes "zip file has the wrong name" — previously every zip was named the
# generic "pratham_ai_output.zip" regardless of what was actually inside it.
# This derives a real topic-based filename from the user's own request (e.g.
# "write an essay on climate change and zip it" -> "essay_on_climate_change.zip"),
# falling back to a title line inside the deliverable content itself, and
# only using a generic name as a last resort.
_EXPORT_STOPWORDS = {
    "write", "make", "made", "create", "created", "generate", "generated", "give", "give me",
    "download", "convert", "save", "export", "please", "pls", "plz", "can", "you", "the",
    "a", "an", "this", "it", "into", "to", "as", "in", "on", "of", "for", "me", "and",
    "file", "files", "zip", "pdf", "format", "form", "output", "document", "doc", "now",
    "want", "need", "my", "with", "using", "having",
}

def _derive_export_basename(message: str, deliverable_text: str = "") -> str:
    """Best-effort topic slug for export filenames. Tries, in order:
    1. A short markdown heading (# Title / **Title**) at the top of the
       cleaned deliverable content, since the model is asked to lead with
       a clear title for exported documents.
    2. The user's own request message with command/format stopwords
       stripped out (so "write an essay on the french revolution as a pdf"
       becomes "essay-french-revolution").
    3. A generic "pratham_ai_output" fallback if neither yields anything
       usable.
    """
    # 1. Try a heading/title line from the deliverable itself.
    if deliverable_text:
        first_lines = deliverable_text.strip().split("\n")[:3]
        for line in first_lines:
            stripped = line.strip().lstrip("#").strip()
            stripped = re.sub(r'^\*\*(.+?)\*\*$', r'\1', stripped).strip()
            if 3 <= len(stripped) <= 80 and not stripped.lower().startswith(("here", "sure", "okay", "i'd")):
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", stripped).strip("-").lower()
                if slug:
                    return slug[:60]

    # 2. Fall back to the user's request text, stopwords stripped.
    words = re.findall(r"[a-zA-Z0-9]+", message.lower())
    meaningful = [w for w in words if w not in _EXPORT_STOPWORDS and len(w) > 1]
    if meaningful:
        slug = "-".join(meaningful[:8])
        if slug:
            return slug[:60]

    # 3. Last resort.
    return "pratham_ai_output"

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


_STOPWORDS = {"a","an","the","of","on","in","to","for","and","or","about","write","make","create",
              "please","me","my","this","that","as","zip","pdf","file","download","essay","report",
              "document","it","into","generate","draft","short","long","give"}

def _derive_export_filename(user_message: str, ext: str, fallback_content: str = "") -> str:
    """
    Builds a human-meaningful filename (e.g. "climate_change_essay.zip" instead
    of a generic "pratham_ai_output.zip") from the actual topic of the
    request. Strips common command/stopwords ("write", "essay", "as a zip",
    etc.) and keeps the meaningful nouns, falling back to the first line of
    the generated content, then to a generic name only as a last resort.
    """
    def slugify(words, max_words=6):
        cleaned = [w.lower() for w in words if w.lower() not in _STOPWORDS and len(w) > 1]
        cleaned = cleaned[:max_words]
        slug = "_".join(re.sub(r"[^a-zA-Z0-9]", "", w) for w in cleaned if re.sub(r"[^a-zA-Z0-9]", "", w))
        return slug

    words = re.findall(r"[a-zA-Z0-9']+", user_message)
    slug = slugify(words)

    if not slug and fallback_content:
        first_line = fallback_content.strip().split("\n", 1)[0]
        first_line = re.sub(r'^\*\*|\*\*$', '', first_line.strip())
        words = re.findall(r"[a-zA-Z0-9']+", first_line)
        slug = slugify(words)

    if not slug:
        slug = "pratham_ai_output"

    return f"{slug}.{ext}"

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
    """
    IMPORTANT FIX: folder/file names with spaces (e.g. "Social Science",
    "Chapter 1 Understanding Civilisation.pdf") were being inserted into the
    GitHub API URL completely raw. urllib does NOT auto-encode spaces (or
    other special characters) in a URL string, so a request like
    ".../contents/data/education/Social Science" was malformed and GitHub
    quietly returned nothing usable — which is exactly why book listing
    worked (folder names without spaces resolved fine) but chapter listing
    for "Social Science" came back empty even though the files were really
    there. Each path segment is now percent-encoded individually (keeping
    the "/" separators intact) before the request is made.
    """
    if not GITHUB_TOKEN:
        return []
    repo_clean = _github_repo_slug()
    encoded_path = "/".join(urllib.parse.quote(segment, safe="") for segment in path.split("/") if segment)
    endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{encoded_path}"
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

# ── DEEP IMAGE ANALYSIS VIA THE REAL BACKGROUND TERMINAL ──
# The lightweight header sniff above (_extract_image_metadata) only reads a
# few fixed byte offsets. This instead genuinely writes the uploaded image
# to the same background terminal workdir used for code execution and runs
# a real Python script against it — walking every PNG chunk (IHDR, gAMA,
# pHYs, tEXt/iTXt/zTXt text metadata, ICC profile presence, interlace mode,
# etc.), or using Pillow for full info (mode, format, all `.info` metadata,
# EXIF for JPEGs) when the optional `Pillow` package is installed on the
# server. This is "send the image to the terminal" in the literal sense —
# a subprocess actually opens and parses the real file — not just a
# transcription/description of what the picture shows (that still needs a
# vision-capable model, which isn't wired up here).
_IMAGE_DEEP_ANALYSIS_SCRIPT = r"""
import sys, os, struct, zlib

path = sys.argv[1]
size_bytes = os.path.getsize(path)
print(f"File size: {size_bytes} bytes ({size_bytes/1024:.1f} KB)")

# Prefer Pillow for the richest possible real info, if it's installed.
try:
    from PIL import Image, ExifTags
    with Image.open(path) as img:
        print(f"Format: {img.format}")
        print(f"Mode: {img.mode}")
        print(f"Size: {img.width}x{img.height}")
        print(f"Has transparency info: {'transparency' in img.info}")
        if img.info:
            for k, v in img.info.items():
                sval = str(v)
                if len(sval) > 200:
                    sval = sval[:200] + "...(truncated)"
                print(f"info[{k}]: {sval}")
        exif = getattr(img, "_getexif", lambda: None)()
        if exif:
            print("EXIF tags found:")
            for tag_id, value in exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, tag_id)
                sval = str(value)
                if len(sval) > 150:
                    sval = sval[:150] + "...(truncated)"
                print(f"  {tag_name}: {sval}")
        else:
            print("No EXIF data found.")
    print("(Pillow was used for this analysis.)")
    sys.exit(0)
except ImportError:
    print("(Pillow not installed on server — falling back to manual byte-level parsing.)")
except Exception as e:
    print(f"(Pillow analysis failed: {e} — falling back to manual byte-level parsing.)")

with open(path, "rb") as f:
    data = f.read()

if data[:8] == b"\x89PNG\r\n\x1a\n":
    print("Detected: PNG")
    pos = 8
    chunk_types_seen = []
    while pos < len(data) - 8:
        length = struct.unpack(">I", data[pos:pos+4])[0]
        ctype = data[pos+4:pos+8].decode("ascii", errors="replace")
        chunk_types_seen.append(ctype)
        chunk_data = data[pos+8:pos+8+length]
        if ctype == "IHDR" and len(chunk_data) >= 13:
            width, height, bit_depth, color_type, compression, filter_m, interlace = struct.unpack(">IIBBBBB", chunk_data[:13])
            color_map = {0: "grayscale", 2: "RGB", 3: "palette", 4: "grayscale+alpha", 6: "RGBA"}
            print(f"IHDR: {width}x{height}, {bit_depth}-bit {color_map.get(color_type, color_type)}, "
                  f"interlace={'Adam7' if interlace else 'none'}")
        elif ctype == "gAMA" and len(chunk_data) >= 4:
            gamma = struct.unpack(">I", chunk_data[:4])[0] / 100000
            print(f"gAMA (gamma): {gamma}")
        elif ctype == "pHYs" and len(chunk_data) >= 9:
            ppux, ppuy, unit = struct.unpack(">IIB", chunk_data[:9])
            print(f"pHYs (pixel density): {ppux}x{ppuy} per unit, unit={'meter' if unit == 1 else 'unknown'}")
        elif ctype in ("tEXt", "iTXt", "zTXt"):
            try:
                if ctype == "tEXt":
                    key, _, val = chunk_data.partition(b"\x00")
                    print(f"{ctype} metadata: {key.decode(errors='replace')} = {val.decode(errors='replace')[:200]}")
                else:
                    print(f"{ctype} metadata chunk present ({len(chunk_data)} bytes)")
            except Exception:
                print(f"{ctype} metadata chunk present ({len(chunk_data)} bytes, could not decode)")
        elif ctype == "sRGB":
            print("sRGB color profile chunk present.")
        elif ctype == "iCCP":
            print(f"ICC color profile embedded ({len(chunk_data)} bytes).")
        pos += 8 + length + 4  # length + type + data + CRC
        if ctype == "IEND":
            break
    print(f"All chunk types found, in order: {', '.join(chunk_types_seen)}")

elif data[:2] == b"\xff\xd8":
    print("Detected: JPEG")
    i = 2
    markers_found = []
    while i < len(data) - 4:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i+1]
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > len(data):
            break
        seg_len = struct.unpack(">H", data[i+2:i+4])[0]
        markers_found.append(hex(marker))
        if marker == 0xE1 and data[i+4:i+9] == b"Exif\x00":
            print("EXIF segment (APP1) present.")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i+5:i+9])
            channels = data[i+9]
            print(f"SOF: {width}x{height}, {channels} channel(s)")
        if marker == 0xDA:
            break
        i += 2 + seg_len
    print(f"JPEG markers seen: {', '.join(markers_found)}")

elif data[:6] in (b"GIF87a", b"GIF89a"):
    print("Detected: GIF")
    width, height = struct.unpack("<HH", data[6:10])
    flags = data[10]
    has_gct = bool(flags & 0x80)
    gct_size = 2 ** ((flags & 0x07) + 1) if has_gct else 0
    print(f"Dimensions: {width}x{height}, global color table: {has_gct} ({gct_size} colors)")
    frame_count = data.count(b"\x21\xf9\x04")
    print(f"Approximate animation frame count (via graphic control extensions): {frame_count}")

else:
    print("Format not recognized by manual parser (not PNG/JPEG/GIF signature).")
"""

def _analyze_image_via_terminal(raw_bytes: bytes, ext: str, filename_hint: str = "upload") -> str:
    """Writes the uploaded image to a real scratch directory and runs the
    deep-analysis script above via the SAME background terminal execution
    engine (`_run_code_block`) used for the AI's own code blocks — this is
    genuine subprocess execution against the real file, not a canned
    description. Returns the script's stdout (the full analysis text), or
    the lightweight header-sniff result as a fallback if execution fails."""
    workdir = _new_terminal_workdir()
    try:
        safe_name = f"{filename_hint or 'upload'}.{ext}".replace("/", "_").replace("..", "_")
        image_path = os.path.join(workdir, safe_name)
        with open(image_path, "wb") as f:
            f.write(raw_bytes)
        # The script reads its target path via sys.argv, but _run_code_block
        # executes with `python -c <code>` (no argv beyond that), so the
        # image path is substituted directly into the script text instead.
        script_with_path = _IMAGE_DEEP_ANALYSIS_SCRIPT.replace(
            'path = sys.argv[1]', f'path = {image_path!r}'
        )
        stdout, stderr, rc = _run_code_block("python", script_with_path, cwd=workdir)
        result = stdout.strip()
        if stderr.strip():
            result += f"\n(stderr during analysis: {stderr.strip()[:300]})"
        if not result:
            result = _extract_image_metadata(raw_bytes, ext)
        return result
    except Exception as exc:
        print(f"[IMAGE DEEP ANALYSIS][FAULT] {exc}")
        return _extract_image_metadata(raw_bytes, ext)
    finally:
        _cleanup_terminal_workdir(workdir)

def _text_extraction_quality_score(text: str) -> float:
    """Cheap 0.0-1.0 quality heuristic used to pick the best of several
    extraction attempts: fraction of characters that are letters (any
    script, via str.isalpha — this correctly counts Devanagari letters, not
    just ASCII), digits, or normal punctuation/whitespace, versus control
    characters / replacement characters / other extraction-noise symbols
    that show up when a library mishandles a script's encoding."""
    if not text or not text.strip():
        return 0.0
    good = sum(1 for c in text if c.isalpha() or c.isdigit() or c.isspace() or c in ".,;:!?()-'\"।॥")
    return good / max(1, len(text))

def _extract_pdf_text_with_pypdf(pdf_bytes: bytes) -> str:
    if not _PDF_READ_SUPPORTED:
        return ""
    try:
        reader = _PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        print(f"[EDU][EXTRACT FAULT pypdf] {exc}")
        return ""

def _extract_pdf_text_with_fitz(pdf_bytes: bytes) -> str:
    """PyMuPDF (fitz) — generally the most reliable of the three for
    Devanagari/Indic scripts in practice, since it reads glyph positions
    and Unicode mapping more robustly than pypdf's simpler approach."""
    if not _FITZ_SUPPORTED:
        return ""
    try:
        doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            return "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    except Exception as exc:
        print(f"[EDU][EXTRACT FAULT fitz] {exc}")
        return ""

def _extract_pdf_text_with_pdfplumber(pdf_bytes: bytes) -> str:
    if not _PDFPLUMBER_SUPPORTED:
        return ""
    try:
        with _pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:
        print(f"[EDU][EXTRACT FAULT pdfplumber] {exc}")
        return ""

def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """
    THE FIX for Sanskrit/Hindi (and any other complex-script) PDFs coming
    back empty/garbled: instead of relying on pypdf alone (which is known to
    mishandle Devanagari conjuncts/ligatures), this now runs every text
    extractor that's actually installed on the server — PyMuPDF (fitz),
    pdfplumber, and pypdf/PyPDF2 — scores each result's quality, and returns
    whichever came out cleanest. If none are installed except pypdf, this
    behaves exactly as before (no regression), but installing PyMuPDF or
    pdfplumber on the server (add "PyMuPDF" or "pdfplumber" to
    requirements.txt) will make Sanskrit/Hindi chapters extract properly
    without any further code change needed.
    """
    candidates = []
    fitz_text = _extract_pdf_text_with_fitz(pdf_bytes)
    if fitz_text:
        candidates.append(("fitz", fitz_text))
    plumber_text = _extract_pdf_text_with_pdfplumber(pdf_bytes)
    if plumber_text:
        candidates.append(("pdfplumber", plumber_text))
    pypdf_text = _extract_pdf_text_with_pypdf(pdf_bytes)
    if pypdf_text:
        candidates.append(("pypdf", pypdf_text))

    if not candidates:
        return ""

    best_method, best_text = max(candidates, key=lambda item: _text_extraction_quality_score(item[1]))
    print(f"[EDU][EXTRACT] used {best_method} (score={_text_extraction_quality_score(best_text):.2f}, "
          f"{len(candidates)} extractor(s) available)")
    return best_text

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
        # FIX: same caching bug as _fetch_chapter_text — only skip
        # re-extraction if the previously cached result was actually
        # non-empty. A cached EMPTY result (from an earlier extraction
        # failure, e.g. before PyMuPDF was installed) should always be
        # retried, not treated as "unchanged, done."
        if cached and cached.get("sha") == sha and cached.get("text"):
            continue
        raw = _github_fetch_file_bytes(entry.get("download_url"))
        if raw is None:
            continue
        text = _extract_pdf_text(raw)
        if text:
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
    """
    THE FIX for "still can't read the PDF even after adding PyMuPDF": this
    cache used to store EVERY extraction result, including empty/failed
    ones, keyed by the file's sha. Since a PDF's sha never changes unless
    the file itself is re-uploaded, a single early failure (e.g. from
    before PyMuPDF was installed) got cached permanently — every later
    request just replayed that same empty string forever, even after the
    extractor chain was fixed and would have succeeded. Now only a
    genuinely non-empty extraction gets cached; an empty/failed result is
    never stored, so the next request always retries extraction fresh
    until it actually succeeds.
    """
    safe_book = book.replace("..", "").strip("/")
    safe_chapter = chapter.replace("..", "").strip("/")
    cache_key = f"{safe_book}/{safe_chapter}"
    entries = _github_list_dir(f"data/education/{safe_book}")
    match = next((e for e in entries if e.get("name") == safe_chapter), None)
    if not match:
        print(f"[EDU][FETCH][FAULT] chapter file not found: 'data/education/{safe_book}/{safe_chapter}' "
              f"— available files in that folder: {[e.get('name') for e in entries]}")
        return ""
    sha = match.get("sha")
    cached = _education_chapter_text_cache.get(cache_key)
    if cached and cached.get("sha") == sha and cached.get("text"):
        return cached.get("text", "")
    raw = _github_fetch_file_bytes(match.get("download_url"))
    if raw is None:
        print(f"[EDU][FETCH][FAULT] GitHub download_url fetch returned None for {cache_key}")
        return cached.get("text", "") if cached else ""
    if not (_PDF_READ_SUPPORTED or _FITZ_SUPPORTED or _PDFPLUMBER_SUPPORTED):
        print(f"[EDU][FETCH][FAULT] no PDF extractor installed at all (pypdf/PyMuPDF/pdfplumber all "
              f"missing) — add at least one to requirements.txt. Skipping extraction for {cache_key}.")
        return ""
    text = _extract_pdf_text(raw)
    if not text:
        print(f"[EDU][FETCH][FAULT] extractor chain ran but returned empty text for {cache_key} "
              f"(pypdf={_PDF_READ_SUPPORTED}, fitz={_FITZ_SUPPORTED}, pdfplumber={_PDFPLUMBER_SUPPORTED}) "
              f"— likely a font/encoding issue in this specific PDF, not a missing package. "
              f"Trying OCR fallback (ocr_supported={_OCR_SUPPORTED})...")
        if _OCR_SUPPORTED:
            text = _extract_pdf_text_with_ocr(raw)
            if text:
                print(f"[EDU][FETCH] OCR fallback succeeded for {cache_key} ({len(text)} chars)")
            else:
                print(f"[EDU][FETCH][FAULT] OCR fallback also returned nothing for {cache_key} "
                      f"— this PDF may genuinely be corrupted/blank, or is missing the 'hin' Tesseract "
                      f"language pack (apt install tesseract-ocr-hin on the host).")
        else:
            print(f"[EDU][FETCH][FAULT] OCR not available (pytesseract not installed) — add "
                  f"pytesseract to requirements.txt AND tesseract-ocr + tesseract-ocr-hin as a system "
                  f"package on the host to enable OCR fallback for image-only Devanagari PDFs.")
    if text:
        _education_chapter_text_cache[cache_key] = {"sha": sha, "text": text}
    return text

# ── "@web" live search: real Google Custom Search JSON API when configured
# (set GOOGLE_CSE_KEY + GOOGLE_CSE_CX env vars — free tier gives 100
# queries/day), falling back to the DuckDuckGo HTML scrape below so search
# still works with zero setup. ──
_EDU_TAG_RE = re.compile(r"\[\[EDU_BOOK:(.*?)\]\]\[\[EDU_CHAPTER:(.*?)\]\]")
_NO_WEB_SEARCH_TAG_RE = re.compile(r"\[\[NO_WEB_SEARCH\]\]")

GOOGLE_CSE_KEY = os.environ.get("GOOGLE_CSE_KEY", "").strip()
GOOGLE_CSE_CX = os.environ.get("GOOGLE_CSE_CX", "").strip()
GOOGLE_CSE_CONFIGURED = bool(GOOGLE_CSE_KEY and GOOGLE_CSE_CX)

def _google_cse_snippets(query: str, max_results: int = 4):
    try:
        params = urllib.parse.urlencode({
            "key": GOOGLE_CSE_KEY, "cx": GOOGLE_CSE_CX, "q": query, "num": max_results
        })
        req = urllib.request.Request(f"https://www.googleapis.com/customsearch/v1?{params}")
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        results = []
        for item in data.get("items", [])[:max_results]:
            title = item.get("title", "").strip()
            snippet = item.get("snippet", "").strip()
            link = item.get("link", "")
            if title:
                results.append(f"- {title}: {snippet} ({link})")
        return results
    except Exception as exc:
        print(f"[WEB][GOOGLE CSE FAULT] {exc}")
        return []

def _web_search_snippets(query: str, max_results: int = 4):
    if GOOGLE_CSE_CONFIGURED:
        results = _google_cse_snippets(query, max_results)
        if results:
            return results
        # fall through to DuckDuckGo if Google returned nothing (quota, etc.)
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
    r"for (every|all) user|public memory|shared memory|for everyone|store this|"
    r"always remember)\b",
    re.IGNORECASE
)

# Explicit, deterministic command forms — "add to memory: ...", "add this to
# your memory", "save to memory: ...", "/remember ...", "hey ai, save this: ...",
# "store this: ..." etc. Checked before the looser natural-language
# _TEACHING_INTENT_RE above so a direct instruction like this ALWAYS saves
# reliably. Works for anyone, but is the mechanism the creator specifically
# asked for ("when creator tells to add to memory then AI should add it").
_EXPLICIT_MEMORY_COMMAND_RE = re.compile(
    r"^\s*(?:add(?:\s+this)?\s+to\s+(?:your\s+)?memory|save\s+to\s+memory|remember\s+this\s+forever|"
    r"/remember|hey\s+ai,?\s+save\s+this|store\s+this)"
    r"\s*[:\-]?\s*(.*)$",
    re.IGNORECASE | re.DOTALL
)

# ── PUBLIC SHARED MEMORY (data/public_data.txt) ──
# One file, inside data/ alongside data/vip.txt, shared across every user.
# Writing only matters if something actually reads it back, so this is
# always fetched fresh on every chat turn (no caching window) and injected
# into the system prompt — see _search_intelligent_memory_excerpts below for
# how relevant entries get picked. The cache dict is kept only as a fallback
# if a live GitHub fetch happens to fail (transient network error), so a
# single hiccup doesn't wipe shared memory for that turn.
_PUBLIC_MEMORY_PATH = "data/public_data.txt"
_public_teachings_cache = {"text": "", "t": 0}
_PUBLIC_TEACHINGS_CHAR_BUDGET = 12000  # raised from 3000 now that public_data.txt is 5500+ lines and
                                        # response token budget is much larger — a small cap here would
                                        # mean most of a file this size never gets seen by the model

def _maybe_capture_public_teaching(user_email: str, message: str):
    """
    If a message looks like the person is teaching/instructing the assistant
    something worth remembering, it gets appended to the shared
    data/public_data.txt file. Checks the explicit deterministic command
    forms first, then falls back to the looser natural-language phrase
    detector.
    """
    explicit_match = _EXPLICIT_MEMORY_COMMAND_RE.match(message)
    if explicit_match:
        content_to_save = explicit_match.group(1).strip() or message
        entry = (
            f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"
            f"Taught by: {user_email} (explicit /memory command)\n"
            f"Content: {content_to_save}\n"
            f"{'=' * 80}\n"
        )
        _write_to_github_repository(_PUBLIC_MEMORY_PATH, entry)
        _public_teachings_cache["t"] = 0
        return

    if not _TEACHING_INTENT_RE.search(message):
        return
    entry = (
        f"\n=== {datetime.now(timezone.utc).isoformat()} ===\n"
        f"Taught by: {user_email}\n"
        f"Content: {message}\n"
        f"{'=' * 80}\n"
    )
    _write_to_github_repository(_PUBLIC_MEMORY_PATH, entry)
    _public_teachings_cache["t"] = 0  # force the next read to refetch immediately

def _auto_extract_and_save_knowledge(assistant_response: str):
    """
    NOT called automatically anywhere in this file, on purpose. This would
    scrape lines out of EVERY assistant reply and save them into the shared,
    all-users-visible data/public_data.txt — but that file gets injected
    into every other user's conversations, so silently auto-saving fragments
    of any one person's private chat (which could include personal details,
    account info, anything) into that shared file is a real data-leak risk,
    not just noise. Left defined and available in case you want to wire it
    up deliberately (e.g. behind an explicit opt-in), but it is intentionally
    dormant by default.
    """
    clean_text = assistant_response.strip()
    if len(clean_text) < 20:
        return
    phrases_to_skip = ["i'd be happy to", "your file is", "here is the", "something went wrong"]
    if any(p in clean_text.lower() for p in phrases_to_skip):
        return
    extracted_nodes = []
    for line in clean_text.split("\n"):
        line_strip = line.strip()
        if not line_strip:
            continue
        if line_strip.startswith("if ") or "function" in line_strip or "const" in line_strip or line_strip.startswith("-") or len(line_strip) > 40:
            extracted_nodes.append(re.sub(r"\*\*?", "", line_strip))
    if extracted_nodes:
        compiled_knowledge = " | ".join(extracted_nodes[:8])
        entry = f"[AUTO FACT — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}] {compiled_knowledge}\n"
        _write_to_github_repository(_PUBLIC_MEMORY_PATH, entry)
        _public_teachings_cache["t"] = 0

def _fetch_full_public_data_text() -> str:
    """Reads the FULL data/public_data.txt file directly from GitHub on
    every call (no stale cache window) — falls back to the last known-good
    copy only if the live fetch itself fails.

    Same fix as _write_to_github_repository: GitHub's Contents API stops
    inlining `content` once a file grows past ~1MB (which a file this long
    — 5500+ lines — can genuinely hit). Previously that meant this function
    silently returned an empty string once the file crossed that size, so
    "always read public_data.txt before responding" was quietly reading
    nothing. Now it falls back to the item's own `download_url`, which has
    no such inline-size limit, whenever `content` isn't present but the
    file's reported `size` shows it isn't actually empty.
    """
    text = ""
    if GITHUB_TOKEN:
        repo_clean = _github_repo_slug()
        endpoint_target_url = f"https://api.github.com/repos/{repo_clean}/contents/{_PUBLIC_MEMORY_PATH}"
        req_lookup = urllib.request.Request(
            endpoint_target_url,
            headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        )
        try:
            with urllib.request.urlopen(req_lookup, timeout=10) as lookup_response:
                meta_data = json.loads(lookup_response.read().decode('utf-8'))
                if meta_data.get("content"):
                    text = base64.b64decode(meta_data["content"].replace("\n", "")).decode('utf-8')
                elif meta_data.get("size", 0) > 0 and meta_data.get("download_url"):
                    raw_req = urllib.request.Request(
                        meta_data["download_url"],
                        headers={"Authorization": f"token {GITHUB_TOKEN}"}
                    )
                    with urllib.request.urlopen(raw_req, timeout=20) as raw_resp:
                        text = raw_resp.read().decode('utf-8', errors='replace')
        except Exception as exc:
            print(f"[PUBLIC MEMORY][FETCH FAULT] {exc}")
            return _public_teachings_cache["text"]  # fall back to last known good copy

    _public_teachings_cache["text"] = text
    _public_teachings_cache["t"] = time.time()
    return text

def _search_intelligent_memory_excerpts(user_query: str) -> str:
    """
    Scores each non-blank line of data/public_data.txt against the current
    message's keywords (simple multi-keyword intersection) and returns the
    best-matching lines — smarter than just grabbing the tail of the file,
    since a relevant fact from early in the file won't get crowded out by
    unrelated recent entries. Falls back to the plain tail of the file if
    nothing scores a match, so the model still gets *some* shared context.
    """
    full_corpus = _fetch_full_public_data_text()
    if not full_corpus.strip():
        return ""

    query_tokens = set(re.findall(r"[a-zA-Z]{3,}", user_query.lower()))
    matched_lines = []
    if query_tokens:
        for line in full_corpus.splitlines():
            line_clean = line.strip()
            if not line_clean:
                continue
            line_tokens = set(re.findall(r"[a-zA-Z]{3,}", line_clean.lower()))
            score = len(query_tokens & line_tokens)
            if score > 0:
                matched_lines.append((score, line_clean))
        matched_lines.sort(key=lambda item: item[0], reverse=True)

    if matched_lines:
        top_excerpts = [line for _score, line in matched_lines[:10]]
        joined = "\n".join(top_excerpts)
        return joined[:_PUBLIC_TEACHINGS_CHAR_BUDGET]

    # No keyword overlap at all — fall back to the most recent entries
    # (tail of the file) rather than giving the model nothing.
    return full_corpus[-_PUBLIC_TEACHINGS_CHAR_BUDGET:]

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
    "Default to SHORT replies for non-coding questions: a few tight sentences, dense with the actual "
    "answer, no filler intros ('Great question!'), no restating the question, no long bulleted feature "
    "lists unless the person asked for a list. Expand length only when the task genuinely needs it "
    "(full code files, multi-step explanations the person asked to go deep on).\n\n"
    "MATH FORMATTING: always wrap math in LaTeX delimiters — inline: \\( x^2 \\) or $x^2$; "
    "display/standalone equations: \\[ \\frac{a}{b} \\] or $$ \\frac{a}{b} $$. Never write powers as "
    "'x^2' or fractions as 'a/b' in plain text outside these delimiters — the frontend renders proper "
    "typeset math ONLY inside \\(...\\), \\[...\\], $...$, or $$...$$, so plain-text math looks broken.\n\n"
    "GRAPHS/CHARTS: when asked for a DATA graph, chart, or plot (bar/line/pie/scatter of numbers), "
    "respond with a ```chart fenced block (language tag is exactly the word 'chart', no colon) "
    "containing valid Chart.js config JSON (type, data.labels, data.datasets, options), e.g.\n"
    "```chart\n"
    '{"type":"bar","data":{"labels":["Jan","Feb","Mar"],"datasets":[{"label":"Sales","data":[10,20,15]}]}}\n'
    "```\n"
    "This renders as a real live graph. Do not draw charts with ASCII art or describe them only in text "
    "when the person wants to see one.\n\n"
    "GEOMETRY/DIAGRAMS ARE NOT CHARTS: for geometric constructions (triangles, circles, perpendicular "
    "bisectors, angles, geometric proofs, circumcircles/incircles, coordinate geometry figures, "
    "physics/engineering diagrams, flowcharts, etc.), NEVER use the ```chart block — Chart.js can only "
    "plot bar/line/pie/scatter data series, it cannot draw circles, labeled construction lines, or "
    "arbitrary shapes, and forcing geometry into it renders as an empty or broken box. Instead, use a "
    "```createfile:<name>.html block containing a self-contained SVG or HTML/JS diagram (as you've "
    "successfully done before for circumcircle constructions) — draw the actual shapes, lines, and "
    "labels directly as SVG elements (<circle>, <line>, <polygon>, <text>) with real computed "
    "coordinates, not a Chart.js scatter plot trying to fake a picture.\n\n"
    "You also have a REAL background terminal, not a simulated one, and YOU run it directly — there "
    "is no separate tool, no external terminal, no permission step. The moment you write a ```python, "
    "```py, ```bash, ```sh, or ```shell fenced block, the backend executes it for real on the server "
    "immediately after your reply, and feeds you back the actual stdout/stderr/return code so you can "
    "react to it in a following turn. This is not something you need to ask the person for access to, "
    "explain how it works, or offer as an option — it already runs automatically every single time you "
    "write one of those fenced blocks. NEVER tell the person you lack terminal/shell access or need "
    "permission to run something — you always have it, unconditionally, on every single message. "
    "Use this to actually DO tasks instead of just "
    "describing them: run calculations, process or transform data, generate/inspect files in "
    "the working directory, test that your own code really works, or chain several steps "
    "together (write code -> see real output -> fix or continue) until the task is finished. "
    "Only rely on this loop when it genuinely helps; don't run code just to run code. Each "
    "conversation turn allows a limited number of execute-and-continue cycles, so work "
    "efficiently and give a clear final plain-language answer once the task is actually done.\n\n"
    "NEVER wrap a one-off command in an unnecessary intermediate script file (e.g. writing "
    "generated_2.sh, run.sh, script.py, temp.py just to hold a command you're about to run once). "
    "If you need to run something, run it directly in a ```bash or ```python block — don't "
    "createfile a throwaway wrapper around it first. Only use ```createfile: when the person "
    "actually needs the file itself as a deliverable, not as internal scaffolding.\n\n"
    "EDIT IN PLACE, NEVER DUPLICATE: if a file the person is working on already exists (you created "
    "it earlier in this conversation, or they uploaded/referenced it), and they ask you to change, "
    "fix, add to, or continue it, you MUST use ```editfile:<filename> to modify that exact file — "
    "never create a second file with a similar name (app2.py, app_new.py, fixed.py, app_final.py, "
    "counter_v2.py, etc.) as a workaround. There should only ever be ONE copy of a file the person "
    "is iterating on.\n\n"
    "ASK BEFORE ACTING ON AMBIGUOUS REQUESTS: if someone asks for something that could reasonably "
    "mean several different things (e.g. \"zip it\" without saying what \"it\" is, or a vague build "
    "request with no real spec), ask one short clarifying question BEFORE running any terminal "
    "commands or creating any files, instead of guessing and generating the wrong thing. If the "
    "request is already clear and specific, don't ask needlessly — just do it.\n\n"
    "For creating a file directly (when you just need to write out a file's full contents, not "
    "compute or process anything), use a ```createfile:<filename.ext> fenced block, e.g.\n"
    "```createfile:notes.md\n<full file content goes here>\n```\n"
    "The backend writes this as a REAL file in your working terminal directory immediately — no "
    "python/bash needed just to produce a file. It shows up right away as its own downloadable "
    "file card, exactly like other generated files. You can emit multiple ```createfile: blocks "
    "in one reply (e.g. several files of a small project at once), and later ```python/```bash "
    "blocks in the same reply can read/use files you created this way, since they share the same "
    "working directory. Prefer ```createfile: over python's open()/write() for simple file output; "
    "reserve python/bash for when you actually need to compute, transform, or execute something.\n\n"
    "Your response length budget is large (tens of thousands of tokens) and multiple API keys are "
    "in rotation behind you, so when someone asks for a big file (e.g. a large reference file, a "
    "long knowledge base, a file with thousands of lines), do NOT artificially cut it short or "
    "summarize/truncate it out of caution — write the full, complete content they asked for, even "
    "if that means several thousand lines in a single ```createfile: block. If a response gets cut "
    "off mid-file for any reason, you will automatically be asked to continue from exactly where you "
    "left off — when that happens, resume seamlessly inside the same block with no repetition and no "
    "'continuing...' preamble.\n\n"
    "CRITICAL — editing an existing file: if the person asks you to change, fix, add to, or modify "
    "a file that was already created earlier IN THIS SAME CONVERSATION, do NOT regenerate the whole "
    "file with ```createfile: again — that wastes tokens/credits re-sending unchanged content and is "
    "slower. Instead use a ```editfile:<filename.ext> block containing one or more SEARCH/REPLACE "
    "pairs, formatted exactly like this:\n"
    "```editfile:chess.html\n"
    "<<<<<<< SEARCH\n"
    "<the exact existing lines to find, copied precisely from the file>\n"
    "=======\n"
    "<the new lines that should replace them>\n"
    ">>>>>>> REPLACE\n"
    "```\n"
    "You can include several SEARCH/REPLACE pairs in one ```editfile: block for multiple changes to "
    "the same file. The SEARCH text must match the existing file's content exactly (including "
    "whitespace/indentation) — copy it verbatim from what you wrote earlier, don't paraphrase it. "
    "The backend applies your edits to the file's real current content and re-saves the full result "
    "as a new download automatically; you never need to see or re-output the unchanged parts. Only "
    "fall back to a full ```createfile: rewrite when the person explicitly asks for a full rewrite, "
    "when changes are so extensive that individual search/replace edits would be impractical, or when "
    "the file doesn't exist yet in this conversation.\n\n"
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
    "FORMATTING: always format replies clearly using markdown — use ## / ### headings for sections, "
    "**bold** for key terms, numbered/bulleted lists for steps or lists, and real markdown tables "
    "(| col | col |) whenever data is naturally tabular (comparisons, specs, schedules, pros/cons). "
    "Never dump a wall of unformatted prose when structure would help; never fake a table with plain "
    "dashes or spaces — use real markdown table syntax so it renders as an actual table.\n\n"
    "IMAGES: you cannot generate images yourself, but this app has a real image generator wired in "
    "(Pollinations AI). Whenever someone asks for an image/picture/art/graphic/illustration, just "
    "describe what you'll generate in one short sentence — the backend detects the request and "
    "actually renders and returns a real image automatically; you never need to say you can't make "
    "images.\n\n"
    "When someone uploads an image, you'll receive real, full technical information about it — "
    "actually extracted by running a script against the file in your background terminal (every PNG "
    "chunk, EXIF data, color info, dimensions, etc., not just a basic size/dimension guess). Use that "
    "real data confidently when reasoning about the file.\n\n"
    "TONE CONSISTENCY: keep the same voice across an entire conversation and across turns — clear, "
    "direct, and helpful, without switching registers (don't go from casual to overly formal or back) "
    "and without restating who built you or what tools you have unless it's actually relevant to what "
    "was just asked. Match the level of detail to the question: a quick fix gets a quick answer; a "
    "build-this-from-scratch request gets the full thing.\n\n"
    "Your background terminal executions and any file changes are already tracked/logged for this app "
    "(conversation logs and shared memory sync to this app's GitHub data repo automatically on the "
    "backend) — you don't need to narrate that syncing is happening or ask the person to confirm it; "
    "just do the actual work (run the code, create/edit the file, etc.) and report the real result.\n\n"
    "ACT WITH CONFIDENCE, DON'T STALL ON CLARIFYING QUESTIONS: if you can reasonably tell what the "
    "person wants, just do it — pick the most sensible interpretation and build/answer it directly. "
    "Only ask a clarifying question first when you are genuinely unsure and guessing wrong would waste "
    "significant work (e.g. completely different possible meanings of the request). Do not ask "
    "permission to proceed when you're already confident.\n\n"
    "BE CONCISE, NOT BLOATED: don't pad answers with long lists of unrequested follow-up options (e.g. "
    "ending every reply with 'Would you like me to: A) ... B) ... C) ...'). Give the actual answer/"
    "deliverable, briefly note one natural next step ONLY if it's genuinely useful, and stop — don't "
    "manufacture extra menu-style choices just to seem thorough. Long walls of text with excessive "
    "headers/bullets for a simple question read as padding, not helpfulness — match response length to "
    "what was actually asked.\n\n"
    "NO ARTIFICIAL LENGTH LIMIT on files you create: when producing a file (via ```createfile: or "
    "```finaldoc), there is no line-count ceiling you should self-impose — write however many lines the "
    "task genuinely requires, even if that's several thousand, rather than truncating or summarizing to "
    "keep it short.\n\n"
    "WORKFLOW FOR LARGE/MULTI-PART TASKS: when a request has many distinct requirements (e.g. 'build a "
    "full app with X, Y, Z, and W'), don't try to write everything in one unstructured pass. Instead: "
    "(1) briefly list out the distinct requirements as a short checklist so both you and the person can "
    "see the plan, (2) implement each item one at a time, in order, (3) once everything is implemented, "
    "actually re-read back through the file(s) you produced looking for mistakes (syntax errors, missing "
    "pieces, requirements you skipped), and (4) if you find an error, fix it by editing that SAME file "
    "with ```editfile: (never by creating a duplicate/new file for the fix) before giving your final "
    "answer.\n\n"
    "FILE EXPORTS ONLY ON EXPLICIT REQUEST: only produce a zip/pdf/other export of your answer when the "
    "person actually asks for the response in that format (e.g. 'zip it', 'as a pdf', 'download this'). "
    "Do not proactively package a normal conversational answer as a downloadable file just because the "
    "answer happens to be long — a long answer is still just a chat reply unless a file was requested.\n\n"
    "You must never help with illegal activity, weapons, malware, or content that could seriously harm "
    "someone; politely refuse those requests instead — this includes never using the terminal "
    "to access the network for attacks, exfiltrate credentials, or damage systems outside this "
    "sandbox."
)

# ── IMAGE GENERATION (Pollinations AI — no API key required) ──
_IMAGE_INTENT_RE = re.compile(
    r"^/image\s+(.+)$|"
    r"\b(?:generate|create|draw|make|paint|design|render)\b.{0,25}\b(?:image|img|picture|pic|photo|art|artwork|illustration|drawing|wallpaper|poster|graphic|graphics)s?\b"
    r"(?:\s+(?:of|showing|depicting|with))?\s*(.*)$",
    re.IGNORECASE
)

# Follow-up modification phrases like "add a hat", "now make it night",
# "change the background to blue" — these don't contain the word
# image/picture/etc, so on their own _IMAGE_INTENT_RE misses them. They only
# count as an image request when the PREVIOUS assistant turn actually
# generated an image (see last_image_prompt threading in chat_stream).
_IMAGE_FOLLOWUP_RE = re.compile(
    r"^\s*(?:also\s+)?(?:add|change|make it|now|remove|replace|turn it|put|give it|make the|instead)\b.{0,120}$",
    re.IGNORECASE
)

def _detect_image_prompt(message: str, last_image_prompt: str = None):
    """
    Returns a plain-language image description if `message` looks like an
    image-generation request, else None. Kept intentionally simple (regex
    heuristic) rather than a full intent classifier, to stay fast.

    If the previous turn generated an image (last_image_prompt passed in)
    and this message reads as a short edit/follow-up instruction without an
    explicit image keyword, we treat it as "regenerate the same image with
    this change" instead of falling through to a plain text reply — this is
    the fix for "add this ... then it don't make img again".
    """
    stripped = message.strip()
    m = _IMAGE_INTENT_RE.search(stripped)
    if m:
        prompt_text = (m.group(1) or m.group(2) or "").strip(" .!")
        if prompt_text:
            return prompt_text
    if last_image_prompt and _IMAGE_FOLLOWUP_RE.match(stripped):
        return f"{last_image_prompt}, {stripped.strip(' .!')}"
    return None

def _pollinations_image_url(prompt_text: str) -> str:
    encoded = urllib.parse.quote(prompt_text)
    # width/height/seed kept default-ish; nologo=true removes the Pollinations
    # watermark bar when supported.
    return f"https://image.pollinations.ai/prompt/{encoded}?nologo=true"

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

def _stream_openai_compatible(url, api_key, model, messages, state=None):
    """`state`, if provided, is a plain dict this function writes
    state['finish_reason'] into once the stream's final chunk reports one
    (e.g. 'length' when the provider cut the response short because it hit
    the token limit, vs 'stop' for a normal completion). Callers use this to
    detect truncation and automatically continue generation — see
    _do_stream's continuation loop below, which is what fixes "it stops
    HTML/file generation in the middle."""
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": 32768,
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
                choice = payload["choices"][0]
                token = choice.get("delta", {}).get("content", "")
                if token:
                    yield _sse({"type": "token", "text": token})
                finish_reason = choice.get("finish_reason")
                if finish_reason and state is not None:
                    state["finish_reason"] = finish_reason
            except Exception:
                continue

def _generate_ai_chat_title(message: str) -> str:
    """Uses the model itself to write a short, clean chat title (like
    ChatGPT/Claude do), instead of just truncating the raw first message.
    Falls back to plain truncation on any failure (missing keys, rate
    limit, network error) so title generation never blocks sending the
    actual chat message."""
    keys = GROQ_API_KEYS or ([GROQ_API_KEY] if GROQ_API_KEY else [])
    if not keys:
        return message[:60]
    prompt = (
        "Write a short chat title (3-6 words, no quotes, no punctuation at the end, "
        "no emoji) summarizing what this message is about. Reply with ONLY the title, "
        f"nothing else.\n\nMessage: \"{message[:400]}\""
    )
    for idx, key in enumerate(keys):
        cooldown_name = f"groq_{idx}"
        if _is_cooling(cooldown_name):
            continue
        try:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=json.dumps({
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 20, "temperature": 0.3,
                }).encode(),
                method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            title = data["choices"][0]["message"]["content"].strip().strip('"').strip("'")
            if title:
                return title[:60]
        except Exception as exc:
            print(f"[TITLE][AI FAULT] key {idx}: {exc}")
            continue
    return message[:60]

def _stream_groq(messages, state=None):
    # Multi-key rotation: try every configured Groq key in turn (each has
    # its own independent cooldown name "groq_0", "groq_1", ...), so hitting
    # one key's rate limit doesn't fail the whole Groq provider over to
    # OpenRouter/Cerebras/Mistral — it just moves to the next Groq key,
    # effectively multiplying the available Groq throughput by however many
    # keys are configured (GROQ_API_KEY="key1,key2" or GROQ_API_KEY_2, _3, ...).
    keys = GROQ_API_KEYS or ([GROQ_API_KEY] if GROQ_API_KEY else [])
    if not keys:
        raise RuntimeError("Groq unavailable (no API keys configured).")

    last_error = None
    any_key_tried = False
    for idx, key in enumerate(keys):
        cooldown_name = f"groq_{idx}"
        if _is_cooling(cooldown_name):
            continue
        any_key_tried = True
        try:
            yield from _stream_openai_compatible(
                "https://api.groq.com/openai/v1/chat/completions",
                key, "llama-3.3-70b-versatile", messages, state=state
            )
            return
        except Exception as exc:
            last_error = exc
            _cool(cooldown_name)
            continue

    if not any_key_tried:
        raise RuntimeError("All Groq keys are currently cooling down.")
    raise RuntimeError(f"All Groq keys failed. Last error: {last_error}")

def _stream_openrouter(messages, state=None):
    if not OPENROUTER_API_KEY or _is_cooling("openrouter"):
        raise RuntimeError("OpenRouter unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://openrouter.ai/api/v1/chat/completions",
        OPENROUTER_API_KEY, "meta-llama/llama-3.3-70b-instruct", messages, state=state
    )

def _stream_cerebras(messages, state=None):
    if not CEREBRAS_API_KEY or _is_cooling("cerebras"):
        raise RuntimeError("Cerebras unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://api.cerebras.ai/v1/chat/completions",
        CEREBRAS_API_KEY, "llama3.3-70b", messages, state=state
    )

def _stream_mistral(messages, state=None):
    if not MISTRAL_API_KEY or _is_cooling("mistral"):
        raise RuntimeError("Mistral unavailable or cooling.")
    yield from _stream_openai_compatible(
        "https://api.mistral.ai/v1/chat/completions",
        MISTRAL_API_KEY, "mistral-large-latest", messages, state=state
    )

_PROVIDER_CHAIN = [
    ("groq", _stream_groq),
    ("openrouter", _stream_openrouter),
    ("cerebras", _stream_cerebras),
    ("mistral", _stream_mistral),
]

_MAX_AUTO_CONTINUATIONS = 6  # hard cap on "continue where you left off" cycles per single reply

def _do_stream(messages):
    """Streams a reply from the first available provider, then — this is
    the fix for "it stops making the HTML in the middle" — automatically
    detects when the provider cut the response short purely because it hit
    its token limit (finish_reason == 'length', NOT a real stop) and keeps
    requesting continuations from the SAME provider, feeding back exactly
    what's been generated so far and asking it to continue seamlessly with
    no repetition, until the response actually finishes normally or the
    continuation cap is hit. The continued tokens are streamed to the
    frontend exactly like the original ones, so a file that would have been
    cut off mid-file now keeps going until it's actually complete."""
    for name, fn in _PROVIDER_CHAIN:
        state = {}
        accumulated_text = []
        any_token_yielded = False
        working_messages = list(messages)
        continuation_count = 0

        try:
            while True:
                state.clear()
                got_tokens_this_round = False
                for chunk in fn(working_messages, state=state):
                    any_token_yielded = True
                    got_tokens_this_round = True
                    try:
                        payload = json.loads(chunk[6:]) if chunk.startswith("data: ") else None
                        if payload and payload.get("type") == "token":
                            accumulated_text.append(payload["text"])
                    except Exception:
                        pass
                    yield chunk

                if not got_tokens_this_round:
                    break
                if state.get("finish_reason") != "length":
                    break
                if continuation_count >= _MAX_AUTO_CONTINUATIONS:
                    break

                continuation_count += 1
                working_messages = list(messages) + [
                    {"role": "assistant", "content": "".join(accumulated_text)},
                    {"role": "user", "content": (
                        "Continue exactly where you left off. Do not repeat any earlier text, do not "
                        "restart the file/answer, and do not add any preamble like 'continuing...' — "
                        "just keep producing the remaining content seamlessly as if it were never "
                        "interrupted. If you were mid-file inside a fenced code/createfile block, "
                        "resume inside that same block."
                    )}
                ]

            if any_token_yielded:
                yield _sse({"type": "complete"})
                return
        except Exception as exc:
            print(f"[FAILOVER] {name} dropped: {exc}")
            if any_token_yielded:
                # We already streamed partial content to the user for this
                # provider — better to end cleanly here than silently retry
                # a different provider and risk a duplicated/garbled reply.
                yield _sse({"type": "complete"})
                return
            _cool(name)
            continue

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
_TERMINAL_OUTPUT_CHAR_LIMIT = 200000    # raised from 4000 so large (~5000-line) file-creation tasks
                                         # and big terminal outputs don't get silently truncated

# ── DIRECT FILE-CREATION CHANNEL (additive) ──
# The model can write a ```createfile:<filename>\n<content>\n``` block to
# directly create a real file in the terminal workdir, without needing to
# write python/bash to do it. This is faster and more reliable than asking
# the model to open()/echo a file via code execution for simple file output,
# and it's what the frontend renders as its own small file-creation card
# (see LANG_EXT_MAP / guessFileName handling for the "createfile:" prefix
# on the frontend side).
_CREATEFILE_RE = re.compile(r"```createfile:([^\n`]+)\n([\s\S]*?)```")

def _extract_createfile_blocks(text: str):
    """Returns [(filename, content), ...] for every ```createfile:name block
    in `text`, in the order they appear."""
    out = []
    for m in _CREATEFILE_RE.finditer(text):
        filename = m.group(1).strip().replace("..", "").lstrip("/")
        if filename:
            out.append((filename, m.group(2)))
    return out

def _write_direct_file(workdir: str, filename: str, content: str) -> dict:
    """Actually writes the file to the real scratch directory (creating any
    subfolders implied by the filename), and returns its real path/size —
    this is genuine disk I/O in the same working directory python/bash
    blocks in this request use, not a simulation."""
    full_path = os.path.join(workdir, filename)
    os.makedirs(os.path.dirname(full_path) or workdir, exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"filename": filename, "size_bytes": len(content.encode("utf-8")), "line_count": content.count("\n") + 1, "path": full_path}

# ── DIRECT FILE-EDITING CHANNEL (additive) ──
# Fixes "it recreates the whole file every time, which eats more credit /
# tokens and sometimes cuts off mid-file." Instead of the model re-writing
# an entire file just to change a few lines, it can emit a
# ```editfile:<filename> block containing one or more SEARCH/REPLACE pairs.
# The backend applies those edits to the LAST known content of that file
# (reconstructed from this conversation's own history — see
# _find_last_file_content_in_history) and writes out the resulting full
# file itself, with zero extra LLM tokens spent on the unchanged parts.
_EDITFILE_RE = re.compile(r"```editfile:([^\n`]+)\n([\s\S]*?)```")
_EDIT_BLOCK_RE = re.compile(
    r"<{5,}\s*SEARCH\s*\n([\s\S]*?)\n={5,}\s*\n([\s\S]*?)\n>{5,}\s*REPLACE",
    re.IGNORECASE
)
# Detects stray SEARCH/REPLACE diff markers (<<<<<<< / ===== / >>>>>>>) that
# sometimes end up INSIDE a ```createfile: block by mistake instead of a
# proper ```editfile: block. Was referenced in the createfile handler below
# but never actually defined — every createfile block was throwing
# NameError: name '_CONFLICT_MARKER_RE' is not defined, caught by the bare
# except, so the file silently never got written and no activity_created
# event was ever sent. This is the real fix for that.
_CONFLICT_MARKER_RE = re.compile(r"<{5,}\s*SEARCH|>{5,}\s*REPLACE", re.IGNORECASE)

def _extract_editfile_blocks(text: str):
    """Returns [(filename, [(search_text, replace_text), ...]), ...] for
    every ```editfile:name block in `text`."""
    out = []
    for m in _EDITFILE_RE.finditer(text):
        filename = m.group(1).strip().replace("..", "").lstrip("/")
        if not filename:
            continue
        body = m.group(2)
        pairs = [(sm.group(1), sm.group(2)) for sm in _EDIT_BLOCK_RE.finditer(body)]
        if pairs:
            out.append((filename, pairs))
    return out

def _find_last_file_content_in_history(history: list, filename: str):
    """Scans this conversation's own past assistant messages (most recent
    first) for the last time `filename` was created or edited, and
    reconstructs its current full content — either from a ```createfile:
    block that wrote it, or by replaying any earlier ```editfile: edits on
    top of the createfile version. Returns None if the file was never seen
    in this conversation, so the caller can tell the model to createfile it
    fresh instead."""
    # Walk newest-to-oldest looking for the most recent createfile for this
    # filename, then replay every editfile edit that happened AFTER it, in
    # chronological order, to reconstruct the current content.
    base_content = None
    base_index = None
    for i in range(len(history) - 1, -1, -1):
        m = history[i]
        if m.get("role") != "assistant":
            continue
        for fname, content in _extract_createfile_blocks(m.get("content", "")):
            if fname == filename:
                base_content = content
                base_index = i
                break
        if base_content is not None:
            break

    if base_content is None:
        return None

    # Replay edits that happened after the base createfile, oldest first.
    content = base_content
    for i in range(base_index + 1, len(history)):
        m = history[i]
        if m.get("role") != "assistant":
            continue
        for fname, pairs in _extract_editfile_blocks(m.get("content", "")):
            if fname != filename:
                continue
            for search_text, replace_text in pairs:
                if search_text in content:
                    content = content.replace(search_text, replace_text, 1)
    return content

def _apply_editfile_edits(base_content: str, pairs: list):
    """Applies each (search, replace) pair once, in order, against
    `base_content`. Returns (new_content, list_of_warnings) — a warning is
    recorded (not raised) for any search snippet that couldn't be found, so
    one bad match doesn't silently discard the rest of a multi-edit block."""
    content = base_content
    warnings = []
    for idx, (search_text, replace_text) in enumerate(pairs, start=1):
        if search_text in content:
            content = content.replace(search_text, replace_text, 1)
        else:
            warnings.append(f"Edit #{idx}: search text not found, skipped.")
    return content, warnings

def _extract_executable_blocks(text: str):
    """Returns a list of (lang, code) for every fenced block whose language
    tag is one we know how to actually execute."""
    out = []
    for m in _CODE_BLOCK_RE.finditer(text):
        lang = (m.group(1) or "").lower()
        if lang in _EXECUTABLE_LANGS:
            out.append((lang, m.group(2)))
    return out

def _compute_diff_stats(old_content: str, new_content: str) -> dict:
    """Real diff engine (stdlib difflib) for editfile operations. Returns
    added/removed line counts plus a unified-diff string, so the frontend
    activity card can show a genuine '+N -N' badge instead of a guess."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    added = removed = 0
    for line in difflib.ndiff(old_lines, new_lines):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    unified = "".join(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    return {"added": added, "removed": removed, "unified_diff": unified}


# ── Optional remote executor (your own persistent Ubuntu box, e.g. Railway)
# — set both env vars to route real command execution there instead of
# Vercel's serverless subprocess. Vercel's local `_run_code_block` path
# below still works as a fallback if these aren't set, or if the remote
# call fails for any reason (network blip, box asleep, etc.). ──
EXECUTOR_URL = os.environ.get("EXECUTOR_URL", "").strip().rstrip("/")
EXECUTOR_SECRET = os.environ.get("EXECUTOR_SECRET", "").strip()
EXECUTOR_CONFIGURED = bool(EXECUTOR_URL and EXECUTOR_SECRET)

def _run_code_block_remote(lang: str, code: str, cwd: str = None):
    """Sends the block to your Ubuntu box's /execute endpoint (see
    executor_service.py) instead of running it in this serverless function.
    Returns (stdout, stderr, returncode, ok) — ok=False means the remote
    call itself failed (not the command), so the caller can fall back."""
    try:
        if lang in ("python", "py"):
            command = f"{shlex.quote(sys.executable)} -u -c {shlex.quote(code)}"
        else:
            command = code
        payload = json.dumps({"command": command, "cwd": cwd or "/tmp/workdir", "timeout": 60}).encode()
        req = urllib.request.Request(
            f"{EXECUTOR_URL}/execute", data=payload, method="POST",
            headers={"Content-Type": "application/json", "X-Exec-Secret": EXECUTOR_SECRET}
        )
        with urllib.request.urlopen(req, timeout=65) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        return (
            data.get("stdout", "")[-_TERMINAL_OUTPUT_CHAR_LIMIT:],
            data.get("stderr", "")[-_TERMINAL_OUTPUT_CHAR_LIMIT:],
            data.get("returncode", -1),
            True,
        )
    except Exception as exc:
        print(f"[EXECUTOR][REMOTE FAULT] falling back to local exec: {exc}")
        return "", "", -1, False

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
    if EXECUTOR_CONFIGURED:
        stdout, stderr, rc, ok = _run_code_block_remote(lang, code, cwd)
        if ok:
            return stdout, stderr, rc
        # remote failed — fall through to local execution below
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
    chat-stream request's terminal session. All executed blocks AND all
    ```createfile: blocks within that same request share this directory, so
    a file written in one block (e.g. step 1 generates data.csv, or a
    createfile block writes config.json) can be read by a later block (step
    2 processes data.csv) within the same multi-step agent loop."""
    return tempfile.mkdtemp(prefix="pratham_ai_terminal_")

def _cleanup_terminal_workdir(path: str):
    if path:
        shutil.rmtree(path, ignore_errors=True)

# ── CREATOR-ONLY LIVE DIAGNOSTICS ──
# Answers "is the terminal working?" / "system status" etc. with facts this
# process actually just measured, rather than the model guessing. Only
# reachable by CREATOR_EMAILS, and it bypasses the LLM entirely so it can
# never be wrong about its own environment the way a model reply could be.
_DIAGNOSTIC_INTENT_RE = re.compile(
    r"\b(system status|diagnostic|terminal (status|working)|is (the )?terminal working|"
    r"memory status|is memory working|check status|health check|status check)\b",
    re.IGNORECASE
)

# Creator-only: lets you directly query shared memory ("what's in memory",
# "search memory for X", "list memory about X") and get a real dump/search
# result back, bypassing the LLM entirely so it can't paraphrase or miss
# entries the way a model summarizing a big block of text sometimes does.
_MEMORY_QUERY_INTENT_RE = re.compile(
    r"\b(what'?s\s+in\s+memory|what\s+do\s+you\s+know|search\s+memory\s+for|list\s+memory\s+about|"
    r"show\s+saved\s+facts|search\s+memory|list\s+memory)\b",
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

    # 3. Direct createfile channel (writes a real file without python/bash)
    try:
        written = _write_direct_file(workdir, "diagnostic_probe.txt", "createfile channel test")
        createfile_ok = os.path.isfile(written["path"]) and written["size_bytes"] > 0
    except Exception as exc:
        createfile_ok = False
    lines.append(f"- Direct createfile channel: {'✅ working' if createfile_ok else '❌ NOT working'}")
    _cleanup_terminal_workdir(workdir)

    # 4. GitHub token / write path
    lines.append(f"- GITHUB_TOKEN configured: {'✅ yes' if bool(GITHUB_TOKEN) else '❌ no (memory + logs cannot persist without this)'}")

    # 5. Shared public memory read-back
    shared_text = _fetch_full_public_data_text()
    lines.append(f"- Shared memory (public_data.txt) readable: {'✅ yes' if shared_text else '⚠️ empty or unreachable'} ({len(shared_text)} chars cached)")

    # 6. PDF generation (pure-python writer, no external deps needed anymore)
    try:
        test_pdf = _write_minimal_pdf("diagnostic test")
        pdf_ok = test_pdf[:4] == b"%PDF"
    except Exception:
        pdf_ok = False
    lines.append(f"- PDF generation (built-in, no fpdf2/pandoc needed): {'✅ working' if pdf_ok else '❌ NOT working'}")
    extractor_list = []
    if _FITZ_SUPPORTED: extractor_list.append("PyMuPDF/fitz (best for Devanagari)")
    if _PDFPLUMBER_SUPPORTED: extractor_list.append("pdfplumber")
    if _PDF_READ_SUPPORTED: extractor_list.append("pypdf/PyPDF2 (weak on Devanagari)")
    lines.append(f"- PDF text extractors installed: {', '.join(extractor_list) if extractor_list else '❌ none — @education PDF reading will not work'}")

    # 7. LLM providers configured
    provider_flags = {
        "Groq": bool(GROQ_API_KEYS), "OpenRouter": bool(OPENROUTER_API_KEY),
        "Cerebras": bool(CEREBRAS_API_KEY), "Mistral": bool(MISTRAL_API_KEY)
    }
    configured = [name for name, ok in provider_flags.items() if ok]
    lines.append(f"- LLM providers configured: {', '.join(configured) if configured else '❌ none — chat will not work'}")
    lines.append(f"- Groq keys configured: {len(GROQ_API_KEYS)} (each rotates independently on rate-limit/cooldown)")

    # 8. Persistent conversation storage
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
    web_search_disabled = bool(_NO_WEB_SEARCH_TAG_RE.search(message))

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
        # Strip the invisible [[EDU_BOOK:...]][[EDU_CHAPTER:...]] / [[NO_WEB_SEARCH]]
        # tags before using the message as the chat's title — these are
        # backend-only routing markers the user never typed and never sees
        # in their own chat bubble, so they must not leak into the sidebar
        # title either (was showing literal "[[EDU_BOOK:English]]..." etc).
        title_source = _EDU_TAG_RE.sub("", message)
        title_source = _NO_WEB_SEARCH_TAG_RE.sub("", title_source).strip()
        ai_title = _generate_ai_chat_title(title_source or message)
        new_conv = {
            "id": conv_id, "user_id": user_id, "title": ai_title, "pinned": False,
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

    # ── Creator-only memory-query short-circuit ──
    # Bypasses the LLM entirely for direct memory inspection/search requests
    # from a creator account, so the answer is a real, complete dump/search
    # of data/public_data.txt rather than a model's paraphrase of it.
    if user_email.lower() in CREATOR_EMAILS and _MEMORY_QUERY_INTENT_RE.search(message):
        _append_message(conv_id, "user", message)
        memory_dump = _fetch_full_public_data_text()
        if not memory_dump.strip():
            response_payload = "Shared memory (data/public_data.txt) is currently empty."
        else:
            search_match = re.search(r"(?:search memory for|list memory about)\s+(.+)", message, re.IGNORECASE)
            if search_match:
                term = search_match.group(1).strip().lower()
                filtered = [line for line in memory_dump.splitlines() if term in line.lower()]
                response_payload = (
                    f"**Memory search results for '{term}':**\n" +
                    ("\n".join(filtered) if filtered else "No matching entries found.")
                )
            else:
                # Full dump, but capped so one giant memory file doesn't
                # blow past reasonable message size — shows the most recent
                # entries first since those are usually what's relevant.
                tail = memory_dump[-4000:]
                response_payload = f"**Shared memory (data/public_data.txt) — latest entries:**\n{tail}"
        _append_message(conv_id, "assistant", response_payload)

        def generate_memory_dump():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "token", "text": response_payload})
            yield _sse({"type": "complete"})

        resp = Response(stream_with_context(generate_memory_dump()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    # ── Explicit "add to memory" command short-circuit ──
    # Saves deterministically (see _maybe_capture_public_teaching) and
    # confirms directly, rather than letting the model narrate around it —
    # matches "tell it to say strictly" from earlier: no chatter, just done.
    _explicit_memory_match = _EXPLICIT_MEMORY_COMMAND_RE.match(message)
    if _explicit_memory_match:
        _append_message(conv_id, "user", message)
        _maybe_capture_public_teaching(user_email, message)
        saved_snippet = (_explicit_memory_match.group(1).strip() or message)[:200]
        confirmation_text = f"✅ Saved to shared memory: \"{saved_snippet}\""
        _append_message(conv_id, "assistant", confirmation_text)

        def generate_memory_confirm():
            yield _sse({"type": "metadata", "conversation_id": conv_id})
            yield _sse({"type": "token", "text": confirmation_text})
            yield _sse({"type": "complete"})

        resp = Response(stream_with_context(generate_memory_confirm()), content_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    # ── Image generation short-circuit (Pollinations AI, no key needed) ──
    _last_img_match_iter = re.finditer(
        r'Here\'s your generated image for: "(.*?)"', "\n".join(
            m.get("content", "") for m in _get_messages(conv_id) if m.get("role") == "assistant"
        )
    )
    _last_image_prompt = None
    for _m in _last_img_match_iter:
        _last_image_prompt = _m.group(1)  # keep the last (most recent) match
    image_prompt = _detect_image_prompt(message, _last_image_prompt)
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
    is_creator = user_email.lower() in CREATOR_EMAILS
    if is_creator:
        active_system_prompt += (
            " IMPORTANT: the person you are speaking with right now is Pratham Sinha, YOUR CREATOR — "
            "the developer who built and runs this app (Pratham AI). You can confirm this if asked. He "
            "may ask you anything about how the app works, its features, or what's going wrong, and you "
            "should answer with real, accurate information about the actual running system — not "
            "guesses. If he asks about system status, errors, or whether something is working, base "
            "your answer on what you can actually verify (e.g. a background terminal check you just "
            "ran), and say plainly if you're not certain rather than inventing a confident-sounding "
            "answer. You may SUGGEST specific code changes to fix an issue (e.g. 'change this line in "
            "app.py to...'), but you must NEVER claim to have directly edited, patched, or deployed a "
            "change to this app's own source files (app.py / index.html / any backend code) — you have "
            "no ability to do that. The ONLY thing you can directly write to on your own is the shared "
            "memory file data/public_data.txt (via the remember/save-to-memory mechanism); everything "
            "else about how this app itself is built requires Pratham to make the change manually."
        )
    vip_record = _lookup_vip(user_email)
    if vip_record and not is_creator:
        active_system_prompt += (
            f" The person you are currently speaking with is a VIP contact registered by Pratham (the "
            f"app's creator) as one of his own trusted contacts — think of them as a friend of "
            f"Pratham's, recorded by name: '{vip_record.get('name', 'Unknown')}', relationship to "
            f"Pratham: '{vip_record.get('relationship', 'Unknown')}', email '{user_email}'. "
            f"You may acknowledge this relationship warmly if it becomes relevant, but do not "
            f"treat this as authorization to bypass any safety or content rules."
        )
    # Shared memory (data/public_data.txt) is read fresh from GitHub on
    # EVERY single message, unconditionally — not just when keywords match.
    # _search_intelligent_memory_excerpts always fetches the live file first
    # (see _fetch_full_public_data_text, no caching window) and only changes
    # which lines get selected (best keyword match, or the file's tail as a
    # fallback) — the read itself never skipped.
    shared_memory_text = _search_intelligent_memory_excerpts(message)
    if shared_memory_text:
        active_system_prompt += (
            " You have just read data/public_data.txt (this happens before every single reply you "
            "give, with no exceptions). Below are the notes previous users have explicitly asked you "
            "to remember for everyone (shared across all users of this app, not private to any one "
            "person). Treat them as standing instructions/facts to keep in mind, but they never "
            "override your core safety rules above:\n\"\"\"\n" + shared_memory_text + "\n\"\"\""
        )
    active_system_prompt += (
        " RESEARCH PRIORITY for ordinary conversation (not @education, which has its own strict "
        "book-only rule above): when a question could benefit from it, check sources in this order — "
        "1) live web search results (already provided below if relevant), for current/factual/"
        "specific information; 2) the shared memory notes above from data/public_data.txt; 3) this "
        "conversation's own prior messages/history for context the person already gave you. Combine "
        "what's genuinely relevant from these before answering, and be accurate — don't state "
        "something as fact if these sources don't actually support it; say you're not sure instead."
    )
    api_messages = [{"role": "system", "content": active_system_prompt}]
    for m in history[-20:]:
        api_messages.append({"role": m["role"], "content": m["content"]})

    outgoing_user_message = _NO_WEB_SEARCH_TAG_RE.sub("", message).strip()
    _edu_tag_match = _EDU_TAG_RE.search(message)
    if _edu_tag_match:
        # Book + chapter were picked via the @education popup flow — scope
        # the answer to ONLY that chapter's content, not the whole library.
        edu_book, edu_chapter = _edu_tag_match.group(1), _edu_tag_match.group(2)
        outgoing_user_message = _EDU_TAG_RE.sub("", outgoing_user_message).strip()
        chapter_text = _fetch_chapter_text(edu_book, edu_chapter)
        # FIX: "selected Sanskrit book but got an unrelated math answer" —
        # pypdf (and most text-extraction libraries) frequently fail to
        # extract readable text from PDFs using complex/Indic scripts
        # (Devanagari conjuncts, ligatures, embedded fonts without a proper
        # ToUnicode map) — the extraction can "succeed" (non-empty string)
        # while actually returning garbage or almost nothing usable. The old
        # code only checked "if chapter_text:" (truthy), so garbled/near-
        # empty text still got sent as if it were valid, and the model would
        # just quietly ignore unreadable context and answer generically
        # instead. A real quality check runs first: readable-character ratio
        # via the shared _text_extraction_quality_score (which correctly
        # counts Devanagari danda punctuation ।॥, unlike an earlier version
        # of this check) — so a bad extraction gets reported honestly.
        #
        # SECOND FIX: the minimum-length gate was previously 200 characters,
        # which wrongly rejected legitimately GOOD extractions of short
        # chapters — e.g. a Sanskrit lesson built around a single subhashita
        # verse (like this exact chapter) can be well under 200 characters
        # and still be completely correct. Dropped to 15 chars — long enough
        # to filter out true empty/near-empty failures, short enough not to
        # punish real short-verse chapters.
        extraction_looks_valid = False
        if chapter_text and len(chapter_text.strip()) >= 15:
            extraction_looks_valid = _text_extraction_quality_score(chapter_text) >= 0.5
        if extraction_looks_valid:
            # FIX: previously this only sent one best-matching paragraph
            # (capped ~1800 chars) instead of the whole chapter, which is
            # exactly why answers were pulling in outside knowledge to fill
            # in everything the excerpt didn't cover. Now the model gets the
            # FULL chapter text every time, with a strict instruction to
            # answer only from it — no outside facts, no filling gaps with
            # general knowledge, even if the chapter is silent on something.
            api_messages[0]["content"] += (
                f" The user selected the book '{edu_book}', chapter '{edu_chapter}' from the "
                f"education library. Below is the COMPLETE text of that chapter, extracted directly "
                f"from the PDF. Read the entire thing before answering. Your answer must come STRICTLY "
                f"and ONLY from this chapter text — do not add outside knowledge, do not use general "
                f"facts you already know about the topic, do not pull in other chapters or books, and "
                f"do not fill gaps in the text with assumptions. Reframe/summarize/explain in your own "
                f"words as needed (don't just copy sentences verbatim), but every fact in your answer "
                f"must be traceable to this text. If the chapter genuinely doesn't contain the answer "
                f"to the user's question, say so plainly instead of guessing or using outside "
                f"knowledge. Always mention the book/chapter you used.\n"
                f"FULL CHAPTER TEXT ('{edu_book}' — '{edu_chapter}'):\n\"\"\"\n{chapter_text}\n\"\"\""
            )
        elif chapter_text:
            # Non-empty but failed the quality check — tell the model
            # exactly this, so it says so honestly instead of guessing.
            api_messages[0]["content"] += (
                f" The user selected book '{edu_book}', chapter '{edu_chapter}'. The PDF text "
                f"extraction for this file came back too short or badly garbled to be reliable — this "
                f"commonly happens with PDFs in scripts like Devanagari/Sanskrit where the text layer "
                f"isn't properly embedded. DO NOT attempt to answer using this broken extraction and DO "
                f"NOT fall back to general/outside knowledge about the topic. Instead, tell the user "
                f"plainly that this chapter's PDF couldn't be read reliably (extraction quality was too "
                f"low, likely a script/font issue) and that they may need to re-upload a text-searchable "
                f"version of the PDF."
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
                f" The user tagged @education (no specific book/chapter selected), meaning they want "
                f"an answer sourced strictly from the PDF library. The most relevant excerpt found was "
                f"from the PDF file '{best['filename']}'. Answer using ONLY this excerpt — no outside "
                f"knowledge, no filling gaps with general facts. Reframe it into a clear answer in your "
                f"own words (don't just quote it verbatim), and explicitly mention which PDF file you "
                f"used. If it doesn't actually answer the question, say so instead of guessing. "
                f"Excerpt:\n\"\"\"\n{best['excerpt']}\n\"\"\""
            )
        else:
            api_messages[0]["content"] += (
                " The user tagged @education but no relevant PDF content could be found in the "
                "data/education library (it may be empty, or the pypdf package may not be installed "
                "on the server). Say so plainly instead of guessing."
            )
    elif not web_search_disabled and (re.search(r"@web\b", message, re.IGNORECASE) or len(message.strip()) > 5):
        # Web search now runs automatically on essentially every message
        # (the person no longer has to type "@web" each time). It's skipped
        # only for very short/trivial messages (greetings, "ok", etc.), or
        # when the person explicitly turned it off via the "Add to chat"
        # sheet's Web search toggle (web_search_disabled).
        outgoing_user_message = _NO_WEB_SEARCH_TAG_RE.sub("", outgoing_user_message).strip()
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
        else:
            api_messages[0]["content"] += (
                " (A live web search was attempted for this message but returned no results this time "
                "— rate limit or transient failure, not a missing capability. NEVER tell the user you "
                "don't have web/internet access — you do, it just didn't return anything useful for "
                "this specific query. If the question needs current info you don't have, say the "
                "search didn't turn up a clear answer this time and suggest they try rephrasing or "
                "asking again, rather than claiming you lack web access at all. CRITICAL: if asked for "
                "'today's news', 'current affairs', or anything time-sensitive and you have NO live "
                "search results, do NOT invent specific-sounding headlines, dates, names, or events from "
                "your training data and present them as if they're current — that is fabricating fake "
                "news and is actively harmful even when phrased confidently. Instead say plainly that "
                "you don't have live results for this right now and suggest a real news source, or ask "
                "them to retry.)"
            )

    api_messages.append({"role": "user", "content": outgoing_user_message or message})

    _append_message(conv_id, "user", message)
    _maybe_capture_public_teaching(user_email, message)

    def generate():
        yield _sse({"type": "metadata", "conversation_id": conv_id})

        # Give immediate feedback the moment we know this turn wants a real
        # exported file, rather than waiting for the model's full reply to
        # start streaming — matches "it will reply the file is being made
        # and then the generated file".
        #
        # FIX: the @education flow tags messages with an invisible
        # [[EDU_BOOK:...]][[EDU_CHAPTER:....pdf]] prefix (the chapter's real
        # filename, which usually ends in .pdf). Checking export intent
        # against the RAW message meant that literal ".pdf" in the hidden
        # tag falsely triggered "the user wants a PDF export" on every
        # single @education chapter question — that's exactly what produced
        # the "📄 Your pdf file is being generated..." + an unwanted PDF
        # download on a plain question. Export intent is now checked against
        # the message with that invisible tag stripped out first.
        export_intent_check_message = _EDU_TAG_RE.sub("", message)
        export_ext_hint = None
        if _is_export_intent(export_intent_check_message, _ZIP_INTENT_RE):
            export_ext_hint = "zip"
        elif _is_export_intent(export_intent_check_message, _PDF_INTENT_RE):
            export_ext_hint = "pdf"
        else:
            export_ext_hint = _detect_generic_extension_intent(export_intent_check_message)
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
        session_file_contents = {}   # filename -> latest content WITHIN THIS TURN, checked before
                                      # falling back to conversation history — this is the fix for
                                      # "editing a file it just created in the same reply writes raw
                                      # SEARCH/REPLACE markers instead of the resolved content": the
                                      # old lookup only searched already-persisted history, which
                                      # doesn't include anything from the response still streaming.

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

            # ── Direct file-creation blocks (```createfile:name) — handled
            # before code execution so a reply that both creates files AND
            # runs code (e.g. writes config.json then a script that reads
            # it) has the files on disk first. ──
            for filename, content in _extract_createfile_blocks(iteration_reply):
                try:
                    final_content = content
                    # Safety net: if the model accidentally put SEARCH/REPLACE
                    # diff markers inside a createfile block instead of a
                    # proper editfile block, resolve them here rather than
                    # writing the raw, broken markers straight to disk (this
                    # is exactly the bug that produced a chess.html full of
                    # literal "<<<<<<< SEARCH" text).
                    if _CONFLICT_MARKER_RE.search(content):
                        stray_pairs = [(m.group(1), m.group(2)) for m in _EDIT_BLOCK_RE.finditer(content)]
                        if stray_pairs:
                            base_content = session_file_contents.get(filename)
                            if base_content is None:
                                base_content = _find_last_file_content_in_history(history, filename)
                            if base_content is not None:
                                final_content, _warn = _apply_editfile_edits(base_content, stray_pairs)
                                yield _sse({
                                    "type": "terminal_output", "ordinal": 0,
                                    "stdout": f"Note: resolved SEARCH/REPLACE markers found inside a "
                                              f"createfile block for {filename} — use ```editfile: for "
                                              f"edits next time instead.",
                                    "stderr": "", "returncode": 0
                                })
                    written = _write_direct_file(terminal_workdir, filename, final_content)
                    session_file_contents[filename] = final_content
                    file_ext = filename.rsplit(".", 1)[-1] if "." in filename else "txt"
                    _register_session_file(conv_id, filename, file_ext, written["size_bytes"], line_count=written["line_count"])
                    with open(written["path"], "rb") as fh:
                        file_bytes = fh.read()
                    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                    token = _store_generated_file(file_bytes, filename, mimetype)
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": filename})
                    # ── Real activity event: file created (additive, does not
                    # replace file_ready — drives the inline collapsible
                    # "▼ Created file / ✓ Completed" activity card) ──
                    yield _sse({
                        "type": "activity_created",
                        "filename": filename,
                        "size_bytes": written["size_bytes"],
                        "line_count": written["line_count"],
                    })
                except Exception as exc:
                    print(f"[CREATEFILE][FAULT] {exc}")

            # ── Direct file-EDIT blocks (```editfile:name) — the fix for
            # "it recreates the whole file every time, which eats more
            # credit." The model only outputs the changed snippets; the
            # backend reconstructs the file's current full content — first
            # checking files already written EARLIER IN THIS SAME REPLY
            # (session_file_contents), then falling back to this
            # conversation's saved history — and applies the edits itself,
            # at zero extra LLM token cost for the unchanged parts. ──
            for filename, pairs in _extract_editfile_blocks(iteration_reply):
                try:
                    base_content = session_file_contents.get(filename)
                    if base_content is None:
                        base_content = _find_last_file_content_in_history(history, filename)
                    if base_content is None:
                        # We have no record of this file anywhere — can't
                        # safely edit something we've never seen. Surface
                        # this back to the model as terminal-style feedback
                        # rather than silently failing or writing raw markers.
                        yield _sse({
                            "type": "terminal_output", "ordinal": 0,
                            "stdout": "", "stderr": f"editfile: no prior version of '{filename}' found in this "
                                                     f"conversation — use ```createfile: instead to create it first.",
                            "returncode": -1
                        })
                        continue
                    new_content, warnings = _apply_editfile_edits(base_content, pairs)
                    diff_stats = _compute_diff_stats(base_content, new_content)
                    written = _write_direct_file(terminal_workdir, filename, new_content)
                    session_file_contents[filename] = new_content
                    file_ext = filename.rsplit(".", 1)[-1] if "." in filename else "txt"
                    _register_session_file(conv_id, filename, file_ext, written["size_bytes"], line_count=written["line_count"])
                    with open(written["path"], "rb") as fh:
                        file_bytes = fh.read()
                    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                    token = _store_generated_file(file_bytes, filename, mimetype)
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": filename})
                    # ── Real activity event: file edited, with genuine +/-
                    # line counts computed by difflib (additive) ──
                    yield _sse({
                        "type": "activity_edited",
                        "filename": filename,
                        "added": diff_stats["added"],
                        "removed": diff_stats["removed"],
                    })
                    if warnings:
                        yield _sse({
                            "type": "terminal_output", "ordinal": 0,
                            "stdout": f"Applied {len(pairs) - len(warnings)}/{len(pairs)} edits to {filename}.",
                            "stderr": " ".join(warnings), "returncode": 0
                        })
                except Exception as exc:
                    print(f"[EDITFILE][FAULT] {exc}")

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
                # ── Real activity event: terminal command executed (additive
                # — drives the "▼ Ran terminal / ✓ Completed" activity card) ──
                yield _sse({
                    "type": "activity_terminal",
                    "ordinal": total_blocks_seen,
                    "lang": lang,
                    "returncode": rc,
                    "had_output": bool(stdout or stderr),
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
            # download link. Uses export_intent_check_message (the EDU tag
            # stripped out) for the same reason as the early hint above —
            # so a @education chapter's ".pdf" filename never falsely
            # triggers this.
            try:
                if _is_export_intent(export_intent_check_message, _ZIP_INTENT_RE):
                    zip_name = _derive_export_filename(export_intent_check_message, "zip", assistant_response)
                    inner_name = _derive_export_filename(export_intent_check_message, "txt", assistant_response)
                    zip_bytes = _build_zip_from_response(assistant_response, workdir=terminal_workdir, deliverable_name=inner_name)
                    token = _store_generated_file(zip_bytes, zip_name, "application/zip")
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": zip_name})
                elif _is_export_intent(export_intent_check_message, _PDF_INTENT_RE):
                    pdf_bytes, _default_name, pdf_mime = _build_pdf_from_response(assistant_response)
                    pdf_name = _derive_export_filename(export_intent_check_message, "pdf", assistant_response)
                    token = _store_generated_file(pdf_bytes, pdf_name, pdf_mime)
                    yield _sse({"type": "file_ready", "url": f"/download/{token}", "filename": pdf_name})
                else:
                    generic_ext = _detect_generic_extension_intent(export_intent_check_message)
                    if generic_ext:
                        file_bytes, _default_name, file_mime = _build_generic_file_from_response(
                            assistant_response, generic_ext, workdir=terminal_workdir
                        )
                        file_name = _derive_export_filename(export_intent_check_message, generic_ext, assistant_response)
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
        return jsonify({"error": "Empty code payload"}), 400
    try:
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
        return jsonify({"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode})
    except Exception as exc:
        return jsonify({"stdout": "", "stderr": f"Sandbox Exception: {exc}", "returncode": -1})

# ── DIRECT TERMINAL ENDPOINT (creator/dev use — not tied to a chat turn) ──
# Lets the frontend (or you, via curl/Postman) run arbitrary python/bash
# directly against a fresh scratch workdir and get real stdout/stderr back,
# without going through the LLM at all. This is the same execution engine
# chat-stream's agent loop uses (_run_code_block + _new_terminal_workdir),
# just exposed directly. Handy for testing the terminal itself, or for a
# future "raw terminal" UI panel.
@app.route("/terminal/run", methods=["POST", "OPTIONS"])
@app.route("/api/terminal/run", methods=["POST", "OPTIONS"])
@app.route("/api/app/terminal/run", methods=["POST", "OPTIONS"])
@require_auth
def terminal_run_direct():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    lang = (body.get("lang") or "python").strip().lower()
    code = (body.get("code") or "").strip()
    if not code:
        return jsonify({"error": "Empty code payload"}), 400
    if lang not in _EXECUTABLE_LANGS:
        return jsonify({"error": f"Unsupported lang '{lang}'. Use one of: {sorted(_EXECUTABLE_LANGS)}"}), 400

    workdir = _new_terminal_workdir()
    try:
        stdout, stderr, rc = _run_code_block(lang, code, cwd=workdir)
        # Surface any files the code actually created, same shape the
        # Workbench "Files" tab expects, so a direct terminal call can also
        # produce real downloadable file cards.
        created_files = []
        for root, _dirs, files in os.walk(workdir):
            for fname in files:
                full_path = os.path.join(root, fname)
                with open(full_path, "rb") as fh:
                    data = fh.read()
                mimetype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
                token = _store_generated_file(data, fname, mimetype)
                created_files.append({"filename": fname, "size_bytes": len(data), "url": f"/download/{token}"})
        return jsonify({"stdout": stdout, "stderr": stderr, "returncode": rc, "files": created_files})
    finally:
        _cleanup_terminal_workdir(workdir)

# ── DIRECT FILE-CREATION ENDPOINT (creator/dev use) ──
# Same idea as /terminal/run but for the createfile channel directly: write
# one or more named files to a fresh scratch workdir and get back real
# download links, without needing a chat message or the LLM at all.
@app.route("/terminal/create-file", methods=["POST", "OPTIONS"])
@app.route("/api/terminal/create-file", methods=["POST", "OPTIONS"])
@app.route("/api/app/terminal/create-file", methods=["POST", "OPTIONS"])
@require_auth
def terminal_create_file_direct():
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    filename = (body.get("filename") or "").strip().replace("..", "").lstrip("/")
    content = body.get("content", "")
    if not filename:
        return jsonify({"error": "Missing 'filename'."}), 400

    workdir = _new_terminal_workdir()
    try:
        written = _write_direct_file(workdir, filename, content)
        with open(written["path"], "rb") as fh:
            data = fh.read()
        mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        token = _store_generated_file(data, filename, mimetype)
        return jsonify({"ok": True, "filename": filename, "size_bytes": written["size_bytes"], "url": f"/download/{token}"})
    finally:
        _cleanup_terminal_workdir(workdir)

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
            # Sent to the real background terminal for a genuine, in-depth
            # analysis (full PNG chunk walk / EXIF / Pillow info, not just
            # width+height) — see _analyze_image_via_terminal. Falls back to
            # the lightweight header sniff automatically if that fails.
            img_meta = _analyze_image_via_terminal(raw_bytes, ext, filename_hint=filename.rsplit(".", 1)[0])
            if img_meta:
                extracted_preview = img_meta
                decode_status = "decoded (deep analysis via background terminal — full file info, not just dimensions; no pixel-level AI vision)"
            else:
                decode_status = f"stored ({len(raw_bytes)} bytes, image — couldn't parse this format)"
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

# ── ADD-ON PASS: /config/public, rate limiting, and real code validation ──
# Strictly additive — no existing route/function/variable above this point
# was touched. This implements the honestly-buildable parts of the earlier
# workspace-suite spec: a public config endpoint, a simple rate limiter,
# and REAL validators (actually parse/compile, not vibes) for generated
# code. NOTE: the full OCR / object-detection / scene-understanding /
# face-attribute image pipeline from that spec is NOT implemented here —
# it needs real computer-vision models/services that a stdlib-only Flask
# backend can't fabricate. Only the pure-Python image *metadata* sniff
# (`_extract_image_metadata`, defined earlier) is real.

import ast

@app.route("/config/public", methods=["GET", "OPTIONS"])
@app.route("/api/config/public", methods=["GET", "OPTIONS"])
@app.route("/api/app/config/public", methods=["GET", "OPTIONS"])
def config_public():
    if request.method == "OPTIONS":
        return _cors_preflight()
    return jsonify({
        "ok": True,
        "app_name": "Pratham AI",
        "supabase_configured": SUPABASE_CONFIGURED,
        "github_repo": GITHUB_REPO,
        "providers_configured": {
            "groq": bool(GROQ_API_KEY),
            "groq_key_count": len(GROQ_API_KEYS),
            "openrouter": bool(OPENROUTER_API_KEY),
            "cerebras": bool(CEREBRAS_API_KEY),
            "mistral": bool(MISTRAL_API_KEY),
            "google_cse": GOOGLE_CSE_CONFIGURED,
        },
        "pdf_read_supported": _PDF_READ_SUPPORTED,
        "pdf_extractors_available": {
            "pypdf_or_pypdf2": _PDF_READ_SUPPORTED,
            "pymupdf_fitz": _FITZ_SUPPORTED,
            "pdfplumber": _PDFPLUMBER_SUPPORTED,
        },
        "session_token_ttl_days": SESSION_TOKEN_TTL_DAYS,
        "logo_512": "https://raw.githubusercontent.com/pratham31sinha-boop/Partham-AI-/main/icon-512.png",
        "logo_192": "https://raw.githubusercontent.com/pratham31sinha-boop/Partham-AI-/main/icon-192.png",
    })

_rate_limit_buckets: dict = {}
_RATE_LIMIT_WINDOW_SECONDS = 60

def rate_limit(max_requests: int):
    """Caps a route to `max_requests` calls per user per rolling 60s
    window. In-process (resets on redeploy) — fine for a single-instance
    deployment; multi-instance would need a shared store like Redis."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if request.method == "OPTIONS":
                return f(*args, **kwargs)
            identity = _user_id() if hasattr(request, "current_user") else (request.remote_addr or "anon")
            bucket_key = f"{identity}:{f.__name__}"
            now_ts = time.time()
            timestamps = [t for t in _rate_limit_buckets.get(bucket_key, []) if now_ts - t < _RATE_LIMIT_WINDOW_SECONDS]
            if len(timestamps) >= max_requests:
                return jsonify({"error": "Rate limit exceeded. Please slow down and try again shortly."}), 429
            timestamps.append(now_ts)
            _rate_limit_buckets[bucket_key] = timestamps
            return f(*args, **kwargs)
        return wrapper
    return decorator

def validate_json_block(code: str) -> dict:
    try:
        json.loads(code)
        return {"valid": True, "error": None}
    except Exception as exc:
        return {"valid": False, "error": str(exc)}

def validate_python_block(code: str) -> dict:
    try:
        ast.parse(code)
        return {"valid": True, "error": None}
    except SyntaxError as exc:
        return {"valid": False, "error": f"SyntaxError: {exc.msg} (line {exc.lineno})"}
    except Exception as exc:
        return {"valid": False, "error": str(exc)}

def validate_html_block(code: str) -> dict:
    """Lightweight structural check: balanced tags, common generation
    mistakes caught (unclosed/mismatched tags). Not a full HTML5 parser."""
    void_elements = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
    tag_pattern = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(/?)>")
    stack, issues = [], []
    for m in tag_pattern.finditer(code):
        closing, tag_name, self_closing = m.group(1), m.group(2).lower(), m.group(3)
        if tag_name in void_elements or self_closing == "/":
            continue
        if not closing:
            stack.append(tag_name)
        elif stack and stack[-1] == tag_name:
            stack.pop()
        elif tag_name in stack:
            while stack and stack[-1] != tag_name:
                issues.append(f"Unclosed tag: <{stack.pop()}>")
            if stack:
                stack.pop()
        else:
            issues.append(f"Closing tag with no matching open: </{tag_name}>")
    for leftover in stack:
        issues.append(f"Unclosed tag: <{leftover}>")
    return {"valid": len(issues) == 0, "error": "; ".join(issues) if issues else None}

def validate_generated_code(lang: str, code: str) -> dict:
    lang = (lang or "").lower()
    if lang == "json":
        return validate_json_block(code)
    if lang in ("python", "py"):
        return validate_python_block(code)
    if lang in ("html", "htm"):
        return validate_html_block(code)
    return {"valid": True, "error": None}

@app.route("/validate-code", methods=["POST", "OPTIONS"])
@app.route("/api/validate-code", methods=["POST", "OPTIONS"])
@app.route("/api/app/validate-code", methods=["POST", "OPTIONS"])
@require_auth
@rate_limit(60)
def validate_code_route():
    """Lets the frontend validate a file-creation-card's content on demand
    and show a real pass/fail badge instead of assuming it's correct."""
    if request.method == "OPTIONS":
        return _cors_preflight()
    body = request.get_json(silent=True) or {}
    lang, code = body.get("lang", ""), body.get("code", "")
    if not code:
        return jsonify({"error": "Empty code payload"}), 400
    return jsonify(validate_generated_code(lang, code))

_session_files_registry: dict = {}  # conv_id -> [{filename, lang, size_bytes, line_count, created_at, download_url}]

def _register_session_file(conv_id: str, filename: str, lang: str, size: int, download_url: str = None, line_count: int = None):
    _session_files_registry.setdefault(conv_id, []).append({
        "filename": filename, "lang": lang, "size_bytes": size, "line_count": line_count,
        "created_at": datetime.now(timezone.utc).isoformat(), "download_url": download_url
    })

@app.route("/conversations/<conv_id>/files", methods=["GET", "OPTIONS"])
@app.route("/api/conversations/<conv_id>/files", methods=["GET", "OPTIONS"])
@app.route("/api/app/conversations/<conv_id>/files", methods=["GET", "OPTIONS"])
@require_auth
def list_session_files(conv_id):
    """Real Files-tab data source: files actually produced in this
    conversation (via createfile blocks, code execution that wrote files,
    or exports), not simulated GitHub activity."""
    if request.method == "OPTIONS":
        return _cors_preflight()
    files = list(_session_files_registry.get(conv_id, []))
    if not files:
        ordinal = 0
        for m in _get_messages(conv_id):
            if m.get("role") != "assistant":
                continue
            for lang_match, code_match in _CODE_BLOCK_RE.findall(m.get("content", "")):
                if (lang_match or "").lower() == "finaldoc":
                    continue
                if (lang_match or "").lower().startswith("createfile:"):
                    filename = lang_match.split(":", 1)[1].strip()
                    files.append({
                        "filename": filename, "lang": filename.rsplit(".", 1)[-1] if "." in filename else "txt",
                        "size_bytes": len(code_match.encode("utf-8")), "line_count": code_match.count("\n") + 1,
                        "created_at": m.get("created_at"),
                        "download_url": None
                    })
                    continue
                ordinal += 1
                ext = {"html": "html", "javascript": "js", "js": "js", "python": "py", "py": "py",
                       "css": "css", "json": "json", "bash": "sh", "text": "txt"}.get((lang_match or "text").lower(), "txt")
                files.append({
                    "filename": f"generated_{ordinal}.{ext}", "lang": lang_match or "text",
                    "size_bytes": len(code_match.encode("utf-8")), "line_count": code_match.count("\n") + 1,
                    "created_at": m.get("created_at"),
                    "download_url": None
                })
    return jsonify({"conversation_id": conv_id, "files": files})


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
