import os
import urllib.request
import json
import zipfile
from PIL import Image, ImageDraw, ImageFont

os.makedirs("assets", exist_ok=True)

# Character details dictionary
characters = [
    {
        "name": "Chhota Bheem",
        "role": "The Hero & Protector of Dholakpur",
        "age": "9 years old",
        "favorite_food": "Laddoo (from Tuntun Mausi)",
        "traits": "Superhuman strength, bravery, kindness, fairness, unwavering loyalty.",
        "bio": "Bheem is an exceptionally brave, kind, and strong 9-year-old boy living in the town of Dholakpur. Armed with an appetite for freshly made laddoos which multiply his physical strength, Bheem selflessly safeguards the kingdom of Dholakpur from bandits, evil sorcerers, monstrous beasts, and scheming rival kingdoms. He values friendship, justice, and humility above all else.",
        "color": (230, 81, 0), # Deep Orange
        "icon_symbol": "💪"
    },
    {
        "name": "Chutki",
        "role": "Bheem's Best Friend & Strategist",
        "age": "7 years old",
        "favorite_food": "Laddoos & Homemade sweets",
        "traits": "Intelligent, empathetic, quick-witted, caring, resourceful.",
        "bio": "Chutki is Tuntun Mausi's daughter and Bheem's closest confidante. While gentle and compassionate, she is fierce when defending her friends. Chutki frequently devises clever plans during difficult missions, helps manage team dynamics, and often supplies Bheem with his essential vitality-boosting laddoos in times of peril.",
        "color": (233, 30, 99), # Vibrant Pink
        "icon_symbol": "🌸"
    },
    {
        "name": "Raju",
        "role": "The Fearless Little Archer",
        "age": "4-5 years old",
        "favorite_food": "Fresh fruits & snacks",
        "traits": "Courageous, aspiring warrior, sharp archer, loyal, spirited.",
        "bio": "Raju is an energetic young boy who considers Bheem his ultimate role model and elder brother. Despite his small stature, Raju possesses remarkable marksmanship with his bow and arrow. He never hesitates to step into danger alongside Bheem, dreaming of becoming the chief army commander of Dholakpur like his father Senapati.",
        "color": (33, 150, 243), # Sky Blue
        "icon_symbol": "🏹"
    },
    {
        "name": "Jaggu",
        "role": "The Talking Monkey Companion",
        "age": "Ageless Companion",
        "favorite_food": "Bananas & Forest Fruits",
        "traits": "Playful, agile acrobat, humorous, linguistically gifted.",
        "bio": "Jaggu is a talking monkey with exceptional agility and intelligence. Able to communicate fluently with humans, he serves as the team's scout across tree canopies and narrow terrains. Jaggu provides comedic relief through witty banter, but his scout surveillance and distraction tactics regularly turn the tide in Bheem's favor.",
        "color": (121, 85, 72), # Warm Brown
        "icon_symbol": "🐒"
    },
    {
        "name": "Kalia Pahelwan",
        "role": "The Boastful Rival-Turned-Ally",
        "age": "10-11 years old",
        "favorite_food": "Curry, sweets, and feast platters",
        "traits": "Envious, boastful, physically tough, secretly good-hearted.",
        "bio": "Kalia is an older, stout boy who constantly seeks to prove he is stronger and superior to Bheem. Flanked by twin cronies Dholu and Bholu, Kalia frequently challenges Bheem to competitions. Despite his boastful jealousy and schemes, Kalia possesses genuine bravery and stands shoulder-to-shoulder with Bheem whenever Dholakpur faces genuine threats.",
        "color": (76, 175, 80), # Forest Green
        "icon_symbol": "🤼"
    },
    {
        "name": "Dholu & Bholu",
        "role": "The Mischievous Twin Sidekicks",
        "age": "6-7 years old",
        "favorite_food": "Laddoos and Kalia's leftovers",
        "traits": "Identical, goofy, easily frightened, comic mimics.",
        "bio": "Dholu and Bholu are identical twin brothers who serve as Kalia's loyal yet clumsy followers. They echo Kalia's boastful remarks, though their accidental blunders frequently expose Kalia's plans. Despite following Kalia, they look up to Bheem with awe and provide endless laughter across Dholakpur.",
        "color": (255, 152, 0), # Amber
        "icon_symbol": "👬"
    },
    {
        "name": "Princess Indumati",
        "role": "Princess of Dholakpur",
        "age": "8-9 years old",
        "favorite_food": "Royal delicacies and sweets",
        "traits": "Graceful, generous, gentle, dignified, just.",
        "bio": "Princess Indumati is the beloved daughter of King Indraverma. Unpretentious and warm despite her regal status, she shares an affectionate bond with Bheem, Chutki, and their squad. She regularly joins their village games, assists in charity, and counts on Bheem as the kingdom's supreme protector.",
        "color": (156, 39, 176), # Royal Purple
        "icon_symbol": "👑"
    },
    {
        "name": "King Indraverma",
        "role": "The Benevolent Ruler of Dholakpur",
        "age": "Middle-aged",
        "favorite_food": "Royal banquets",
        "traits": "Wise, compassionate, honorable, trusting of Bheem.",
        "bio": "Raja Indraverma is the wise and noble monarch of Dholakpur. Dedicated to peace and the well-being of his subjects, the King relies on Bheem's unmatched courage to resolve crises that challenge the kingdom's royal army. He treats Bheem with tremendous respect and fatherly affection.",
        "color": (218, 165, 32), # Golden Ochre
        "icon_symbol": "🏰"
    },
    {
        "name": "Tuntun Mausi",
        "role": "Master Laddoo Maker & Chutki's Mother",
        "age": "Middle-aged",
        "favorite_food": "Freshly crafted laddoos",
        "traits": "Fiery-tempered, motherly, culinary master, protective.",
        "bio": "Tuntun Mausi is Dholakpur's most famous sweet maker whose golden laddoos are renowned across kingdoms. While she playfully chases Bheem when he sneakily snatches laddoos from her shop, she deeply adores him and lovingly bakes the special laddoos that power his heroic feats.",
        "color": (198, 40, 40), # Crimson
        "icon_symbol": "🟡"
    },
    {
        "name": "Professor Dhoomketu",
        "role": "The Eccentric Inventor",
        "age": "Elderly Scientist",
        "favorite_food": "Herbal tea and biscuits",
        "traits": "Genius inventor, eccentric, absent-minded, visionary.",
        "bio": "Professor Dhoomketu is Dholakpur's resident inventor and scientist. His fantastical contraptions, ranging from hot-air flying pods to automated gadgets, often malfunction comically or accidentally cause trouble, creating exciting scientific adventures for Bheem and his friends to solve.",
        "color": (0, 150, 136), # Teal
        "icon_symbol": "🔬"
    },
    {
        "name": "Kichak",
        "role": "The Rival Champion of Pehelwanpur",
        "age": "11-12 years old",
        "favorite_food": "Pehelwanpur delicacies",
        "traits": "Arrogant, fiercely competitive, cunning athlete.",
        "bio": "Hailing from the neighboring village of Pehelwanpur, Kichak is Bheem's arch athletic competitor. Fiercely arrogant and obsessed with proving Pehelwanpur's supremacy, Kichak frequently challenges Dholakpur to village tournaments, cricket clashes, and wrestling bouts, using every trick in the book.",
        "color": (92, 107, 115), # Slate Grey
        "icon_symbol": "⚡"
    }
]

# Function to fetch web images or generate rich stylized character profile portraits
def prepare_character_images():
    try:
        from fetch_image import fetch_web_image
    except ImportError:
        import sys
        sys.path.append("/workspace/bold-curie")
        from fetch_image import fetch_web_image

    real_img_dir = "/workspace/bold-curie/chhota_bheem_character_images"
    existing_map = {
        "chhota_bheem": f"{real_img_dir}/01_chhota_bheem.png",
        "chutki": f"{real_img_dir}/02_chutki.png",
        "raju": f"{real_img_dir}/03_raju.png",
        "jaggu": f"{real_img_dir}/04_jaggu_bandar.png",
        "kalia_pahelwan": f"{real_img_dir}/05_kalia_tevar.png",
        "dholu_and_bholu": f"{real_img_dir}/06_dholu_and_bholu.png",
        "princess_indumati": f"{real_img_dir}/08_princess_indumati.png",
        "king_indraverma": f"{real_img_dir}/07_raja_indraverma.png",
        "tuntun_mausi": f"{real_img_dir}/09_tuntun_mausi.png",
        "professor_dhoomketu": f"{real_img_dir}/10_prof_dhoomketu.png",
        "kichak": f"{real_img_dir}/05_kalia_tevar.png",
    }

    for char in characters:
        slug = char["name"].lower().replace(" ", "_").replace("&", "and")
        img_path = f"assets/{slug}.png"
        
        # 1. Use verified high-res disk image if available
        if slug in existing_map and os.path.exists(existing_map[slug]):
            try:
                im = Image.open(existing_map[slug])
                im.convert("RGB").save(img_path, "PNG")
                char["image_path"] = img_path
                continue
            except Exception:
                pass

        # 2. Fetch real image from web using fetch_image
        fetched = False
        try:
            fetched = fetch_web_image(f"{char['name']} Chhota Bheem character", img_path, timeout=5.0)
        except Exception:
            fetched = False

        if not fetched or not os.path.exists(img_path) or os.path.getsize(img_path) < 1000:
            # Fallback high-resolution stylized character portrait badge
            W, H = 600, 600
            im = Image.new("RGBA", (W, H), (255, 255, 255, 0))
            draw = ImageDraw.Draw(im)
            c = char["color"]
            draw.ellipse([20, 20, W-20, H-20], fill=(c[0], c[1], c[2], 255), outline=(255, 215, 0), width=12)
            draw.ellipse([45, 45, W-45, H-45], fill=(255, 255, 255, 240), outline=(c[0], c[1], c[2], 180), width=4)
            draw.ellipse([90, 90, W-90, H-90], fill=(c[0], c[1], c[2], 30))
            draw.rectangle([60, 390, W-60, 480], fill=(c[0], c[1], c[2], 240))
            draw.rectangle([65, 395, W-65, 475], fill=None, outline=(255, 215, 0), width=3)
            try:
                font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 90)
                font_mid = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
                font_role = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
            except Exception:
                font_large = ImageFont.load_default()
                font_mid = font_large
                font_role = font_large
            initials = "".join([part[0] for part in char["name"].split() if part[0].isalpha()])[:2]
            draw.text((W/2, 230), initials, fill=c, font=font_large, anchor="mm")
            draw.text((W/2, 437), char["name"], fill=(255, 255, 255), font=font_mid, anchor="mm")
            draw.text((W/2, 515), char["role"][:32], fill=(60, 60, 60), font=font_role, anchor="mm")
            im.save(img_path, "PNG")

        char["image_path"] = img_path

prepare_character_images()

# Now build the PDF using ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

pdf_filename = "Chhota_Bheem_Characters_Encyclopedia.pdf"

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        # Top banner line
        self.setStrokeColor(colors.HexColor("#D84315"))
        self.setLineWidth(1.5)
        self.line(40, 805, 555, 805)
        
        # Header text
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#E65100"))
        self.drawString(42, 812, "CHHOTA BHEEM OFFICIAL CHARACTER ENCYCLOPEDIA")
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#757575"))
        self.drawRightString(553, 812, "DHOLAKPUR CHRONICLES")

        # Bottom footer line
        self.setStrokeColor(colors.HexColor("#E0E0E0"))
        self.setLineWidth(1)
        self.line(40, 45, 555, 45)

        # Footer text
        self.drawString(42, 32, "Created with Pratham AI • High-Definition Collector's Edition")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(553, 32, page_str)
        self.restoreState()

doc = SimpleDocTemplate(
    pdf_filename,
    pagesize=A4,
    leftMargin=40,
    rightMargin=40,
    topMargin=50,
    bottomMargin=55
)

styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    'DocTitle',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=26,
    leading=32,
    textColor=colors.HexColor("#D84315"),
    alignment=1, # Center
    spaceAfter=6
)

subtitle_style = ParagraphStyle(
    'DocSubtitle',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=13,
    leading=18,
    textColor=colors.HexColor("#4E342E"),
    alignment=1,
    spaceAfter=15
)

overview_style = ParagraphStyle(
    'OverviewText',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=10,
    leading=15,
    textColor=colors.HexColor("#263238"),
    alignment=4, # Justified
    spaceAfter=15
)

char_name_style = ParagraphStyle(
    'CharName',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=16,
    leading=20,
    textColor=colors.HexColor("#BF360C")
)

char_role_style = ParagraphStyle(
    'CharRole',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=10,
    leading=14,
    textColor=colors.HexColor("#0277BD")
)

label_style = ParagraphStyle(
    'MetaLabel',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=9,
    leading=13,
    textColor=colors.HexColor("#37474F")
)

value_style = ParagraphStyle(
    'MetaVal',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=9,
    leading=13,
    textColor=colors.HexColor("#455A64")
)

bio_style = ParagraphStyle(
    'CharBio',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=9.5,
    leading=14,
    textColor=colors.HexColor("#212121"),
    alignment=4
)

story = []

# Title & Introduction
story.append(Spacer(1, 10))
story.append(Paragraph("👑 CHHOTA BHEEM & FRIENDS 👑", title_style))
story.append(Paragraph("Comprehensive Character Guide & Dholakpur Heroes Compendium", subtitle_style))
story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#FF6F00"), spaceAfter=14))

intro_text = (
    "<b>Chhota Bheem</b> is one of India's most iconic and beloved animated television series, created by "
    "Green Gold Animations. Set in the vibrant mythical town of <b>Dholakpur</b>, the show chronicles the adventures "
    "of a superhumanly strong nine-year-old boy named Bheem and his loyal band of friends. Together, they resolve "
    "village disputes, uphold truth and morality, and defend the kingdom against magical sorcerers, thieves, and neighboring challengers. "
    "Below is the complete profile guide containing portraits, personality traits, and in-depth backgrounds for all iconic characters."
)
story.append(Paragraph(intro_text, overview_style))
story.append(Spacer(1, 10))

# Iterate through characters and format them as sleek profile cards
for i, char in enumerate(characters):
    # Prepare image
    img = RLImage(char["image_path"], width=130, height=130)
    
    # Metadata table
    meta_data = [
        [Paragraph(f"<b>{char['name']}</b>", char_name_style)],
        [Paragraph(f"<b>Title:</b> {char['role']}", char_role_style)],
        [Paragraph(f"<b>Key Traits:</b> {char['traits']}", value_style)],
        [Paragraph(f"<b>Favorite Snack:</b> {char['favorite_food']}", value_style)],
        [Paragraph(f"<b>Age / Profile:</b> {char['age']}", value_style)],
        [Spacer(1, 4)],
        [Paragraph(f"<b>Character Biography:</b> {char['bio']}", bio_style)]
    ]
    meta_table = Table(meta_data, colWidths=[360])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    
    card_data = [[img, meta_table]]
    card_table = Table(card_data, colWidths=[140, 365])
    
    # Background accent based on character color
    hex_c = '#%02x%02x%02x' % char['color']
    card_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#FAFAFA")),
        ('BOX', (0, 0), (-1, -1), 1.2, colors.HexColor(hex_c)),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    
    story.append(card_table)
    story.append(Spacer(1, 14))
    
    # Add page breaks nicely to keep cards clean (2 cards per page after page 1)
    if i in [1, 3, 5, 7, 9]:
        story.append(PageBreak())

# Build document
doc.build(story, canvasmaker=NumberedCanvas)
print("PDF built successfully:", pdf_filename)

# Create ZIP archive containing the PDF and character images
zip_filename = "Chhota_Bheem_Characters_Package.zip"
with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
    zipf.write(pdf_filename, arcname=pdf_filename)
    for root, dirs, files in os.walk("assets"):
        for file in files:
            file_path = os.path.join(root, file)
            zipf.write(file_path, arcname=os.path.join("character_images", file))

print("ZIP built successfully:", zip_filename)
print("Zip contents:", zipfile.ZipFile(zip_filename).namelist())
