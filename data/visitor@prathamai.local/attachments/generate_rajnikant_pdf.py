import os
import urllib.request
import json
import urllib.parse
from PIL import Image as PILImage, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether
from reportlab.pdfgen import canvas

os.makedirs("images", exist_ok=True)

def fetch_or_generate_image(query, filename, fallback_label):
    filepath = os.path.join("images", filename)
    if os.path.exists(filepath):
        return filepath

    # 1. Try Wikipedia API
    try:
        wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch={urllib.parse.quote(query)}&gsrlimit=1&prop=pageimages&pithumbsize=600&format=json"
        req = urllib.request.Request(wiki_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            pages = data.get('query', {}).get('pages', {})
            for pid, pdata in pages.items():
                if 'thumbnail' in pdata and 'source' in pdata['thumbnail']:
                    img_src = pdata['thumbnail']['source']
                    img_req = urllib.request.Request(img_src, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    with urllib.request.urlopen(img_req, timeout=4) as img_resp:
                        with open(filepath, 'wb') as f:
                            f.write(img_resp.read())
                    with PILImage.open(filepath) as img:
                        img.verify()
                    return filepath
    except Exception:
        pass

    # 2. Try Pollinations AI prompt
    try:
        poll_prompt = urllib.parse.quote(f"Bahu Hamari Rajnikant TV show Indian sitcom humanoid robot Rajni Kant {fallback_label}")
        poll_url = f"https://image.pollinations.ai/prompt/{poll_prompt}?width=600&height=400&nologo=true"
        req = urllib.request.Request(poll_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            with open(filepath, 'wb') as f:
                f.write(resp.read())
        with PILImage.open(filepath) as img:
            img.verify()
        return filepath
    except Exception:
        pass

    # 3. Fallback: Draw stylish card with Pillow
    img = PILImage.new('RGB', (600, 400), color=(26, 35, 126))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 590, 390], outline=(0, 229, 255), width=4)
    draw.rectangle([20, 20, 580, 70], fill=(40, 53, 147))
    draw.text((35, 35), "Bahu Hamari Rajni_Kant", fill=(255, 255, 255))
    draw.text((50, 180), fallback_label, fill=(0, 229, 255))
    draw.text((50, 240), "[Image Illustration Placeholder]", fill=(179, 229, 252))
    img.save(filepath, format="JPEG")
    return filepath

characters = [
    {
        "name": "Rajni Kant (R.A.J.N.I.)",
        "actor": "Ridhima Pandit",
        "role": "Super Humanoid Robot Daughter-in-Law (Randomly Accessible Jobs Neural Interface)",
        "desc": "Created by eccentric scientist Shaan Kant, Rajni is a highly advanced robot with superhuman strength, 10x human intelligence, and literal comprehension of human sayings. She enters the Kant family as their daughter-in-law, navigating hilarious domestic challenges.",
        "search": "Ridhima Pandit Bahu Hamari Rajnikant",
        "file": "rajni.jpg"
    },
    {
        "name": "Shantanu 'Shaan' Kant",
        "actor": "Karan Grover / Raqesh Bapat",
        "role": "Robotics Scientist & Creator / Husband",
        "desc": "A genius scientist who invents Rajni to prove his engineering capabilities and to save himself from his family's marriage pressure. Constantly stressed trying to prevent his quirky family from discovering Rajni's secret robotic identity.",
        "search": "Karan Grover Bahu Hamari Rajnikant",
        "file": "shaan.jpg"
    },
    {
        "name": "Surili Kant",
        "actor": "Pallavi Pradhan",
        "role": "Matriarch / Mother-in-Law",
        "desc": "The dramatic, sophisticated, and high-class mother-in-law who expects perfection from her daughters-in-law. Rajni's bizarre literal interpretations of household orders keep Surili perpetually puzzled and frustrated.",
        "search": "Pallavi Pradhan Bahu Hamari Rajnikant",
        "file": "surili.jpg"
    },
    {
        "name": "Amrish Kant",
        "actor": "Rajendra Chawla",
        "role": "Patriarch / Father-in-Law",
        "desc": "The warm-hearted, loving, and comical father of Shaan. Unlike Surili, Amrish often admires Rajni's dutifulness, innocence, and superhuman capabilities, considering her a blessing to their family.",
        "search": "Rajendra Chawla Bahu Hamari Rajnikant",
        "file": "amrish.jpg"
    },
    {
        "name": "Dev Kant",
        "actor": "Neel Motwani",
        "role": "Shaan's Best Friend & Co-conspirator",
        "desc": "Shaan's loyal friend who knows Rajni's true identity. He often assists Shaan in charging, calibrating, and troubleshooting Rajni, often getting caught in absurdly comical situations.",
        "search": "Neel Motwani Bahu Hamari Rajnikant",
        "file": "dev.jpg"
    },
    {
        "name": "Maggie & Sharmila Kant",
        "actor": "Vahbiz Dorabjee & Tanvi Thakkar",
        "role": "Sisters-in-Law (Jethanis)",
        "desc": "Shaan's talkative, dramatic sisters-in-law who constantly conspire against Rajni in kitchen politics, only to find Rajni completing all impossible tasks effortlessly using her robotic algorithms.",
        "search": "Vahbiz Dorabjee Bahu Hamari Rajnikant",
        "file": "maggie.jpg"
    }
]

scenes = [
    {
        "title": "Scene 1: Rajni's Unbelievable Cooking & Household Chores",
        "desc": "When tasked with cooking an elaborate 56-course meal for the entire family in just 20 minutes, Rajni utilizes multi-threaded motor speed, chopping veggies at lightning velocity and stirring multiple pots at once, completely shocking Surili.",
        "search": "Bahu Hamari Rajnikant cooking robot scene",
        "file": "scene_cooking.jpg"
    },
    {
        "title": "Scene 2: Defeating Goons with Superhuman Strength",
        "desc": "When street thugs threaten the Kant family, Rajni switches to combat defense mode. Without wrinkling her traditional saree, she lifts thugs with one hand and spins them around, passing it off as 'traditional yogic self-defense'.",
        "search": "Bahu Hamari Rajnikant fight scene action",
        "file": "scene_fight.jpg"
    },
    {
        "title": "Scene 3: The Low Battery & Emergency Recharging Complications",
        "desc": "During a family pooja ceremony, Rajni's battery drops to 2%. Shaan and Dev frantically scramble to plug her into a wall socket disguised behind a holy curtain while Rajni starts repeating system error voice prompts.",
        "search": "Bahu Hamari Rajnikant comedy charging scene",
        "file": "scene_charging.jpg"
    },
    {
        "title": "Scene 4: The Grand Wedding of Shaan and Rajni",
        "desc": "Shaan brings Rajni to the altar to prevent disaster, creating Indian television history where a scientist weds a humanoid robot with traditional rituals, vermilion, and mangalsutra amidst loud celebrations.",
        "search": "Bahu Hamari Rajnikant wedding bride groom",
        "file": "scene_wedding.jpg"
    }
]

for char in characters:
    fetch_or_generate_image(char['search'], char['file'], char['name'])

for sc in scenes:
    fetch_or_generate_image(sc['search'], sc['file'], sc['title'])

header_img = fetch_or_generate_image("Bahu Hamari Rajnikant Life OK TV Show Poster", "header_poster.jpg", "Bahu Hamari Rajni_Kant Show Poster")

pdf_path = "bahu_hamari_rajnikant.pdf"
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
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=24,
    leading=28,
    textColor=colors.HexColor('#1A237E'),
    alignment=1
)

subtitle_style = ParagraphStyle(
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
    fontSize=17,
    leading=21,
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
    spaceBefore=4,
    spaceAfter=4
)

body_style = ParagraphStyle(
    'Body',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=10,
    leading=14,
    textColor=colors.HexColor('#212121')
)

badge_style = ParagraphStyle(
    'Badge',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=9.5,
    leading=13,
    textColor=colors.HexColor('#D81B60')
)

story = []

story.append(Paragraph("BAHU HAMARI RAJNI_KANT", title_style))
story.append(Spacer(1, 4))
story.append(Paragraph("The Ultimate Retrospective: Characters, Highlights & Iconic Scenes", subtitle_style))
story.append(Spacer(1, 12))

if os.path.exists(header_img):
    try:
        story.append(Image(header_img, width=540, height=180))
        story.append(Spacer(1, 12))
    except Exception:
        pass

overview_text = (
    "<b>Bahu Hamari Rajni_Kant</b> is a path-breaking Indian sci-fi comedy sitcom produced by Sonali Jaffar "
    "and Amir Jaffar. The series aired on Life OK and captured millions of hearts with its revolutionary concept: "
    "an ultra-advanced humanoid robot programmed with super-intelligence who enters a typical, melodramatic joint family "
    "as the ideal daughter-in-law (Bahu). Packed with side-splitting humor, high-tech quirks, and heartwarming family dynamics, "
    "the show stands out as one of the most innovative comedies on Indian television."
)
story.append(Paragraph(overview_text, body_style))
story.append(Spacer(1, 16))

story.append(Paragraph("🌟 Key Characters & Cast", h1_style))
story.append(Spacer(1, 6))

for c in characters:
    img_elem = None
    c_img_path = os.path.join("images", c['file'])
    if os.path.exists(c_img_path):
        try:
            img_elem = Image(c_img_path, width=130, height=105)
        except Exception:
            pass

    info_paras = [
        Paragraph(f"<b>{c['name']}</b>", h2_style),
        Paragraph(f"<b>Played by:</b> {c['actor']} | <i>{c['role']}</i>", badge_style),
        Spacer(1, 4),
        Paragraph(c['desc'], body_style)
    ]

    t_data = [[img_elem if img_elem else "", info_paras]]
    char_table = Table(t_data, colWidths=[140, 395])
    char_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F5F7FA')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CFD8DC')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))

    story.append(KeepTogether([char_table, Spacer(1, 10)]))

story.append(PageBreak())

story.append(Paragraph("🎬 Most Iconic & Memorable Scenes", h1_style))
story.append(Paragraph("A tribute to the highest-rated comedic and action sequences from the show:", subtitle_style))
story.append(Spacer(1, 12))

for sc in scenes:
    sc_img_path = os.path.join("images", sc['file'])
    img_elem = None
    if os.path.exists(sc_img_path):
        try:
            img_elem = Image(sc_img_path, width=180, height=115)
        except Exception:
            pass

    sc_paras = [
        Paragraph(f"<b>{sc['title']}</b>", h2_style),
        Spacer(1, 4),
        Paragraph(sc['desc'], body_style)
    ]

    sc_table_data = [[img_elem if img_elem else "", sc_paras]]
    sc_table = Table(sc_table_data, colWidths=[190, 345])
    sc_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF9C4')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#FFE082')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))

    story.append(KeepTogether([sc_table, Spacer(1, 12)]))

story.append(Spacer(1, 10))
story.append(Paragraph("⚙️ Quick Facts & Show Legacy", h1_style))
facts_text = (
    "• <b>Full Form:</b> R.A.J.N.I stands for <i>Randomly Accessible Jobs Neural Interface</i>.<br/>"
    "• <b>Super Features:</b> 100-gigabyte instant memory recall, super strength capable of lifting cars, voice modulation, and facial scan diagnostics.<br/>"
    "• <b>Award Recognition:</b> Ridhima Pandit won the Zee Gold Award for Best Debutante for her portrayal of Rajni.<br/>"
    "• <b>Cult Following:</b> Broadcast across over 200 episodes, it revolutionized Indian comedic television by fusing domestic sitcom dynamics with high-concept robotics."
)
story.append(Paragraph(facts_text, body_style))

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
        self.setFillColor(colors.HexColor("#757575"))
        self.drawString(36, 20, "Bahu Hamari Rajni_Kant Retrospective | Pratham AI")
        self.drawRightString(letter[0] - 36, 20, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()

doc.build(story, canvasmaker=NumberedCanvas)
print("PDF successfully generated: bahu_hamari_rajnikant.pdf")
