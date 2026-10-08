import os
import urllib.request
import urllib.parse
import json
from PIL import Image as PILImage, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether
from reportlab.pdfgen import canvas

os.makedirs("rajni_assets", exist_ok=True)

def download_or_generate_image(query, target_filename, label_text):
    target_path = os.path.join("rajni_assets", target_filename)
    if os.path.exists(target_path) and os.path.getsize(target_path) > 1000:
        return target_path

    # Try Wikipedia Search API
    try:
        wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch={urllib.parse.quote(query)}&gsrlimit=1&prop=pageimages&pithumbsize=600&format=json"
        req = urllib.request.Request(wiki_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode('utf-8'))
            pages = data.get('query', {}).get('pages', {})
            for pid, page in pages.items():
                if 'thumbnail' in page and 'source' in page['thumbnail']:
                    img_url = page['thumbnail']['source']
                    img_req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    with urllib.request.urlopen(img_req, timeout=4) as img_resp:
                        with open(target_path, 'wb') as f:
                            f.write(img_resp.read())
                    with PILImage.open(target_path) as test_img:
                        test_img.verify()
                    return target_path
    except Exception:
        pass

    # Try Pollinations image generation
    try:
        poll_prompt = urllib.parse.quote(f"Bahu Hamari Rajnikant TV show Indian sitcom humanoid robot Rajni Kant {label_text}")
        poll_url = f"https://image.pollinations.ai/prompt/{poll_prompt}?width=600&height=400&nologo=true"
        req = urllib.request.Request(poll_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=4) as response:
            with open(target_path, 'wb') as f:
                f.write(response.read())
        with PILImage.open(target_path) as test_img:
            test_img.verify()
        return target_path
    except Exception:
        pass

    # High-quality fallback graphic card
    img = PILImage.new('RGB', (600, 400), color=(24, 32, 60))
    draw = ImageDraw.Draw(img)
    draw.rectangle([12, 12, 588, 388], outline=(0, 200, 255), width=3)
    draw.rectangle([20, 20, 580, 80], fill=(36, 50, 95))
    draw.text((35, 40), "Bahu Hamari Rajni_Kant", fill=(255, 255, 255))
    draw.text((40, 180), label_text, fill=(0, 220, 255))
    draw.text((40, 240), "[Visual Illustration]", fill=(180, 210, 240))
    img.save(target_path, format="JPEG")
    return target_path

characters = [
    {
        "name": "Rajni Kant (R.A.J.N.I.)",
        "actor": "Ridhima Pandit",
        "role": "Super Humanoid Robot / Ideal Daughter-in-Law",
        "bio": "Randomly Accessible Jobs Neural Interface. A hyper-advanced female humanoid robot equipped with superhuman physical strength, multi-tasking engines, literal interpretations, and 10x human cognitive computing power.",
        "search": "Ridhima Pandit Bahu Hamari Rajnikant",
        "file": "rajni_ridhima.jpg"
    },
    {
        "name": "Shantanu 'Shaan' Kant",
        "actor": "Karan Grover / Raqesh Bapat",
        "role": "Robotics Scientist & Creator / Husband",
        "bio": "The brilliant yet chronically panicked inventor who creates Rajni to showcase the pinnacle of robotics and satisfy family matrimonial demands, spending every day protecting Rajni's secret identity.",
        "search": "Karan Grover actor Bahu Hamari Rajnikant",
        "file": "shaan_karan.jpg"
    },
    {
        "name": "Surili Amrish Kant",
        "actor": "Pallavi Pradhan",
        "role": "The Matriarch / Mother-in-Law (Sasu Maa)",
        "bio": "The sophisticated, high-society mother-in-law obsessed with perfection, Bengali aristocracy traditions, and domestic supremacy, who is constantly bewildered by Rajni's bizarre literal obedience.",
        "search": "Pallavi Pradhan Bahu Hamari Rajnikant",
        "file": "surili_kant.jpg"
    },
    {
        "name": "Amrish Kant",
        "actor": "Rajendra Chawla",
        "role": "The Patriarch / Father-in-Law (Sasur Ji)",
        "bio": "The lovable, good-humored, and peace-loving father of Shaan who adores Rajni's sincerity, innocence, and exceptional abilities, consistently defending her against family drama.",
        "search": "Rajendra Chawla Bahu Hamari Rajnikant",
        "file": "amrish_kant.jpg"
    },
    {
        "name": "Dev Kant",
        "actor": "Neel Motwani",
        "role": "Shaan's Best Friend & Co-conspirator",
        "bio": "Shaan's trusted partner-in-crime who knows Rajni's secret mechanics. Responsible for covert battery chargers, software calibration, and comical diversions when things go haywire.",
        "search": "Neel Motwani actor Bahu Hamari Rajnikant",
        "file": "dev_motwani.jpg"
    },
    {
        "name": "Maggie & Sharmila Kant",
        "actor": "Vahbiz Dorabjee & Tanvi Thakkar",
        "role": "The Sisters-in-Law (Jethanis)",
        "bio": "The drama-loving, scheming sisters-in-law who constantly set domestic traps in the kitchen and family events, only to be outsmarted effortlessly by Rajni's automated capabilities.",
        "search": "Vahbiz Dorabjee Bahu Hamari Rajnikant",
        "file": "maggie_vahbiz.jpg"
    }
]

scenes = [
    {
        "title": "Scene 1: 56-Course Meal Cooked in 15 Minutes",
        "desc": "Challenged by Surili to prepare an impossible royal banquet, Rajni activates high-speed multi-threading motor mode, slicing vegetables at mach speed and handling 6 pans simultaneously with robotic precision.",
        "search": "Bahu Hamari Rajnikant cooking robot kitchen",
        "file": "scene_cooking.jpg"
    },
    {
        "title": "Scene 2: Saree-Clad Martial Arts & Beating Goons",
        "desc": "When dangerous hoodlums ambush the Kant family, Rajni switches into combat defense protocol, tossing villains through the air with a single wrist flip while maintaining her traditional poised demeanor.",
        "search": "Bahu Hamari Rajnikant action fight scene",
        "file": "scene_combat.jpg"
    },
    {
        "title": "Scene 3: The 1% Battery Crisis at the Pooja",
        "desc": "During an auspicious joint family ritual, Rajni's power cell dips to 1%. Shaan and Dev frantically snake charging cables across the altar while Rajni starts speaking in system diagnostic loops.",
        "search": "Bahu Hamari Rajnikant comedy charging battery",
        "file": "scene_battery.jpg"
    },
    {
        "title": "Scene 4: The Historic Scientist-Robot Wedding",
        "desc": "Shaan walks down the aisle with his creation in a glittering traditional bridal attire, making television history with full Vedic rituals, holy fire circumambulations, and mangalsutra.",
        "search": "Bahu Hamari Rajnikant wedding bridal",
        "file": "scene_wedding.jpg"
    }
]

# Fetch assets
for c in characters:
    download_or_generate_image(c['search'], c['file'], c['name'])

for s in scenes:
    download_or_generate_image(s['search'], s['file'], s['title'])

banner_img = download_or_generate_image("Bahu Hamari Rajnikant show poster Life OK", "banner_poster.jpg", "Bahu Hamari Rajni_Kant Poster")

pdf_file = "bahu_hamari_rajnikant_guide.pdf"
doc = SimpleDocTemplate(
    pdf_file,
    pagesize=letter,
    leftMargin=36,
    rightMargin=36,
    topMargin=36,
    bottomMargin=36
)

styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    'DocTitle',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=24,
    leading=28,
    textColor=colors.HexColor('#1A237E'),
    alignment=1
)

sub_style = ParagraphStyle(
    'DocSubTitle',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=13,
    leading=17,
    textColor=colors.HexColor('#0D47A1'),
    alignment=1
)

h1_style = ParagraphStyle(
    'H1',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=16,
    leading=20,
    textColor=colors.HexColor('#B71C1C'),
    spaceBefore=14,
    spaceAfter=8
)

h2_style = ParagraphStyle(
    'H2',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=13,
    leading=16,
    textColor=colors.HexColor('#1A237E'),
    spaceBefore=2,
    spaceAfter=3
)

body_style = ParagraphStyle(
    'Body',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=10,
    leading=14,
    textColor=colors.HexColor('#263238')
)

tag_style = ParagraphStyle(
    'Tag',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=9.5,
    leading=13,
    textColor=colors.HexColor('#C2185B')
)

story = []

# Title & Banner
story.append(Paragraph("BAHU HAMARI RAJNI_KANT", title_style))
story.append(Spacer(1, 4))
story.append(Paragraph("The Definitive Illustrated Character & Episode Guide", sub_style))
story.append(Spacer(1, 12))

if os.path.exists(banner_img):
    try:
        story.append(Image(banner_img, width=540, height=180))
        story.append(Spacer(1, 10))
    except Exception:
        pass

intro_text = (
    "<b>Bahu Hamari Rajni_Kant</b> is an iconic Indian science-fiction sitcom produced by Sonali Jaffar and "
    "Amir Jaffar that aired on Life OK. The show captivated viewers with an unprecedented premise: "
    "a brilliant scientist invents an ultra-advanced humanoid robot (Rajni) and ends up marrying her to fulfill "
    "his family's matrimonial expectations. As Rajni takes on the role of the quintessential Indian daughter-in-law, "
    "her literal algorithmic logic, superhuman capabilities, and pure heart create a non-stop rollercoaster of laughter."
)
story.append(Paragraph(intro_text, body_style))
story.append(Spacer(1, 14))

# Characters Section
story.append(Paragraph("🌟 Character Profiles & Cast", h1_style))
story.append(Spacer(1, 6))

for c in characters:
    c_path = os.path.join("rajni_assets", c['file'])
    img_obj = None
    if os.path.exists(c_path):
        try:
            img_obj = Image(c_path, width=135, height=105)
        except Exception:
            pass

    info_col = [
        Paragraph(f"<b>{c['name']}</b>", h2_style),
        Paragraph(f"<b>Portrayed by:</b> {c['actor']} &bull; <i>{c['role']}</i>", tag_style),
        Spacer(1, 3),
        Paragraph(c['bio'], body_style)
    ]

    t_data = [[img_obj if img_obj else "", info_col]]
    c_table = Table(t_data, colWidths=[145, 395])
    c_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(KeepTogether([c_table, Spacer(1, 10)]))

story.append(PageBreak())

# Best Scenes Section
story.append(Paragraph("🎬 Most Iconic & Best-Loved Scenes", h1_style))
story.append(Paragraph("Moments that made the sitcom a landmark achievement in Indian comedy television:", sub_style))
story.append(Spacer(1, 10))

for s in scenes:
    s_path = os.path.join("rajni_assets", s['file'])
    img_obj = None
    if os.path.exists(s_path):
        try:
            img_obj = Image(s_path, width=180, height=115)
        except Exception:
            pass

    desc_col = [
        Paragraph(f"<b>{s['title']}</b>", h2_style),
        Spacer(1, 3),
        Paragraph(s['desc'], body_style)
    ]

    s_data = [[img_obj if img_obj else "", desc_col]]
    s_table = Table(s_data, colWidths=[190, 350])
    s_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFFDE7')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#FFE082')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(KeepTogether([s_table, Spacer(1, 12)]))

# Trivia & Legacy
story.append(Spacer(1, 8))
story.append(Paragraph("⚙️ Technical Specs & Trivia", h1_style))
trivia_text = (
    "&bull; <b>Full Name:</b> R.A.J.N.I = <i>Randomly Accessible Jobs Neural Interface</i>.<br/>"
    "&bull; <b>Hardware & Features:</b> 10-horsepower hydraulic limbs, voice synthesizer mimicry, retinal scanner, multi-lingual database, battery backup with discreet recharge port.<br/>"
    "&bull; <b>Accolades:</b> Lead actress Ridhima Pandit received widespread praise and won Best Debutante for her robotic mannerisms and comic timing.<br/>"
    "&bull; <b>Broadcasting:</b> Aired from February 2016 to February 2017 with 269 memorable episodes on Life OK."
)
story.append(Paragraph(trivia_text, body_style))

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
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(36, 20, "Bahu Hamari Rajni_Kant Retrospective Guide | Pratham AI")
        self.drawRightString(letter[0] - 36, 20, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()

doc.build(story, canvasmaker=NumberedCanvas)
print("SUCCESS: bahu_hamari_rajnikant_guide.pdf compiled successfully!")
