import os
import urllib.request
import json
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

os.makedirs("/workspace/bold-curie/bheem_assets", exist_ok=True)

# List of all key Chhota Bheem characters with brief descriptions and image URLs / fallback styling
characters = [
    {
        "name": "Chhota Bheem",
        "title": "The Brave & Kind Hero of Dholakpur",
        "desc": "Bheem is an exceptionally strong, adventurous, and kind-hearted 9-year-old boy living in Dholakpur. His superhuman strength multiplies whenever he eats freshly made laddoos from Tuntun Mausi. He is deeply loyal, protects the kingdom from evil villains, and stands up for justice and friendship.",
        "color": "#D35400",
        "url": "https://upload.wikimedia.org/wikipedia/en/thumb/f/f6/Chhota_Bheem.jpg/220px-Chhota_Bheem.jpg"
    },
    {
        "name": "Chutki",
        "title": "Bheem's Intelligent & Supportive Best Friend",
        "desc": "Chutki is a clever, sweet, and spirited 7-year-old girl, daughter of Tuntun Mausi. She is Bheem's closest confidante, frequently helping the gang solve puzzles, prepare delicious laddoos, and strategize when tackling crises facing Dholakpur.",
        "color": "#E91E63",
        "url": "https://upload.wikimedia.org/wikipedia/en/thumb/b/b2/Chutki_%28Chhota_Bheem%29.png/220px-Chutki_%28Chhota_Bheem%29.png"
    },
    {
        "name": "Raju",
        "title": "The Fearless Little Archer",
        "desc": "Raju is an energetic, brave 4-year-old boy whose idol is Bheem. Despite his young age, he is remarkably courageous and skilled with a bow and arrow. His father is an army chief, and Raju aspires to become a celebrated soldier.",
        "color": "#2980B9",
        "url": "https://upload.wikimedia.org/wikipedia/en/thumb/5/53/Raju_%28Chhota_Bheem%29.png/220px-Raju_%28Chhota_Bheem%29.png"
    },
    {
        "name": "Jaggu",
        "title": "The Cheerful & Agile Talking Monkey",
        "desc": "Jaggu is a talking monkey with sharp wits, exceptional agility, and playful humor. He can swing swiftly across trees to scout enemy movements, gather intel, and help Bheem outmaneuver forest adversaries.",
        "color": "#8E44AD",
        "url": "https://upload.wikimedia.org/wikipedia/en/thumb/3/36/Jaggu_Bandar.png/220px-Jaggu_Bandar.png"
    },
    {
        "name": "Kalia (Kalia Ustad)",
        "title": "The Boastful Rival-Turned-Ally",
        "desc": "Kalia is an overweight, boastful 10-year-old bully who envies Bheem's popularity and prowess. Although he often challenges Bheem or shows off, in moments of real peril Kalia unites with Bheem's squad to defend Dholakpur.",
        "color": "#16A085",
        "url": "https://upload.wikimedia.org/wikipedia/en/thumb/7/7b/Kalia_Tevar.png/220px-Kalia_Tevar.png"
    },
    {
        "name": "Dholu & Bholu",
        "title": "Kalia's Mischievous Twin Followers",
        "desc": "Dholu and Bholu are identical twin brothers who constantly shadow Kalia. While they flatter Kalia and echo his boasts, their innocent slips of the tongue often reveal the truth and cause hilarious comedic moments.",
        "color": "#F39C12",
        "url": "https://upload.wikimedia.org/wikipedia/en/thumb/c/cd/Dholu_Bholu.png/220px-Dholu_Bholu.png"
    },
    {
        "name": "King Indraverma",
        "title": "The Benevolent Ruler of Dholakpur",
        "desc": "Raja Indraverma is the wise and compassionate monarch of Dholakpur. He places immense trust in Bheem to safeguard the kingdom against hostile neighbouring rulers and supernatural fiends.",
        "color": "#C0392B",
        "url": "https://static.wikia.nocookie.net/chhotabheem/images/9/91/Raja_indraverma.png"
    },
    {
        "name": "Princess Indumati",
        "title": "The Kind-Hearted Princess of Dholakpur",
        "desc": "Indumati is the gentle, polite, and generous young princess of Dholakpur. She loves playing with Bheem and his gang, frequently joining in festivities and village events.",
        "color": "#9B59B6",
        "url": "https://static.wikia.nocookie.net/chhotabheem/images/8/87/Princess_Indumati.png"
    },
    {
        "name": "Tuntun Mausi",
        "title": "The Famed Laddoo Maker of Dholakpur",
        "desc": "Tuntun Mausi is Chutki's mother and the town's premier sweetmaker. Her magical, mouthwatering laddoos give Bheem limitless energy and power, making her a cornerstone of the Dholakpur community.",
        "color": "#D35400",
        "url": "https://static.wikia.nocookie.net/chhotabheem/images/5/5a/Tuntun_Mausi.png"
    },
    {
        "name": "Professor Dhoomketu",
        "title": "The Eccentric Inventor & Scientist",
        "desc": "An eccentric genius inventor who lives near the hills. Dhoomketu invents bizarre gadgets, flying pods, time machines, and scientific wonders that often kickstart adventures or save the day.",
        "color": "#27AE60",
        "url": "https://static.wikia.nocookie.net/chhotabheem/images/b/bc/Professor_Dhoomketu.png"
    },
    {
        "name": "Kirmada",
        "title": "The Formidable Dark Sorcerer",
        "desc": "Kirmada is the primary arch-nemesis of Bheem. A ruthless demon king with immense dark sorcery, he commands shadow armies and requires the full strength and courage of Bheem to defeat.",
        "color": "#2C3E50",
        "url": "https://static.wikia.nocookie.net/chhotabheem/images/8/82/Kirmada.png"
    },
    {
        "name": "Daku Mangal Singh",
        "title": "The Infamous Forest Bandit",
        "desc": "Mangal Singh is a notorious bandit chieftain who terrorizes travelers passing through the outskirts of Dholakpur. Bheem routinely foils his robbery schemes and captures him for the royal guards.",
        "color": "#7F8C8D",
        "url": "https://static.wikia.nocookie.net/chhotabheem/images/7/77/Mangal_singh.png"
    }
]

def make_fallback_avatar(name, color_hex, out_path):
    img = Image.new('RGB', (300, 300), color=color_hex)
    draw = ImageDraw.Draw(img)
    # Draw simple avatar frame and initials
    draw.rectangle([10, 10, 290, 290], outline='#FFFFFF', width=4)
    # Circle
    draw.ellipse([50, 40, 250, 240], fill='#FFFFFF')
    draw.ellipse([60, 50, 240, 230], fill=color_hex)
    
    # Text Initials
    initials = "".join([part[0] for part in name.split()[:2]]).upper()
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        draw.text((150, 140), initials, fill='#FFFFFF', anchor="mm", font=font)
    except:
        draw.text((120, 120), initials, fill='#FFFFFF')
    img.save(out_path, format="JPEG", quality=90)

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

for idx, char in enumerate(characters):
    img_filename = f"/workspace/bold-curie/bheem_assets/char_{idx}.jpg"
    downloaded = False
    try:
        req = urllib.request.Request(char["url"], headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw_data = resp.read()
            # Verify image can be opened by PIL
            from io import BytesIO
            pil_img = Image.open(BytesIO(raw_data)).convert('RGB')
            pil_img.thumbnail((300, 300))
            pil_img.save(img_filename, format="JPEG", quality=88)
            downloaded = True
    except Exception as e:
        downloaded = False
    
    if not downloaded:
        make_fallback_avatar(char["name"], char["color"], img_filename)
    char["local_img"] = img_filename

pdf_path = "/workspace/bold-curie/chhota_bheem_characters_encyclopedia.pdf"
doc = SimpleDocTemplate(
    pdf_path,
    pagesize=letter,
    leftMargin=36,
    rightMargin=36,
    topMargin=36,
    bottomMargin=36
)

styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    'DocTitle',
    parent=styles['Heading1'],
    fontName='Helvetica-Bold',
    fontSize=24,
    leading=28,
    alignment=1, # Center
    textColor=colors.HexColor('#D35400')
)

subtitle_style = ParagraphStyle(
    'DocSubTitle',
    parent=styles['Normal'],
    fontName='Helvetica-Oblique',
    fontSize=11,
    leading=15,
    alignment=1,
    textColor=colors.HexColor('#555555')
)

char_name_style = ParagraphStyle(
    'CharName',
    parent=styles['Heading2'],
    fontName='Helvetica-Bold',
    fontSize=14,
    leading=18,
    textColor=colors.HexColor('#8B0000'),
    spaceAfter=2
)

char_role_style = ParagraphStyle(
    'CharRole',
    parent=styles['Normal'],
    fontName='Helvetica-BoldOblique',
    fontSize=10,
    leading=13,
    textColor=colors.HexColor('#D35400'),
    spaceAfter=5
)

char_desc_style = ParagraphStyle(
    'CharDesc',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=9.5,
    leading=13.5,
    textColor=colors.HexColor('#222222')
)

elements = []

# Title Section
elements.append(Paragraph("Chhota Bheem: Characters & Heroes Encyclopedia", title_style))
elements.append(Spacer(1, 4))
elements.append(Paragraph("Complete Illustrated Character Guide with Profiles & Lore of Dholakpur", subtitle_style))
elements.append(Spacer(1, 10))
elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#D35400'), spaceBefore=2, spaceAfter=14))

# Add characters two per page or nicely formatted table blocks
for i in range(0, len(characters), 2):
    pair = characters[i:i+2]
    for char in pair:
        img_elem = RLImage(char["local_img"], width=105, height=105)
        
        text_block = [
            Paragraph(char["name"], char_name_style),
            Paragraph(char["title"], char_role_style),
            Paragraph(char["desc"], char_desc_style)
        ]
        
        card_table = Table(
            [[img_elem, text_block]],
            colWidths=[115, 425]
        )
        card_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF9F4')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E0B088')),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))
        
        elements.append(card_table)
        elements.append(Spacer(1, 12))
    
    if i + 2 < len(characters):
        elements.append(PageBreak())

doc.build(elements)
print("PDF successfully built at:", pdf_path)
