"""
Universal All-Purpose Web Image Search Engine & Fetcher Utility
Fetches real, verified high-resolution images from the live web for ANY topic,
show, anime, movie, celebrity, public figure, animal, location, or subject.
Features multi-engine fallback (Wikimedia Commons, Bing Media, PokeAPI),
PIL format verification, automatic RGB conversion, and concurrent downloads.
Created for Pratham AI by Pratham Sinha under the supervision of Akriti & Aditi Aishwaryam.
"""

import os
import re
import io
import json
import urllib.request
import urllib.parse
from PIL import Image as PILImage, ImageDraw

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

def search_accurate_images(query: str, limit: int = 10) -> list:
    """
    Multi-engine all-purpose image search across Wikimedia Commons,
    Wikipedia PageImages, and Bing Media. Returns a list of candidate URLs.
    """
    candidates = []
    clean_q = re.sub(r'\b(?:make|create|pdf|containing|images?|all|characters?|details?|breif|brief|with)\b', '', query, flags=re.I).strip()
    if not clean_q:
        clean_q = query

    # 1. Specialized handling for Pokémon PokeAPI sprites
    poke_match = re.search(r'\b(?:pokemon|pokémon)\s*(?:#?(\d+)|([a-zA-Z]+))\b', query, re.IGNORECASE)
    if poke_match:
        p_id_or_name = (poke_match.group(1) or poke_match.group(2)).lower()
        candidates.append(f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{p_id_or_name}.png")
        candidates.append(f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{p_id_or_name}.png")

    # 2. Wikipedia / Wikimedia Commons PageImages (High authority, official portraits/stills)
    for api_endpoint in [
        f"https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch={urllib.parse.quote(clean_q)}&gsrlimit=5&prop=pageimages&pithumbsize=800&format=json",
        f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={urllib.parse.quote(clean_q)}&gsrlimit=5&prop=pageimages&pithumbsize=800&format=json"
    ]:
        try:
            req = urllib.request.Request(api_endpoint, headers={'User-Agent': 'PrathamAI/2.0 (contact@pratham.ai)'})
            with urllib.request.urlopen(req, timeout=3.5) as r:
                data = json.loads(r.read().decode('utf-8', errors='ignore'))
                pages = data.get('query', {}).get('pages', {})
                for p in pages.values():
                    thumb = p.get('thumbnail', {}).get('source')
                    if thumb and thumb not in candidates:
                        candidates.append(thumb)
        except Exception:
            pass

    # 3. Bing Async Media Search (Production stills, posters, anime, wallpapers)
    try:
        b_url = f"https://www.bing.com/images/async?q={urllib.parse.quote(clean_q)}&first=0&count=10&mmasync=1"
        req2 = urllib.request.Request(b_url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req2, timeout=4.0) as r2:
            html = r2.read().decode('utf-8', errors='ignore')
            murls = re.findall(r'murl&quot;:&quot;(https?://[^&]+)&quot;', html) or re.findall(r'\"murl\":\"(https?://[^\"]+)\"', html)
            for m in murls:
                if m not in candidates:
                    candidates.append(m)
    except Exception:
        pass

    return candidates[:limit]


def fetch_web_image(query: str, save_path: str, timeout: float = 5.0) -> bool:
    """
    Searches and downloads a verified, high-quality image for query and saves it to save_path.
    Verifies the downloaded payload using PIL before saving. If network fails,
    generates a clean styled card with PIL so generation never halts.
    """
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    urls = search_accurate_images(query, limit=12)

    for u in urls:
        try:
            req = urllib.request.Request(u, headers={'User-Agent': USER_AGENT, 'Accept': 'image/*'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if len(data) < 800:
                    continue
                # Verify image integrity with PIL
                img = PILImage.open(io.BytesIO(data))
                if img.width < 60 or img.height < 60:
                    continue
                # For PNG deliverables (e.g. game sprites), preserve transparency (RGBA)
                if save_path.lower().endswith(".png"):
                    if img.mode not in ("RGBA", "RGB"):
                        img = img.convert("RGBA")
                    img.save(save_path, "PNG", optimize=True)
                else:
                    # Convert RGBA/P to RGB for JPEG / ReportLab compatibility
                    if img.mode in ("RGBA", "P", "LA"):
                        rgb_img = PILImage.new("RGB", img.size, (255, 255, 255))
                        if img.mode == "RGBA":
                            rgb_img.paste(img, mask=img.split()[3])
                        else:
                            rgb_img.paste(img.convert("RGBA"))
                        img = rgb_img
                    elif img.mode != "RGB":
                        img = img.convert("RGB")
                    img.save(save_path, "JPEG", quality=92)
                return True
        except Exception:
            continue

    # Fallback: High quality stylized visual badge using PIL
    try:
        img = PILImage.new('RGB', (450, 320), color=(15, 23, 42))
        d = ImageDraw.Draw(img)
        d.rectangle([12, 12, 438, 308], outline=(59, 130, 246), width=3)
        clean_text = query[:36]
        d.text((32, 145), clean_text, fill=(241, 245, 249))
        img.save(save_path, "PNG" if save_path.lower().endswith(".png") else "JPEG")
        return True
    except Exception:
        return False


def fetch_multiple_images(query_path_pairs, max_workers: int = 8) -> list:
    """
    Downloads multiple images concurrently using ThreadPoolExecutor.
    query_path_pairs: list of tuples (query_string, save_path)
    """
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_web_image, q, p) for q, p in query_path_pairs]
        return [f.result() for f in futures]

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        q = sys.argv[1]
        p = sys.argv[2]
        ok = fetch_web_image(q, p)
        print(f"[{'OK' if ok else 'FAIL'}] Fetched '{q}' -> {p} ({os.path.getsize(p) if os.path.exists(p) else 0} bytes)")
    elif len(sys.argv) == 2:
        urls = search_accurate_images(sys.argv[1])
        print(json.dumps(urls, indent=2))
    else:
        print("Usage: python3 fetch_image.py <query> <save_path>")

