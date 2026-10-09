import os
import zipfile
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from PIL import Image

# 1. Prepare character metadata
characters = [
    {
        "name": "Chhota Bheem",
        "title": "The Brave & Legendary Hero of Dholakpur",
        "desc": "Chhota Bheem is an exceptionally strong, adventurous, and pure-hearted 9-year-old boy of Dholakpur. Armed with superhuman vigor that surges tenfold after eating Tuntun Mausi's fresh laddoos, he defends the innocent, repels invaders, and upholds justice across all lands.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/01_chhota_bheem.png",
        "theme": "#C0392B"
    },
    {
        "name": "Chutki",
        "title": "Bheem's Clever, Loyal & Caring Companion",
        "desc": "Chutki is a quick-witted, generous, and brave 7-year-old girl, daughter of Tuntun Mausi. She is Bheem's most loyal best friend who always provides wise advice, strategizes when problems arise, and brings delicious laddoos to fuel Bheem in pivotal battles.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/02_chutki.png",
        "theme": "#E91E63"
    },
    {
        "name": "Raju",
        "title": "The Fearless Prodigy Archer",
        "desc": "Raju is an energetic, brave 4-year-old boy whose idol and role model is Bheem. Despite being the youngest in the squad, Raju displays extraordinary courage, sharp wits, and world-class skill with his bow and arrow in every clash.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/03_raju.png",
        "theme": "#2980B9"
    },
    {
        "name": "Jaggu Bandar",
        "title": "The Wise, Agile & Jovial Monkey",
        "desc": "Jaggu is a talking monkey with acrobatic agility, a quick sense of humor, and deep forest expertise. He scouts high canopies, extracts vital clues, and supports Bheem and friends with daring aerial moves.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/04_jaggu_bandar.png",
        "theme": "#8E44AD"
    },
    {
        "name": "Kalia Tevar (Kalia Ustad)",
        "title": "The Boastful Strongman & Fierce Rival",
        "desc": "Kalia is an ambitious, burly 10-year-old boy who constantly tries to outdo Bheem to prove his own dominance. While boastful and envious of Bheem's acclaim, Kalia has a protective core and stands shoulder-to-shoulder with Bheem when true danger strikes.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/05_kalia_tevar.png",
        "theme": "#D35400"
    },
    {
        "name": "Dholu & Bholu",
        "title": "The Mischievous & Comical Twin Brothers",
        "desc": "Dholu and Bholu are identical twin brothers who eagerly accompany Kalia as his hype crew. Their naive slips of the tongue repeatedly expose Kalia's bluffs, adding constant comedy while staying fiercely devoted to each other.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/06_dholu_and_bholu.png",
        "theme": "#F39C12"
    },
    {
        "name": "Raja Indraverma",
        "title": "The Benevolent & Wise King of Dholakpur",
        "desc": "Raja Indraverma is the noble, fair-minded monarch ruling Dholakpur with integrity and generosity. He holds supreme trust in Bheem's valor and wisdom, regularly enlisting him to handle diplomatic perils, mythical beasts, and foreign warlords.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/07_raja_indraverma.png",
        "theme": "#B71C1C"
    },
    {
        "name": "Princess Indumati",
        "title": "The Gracious & Cheerful Royal Princess",
        "desc": "Princess Indumati is the compassionate daughter of King Indraverma. Unpretentious and warm, she loves playing with Bheem and the village kids, bringing royal charm and harmony to community celebrations.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/08_princess_indumati.png",
        "theme": "#9C27B0"
    },
    {
        "name": "Tuntun Mausi",
        "title": "Dholakpur's Legendary Laddoo Artisan",
        "desc": "Tuntun Mausi is Chutki's feisty, warm-hearted mother who runs the most famous sweet confectionery in the realm. Her delicious laddoos are not only culinary masterpieces, but they also grant Bheem instant super-strength when eaten.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/09_tuntun_mausi.png",
        "theme": "#E67E22"
    },
    {
        "name": "Professor Dhoomketu",
        "title": "The Visionary Hillside Scientist & Inventor",
        "desc": "Professor Dhoomketu is an eccentric genius residing in an observatory near the foothills of Dholakpur. He crafts wondrous futuristic contraptions—from flying machines to sonic gizmos—that propel the gang into high-tech escapades.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/10_prof_dhoomketu.png",
        "theme": "#27AE60"
    },
    {
        "name": "Kirmada",
        "title": "The Dark Demon King & Dreaded Arch-Nemesis",
        "desc": "Kirmada is an ancient, menacing sorcerer-demon who embodies darkness, greed, and conquest. Wielding dark sorcery and shadow armies, he stands as Bheem's most dangerous and fearsome adversary.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/11_kirmada.png",
        "theme": "#212121"
    },
    {
        "name": "Daku Mangal Singh",
        "title": "The Infamous Ravine Bandit Leader",
        "desc": "Mangal Singh is a cunning outlaw captain who lurks along the outskirts and trade roads of Dholakpur with his band of bandits. In spite of his terrifying reputation, his robbery raids are consistently thwarted by Bheem's swift heroism.",
        "img": "/workspace/bold-curie/chhota_bheem_character_images/12_daku_mangal_singh.png",
        "theme": "#546E7A"
    }
]

# 2. Numbered Canvas for publication grade headers and footers
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
            self.draw_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#7F8C8D"))
        
        # Header (Pages 2+)
        if self._pageNumber > 1:
            self.drawString(40, 11 * inch - 30, "CHHOTA BHEEM — COMPLETE CHARACTERS & HEROES ENCYCLOPEDIA")
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.6)
            self.line(40, 11 * inch - 34, 8.5 * inch - 40, 11 * inch - 34)
            
        # Footer
        footer_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(8.5 * inch - 40, 25, footer_text)
        self.setFont("Helvetica", 8)
        self.drawString(40, 25, "Created by Pratham AI (Pratham Sinha under the supervision of Akriti & Aditi Aishwaryam)")
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.6)
        self.line(40, 35, 8.5 * inch - 40, 35)
        
        self.restoreState()

def generate_pdf_and_zip():
    pdf_filename = "/workspace/bold-curie/chhota_bheem_characters_encyclopedia.pdf"
    zip_filename = "/workspace/bold-curie/chhota_bheem_characters_complete_pack.zip"
    
    doc = SimpleDocTemplate(
        pdf_filename,
        pagesize=letter,
        leftMargin=38,
        rightMargin=38,
        topMargin=46,
        bottomMargin=46
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        alignment=1,
        textColor=colors.HexColor('#C0392B')
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        alignment=1,
        textColor=colors.HexColor('#4A5568')
    )
    
    char_name_style = ParagraphStyle(
        'CharName',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#8B0000'),
        spaceAfter=2
    )
    
    char_role_style = ParagraphStyle(
        'CharRole',
        parent=styles['Normal'],
        fontName='Helvetica-BoldOblique',
        fontSize=9.5,
        leading=12.5,
        textColor=colors.HexColor('#D35400'),
        spaceAfter=4
    )
    
    char_desc_style = ParagraphStyle(
        'CharDesc',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#2D3748')
    )
    
    elements = []
    
    # Title Banner
    elements.append(Paragraph("CHHOTA BHEEM: CHARACTERS & HEROES ENCYCLOPEDIA", title_style))
    elements.append(Spacer(1, 3))
    elements.append(Paragraph("Complete Illustrated Character Guide Featuring Full Bios, Profiles & Lore of Dholakpur", subtitle_style))
    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", thickness=1.8, color=colors.HexColor('#C0392B'), spaceBefore=2, spaceAfter=12))
    
    # Add characters in pairs per page
    for i in range(0, len(characters), 2):
        pair = characters[i:i+2]
        for char in pair:
            # Scaled image
            rl_img = RLImage(char["img"], width=110, height=110)
            
            text_block = [
                Paragraph(char["name"], char_name_style),
                Paragraph(char["title"], char_role_style),
                Spacer(1, 2),
                Paragraph(char["desc"], char_desc_style)
            ]
            
            card_table = Table(
                [[rl_img, text_block]],
                colWidths=[120, 416]
            )
            card_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF9F5')),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#ED8936')),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ]))
            
            elements.append(card_table)
            elements.append(Spacer(1, 14))
        
        if i + 2 < len(characters):
            elements.append(PageBreak())
    
    # Build PDF with NumberedCanvas
    doc.build(elements, canvasmaker=NumberedCanvas)
    print("Successfully built PDF:", pdf_filename, "Size:", os.path.getsize(pdf_filename))
    
    # Create ZIP file containing PDF and all individual character images
    with zipfile.ZipFile(zip_filename, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
        # Add PDF
        zipf.write(pdf_filename, arcname="chhota_bheem_characters_encyclopedia.pdf")
        # Add character images
        for char in characters:
            arc_name = f"characters_images/{os.path.basename(char['img'])}"
            zipf.write(char['img'], arcname=arc_name)
    
    print("Successfully built ZIP archive:", zip_filename, "Size:", os.path.getsize(zip_filename))

if __name__ == '__main__':
    generate_pdf_and_zip()
