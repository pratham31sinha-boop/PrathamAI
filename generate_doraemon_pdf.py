import os
import urllib.request
from PIL import Image as PILImage, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

os.makedirs('doraemon_assets', exist_ok=True)

characters = [
    {
        "name": "Doraemon (ドラえもん)",
        "role": "22nd-Century Robotic Cat",
        "desc": "A blue cat-type robot sent back in time from the 22nd century by Sewashi Nobi to aid and guide Nobita. Equipped with his famous 4D Pocket filled with futuristic secret gadgets, he loves Dorayaki (red bean pancakes) and is terrified of mice.",
        "url": "https://upload.wikimedia.org/wikipedia/en/b/bd/Doraemon_character.png",
        "fallback_color": "#1E88E5",
        "file": "doraemon_assets/doraemon.png"
    },
    {
        "name": "Nobita Nobi (野比のび太)",
        "role": "The Kindhearted Protagonist",
        "desc": "An easygoing, clumsy, and kindhearted schoolboy who struggles with academics and sports, but possesses remarkable marksmanship and cat-cradle skills. While he frequently relies on Doraemon's gadgets, his empathy and courage always shine when friends need help.",
        "url": "https://upload.wikimedia.org/wikipedia/en/a/aa/NobitaNobi.png",
        "fallback_color": "#FBC02D",
        "file": "doraemon_assets/nobita.png"
    },
    {
        "name": "Shizuka Minamoto (源静香)",
        "role": "Nobita's Future Bride & Sweet Friend",
        "desc": "A sweet, responsible, intelligent, and gentle girl who is adored by everyone in the neighborhood. She loves sweet potatoes, taking long baths, and practicing the violin (even if poorly) and piano. She is Nobita's future wife and steadfast supporter.",
        "url": "https://upload.wikimedia.org/wikipedia/en/3/3b/Shizuka_Minamoto.png",
        "fallback_color": "#EC407A",
        "file": "doraemon_assets/shizuka.png"
    },
    {
        "name": "Takeshi 'Gian' Goda (剛田武)",
        "role": "The Neighborhood Strongman",
        "desc": "A muscular, loud, and quick-tempered bully who dreams of becoming a legendary pop singer and celebrity chef—despite his singing and cooking being hilariously catastrophic. Deep down, Gian is intensely loyal, fiercely protects his younger sister Jaiko, and stands up for his friends during real crises.",
        "url": "https://upload.wikimedia.org/wikipedia/en/4/4b/Takeshi_Goda.png",
        "fallback_color": "#FB8C00",
        "file": "doraemon_assets/gian.png"
    },
    {
        "name": "Suneo Honekawa (骨川スネ夫)",
        "role": "The Wealthy Bragger & Tactician",
        "desc": "A wealthy, crafty boy with a fox-like grin who constantly flaunts high-end toys, exotic vacations, and comic books. Though he often schemes alongside Gian, Suneo is secretly self-conscious, exceptionally knowledgeable in science and arts, and a loyal friend in serious adventures.",
        "url": "https://upload.wikimedia.org/wikipedia/en/1/14/Suneo_Honekawa.png",
        "fallback_color": "#43A047",
        "file": "doraemon_assets/suneo.png"
    },
    {
        "name": "Dorami (ドラミ)",
        "role": "Doraemon's Capable Little Sister",
        "desc": "Doraemon's younger sister who lives in the 22nd century with Sewashi. Unlike Doraemon, she retains her ears (styled as a red bow), boasts 10,000 horsepower, and rarely has gadget malfunctions. She steps in whenever Doraemon needs maintenance or Nobita needs discipline.",
        "url": "https://static.wikia.nocookie.net/doraemon/images/9/91/Dorami_2005.png",
        "fallback_color": "#FFF176",
        "file": "doraemon_assets/dorami.png"
    },
    {
        "name": "Hidetoshi Dekisugi (出木杉英才)",
        "role": "The Model Student & Scholar",
        "desc": "Nobita's brilliant classmate who excels effortlessly in academics, athletics, cooking, and arts. Despite Nobita viewing him as a romantic rival for Shizuka's attention, Dekisugi is extremely humble, kind, respectful, and always willing to share his vast knowledge.",
        "url": "https://static.wikia.nocookie.net/doraemon/images/b/b2/Dekisugi.png",
        "fallback_color": "#7E57C2",
        "file": "doraemon_assets/dekisugi.png"
    }
]

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

for char in characters:
    filepath = char["file"]
    downloaded = False
    try:
        req = urllib.request.Request(char["url"], headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = resp.read()
            if len(data) > 1000:
                with open(filepath, 'wb') as f:
                    f.write(data)
                # Verify it opens as an image
                with PILImage.open(filepath) as img:
                    img.convert('RGB').save(filepath, 'PNG')
                downloaded = True
    except Exception as e:
        downloaded = False
    
    if not downloaded or not os.path.exists(filepath):
        # Create an artistic badge avatar
        img = PILImage.new('RGBA', (200, 200), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([10, 10, 190, 190], fill=char["fallback_color"], outline='#1A237E', width=4)
        initials = char["name"][0]
        draw.text((80, 70), initials, fill='#FFFFFF')
        img.convert('RGB').save(filepath, 'PNG')

pdf_filename = "doraemon_characters_complete_guide.pdf"

doc = SimpleDocTemplate(
    pdf_filename,
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
    textColor=colors.HexColor('#0D47A1'),
    alignment=1,
    spaceAfter=6
)

subtitle_style = ParagraphStyle(
    'DocSubTitle',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=11,
    leading=14,
    textColor=colors.HexColor('#1E88E5'),
    alignment=1,
    spaceAfter=15
)

name_style = ParagraphStyle(
    'CharName',
    parent=styles['Heading2'],
    fontName='Helvetica-Bold',
    fontSize=14,
    leading=17,
    textColor=colors.HexColor('#0D47A1'),
    spaceAfter=2
)

role_style = ParagraphStyle(
    'CharRole',
    parent=styles['Normal'],
    fontName='Helvetica-Bold',
    fontSize=9,
    leading=12,
    textColor=colors.HexColor('#E53935'),
    spaceAfter=6
)

desc_style = ParagraphStyle(
    'CharDesc',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=9.5,
    leading=13.5,
    textColor=colors.HexColor('#263238')
)

story = []

# Header
story.append(Paragraph("DORAEMON: THE ULTIMATE CHARACTER COMPENDIUM", title_style))
story.append(Paragraph("A Comprehensive Illustrated Character Guide & Profiles &bull; Pratham AI Edition", subtitle_style))
story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1E88E5'), spaceAfter=15))

for char in characters:
    try:
        # Resize image cleanly
        with PILImage.open(char["file"]) as p_img:
            aspect = p_img.height / float(p_img.width) if p_img.width > 0 else 1.0
            display_w = 85
            display_h = 85
        img_flowable = RLImage(char["file"], width=display_w, height=display_h)
    except Exception:
        img_flowable = Paragraph("<b>[Image]</b>", styles['Normal'])

    text_flowables = [
        Paragraph(char["name"], name_style),
        Paragraph(char["role"].upper(), role_style),
        Paragraph(char["desc"], desc_style)
    ]

    table_data = [[img_flowable, text_flowables]]
    card_table = Table(table_data, colWidths=[95, 445])
    card_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F4F8FB')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#BBDEFB')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('LINEBEFORE', (1, 0), (1, 0), 1, colors.HexColor('#E3F2FD')),
    ]))

    story.append(card_table)
    story.append(Spacer(1, 10))

doc.build(story)
print(f"SUCCESS: {pdf_filename} created, size: {os.path.getsize(pdf_filename)} bytes")
