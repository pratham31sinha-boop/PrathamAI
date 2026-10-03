import hashlib

# Fix Python/OpenSSL compatibility issue with reportlab's md5 usage
_orig_md5 = hashlib.md5
def _patched_md5(*args, **kwargs):
    kwargs.pop('usedforsecurity', None)
    return _orig_md5(*args, **kwargs)
hashlib.md5 = _patched_md5

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

def generate_pokemon_pdf(filename="pokemon_essay.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=45,
        bottomMargin=45
    )

    styles = getSampleStyleSheet()

    # Custom typography & styles
    title_style = ParagraphStyle(
        'PokeTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#C81D25'),
        alignment=1, # Centered
        spaceAfter=6
    )

    subtitle_style = ParagraphStyle(
        'PokeSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-BoldOblique',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0B3C5D'),
        alignment=1,
        spaceAfter=14
    )

    section_heading = ParagraphStyle(
        'PokeSection',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#D32F2F'),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'PokeBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14.5,
        textColor=colors.HexColor('#222222'),
        spaceAfter=8,
        alignment=4 # Justified
    )

    caption_style = ParagraphStyle(
        'PokeCaption',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#555555'),
        alignment=1,
        spaceAfter=12
    )

    story = []

    # Title & Subtitle
    story.append(Paragraph("Pokémon Profile: Pikachu (#0025)", title_style))
    story.append(Paragraph("The Electric Mouse Phenomenon and Global Cultural Icon", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#F4D03F'), spaceAfter=14))

    # Image of Pokémon
    img_path = "pikachu.png"
    if os.path.exists(img_path):
        poke_img = Image(img_path, width=2.2*inch, height=2.2*inch)
        poke_img.hAlign = 'CENTER'
        story.append(poke_img)
        story.append(Paragraph("Figure 1: Official Artwork of Pikachu, the Electric-type Mouse Pokémon.", caption_style))

    # Fast Facts Table
    data = [
        [
            Paragraph("<b>National Pokédex:</b> #0025", body_style),
            Paragraph("<b>Type:</b> Electric ⚡", body_style),
            Paragraph("<b>Category:</b> Mouse Pokémon", body_style)
        ],
        [
            Paragraph("<b>Height:</b> 0.4 m (1'04\")", body_style),
            Paragraph("<b>Weight:</b> 6.0 kg (13.2 lbs)", body_style),
            Paragraph("<b>Ability:</b> Static / Lightning Rod", body_style)
        ]
    ]
    t = Table(data, colWidths=[2.3*inch, 2.3*inch, 2.3*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF9E6')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#F4D03F')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#FADBD8')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    # Essay Section 1: Introduction
    story.append(Paragraph("1. Introduction & Origins", section_heading))
    story.append(Paragraph(
        "Introduced in 1996 with Nintendo's pioneering Game Boy releases, <i>Pokémon Red</i> and <i>Green</i>, "
        "Pikachu swiftly transcended its original role as an in-game creature to become the undisputed worldwide "
        "ambassador of the entire Pokémon franchise. Conceived and designed by Atsuko Nishida and finalized under "
        "art director Ken Sugimori, Pikachu's aesthetic is characterized by its bright yellow rodent-like anatomy, "
        "distinctive thunderbolt-shaped tail, and crimson cheek pouches capable of discharging electricity.",
        body_style
    ))

    # Essay Section 2: Biology and Abilities
    story.append(Paragraph("2. Anatomy, Biology & Battle Abilities", section_heading))
    story.append(Paragraph(
        "Within the lore of the Pokémon universe, Pikachu is an Electric-type Pokémon classified as the 'Mouse Pokémon.' "
        "Its biological trademark lies in the twin circular red sacs located on its cheeks. These specialized organs store "
        "high-voltage electrical energy harvested from the atmosphere and rest. When threatened, agitated, or communicating, "
        "Pikachu channels this bio-electricity into signature offensive techniques such as <i>Thunderbolt</i>, <i>Volt Tackle</i>, "
        "and <i>Thunder Wave</i>. When several Pikachu gather in groups, their accumulated electromagnetic output can disrupt weather "
        "conditions and trigger localized lightning storms. Moreover, Pikachu evolves from Pichu through deep emotional friendship "
        "and advances into Raichu upon contact with a Thunder Stone.",
        body_style
    ))

    # Essay Section 3: Cultural Impact and Mascot Status
    story.append(Paragraph("3. Cultural Phenomenon & Mascot Status", section_heading))
    story.append(Paragraph(
        "Pikachu’s ascension to mascot status was solidified with the debut of the 1997 animated television series. Paired as the "
        "first companion to protagonist Ash Ketchum (Satoshi), this stubborn yet fiercely devoted Pikachu established an emotional "
        "anchor that resonated across generations. Unlike most Pokémon confined to Pokéballs, Ash's Pikachu journeyed alongside him "
        "on his shoulder, cementing an iconic image recognized across the globe. Pikachu has appeared as giant parade balloons in the "
        "Macy's Thanksgiving Day Parade, graced the fuselage of commercial Boeing 747 aircraft with All Nippon Airways, and starred in "
        "Hollywood's live-action feature film <i>Detective Pikachu</i> (voiced by Ryan Reynolds).",
        body_style
    ))

    # Essay Section 4: Conclusion
    story.append(Paragraph("4. Legacy and Conclusion", section_heading))
    story.append(Paragraph(
        "More than a quarter-century after its debut, Pikachu remains a rare cultural touchstone that bridges generational, linguistic, "
        "and geographic barriers. Standing alongside historic cartoon icons such as Mickey Mouse and Bugs Bunny, Pikachu symbolizes "
        "camaraderie, adventure, and the enduring charm of Japanese pop culture.",
        body_style
    ))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CCCCCC'), spaceAfter=8))
    story.append(Paragraph("Document synthesized by Pratham AI • Complete Pokémon Profile & Analytical Essay", caption_style))

    doc.build(story)
    print("PDF successfully generated:", filename)

if __name__ == "__main__":
    generate_pokemon_pdf()
