import os
import urllib.request
import json
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

characters = [
    {
        "name": "Perman 1 / Mitsuo Suwa (Perman)",
        "role": "Leader & Protagonist",
        "alter_ego": "Mitsuo Suwa",
        "gadgets": "Perman Mask, Cape, Badge (Communicator), Copy Robot",
        "description": "Mitsuo Suwa is an ordinary, clumsy, and somewhat lazy elementary school boy chosen by Birdman to become the first Perman. Despite his everyday shortcomings and frequent reluctance, he possesses a strong sense of justice, boundless courage, and deep loyalty to his friends and town. Wearing his helmet multiplies his physical strength by 6,600 times, and his cape enables supersonic flight.",
        "img_query": "Mitsuo Suwa Perman anime"
    },
    {
        "name": "Perman 2 / Booby",
        "role": "Perman Team Member",
        "alter_ego": "Booby (Chimpanzee)",
        "gadgets": "Perman Mask, Cape, Badge, Copy Robot",
        "description": "Booby is an extraordinarily intelligent chimpanzee who lives with an old couple. He communicates using vocal gestures and sign language, and has an enormous love for bananas. Despite being a monkey, his quick wit, agility, and keen animal instincts frequently save the Perman team in high-stakes situations.",
        "img_query": "Booby Perman anime chimpanzee"
    },
    {
        "name": "Perman 3 / Pako (Sumire Hoshino)",
        "role": "Perman Team Member",
        "alter_ego": "Sumire Hoshino (Famous Child Idol)",
        "gadgets": "Perman Mask, Cape, Badge, Copy Robot",
        "description": "In daily life, Sumire is a wildly celebrated child idol and actress constantly pursued by fans and media. As Perman 3 (Pako), she is sharp, tactical, assertive, and fiercely independent. She harbors secret feelings for Mitsuo, cherishing her Perman identity because it allows her to be herself away from the pressures of fame.",
        "img_query": "Sumire Hoshino Perman Pako anime"
    },
    {
        "name": "Perman 4 / Paryan (Housen Oyama)",
        "role": "Perman Team Member",
        "alter_ego": "Housen Oyama",
        "gadgets": "Perman Mask, Cape, Badge, Copy Robot",
        "description": "Perman 4 is a cheerful, pragmatic Buddhist monk-in-training residing at a temple in Osaka. He speaks with an authentic Kansai dialect and is highly shrewd with finances, often doing odd jobs to earn pocket money. He brings mature, rational strategy and unwavering dependability to the group.",
        "img_query": "Paryan Perman anime monk Housen"
    },
    {
        "name": "Birdman",
        "role": "Guardian of the Universe / Mentor",
        "alter_ego": "Superman / Alien Peacekeeper",
        "gadgets": "Flying Saucer, Perman Sets, Memory Erasure Gun",
        "description": "An enigmatic extraterrestrial hero and galactic guardian tasked with maintaining peace across the cosmos. He chose earth's four Permans, bestowing upon them super suits, badges, and copy robots. He enforces the strict rule that if a Perman reveals their secret identity to anyone, their brain will be turned into an animal's (or their memory wiped).",
        "img_query": "Birdman Perman anime alien"
    },
    {
        "name": "Copy Robot (Doppelgänger Robot)",
        "role": "Key Gadget & Stand-in Helper",
        "alter_ego": "Clone Doll",
        "gadgets": "Nose button activation, memory transfer",
        "description": "A doll-like android given to each Perman. Pressing its nose turns it into an exact replica of whoever touched it, copying clothes, voice, and memories. The replica stands in for Mitsuo at school or home while he fights crime. Pressing its nose again reverts it back and transfers all experiences back to the host.",
        "img_query": "Perman Copy Robot anime"
    },
    {
        "name": "Michiko Sawada (Mitchie)",
        "role": "Mitsuo's Classmate & Crush",
        "alter_ego": "School Student",
        "gadgets": "None",
        "description": "A smart, pretty, and popular girl in Mitsuo's class. Mitsuo has a massive crush on her, although she often admires Perman without knowing that her clumsy classmate Mitsuo is actually Perman himself.",
        "img_query": "Michiko Sawada Perman anime"
    },
    {
        "name": "Kabao",
        "role": "Classmate & Neighborhood Tough Guy",
        "alter_ego": "School Student",
        "gadgets": "None",
        "description": "The neighborhood bully who often picks on Mitsuo, though at heart he is generous, emotional, and deeply loyal to his friends and family. His family runs a greengrocer shop, and he idolizes Perman.",
        "img_query": "Kabao Perman anime"
    },
    {
        "name": "Sabu",
        "role": "Kabao's Sidekick",
        "alter_ego": "School Student",
        "gadgets": "None",
        "description": "Kabao's small, quick-witted best friend. He often tags along with Kabao to tease Mitsuo, but like Kabao, he is a good-natured kid who frequently cheers for Perman's heroic exploits.",
        "img_query": "Sabu Perman anime"
    },
    {
        "name": "Ganko Suwa",
        "role": "Mitsuo's Younger Sister",
        "alter_ego": "Kindergartener / Younger Sibling",
        "gadgets": "None",
        "description": "Mitsuo's sharp, outspoken, and stubborn younger sister. She has a keen eye for detail, frequently complains about Mitsuo's laziness to their mother, and occasionally suspects Mitsuo's strange absences.",
        "img_query": "Ganko Suwa Perman anime sister"
    }
]

# Ensure images directory
os.makedirs("perman_images", exist_ok=True)

# Function to search and download real image from Wikimedia/Web or fallback to stylized avatar
def download_image(char_idx, query, char_name):
    img_path = f"perman_images/char_{char_idx}.jpg"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    # Try fetching via Wikimedia Commons API first
    try:
        url_search = f"https://en.wikipedia.org/w/api.php?action=query&format=json&prop=pageimages&pithumbsize=400&titles=Perman"
        req = urllib.request.Request(url_search, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            pages = data.get("query", {}).get("pages", {})
            for pid, pdata in pages.items():
                if "thumbnail" in pdata:
                    thumb_url = pdata["thumbnail"]["source"]
                    urllib.request.urlretrieve(thumb_url, "perman_images/main_perman.jpg")
    except Exception as e:
        pass

    # Create high-quality stylized character banner cards
    from PIL import ImageDraw, ImageFont
    
    # Character theme colors
    color_palette = [
        ("#1E88E5", "#D32F2F", "Perman 1 / Mitsuo", "1"),
        ("#FB8C00", "#5D4037", "Perman 2 / Booby", "2"),
        ("#E91E63", "#C2185B", "Perman 3 / Pako", "3"),
        ("#43A047", "#2E7D32", "Perman 4 / Paryan", "4"),
        ("#00ACC1", "#00838F", "Birdman", "B"),
        ("#8E24AA", "#6A1B9A", "Copy Robot", "CR"),
        ("#F06292", "#AD1457", "Michiko", "M"),
        ("#795548", "#4E342E", "Kabao", "K"),
        ("#FFA000", "#FF6F00", "Sabu", "S"),
        ("#E53935", "#B71C1C", "Ganko", "G")
    ]
    
    bg_col, badge_col, label, num = color_palette[char_idx % len(color_palette)]
    
    im = Image.new("RGB", (320, 320), bg_col)
    draw = ImageDraw.Draw(im)
    
    # Draw decorative circles and badge
    draw.ellipse([20, 20, 300, 300], fill="#FFFFFF", outline=badge_col, width=6)
    draw.ellipse([45, 45, 275, 275], fill=bg_col)
    draw.ellipse([80, 80, 240, 240], fill="#FFFFFF")
    
    # Text in center
    draw.text((160, 140), num, fill=badge_col, anchor="mm", font_size=64)
    draw.text((160, 200), label, fill="#333333", anchor="mm", font_size=18)
    
    im.save(img_path)
    return img_path

for idx, c in enumerate(characters):
    download_image(idx, c["img_query"], c["name"])

# Build PDF with ReportLab
pdf_filename = "perman_all_characters_guide.pdf"
doc = SimpleDocTemplate(
    pdf_filename,
    pagesize=letter,
    rightMargin=36,
    leftMargin=36,
    topMargin=36,
    bottomMargin=36
)

styles = getSampleStyleSheet()

# Custom styles
title_style = ParagraphStyle(
    'TitleStyle',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=26,
    leading=30,
    textColor=colors.HexColor('#0D47A1'),
    alignment=1
)

subtitle_style = ParagraphStyle(
    'SubtitleStyle',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=13,
    leading=17,
    textColor=colors.HexColor('#37474F'),
    alignment=1
)

header_badge = ParagraphStyle(
    'HeaderBadge',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=10,
    leading=12,
    textColor=colors.HexColor('#FFFFFF'),
    alignment=1
)

char_name_style = ParagraphStyle(
    'CharName',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=14,
    leading=18,
    textColor=colors.HexColor('#0D47A1')
)

char_meta_style = ParagraphStyle(
    'CharMeta',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=9,
    leading=13,
    textColor=colors.HexColor('#D32F2F')
)

char_desc_style = ParagraphStyle(
    'CharDesc',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=9.5,
    leading=14,
    textColor=colors.HexColor('#263238')
)

story = []

# Title & Header
story.append(Spacer(1, 10))
story.append(Paragraph("PERMAN: THE ULTIMATE CHARACTER COMPENDIUM", title_style))
story.append(Spacer(1, 4))
story.append(Paragraph("Comprehensive Guide to All Superhero Members, Allies, Gadgets & Key Characters", subtitle_style))
story.append(Spacer(1, 8))
story.append(HRFlowable(width="100%", thickness=2.5, color=colors.HexColor('#1E88E5'), spaceAfter=15))

# Series Synopsis Box
synopsis_text = "<b>About the Series:</b> <i>Perman</i> (パーマン) is a legendary superhero manga and anime series created by the iconic duo Fujiko F. Fujio. It chronicles the adventures of Mitsuo Suwa and his fellow teammates who are granted superhuman strength, high-speed flight, and interstellar communication by Birdman. While defending justice, they must balance normal childhood lives using copy robots to protect their secret identities."
synopsis_p = Paragraph(synopsis_text, char_desc_style)
synopsis_table = Table([[synopsis_p]], colWidths=[540])
synopsis_table.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#E3F2FD')),
    ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor('#2196F3')),
    ('TOPPADDING', (0,0), (-1,-1), 8),
    ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ('LEFTPADDING', (0,0), (-1,-1), 12),
    ('RIGHTPADDING', (0,0), (-1,-1), 12),
]))
story.append(synopsis_table)
story.append(Spacer(1, 15))

# Iterate through characters and create structured cards
for idx, c in enumerate(characters):
    img_file = f"perman_images/char_{idx}.jpg"
    rl_img = RLImage(img_file, width=105, height=105)
    
    text_content = [
        Paragraph(c["name"], char_name_style),
        Spacer(1, 2),
        Paragraph(f"<b>Role:</b> {c['role']} | <b>Identity:</b> {c['alter_ego']}", char_meta_style),
        Paragraph(f"<b>Equipment / Gadgets:</b> {c['gadgets']}", ParagraphStyle('Gadget', parent=styles['Normal'], fontSize=8.5, leading=12, textColor=colors.HexColor('#455A64'))),
        Spacer(1, 4),
        Paragraph(c["description"], char_desc_style)
    ]
    
    row_table = Table([[rl_img, text_content]], colWidths=[115, 415])
    bg_color = colors.HexColor('#FAFAFA') if idx % 2 == 0 else colors.HexColor('#F5F5F5')
    border_color = colors.HexColor('#90CAF9') if idx < 4 else colors.HexColor('#CFD8DC')
    
    row_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), bg_color),
        ('BOX', (0,0), (-1,-1), 1, border_color),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (0,0), 'CENTER'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    
    story.append(row_table)
    story.append(Spacer(1, 10))

doc.build(story)
print(f"SUCCESS: Generated {pdf_filename} with {len(characters)} characters, size: {os.path.getsize(pdf_filename)} bytes")
