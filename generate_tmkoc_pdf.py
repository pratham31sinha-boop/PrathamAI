import os
import sys
from concurrent.futures import ThreadPoolExecutor
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle, PageBreak, KeepTogether
from PIL import Image as PILImage, ImageDraw

CACHE_DIR = "/tmp/tmkoc_photos"
os.makedirs(CACHE_DIR, exist_ok=True)

try:
    from fetch_image import fetch_web_image
except ImportError:
    def fetch_web_image(query, path, timeout=1.5):
        return False

TMKOC_CHARACTERS = [
    {
        "name": "Jethalal Champaklal Gada",
        "actor": "Dilip Joshi",
        "role": "Proprietor, Gada Electronics | Gokuldham Society",
        "desc": "The central protagonist of TMKOC. A quirky, hardworking businessman known for his daily 'mushkilein' (troubles), affection for Babita ji, and reverence for Bapuji.",
        "search": "Dilip Joshi Jethalal Gada TMKOC"
    },
    {
        "name": "Daya Jethalal Gada",
        "actor": "Disha Vakani",
        "role": "Homemaker | Queen of Garba",
        "desc": "Famous for her distinct 'Hey Maa Mataji!' catchphrase, energetic Garba dances, delicious cooking, and loving, pure-hearted devotion to her family and society members.",
        "search": "Disha Vakani Daya Ben TMKOC"
    },
    {
        "name": "Champaklal Jayantilal Gada (Bapuji)",
        "actor": "Amit Bhatt",
        "role": "Elder Patriarch | Moral Compass of Gokuldham",
        "desc": "Jethalal's father from Bhachau, Kutch. The moral pillar who scolds Jethalal ('Nahane jaa, nahane jaa!') but showers limitless love on Tapu and resolves all society disputes.",
        "search": "Amit Bhatt Champaklal Gada Bapuji TMKOC"
    },
    {
        "name": "Taarak Mehta",
        "actor": "Shailesh Lodha / Sachin Shroff",
        "role": "Columnist & Writer | Jethalal's 'Fire Brigade'",
        "desc": "A witty writer and Jethalal's best friend and troubleshooter ('Fire Brigade'). Suffering under Anjali's diet food, he narrates life lessons and philosophies at the end of each episode.",
        "search": "Shailesh Lodha Taarak Mehta Fire Brigade TMKOC"
    },
    {
        "name": "Babita Krishnan Iyer",
        "actor": "Munmun Dutta",
        "role": "Glamorous Resident | Gokuldham Society",
        "desc": "Originally from Kolkata, modern and elegant. Married to scientist Krishnan Iyer. Jethalal's neighbor whom Jethalal always tries to impress with hilarious antics.",
        "search": "Munmun Dutta Babita Ji TMKOC"
    },
    {
        "name": "Aatmaram Tukaram Bhide",
        "actor": "Mandar Chandwadkar",
        "role": "Society Secretary | Home Tutor ('Ekmev Secretary')",
        "desc": "A disciplined Marathi teacher, proud of his scooter 'Sakharam' and principles. Famous for his catchphrase 'Humare zamane mein...' and constant funny banter with Jethalal.",
        "search": "Mandar Chandwadkar Aatmaram Bhide Secretary TMKOC"
    },
    {
        "name": "Patrakar Popatlal",
        "actor": "Shyam Pathak",
        "role": "Senior Crime Reporter, Toofan Express",
        "desc": "Ever-eligible bachelor holding an umbrella, famously screaming 'Duniya hila dunga!' and 'Cancel, cancel, cancel!'. Desperately seeking a bride to get married.",
        "search": "Shyam Pathak Popatlal Umbrella TMKOC"
    },
    {
        "name": "Dr. Hansraj Hathi",
        "actor": "Kavi Kumar Azad / Nirmal Soni",
        "role": "Physician | Food Enthusiast",
        "desc": "Gokuldham's beloved, jolly doctor who loves food above everything else. Renowned for his soothing catchphrase: 'Sahi baat hai!'.",
        "search": "Kavi Kumar Azad Dr Hathi TMKOC"
    },
    {
        "name": "Krishnan Subramaniam Iyer",
        "actor": "Tanuj Mahashabde",
        "role": "Senior Research Scientist | Babita's Husband",
        "desc": "A proud Tamilian rocket scientist who takes pride in his intellect and constantly spars with Jethalal over minor society affairs and Babita.",
        "search": "Tanuj Mahashabde Krishnan Iyer TMKOC"
    },
    {
        "name": "Roshan Singh Sodhi",
        "actor": "Gurucharan Singh / Balvinder Suri",
        "role": "Garage Owner | High-Energy Enthusiast",
        "desc": "A high-spirited Punjabi mechanic who fiercely loves his Parsi wife Roshan, is always ready for celebration and 'party-sharty', and protects society members fiercely.",
        "search": "Gurucharan Singh Sodhi TMKOC"
    },
    {
        "name": "Tipendra Gada (Tapu) & Tapu Sena",
        "actor": "Bhavya Gandhi / Raj Anadkat / Nitish Bhaluni",
        "role": "Leader of Tapu Sena",
        "desc": "Jethalal's mischievous yet bright son. Together with Goli, Pinku, Gogi, and Sonu, forms Tapu Sena, organizing society festivals and playful neighborhood adventures.",
        "search": "Tapu Sena Gokuldham Bhavya Gandhi TMKOC"
    },
    {
        "name": "Bagheshwar (Bagha) & Natu Kaka",
        "actor": "Tanmay Vekaria & Ghanshyam Nayak",
        "role": "Employees, Gada Electronics",
        "desc": "Iconic employees of Gada Electronics. Natu Kaka famously saying 'Aapne mujhe kuch kaha, sethji?' and asking for salary hikes, while Bagha delivers quirky solutions ('Jaisi jiski soch').",
        "search": "Tanmay Vekaria Bagha Natu Kaka Gada Electronics TMKOC"
    }
]

def prepare_single_image(args):
    char_idx, char = args
    img_path = os.path.join(CACHE_DIR, f"tmkoc_{char_idx}.jpg")
    if not os.path.exists(img_path) or os.path.getsize(img_path) < 1000:
        fetched = False
        try:
            fetched = fetch_web_image(char["search"], img_path, timeout=1.5)
        except Exception:
            pass
        if not fetched or not os.path.exists(img_path) or os.path.getsize(img_path) < 1000:
            img = PILImage.new("RGB", (320, 320), color=(26, 32, 44))
            draw = ImageDraw.Draw(img)
            draw.rectangle([10, 10, 310, 310], outline=(234, 88, 12), width=4)
            initials = "".join([w[0] for w in char["name"].split()[:2]])
            draw.text((120, 110), initials, fill=(249, 115, 22))
            draw.text((30, 240), char["actor"][:25], fill=(226, 232, 240))
            img.save(img_path, "JPEG")
    return img_path

def generate_tmkoc_pdf(filename="tmkoc_encyclopedia.pdf"):
    # Concurrently fetch images
    tasks = [(idx, char) for idx, char in enumerate(TMKOC_CHARACTERS)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        img_paths = list(ex.map(prepare_single_image, tasks))

    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30
    )
    styles = getSampleStyleSheet()

    header_style = ParagraphStyle(
        'TMKOC_Header',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#C2410C'),
        alignment=1
    )
    sub_style = ParagraphStyle(
        'TMKOC_Sub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#475569'),
        alignment=1
    )
    card_title_style = ParagraphStyle(
        'CardTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#9A3412')
    )
    actor_style = ParagraphStyle(
        'ActorName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#2563EB')
    )
    role_style = ParagraphStyle(
        'RoleTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#64748B')
    )
    desc_style = ParagraphStyle(
        'DescText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor('#1E293B')
    )

    story = []
    story.append(Paragraph("Taarak Mehta Ka Ooltah Chashmah", header_style))
    story.append(Paragraph("Complete Gokuldham Society Character Encyclopedia & Cast Guide", sub_style))
    story.append(Spacer(1, 15))

    for idx, char in enumerate(TMKOC_CHARACTERS):
        img_p = img_paths[idx]
        try:
            rl_img = RLImage(img_p, width=1.4*72, height=1.4*72)
        except Exception:
            rl_img = Paragraph("Photo", desc_style)

        text_cell = [
            Paragraph(char["name"], card_title_style),
            Spacer(1, 2),
            Paragraph(f"<b>Portrayed by:</b> {char['actor']}", actor_style),
            Paragraph(f"<b>Role:</b> {char['role']}", role_style),
            Spacer(1, 4),
            Paragraph(char["desc"], desc_style)
        ]

        card_table = Table([[rl_img, text_cell]], colWidths=[1.6*72, 5.4*72])
        card_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF7ED')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#FDBA74')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        story.append(card_table)
        story.append(Spacer(1, 10))

        if (idx + 1) % 4 == 0 and (idx + 1) < len(TMKOC_CHARACTERS):
            story.append(PageBreak())

    doc.build(story)
    print(f"SUCCESS: {filename} compiled successfully ({len(TMKOC_CHARACTERS)} characters)")
    return filename

if __name__ == "__main__":
    fn = sys.argv[1] if len(sys.argv) > 1 else "tmkoc_encyclopedia.pdf"
    generate_tmkoc_pdf(fn)
