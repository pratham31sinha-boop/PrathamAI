"""
Advanced Mathematical Foundations, Calculus Optimization & Geometric Analysis
Publication-Grade Document & Diagram Generator with ZIP Packaging
Created for Pratham AI by Pratham Sinha under the supervision of Akriti & Aditi Aishwaryam.
"""

import os
import sys
import zipfile
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Arc, Rectangle

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage, PageBreak, HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas

ASSETS_DIR = "/workspace/bold-curie/math_diagram_assets"
os.makedirs(ASSETS_DIR, exist_ok=True)

# -------------------------------------------------------------
# 1. GENERATE NEAT, CLEAN MATHEMATICAL & GEOMETRIC DIAGRAMS
# -------------------------------------------------------------

def generate_figure_1_calculus_optimization():
    fig, ax = plt.subplots(figsize=(7, 3.8), dpi=300)
    plt.style.use('seaborn-v0_8-whitegrid')
    
    x = np.linspace(-1.5, 4.5, 500)
    # f(x) = x^3 - 4x^2 + 2x + 5
    y = x**3 - 4*x**2 + 2*x + 5
    
    # Critical points: f'(x) = 3x^2 - 8x + 2 = 0 => x = (8 +- sqrt(40))/6
    x_local_max = (8 - np.sqrt(40)) / 6
    y_local_max = x_local_max**3 - 4*x_local_max**2 + 2*x_local_max + 5
    x_local_min = (8 + np.sqrt(40)) / 6
    y_local_min = x_local_min**3 - 4*x_local_min**2 + 2*x_local_min + 5
    
    # Plot curve
    ax.plot(x, y, color='#1E40AF', linewidth=2.5, label=r'$f(x) = x^3 - 4x^2 + 2x + 5$')
    
    # Highlight local extrema
    ax.scatter([x_local_max], [y_local_max], color='#DC2626', s=80, zorder=5, label=f'Local Max ({x_local_max:.2f}, {y_local_max:.2f})')
    ax.scatter([x_local_min], [y_local_min], color='#16A34A', s=80, zorder=5, label=f'Local Min ({x_local_min:.2f}, {y_local_min:.2f})')
    
    # Tangent lines at extrema
    ax.axhline(y=y_local_max, xmin=0.2, xmax=0.45, color='#DC2626', linestyle='--', linewidth=1.5, alpha=0.7)
    ax.axhline(y=y_local_min, xmin=0.6, xmax=0.85, color='#16A34A', linestyle='--', linewidth=1.5, alpha=0.7)
    
    # Shaded inflection region
    x_infl = 4.0 / 3.0
    y_infl = x_infl**3 - 4*x_infl**2 + 2*x_infl + 5
    ax.scatter([x_infl], [y_infl], color='#9333EA', s=70, zorder=5, label=f'Inflection Point $f\'\'(x)=0$ ({x_infl:.2f}, {y_infl:.2f})')
    
    ax.set_title("Figure 1: Non-Convex Optimization Landscape & First/Second Derivative Extrema", fontsize=11, fontweight='bold', pad=12, color='#0F172A')
    ax.set_xlabel("Independent Variable $x$", fontsize=9.5, fontweight='bold', color='#1E293B')
    ax.set_ylabel("Objective Value $f(x)$", fontsize=9.5, fontweight='bold', color='#1E293B')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(frameon=True, facecolor='white', framealpha=0.95, fontsize=8.5, loc='upper left')
    
    path = os.path.join(ASSETS_DIR, "fig1_calculus_optimization.png")
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close()
    return path


def generate_figure_2_riemann_integration():
    fig, ax = plt.subplots(figsize=(7, 3.8), dpi=300)
    plt.style.use('seaborn-v0_8-whitegrid')
    
    x = np.linspace(0.5, 5.0, 400)
    # Continuous positive function
    def f(t):
        return t * np.sin(t) + 3.5
    
    y = f(x)
    a, b = 1.0, 4.5
    
    ax.plot(x, y, color='#0D9488', linewidth=2.5, label=r'$f(x) = x \cdot \sin(x) + 3.5$')
    
    # Riemann rectangles
    n_rects = 7
    dx = (b - a) / n_rects
    x_rects = np.linspace(a, b - dx, n_rects)
    
    for xr in x_rects:
        yr = f(xr + dx/2)
        rect = Rectangle((xr, 0), dx, yr, facecolor='#99F6E4', edgecolor='#0F766E', alpha=0.6, linewidth=1.2)
        ax.add_patch(rect)
        
    # Shaded exact definite integral area
    ix = np.linspace(a, b, 200)
    iy = f(ix)
    verts = [(a, 0), *zip(ix, iy), (b, 0)]
    poly = Polygon(verts, facecolor='#2DD4BF', alpha=0.25, edgecolor=None)
    ax.add_patch(poly)
    
    ax.axvline(x=a, color='#0F766E', linestyle=':', linewidth=1.5)
    ax.axvline(x=b, color='#0F766E', linestyle=':', linewidth=1.5)
    
    ax.text(2.6, 1.2, r'$\int_{a}^{b} f(x)\,dx \approx \sum_{i=1}^n f(x_i^*)\Delta x$', fontsize=11, fontweight='bold', color='#0F766E', bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor='#0D9488', alpha=0.9))
    
    ax.set_title("Figure 2: Definite Riemann Integration & Measurable Area Under Continuous Curvature", fontsize=11, fontweight='bold', pad=12, color='#0F172A')
    ax.set_xlabel("Domain Coordinate $x$", fontsize=9.5, fontweight='bold', color='#1E293B')
    ax.set_ylabel("Range $f(x)$", fontsize=9.5, fontweight='bold', color='#1E293B')
    ax.set_xlim(0.4, 5.2)
    ax.set_ylim(0, 6.0)
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(frameon=True, facecolor='white', framealpha=0.95, fontsize=8.5, loc='upper left')
    
    path = os.path.join(ASSETS_DIR, "fig2_riemann_integration.png")
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close()
    return path


def generate_figure_3_geometric_pythagorean_circle():
    fig, ax = plt.subplots(figsize=(7, 3.8), dpi=300)
    plt.style.use('seaborn-v0_8-whitegrid')
    
    # Coordinate system setup
    ax.axhline(0, color='#64748B', linewidth=1.2)
    ax.axvline(0, color='#64748B', linewidth=1.2)
    
    # Unit Circle
    theta = np.linspace(0, 2*np.pi, 300)
    ax.plot(np.cos(theta), np.sin(theta), color='#475569', linestyle='--', linewidth=1.2, label='Unit Circle $x^2 + y^2 = 1$')
    
    # 30-60-90 or 40-degree angle
    ang_deg = 36.87 # (3-4-5 right triangle proportion)
    ang_rad = np.radians(ang_deg)
    
    x_pt = np.cos(ang_rad)
    y_pt = np.sin(ang_rad)
    
    # Right triangle on coordinate plane
    triangle = Polygon([[0, 0], [x_pt, 0], [x_pt, y_pt]], facecolor='#E0F2FE', edgecolor='#0284C7', linewidth=2.2, label='Right Triangle: Adjacent, Opposite & Hypotenuse')
    ax.add_patch(triangle)
    
    # Hypotenuse vector
    ax.plot([0, x_pt], [0, y_pt], color='#BE123C', linewidth=2.5, label=r'Hypotenuse $r = 1.0$')
    
    # Angle arc
    arc = Arc((0, 0), 0.35, 0.35, angle=0, theta1=0, theta2=ang_deg, color='#D97706', linewidth=2.0)
    ax.add_patch(arc)
    ax.text(0.22, 0.07, r'$\theta$', fontsize=11, fontweight='bold', color='#D97706')
    
    # Labels for sides
    ax.text(x_pt / 2, -0.09, r'$\cos(\theta)$ (adj)', fontsize=9.5, fontweight='bold', color='#0369A1', ha='center')
    ax.text(x_pt + 0.04, y_pt / 2, r'$\sin(\theta)$ (opp)', fontsize=9.5, fontweight='bold', color='#0369A1')
    ax.text(x_pt / 2 - 0.08, y_pt / 2 + 0.07, r'$r = 1$', fontsize=9.5, fontweight='bold', color='#BE123C')
    
    # Pythagorean Identity Banner
    ax.text(-0.95, 0.85, r'$\sin^2(\theta) + \cos^2(\theta) = 1$', fontsize=11, fontweight='bold', color='#0F172A', bbox=dict(boxstyle='round,pad=0.4', facecolor='#FEF3C7', edgecolor='#F59E0B', alpha=0.95))
    
    ax.set_xlim(-1.15, 1.25)
    ax.set_ylim(-1.15, 1.15)
    ax.set_aspect('equal')
    ax.set_title("Figure 3: Geometric Trigonometric Circle & Pythagorean Fundamental Proof", fontsize=11, fontweight='bold', pad=12, color='#0F172A')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(frameon=True, facecolor='white', framealpha=0.95, fontsize=8.2, loc='lower left')
    
    path = os.path.join(ASSETS_DIR, "fig3_geometric_pythagorean.png")
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close()
    return path


def generate_figure_4_gaussian_distribution():
    fig, ax = plt.subplots(figsize=(7, 3.8), dpi=300)
    plt.style.use('seaborn-v0_8-whitegrid')
    
    mu, sigma = 0.0, 1.0
    x = np.linspace(-4.0, 4.0, 600)
    y = (1.0 / (sigma * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mu) / sigma)**2)
    
    ax.plot(x, y, color='#4338CA', linewidth=2.5, label=r'Gaussian PDF $\mathcal{N}(\mu=0, \sigma^2=1)$')
    
    # 68-95-99.7 empirical rule shading
    # 1 sigma
    mask1 = (x >= -1) & (x <= 1)
    ax.fill_between(x[mask1], y[mask1], color='#6366F1', alpha=0.35, label=r'$\mu \pm 1\sigma$ (68.27% probability)')
    
    # 2 sigma
    mask2_left = (x >= -2) & (x <= -1)
    mask2_right = (x >= 1) & (x <= 2)
    ax.fill_between(x[mask2_left], y[mask2_left], color='#818CF8', alpha=0.25, label=r'$\mu \pm 2\sigma$ (95.45% probability)')
    ax.fill_between(x[mask2_right], y[mask2_right], color='#818CF8', alpha=0.25)
    
    # 3 sigma
    mask3_left = (x >= -3) & (x <= -2)
    mask3_right = (x >= 2) & (x <= 3)
    ax.fill_between(x[mask3_left], y[mask3_left], color='#C7D2FE', alpha=0.2, label=r'$\mu \pm 3\sigma$ (99.73% probability)')
    ax.fill_between(x[mask3_right], y[mask3_right], color='#C7D2FE', alpha=0.2)
    
    # Mean line
    ax.axvline(0, color='#312E81', linestyle='--', linewidth=1.5)
    ax.text(0.1, 0.35, r'$\mu = 0$', fontsize=10, fontweight='bold', color='#312E81')
    
    ax.set_title("Figure 4: Standard Normal Distribution & Asymptotic Central Limit Confidence Bounds", fontsize=11, fontweight='bold', pad=12, color='#0F172A')
    ax.set_xlabel("Standard Deviations $(z = \frac{x - \mu}{\sigma})$", fontsize=9.5, fontweight='bold', color='#1E293B')
    ax.set_ylabel("Probability Density $p(z)$", fontsize=9.5, fontweight='bold', color='#1E293B')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(frameon=True, facecolor='white', framealpha=0.95, fontsize=8.2, loc='upper right')
    
    path = os.path.join(ASSETS_DIR, "fig4_gaussian_distribution.png")
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close()
    return path


# -------------------------------------------------------------
# 2. NUMBERED CANVAS FOR PUBLICATION-GRADE REPORTLAB PDF
# -------------------------------------------------------------

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
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#475569"))
        
        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 755, "ADVANCED MATHEMATICAL FOUNDATIONS & GEOMETRIC ANALYSIS")
            self.drawRightString(558, 755, "PRATHAM AI RESEARCH MONOGRAPH")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.75)
            self.line(54, 748, 558, 748)
            
        # Footer
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.75)
        self.line(54, 45, 558, 45)
        self.setFont("Helvetica", 8)
        self.drawString(54, 32, "Confidential & Autonomous Engineering Research | Verified by Pratham AI")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 32, page_str)
        self.restoreState()


# -------------------------------------------------------------
# 3. BUILD THE PUBLICATION PDF DOCUMENT
# -------------------------------------------------------------

def build_pdf_document(pdf_path):
    print("Generating mathematical figures...")
    p1 = generate_figure_1_calculus_optimization()
    p2 = generate_figure_2_riemann_integration()
    p3 = generate_figure_3_geometric_pythagorean_circle()
    p4 = generate_figure_4_gaussian_distribution()
    
    print(f"Figures generated: {p1}, {p2}, {p3}, {p4}")

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=colors.HexColor('#0F172A'),
        alignment=0,
        spaceAfter=6
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#2563EB'),
        spaceAfter=14
    )
    
    heading1_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=colors.HexColor('#1E293B'),
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor('#334155'),
        spaceAfter=8
    )
    
    formula_callout = ParagraphStyle(
        'FormulaText',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1
    )
    
    caption_style = ParagraphStyle(
        'FigCaption',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#475569'),
        alignment=1,
        spaceAfter=12
    )

    story = []

    # Title & Metadata
    story.append(Paragraph("Advanced Mathematical Foundations: Calculus Optimization, Integration Theory & Geometric Analysis", title_style))
    story.append(Paragraph("A Comprehensive Autonomous Analytical Monograph with High-Resolution Visual Proofs", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#2563EB'), spaceAfter=14))
    
    # Executive Abstract Card
    meta_table = Table([
        [
            Paragraph("<b>Author & Engineering System:</b> Pratham AI Autonomous Architecture<br/><b>Founder & Creator:</b> Pratham Sinha (Supervised by Akriti & Aditi Aishwaryam)<br/><b>Classification:</b> Applied Calculus, Real Analysis & Geometric Trigonometry", body_style),
            Paragraph("<b>Environment:</b> Autonomous Linux / Python 3.8<br/><b>Graphic Engine:</b> Matplotlib 300 DPI Vector-Aligned Raster<br/><b>Status:</b> Publication-Grade Verified Deliverable", body_style)
        ]
    ], colWidths=[270, 234])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 14))

    # SECTION 1: CALCULUS OPTIMIZATION
    story.append(Paragraph("1. First and Second Derivative Extrema in Non-Convex Spaces", heading1_style))
    story.append(Paragraph(
        "Optimization theory forms the bedrock of classical physics, gradient-based machine learning, and mathematical economics. "
        "Consider a continuous and differentiable objective scalar function <i>f(x) : ℝ → ℝ</i>. "
        "Fermat's Theorem on stationary points states that if a function attains a local extremum at an interior point <i>x*</i>, "
        "its first derivative must vanish identically, <b>f'(x*) = 0</b>.",
        body_style
    ))
    
    # Formula Box
    formula_box = Table([[Paragraph("Stationary Condition: &nbsp; &nbsp; <b>f'(x*) = 0</b> &nbsp; &nbsp; &nbsp; | &nbsp; &nbsp; &nbsp; Second Derivative Test: &nbsp; &nbsp; <b>f''(x*) &gt; 0</b> (Min) &nbsp; &nbsp; <b>f''(x*) &lt; 0</b> (Max)", formula_callout)]], colWidths=[504])
    formula_box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EFF6FF')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#3B82F6')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(formula_box)
    story.append(Spacer(1, 10))
    
    # Figure 1 Flowable
    story.append(RLImage(p1, width=5.2*inch, height=2.8*inch))
    story.append(Paragraph("<b>Figure 1:</b> <i>Analytical depiction of critical stationary points and inflection curvature.</i>", caption_style))
    story.append(Spacer(1, 8))

    # PAGE BREAK
    story.append(PageBreak())

    # SECTION 2: RIEMANN INTEGRATION
    story.append(Paragraph("2. Fundamental Theorem of Calculus & Riemann Sum Convergence", heading1_style))
    story.append(Paragraph(
        "The definite integral quantifies net signed accumulation across a compact continuous interval [a, b]. "
        "Under the Riemann formulation, the interval is partitioned into <i>n</i> subintervals of width Δx = (b - a)/n. "
        "As the norm of the partition approaches zero, the Riemann sum converges uniformly to the exact integral area:",
        body_style
    ))
    
    # Riemann Formula Box
    riemann_box = Table([[Paragraph("<b>∫<sub>a</sub><sup>b</sup> f(x) dx = lim<sub>n→∞</sub> ∑<sub>i=1</sub><sup>n</sup> f(x<sub>i</sub><sup>*</sup>) Δx = F(b) - F(a)</b> &nbsp; where &nbsp; F'(x) = f(x)", formula_callout)]], colWidths=[504])
    riemann_box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F0FDFA')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#0D9488')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(riemann_box)
    story.append(Spacer(1, 10))
    
    # Figure 2 Flowable
    story.append(RLImage(p2, width=5.2*inch, height=2.8*inch))
    story.append(Paragraph("<b>Figure 2:</b> <i>Riemann rectangular discretization converging to analytical smooth integral.</i>", caption_style))
    story.append(Spacer(1, 14))

    # SECTION 3: GEOMETRIC PROOFS & TRIGONOMETRY
    story.append(Paragraph("3. Euclidean Geometry, The Unit Circle & Pythagorean Invariance", heading1_style))
    story.append(Paragraph(
        "By projecting planar rotations onto the Cartesian unit circle, trigonometry establishes a direct bridge between angle measures and coordinate geometry. "
        "For any angle θ, the coordinates of the terminating radius vector are exactly (cos θ, sin θ). "
        "By applying the Euclidean distance norm from the origin, we derive the fundamental Pythagorean trigonometric identity:",
        body_style
    ))
    
    # Figure 3 Flowable
    story.append(RLImage(p3, width=5.2*inch, height=2.8*inch))
    story.append(Paragraph("<b>Figure 3:</b> <i>Geometric coordinate unit circle establishing the Pythagorean invariance sin²θ + cos²θ = 1.</i>", caption_style))
    story.append(Spacer(1, 8))

    # PAGE BREAK
    story.append(PageBreak())

    # SECTION 4: GAUSSIAN PROBABILITY DENSITY
    story.append(Paragraph("4. The Gaussian Normal Distribution & Central Limit Theorem", heading1_style))
    story.append(Paragraph(
        "The Central Limit Theorem (CLT) is one of the crowning triumphs of modern probability theory: "
        "the sum of <i>n</i> independent, identically distributed random variables with finite variance approaches a Gaussian normal distribution as <i>n → ∞</i>. "
        "The standard normal probability density function is parameterized by:",
        body_style
    ))
    
    # Gauss Formula Box
    gauss_box = Table([[Paragraph("<b>p(x) = (1 / (σ √(2π))) · exp(- (x - μ)² / (2σ²))</b>", formula_callout)]], colWidths=[504])
    gauss_box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EEF2FF')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#4F46E5')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(gauss_box)
    story.append(Spacer(1, 10))
    
    # Figure 4 Flowable
    story.append(RLImage(p4, width=5.2*inch, height=2.8*inch))
    story.append(Paragraph("<b>Figure 4:</b> <i>Standard Normal Distribution with empirical 68-95-99.7% confidence regions.</i>", caption_style))
    story.append(Spacer(1, 10))

    # Analytical Comparison Table
    table_data = [
        ["Mathematical Domain", "Core Theorem / Principle", "Key Equation", "Visual Proof"],
        ["Differential Calculus", "Fermat Stationary Theorem", "f'(x*) = 0, f''(x*) ≠ 0", "Fig. 1 (Extrema Curve)"],
        ["Integral Calculus", "Fundamental Theorem (FTC)", "∫ f(x)dx = F(b) - F(a)", "Fig. 2 (Riemann Sums)"],
        ["Planar Geometry", "Pythagorean Identity", "sin²θ + cos²θ = 1", "Fig. 3 (Unit Circle)"],
        ["Probability Theory", "Central Limit Theorem (CLT)", "N(μ, σ²) Asymptotics", "Fig. 4 (Gaussian Bell)"],
    ]
    t = Table(table_data, colWidths=[120, 140, 130, 114])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8.5),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))

    # Signoff Box
    signoff = Paragraph("<b>Verified & Synthesized by Pratham AI:</b> Created by Pratham Sinha under the guidance of Akriti and Aditi Aishwaryam. Publication-grade output rendered at 300 DPI with vector-aligned flowables.", body_style)
    story.append(signoff)

    print("Building ReportLab document...")
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Document built successfully: {pdf_path}")


# -------------------------------------------------------------
# 4. ZIP ARCHIVER
# -------------------------------------------------------------

def package_deliverable_zip(pdf_path, zip_path):
    print("Packaging into ZIP archive...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. Add compiled PDF
        zf.write(pdf_path, arcname=os.path.basename(pdf_path))
        
        # 2. Add high-res figure assets
        for fn in sorted(os.listdir(ASSETS_DIR)):
            if fn.endswith('.png'):
                fp = os.path.join(ASSETS_DIR, fn)
                zf.write(fp, arcname=os.path.join("figures_300dpi", fn))
                
    print(f"ZIP package created: {zip_path} ({os.path.getsize(zip_path)} bytes)")


if __name__ == "__main__":
    pdf_out = "/workspace/bold-curie/advanced_mathematics_compendium.pdf"
    zip_out = "/workspace/bold-curie/advanced_mathematics_compendium.zip"
    build_pdf_document(pdf_out)
    package_deliverable_zip(pdf_out, zip_out)
    print("ALL DELIVERABLES READY.")
