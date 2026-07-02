"""
Generate the comprehensive project report as a PDF.

Builds a structured academic-style document (title page, table of contents,
chapters, embedded charts, tables, page numbers) using reportlab — pure Python,
no system dependencies.

Usage:
    python scripts/generate_report.py
Output:
    docs/report/Carbon_Aware_Scheduling_Full_Report.pdf
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    Image, Table, TableStyle, NextPageTemplate, KeepTogether)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).parent.parent
CHARTS = ROOT / "data" / "processed"
OUT = ROOT / "docs" / "report" / "Carbon_Aware_Scheduling_Full_Report.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY = colors.HexColor("#0B1F3A")
BLUE = colors.HexColor("#1565C0")
GREEN = colors.HexColor("#2E7D32")
RED = colors.HexColor("#C62828")
GREY = colors.HexColor("#5B6B7C")
LIGHT = colors.HexColor("#F4F6FB")
AMBER = colors.HexColor("#E65100")

# ── Styles ────────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

def S(name, **kw):
    styles.add(ParagraphStyle(name, **kw))

S("TitleBig", parent=styles["Title"], fontSize=30, leading=36, textColor=NAVY,
  spaceAfter=10, alignment=TA_CENTER)
S("TitleSub", fontSize=15, leading=20, textColor=GREY, alignment=TA_CENTER,
  spaceAfter=6, fontName="Helvetica-Oblique")
S("Chapter", fontSize=22, leading=26, textColor=NAVY, spaceBefore=8,
  spaceAfter=14, fontName="Helvetica-Bold")
S("H2", fontSize=15, leading=19, textColor=BLUE, spaceBefore=14, spaceAfter=6,
  fontName="Helvetica-Bold")
S("H3", fontSize=12.5, leading=16, textColor=NAVY, spaceBefore=10, spaceAfter=4,
  fontName="Helvetica-Bold")
S("Body", parent=styles["BodyText"], fontSize=10.5, leading=15.5,
  alignment=TA_JUSTIFY, spaceAfter=8, textColor=colors.HexColor("#1A2733"))
S("BulletItem", parent=styles["Body"], leftIndent=16, bulletIndent=4, spaceAfter=4)
S("Caption", fontSize=9, leading=12, textColor=GREY, alignment=TA_CENTER,
  spaceBefore=4, spaceAfter=12, fontName="Helvetica-Oblique")
S("Quote", parent=styles["Body"], leftIndent=18, rightIndent=18,
  textColor=NAVY, fontName="Helvetica-Oblique", borderColor=BLUE,
  borderWidth=0, spaceBefore=6, spaceAfter=10)
S("TOCHeading", fontSize=20, leading=24, textColor=NAVY, fontName="Helvetica-Bold",
  spaceAfter=16)
S("CodeBlock", fontName="Courier", fontSize=8.5, leading=11,
  textColor=colors.HexColor("#222"), backColor=LIGHT, leftIndent=8,
  spaceBefore=4, spaceAfter=8)
S("Small", fontSize=9, leading=12, textColor=GREY)

# ── Content helpers ───────────────────────────────────────────────────────────
story = []
_chap_n = [0]

def chapter(title):
    _chap_n[0] += 1
    story.append(PageBreak())
    p = Paragraph(f"{_chap_n[0]}.&nbsp;&nbsp;{title}", styles["Chapter"])
    p._tocLevel = 0; p._tocText = f"{_chap_n[0]}. {title}"
    story.append(p)

def h2(title):
    story.append(Paragraph(title, styles["H2"]))

def h3(title):
    story.append(Paragraph(title, styles["H3"]))

def body(text):
    story.append(Paragraph(text, styles["Body"]))

def bullets(items):
    for it in items:
        story.append(Paragraph(it, styles["BulletItem"], bulletText="•"))
    story.append(Spacer(1, 4))

def quote(text):
    story.append(Paragraph(text, styles["Quote"]))

def code(text):
    story.append(Paragraph(text.replace(" ", "&nbsp;").replace("\n", "<br/>"), styles["CodeBlock"]))

def gap(h=6):
    story.append(Spacer(1, h))

def figure(name, caption, max_w=16.8*cm):
    path = CHARTS / name
    if not path.exists():
        body(f"[figure missing: {name}]"); return
    iw, ih = ImageReader(str(path)).getSize()
    w = max_w; h = w * ih / iw
    max_h = 20.5*cm
    if h > max_h:
        h = max_h; w = h * iw / ih
    story.append(Spacer(1, 4))
    story.append(KeepTogether([
        Image(str(path), width=w, height=h),
        Paragraph(caption, styles["Caption"])]))
    story.append(Spacer(1, 6))

def table(data, col_widths=None, header=True, font=8.8):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    ts = [
        ("FONTSIZE", (0,0), (-1,-1), font),
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#1A2733")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D5DCE6")),
    ]
    if header:
        ts += [
            ("BACKGROUND", (0,0), (-1,0), NAVY),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT]),
        ]
    t.setStyle(TableStyle(ts))
    story.append(t); gap(10)

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE FURNITURE (footer with page numbers; TOC tracking)
# ══════════════════════════════════════════════════════════════════════════════

def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D5DCE6"))
    canvas.line(2*cm, 1.5*cm, A4[0]-2*cm, 1.5*cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(2*cm, 1.0*cm, "Carbon-Aware Scheduling for Data Centres · IS6611 · Group 11")
    canvas.drawRightString(A4[0]-2*cm, 1.0*cm, f"Page {doc.page}")
    canvas.restoreState()

def title_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1]-4.5*cm, A4[0], 4.5*cm, fill=1, stroke=0)
    canvas.setFillColor(GREEN)
    canvas.rect(0, A4[1]-4.7*cm, A4[0], 0.2*cm, fill=1, stroke=0)
    canvas.restoreState()


class DocTemplate(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if hasattr(flowable, "_tocLevel"):
            self.notify("TOCEntry", (flowable._tocLevel, flowable._tocText, self.page))


def build():
    doc = DocTemplate(str(OUT), pagesize=A4,
                      leftMargin=2*cm, rightMargin=2*cm,
                      topMargin=2*cm, bottomMargin=2*cm,
                      title="Carbon-Aware Scheduling — Full Project Report",
                      author="Group 11")
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="main")
    doc.addPageTemplates([
        PageTemplate(id="title", frames=[frame], onPage=title_page),
        PageTemplate(id="body", frames=[frame], onPage=footer),
    ])
    doc.multiBuild(story)


# ══════════════════════════════════════════════════════════════════════════════
#  DOCUMENT CONTENT
# ══════════════════════════════════════════════════════════════════════════════

# ---- TITLE PAGE ----
story.append(Spacer(1, 3.2*cm))
story.append(Paragraph("Carbon-Aware Scheduling", styles["TitleBig"]))
story.append(Paragraph("for Data Centres", styles["TitleBig"]))
gap(10)
story.append(Paragraph("Reducing Scope 2 Carbon Emissions through Forecast-Driven "
                       "Temporal Workload Shifting", styles["TitleSub"]))
gap(40)
story.append(Paragraph("A Complete Project Report", styles["TitleSub"]))
gap(60)
meta = [
    ["Module", "IS6611 — Applied Research in Business Analytics"],
    ["Institution", "Cork University Business School, University College Cork"],
    ["Group", "11"],
    ["Data Sources", "ORNL Summit Supercomputer · Tennessee Valley Authority (EIA)"],
    ["Deliverable", "End-to-end analytics pipeline + live dashboard"],
]
t = Table(meta, colWidths=[4*cm, 11*cm])
t.setStyle(TableStyle([
    ("FONTSIZE", (0,0), (-1,-1), 10),
    ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
    ("TEXTCOLOR", (0,0), (0,-1), NAVY),
    ("TEXTCOLOR", (1,0), (1,-1), GREY),
    ("TOPPADDING", (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("LINEBELOW", (0,0), (-1,-2), 0.4, colors.HexColor("#E0E5F0")),
]))
story.append(t)
gap(50)
story.append(Paragraph("Group Members: Aditya Anil More · Chetan Dummegere Kumar · "
                       "Jobi Joy Mathew · Kartik Anil Shah · Sarvesh Deepak Pisal · "
                       "Srushti Rajendrakumar Shetti", styles["Small"]))

# ---- TABLE OF CONTENTS ----
story.append(NextPageTemplate("body"))
story.append(PageBreak())
story.append(Paragraph("Table of Contents", styles["TOCHeading"]))
toc = TableOfContents()
toc.levelStyles = [ParagraphStyle("TOC0", fontSize=11, leading=20, fontName="Helvetica",
                                  textColor=colors.HexColor("#1A2733"))]
story.append(toc)

# ══════════════════════════════════════════════════════════════════════════════
exec(open(ROOT / "scripts" / "_report_content.py").read())
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    build()
    size_kb = OUT.stat().st_size // 1024
    print(f"PDF written → {OUT}  ({size_kb} KB)")
