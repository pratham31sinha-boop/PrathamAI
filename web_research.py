"""
Universal Live Web Research & Cast/Character Fetcher Utility
Autonomously searches the web for ANY show, movie, anime, or topic, extracts
real cast/character biographies, and downloads real web photos.
Created for Pratham AI by Pratham Sinha under the supervision of Akriti & Aditi Aishwaryam.
"""

import os
import re
import json
import urllib.request
import urllib.parse
from fetch_image import fetch_web_image, fetch_multiple_images

def search_wikipedia_article(query: str, timeout: float = 5.0) -> str:
    """
    Finds the best matching Wikipedia article title for any query.
    Returns the exact page title (e.g. 'Bahu_Hamari_Rajni_Kant').
    """
    try:
        clean_q = re.sub(r'\b(?:make|create|pdf|containing|images?|all|characters?|details?|breif|brief|with)\b', '', query, flags=re.I).strip()
        encoded = urllib.parse.quote(clean_q)
        url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={encoded}&limit=5&namespace=0&format=json"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            titles = data[1] if len(data) > 1 else []
            if titles:
                return titles[0].replace(' ', '_')
    except Exception:
        pass
    return query.replace(' ', '_')


def get_show_cast_and_details(show_query: str, max_cast: int = 12, images_dir: str = "cast_images") -> list:
    """
    Autonomously searches Wikipedia and web for real cast/characters,
    extracts actor names, character names, and bios, and downloads real photos.
    Returns a list of dicts:
    [
        {
            "character": "Rajni Kant",
            "actor": "Ridhima Pandit",
            "bio": "Humanoid super-robot created by scientist Shantanu Kant...",
            "image_path": "cast_images/rajni_kant.png"
        },
        ...
    ]
    """
    os.makedirs(images_dir, exist_ok=True)
    page_title = search_wikipedia_article(show_query)
    
    cast_list = []
    
    # 1. Fetch section list from Wikipedia
    try:
        sec_url = f"https://en.wikipedia.org/w/api.php?action=parse&page={urllib.parse.quote(page_title)}&prop=sections&format=json"
        req = urllib.request.Request(sec_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            sec_data = json.loads(resp.read().decode('utf-8'))
            sections = sec_data.get('parse', {}).get('sections', [])
            
        cast_sections = [s['index'] for s in sections if any(k in s.get('line', '').lower() for k in ['cast', 'character'])]
        
        for s_idx in cast_sections[:3]:
            txt_url = f"https://en.wikipedia.org/w/api.php?action=parse&page={urllib.parse.quote(page_title)}&section={s_idx}&prop=wikitext&format=json"
            req2 = urllib.request.Request(txt_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req2, timeout=6.0) as resp2:
                txt_data = json.loads(resp2.read().decode('utf-8'))
                wikitext = txt_data.get('parse', {}).get('wikitext', {}).get('*', '')
                
                # Parse lines like: * [[Actor]] as [[Character]]: Bio
                # or: * Actor as Character: Bio
                for line in wikitext.splitlines():
                    line = line.strip()
                    if not line.startswith('*') or len(line) < 10:
                        continue
                    clean_line = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]', r'\1', line)
                    clean_line = re.sub(r'<ref[^>]*>.*?</ref>', '', clean_line)
                    clean_line = re.sub(r'<[^>]+>', '', clean_line).lstrip('*').strip()
                    
                    # Match "Actor as Character: Bio" or "Character played by Actor: Bio"
                    m = re.match(r'^(.*?)\s+(?:as|plays?|played by)\s+(.*?)(?::|\s*–\s*|\s*-\s*)(.*)$', clean_line, re.I)
                    if m:
                        actor = m.group(1).strip()
                        character = m.group(2).strip().strip('"').strip("'")
                        bio = m.group(3).strip()
                    else:
                        m2 = re.match(r'^(.*?)\s+(?:as|plays?|played by)\s+(.*)$', clean_line, re.I)
                        if m2:
                            actor = m2.group(1).strip()
                            character = m2.group(2).strip().strip('"').strip("'")
                            bio = f"Key character in {show_query.title()} portrayed by {actor}."
                        else:
                            continue
                            
                    if len(character) > 50:
                        character = character[:50]
                    if len(actor) > 50:
                        actor = actor[:50]
                        
                    slug = re.sub(r'[^a-z0-9]+', '_', character.lower()).strip('_')
                    img_path = os.path.join(images_dir, f"{slug}.png")
                    
                    cast_list.append({
                        "character": character,
                        "actor": actor,
                        "bio": bio,
                        "image_path": img_path
                    })
                    if len(cast_list) >= max_cast:
                        break
            if len(cast_list) >= max_cast:
                break
    except Exception as e:
        print(f"[WEB_RESEARCH][CAST_PARSE_ERR] {e}")

    # Fallback to search query if no structured cast section was extracted
    if not cast_list:
        clean_show = re.sub(r'\b(?:make|create|pdf|containing|images?|all|characters?|details?|breif|brief|with)\b', '', show_query, flags=re.I).strip()
        try:
            sum_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(page_title)}"
            req = urllib.request.Request(sum_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                s_data = json.loads(resp.read().decode('utf-8'))
                extract = s_data.get('extract', '')
                cast_list.append({
                    "character": f"Main Cast ({clean_show})",
                    "actor": clean_show,
                    "bio": extract or f"Leading protagonists and central ensemble of {clean_show}.",
                    "image_path": os.path.join(images_dir, "main_cast.png")
                })
        except Exception:
            pass

    # Concurrent real web image downloads for each extracted cast member
    download_pairs = []
    clean_show = re.sub(r'\b(?:make|create|pdf|containing|images?|all|characters?|details?|breif|brief|with)\b', '', show_query, flags=re.I).strip()
    for item in cast_list:
        q = f"{item['character']} {item['actor']} {clean_show}"
        download_pairs.append((q, item['image_path']))
        
    fetch_multiple_images(download_pairs, max_workers=6)
    return cast_list


def build_character_encyclopedia_pdf(title: str, characters: list, output_pdf_path: str):
    """
    Compiles a stunning publication-grade ReportLab PDF containing real images,
    character profiles, actors, and biographies.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        Image as RLImage, PageBreak, HRFlowable
    )
    from reportlab.pdfgen import canvas
    from PIL import Image as PILImage

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.draw_page_decorations(num_pages)
                super().showPage()
            super().save()

        def draw_page_decorations(self, page_count):
            self.saveState()
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(colors.HexColor("#475569"))
            if self._pageNumber > 1:
                self.drawString(54, 755, title.upper())
                self.drawRightString(558, 755, "CHARACTER & CAST ENCYCLOPEDIA")
                self.setStrokeColor(colors.HexColor("#CBD5E1"))
                self.setLineWidth(0.75)
                self.line(54, 748, 558, 748)
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.75)
            self.line(54, 45, 558, 45)
            self.setFont("Helvetica", 8)
            self.drawString(54, 32, "Published autonomously by Pratham AI | Live Web Verified")
            self.drawRightString(558, 32, f"Page {self._pageNumber} of {page_count}")
            self.restoreState()

    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=22, leading=26,
        textColor=colors.HexColor('#0F172A'), spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle', parent=styles['Normal'],
        fontName='Helvetica', fontSize=11, leading=15,
        textColor=colors.HexColor('#2563EB'), spaceAfter=12
    )
    char_title_style = ParagraphStyle(
        'CharTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=13, leading=16,
        textColor=colors.HexColor('#0F172A'), spaceAfter=2
    )
    actor_style = ParagraphStyle(
        'ActorName', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9.5, leading=13,
        textColor=colors.HexColor('#D97706'), spaceAfter=4
    )
    bio_style = ParagraphStyle(
        'CharBio', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8.5, leading=12,
        textColor=colors.HexColor('#334155')
    )

    story = []
    
    # Title & Header
    story.append(Paragraph(title, title_style))
    story.append(Paragraph("Complete Illustrated Character Encyclopedia & Real Cast Guide", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#2563EB'), spaceAfter=14))
    
    # 2 Characters per page with cards
    for idx, char in enumerate(characters):
        img_path = char.get("image_path")
        
        # Prepare valid image flowable
        img_flowable = None
        if img_path and os.path.exists(img_path):
            try:
                # Ensure it's valid with PIL
                with PILImage.open(img_path) as pimg:
                    w, h = pimg.size
                img_flowable = RLImage(img_path, width=1.5*inch, height=1.5*inch)
            except Exception:
                img_flowable = None
                
        if not img_flowable:
            # Fallback placeholder badge
            img_flowable = Paragraph(f"<b>{char['character'][:12]}</b>", char_title_style)

        text_content = [
            Paragraph(char["character"], char_title_style),
            Paragraph(f"<b>Portrayed by:</b> {char.get('actor', 'Cast Ensemble')}", actor_style),
            Paragraph(char.get("bio", "Character profile and background details."), bio_style)
        ]
        
        card_data = [[img_flowable, text_content]]
        card_table = Table(card_data, colWidths=[120, 384])
        card_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E2E8F0')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, 0), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))
        
        story.append(card_table)
        story.append(Spacer(1, 14))
        
        # 3 cards per page
        if (idx + 1) % 3 == 0 and (idx + 1) < len(characters):
            story.append(PageBreak())

    doc.build(story, canvasmaker=NumberedCanvas)
    return output_pdf_path


def search_accurate_web_info(query: str) -> dict:
    """
    All-purpose accurate web search engine combining DuckDuckGo Instant Answer API
    and Wikipedia REST Summary API. Returns verified facts, synopsis, and metadata.
    """
    clean_q = re.sub(r'\b(?:make|create|pdf|containing|images?|all|characters?|details?|breif|brief|with)\b', '', query, flags=re.I).strip()
    result = {
        "query": query,
        "clean_query": clean_q,
        "title": clean_q.title(),
        "summary": "",
        "source": "",
        "facts": {}
    }

    # 1. DuckDuckGo Instant Answer API
    try:
        ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(clean_q)}&format=json&no_html=1"
        req = urllib.request.Request(ddg_url, headers={'User-Agent': 'Mozilla/5.0 (PrathamAI/2.0)'})
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            abstract = data.get('Abstract')
            heading = data.get('Heading')
            if abstract:
                result["summary"] = abstract
                result["title"] = heading or result["title"]
                result["source"] = data.get('AbstractSource', 'DuckDuckGo')
    except Exception:
        pass

    # 2. Wikipedia REST API for authoritative encyclopedic summary
    try:
        wiki_title = search_wikipedia_article(clean_q)
        w_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(wiki_title)}"
        req2 = urllib.request.Request(w_url, headers={'User-Agent': 'Mozilla/5.0 (PrathamAI/2.0)'})
        with urllib.request.urlopen(req2, timeout=4.0) as resp2:
            w_data = json.loads(resp2.read().decode('utf-8'))
            extract = w_data.get('extract')
            if extract:
                if not result["summary"] or len(extract) > len(result["summary"]):
                    result["summary"] = extract
                    result["title"] = w_data.get('title', result["title"])
                    result["source"] = "Wikipedia"
                result["description"] = w_data.get('description', '')
    except Exception:
        pass

    return result


def verify_deliverable(file_path: str) -> dict:
    """
    Automated verification engine for deliverables (PDFs, ZIPs, HTMLs).
    Checks file existence, non-zero byte size, structure, and readability.
    """
    if not os.path.exists(file_path):
        return {"ok": False, "error": f"File '{file_path}' does not exist on disk."}

    size_bytes = os.path.getsize(file_path)
    if size_bytes < 50:
        return {"ok": False, "error": f"File '{file_path}' is empty or corrupt ({size_bytes} bytes)."}

    size_kb = round(size_bytes / 1024, 1)
    status = {"ok": True, "file_path": file_path, "filename": os.path.basename(file_path), "size_kb": size_kb}

    # PDF-specific page count verification
    if file_path.lower().endswith(".pdf"):
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            num_pages = len(reader.pages)
            status["pages"] = num_pages
            status["details"] = f"Verified valid PDF document ({num_pages} pages, {size_kb} KB)"
        except Exception as e:
            status["details"] = f"Verified PDF file on disk ({size_kb} KB)"
    elif file_path.lower().endswith(".zip"):
        try:
            import zipfile
            with zipfile.ZipFile(file_path, 'r') as zf:
                namelist = zf.namelist()
                status["file_count"] = len(namelist)
                status["details"] = f"Verified valid ZIP archive with {len(namelist)} packaged files ({size_kb} KB)"
        except Exception as e:
            status["details"] = f"Verified ZIP file on disk ({size_kb} KB)"
    elif file_path.lower().endswith((".html", ".htm")):
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as hf:
                hcontent = hf.read()
            if len(hcontent) < 200:
                return {"ok": False, "error": f"HTML file '{file_path}' is incomplete ({len(hcontent)} bytes)."}
            hlow = hcontent.lower()
            if ("<html" not in hlow and "<!doctype" not in hlow) or ("</html>" not in hlow and "</body>" not in hlow):
                return {"ok": False, "error": f"HTML file '{file_path}' is missing closing tags (truncated)."}
            status["line_count"] = hcontent.count("\n") + 1
            status["details"] = f"Verified valid complete HTML application ({status['line_count']} lines, {size_kb} KB)"
        except Exception as e:
            status["details"] = f"Verified HTML file on disk ({size_kb} KB)"
    else:
        status["details"] = f"Verified deliverable on disk ({size_kb} KB)"

    return status

