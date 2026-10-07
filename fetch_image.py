"""
Web Image Fetcher Utility
Fetches real images from the web for ANY topic, show, anime, celebrity, or character
(e.g., Bahu Hamari Rajni_Kant, TMKOC, Doraemon, Pokémon, Bollywood, Hollywood, etc.)
with concurrent downloads, high-speed fallback, and PIL placeholder generation.
"""

import os
import re
import urllib.request
import urllib.parse
from PIL import Image as PILImage, ImageDraw

def fetch_web_image(query: str, save_path: str, timeout: float = 3.5) -> bool:
    """
    Fetches a real image for any query from the web and saves it to save_path.
    If network retrieval fails, generates a polished visual card using PIL.
    """
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    
    # 1. Specialized handling for Pokémon PokeAPI official sprites
    poke_match = re.search(r'\b(?:pokemon|pokémon)\s*(?:#?(\d+)|([a-zA-Z]+))\b', query, re.IGNORECASE)
    if poke_match:
        p_id_or_name = poke_match.group(1) or poke_match.group(2).lower()
        sprite_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{p_id_or_name}.png"
        try:
            req = urllib.request.Request(sprite_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if len(data) > 200:
                    with open(save_path, 'wb') as f:
                        f.write(data)
                    return True
        except Exception:
            pass

    # 2. General Web Image Search (Bing Async Media Search)
    bing_url = f"https://www.bing.com/images/async?q={urllib.parse.quote(query)}&first=0&count=5&mmasync=1"
    bing_req = urllib.request.Request(
        bing_url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
    )
    try:
        with urllib.request.urlopen(bing_req, timeout=timeout) as r:
            html = r.read().decode('utf-8', errors='ignore')
            murls = re.findall(r'murl&quot;:&quot;(https?://[^&]+)&quot;', html)
            if not murls:
                murls = re.findall(r'\"murl\":\"(https?://[^\"]+)\"', html)
            
            for m in murls[:4]:
                try:
                    img_req = urllib.request.Request(m, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    with urllib.request.urlopen(img_req, timeout=timeout) as img_resp:
                        data = img_resp.read()
                        if len(data) > 1000:
                            with open(save_path, 'wb') as out_f:
                                out_f.write(data)
                            return True
                except Exception:
                    continue
    except Exception:
        pass

    # 3. Fallback: High quality stylized visual badge using PIL
    try:
        img = PILImage.new('RGB', (400, 300), color=(30, 41, 59))
        d = ImageDraw.Draw(img)
        d.rectangle([10, 10, 390, 290], outline=(59, 130, 246), width=3)
        clean_text = query[:30]
        d.text((30, 140), clean_text, fill=(241, 245, 249))
        img.save(save_path)
        return True
    except Exception:
        return False

def fetch_multiple_images(query_path_pairs, max_workers: int = 8):
    """
    Downloads multiple images concurrently using ThreadPoolExecutor.
    query_path_pairs: list of tuples (query_string, save_path)
    """
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_web_image, q, p) for q, p in query_path_pairs]
        return [f.result() for f in futures]
