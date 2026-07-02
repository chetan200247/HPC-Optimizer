"""Generate a concise Data Acquisition section as a PDF (report format)."""
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle)

OUT = Path(__file__).parent.parent / "docs" / "report" / "Data_Acquisition.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

NAVY = colors.HexColor("#0B2545"); BLUE = colors.HexColor("#1565C0")
GREY = colors.HexColor("#5B6B7C"); LIGHT = colors.HexColor("#F4F6FB")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", fontSize=17, leading=21, textColor=colors.white, fontName="Helvetica-Bold")
H2 = ParagraphStyle("H2", fontSize=11.5, leading=15, textColor=BLUE, fontName="Helvetica-Bold",
                    spaceBefore=10, spaceAfter=3)
BODY = ParagraphStyle("BODY", parent=ss["BodyText"], fontSize=10, leading=14.5, alignment=TA_JUSTIFY,
                      textColor=colors.HexColor("#1A2733"), spaceAfter=6)
CAP = ParagraphStyle("CAP", fontSize=8.3, leading=11, textColor=GREY,
                     fontName="Helvetica-Oblique", spaceBefore=2, spaceAfter=10)
story = []

hb = Table([[Paragraph("Phase 1 — Data Acquisition", H1)]], colWidths=[17*cm])
hb.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), NAVY), ("TOPPADDING", (0,0), (-1,-1), 10),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 10), ("LEFTPADDING", (0,0), (-1,-1), 12)]))
story += [hb, Spacer(1, 12)]


def tbl(data, widths, font=8.6):
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), font), ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#1A2733")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 7),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D5DCE6")),
        ("BACKGROUND", (0,0), (-1,0), NAVY), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT]),
    ]))
    story.append(t)


# How captured & sources
story.append(Paragraph("How the data is captured and its sources", H2))
story.append(Paragraph(
    "The project draws on two datasets (Table&nbsp;1). ORNL Summit power data — the <b>demand</b> "
    "side — is captured <b>passively</b> by on-node hardware sensors — NVIDIA DCGM for GPU power "
    "and the Baseboard Management Controller for power-supply draw — and published as Apache "
    "Parquet. TVA grid generation — the <b>supply</b> side — is pulled <b>actively</b> from the "
    "U.S. EIA API.", BODY))
tbl([
    ["Source", "Side", "What it provides", "How captured", "Format / access"],
    ["ORNL Summit", "Demand", "Per-node power · 4,626 nodes · 1-min", "Hardware sensors (DCGM + BMC)",
     "Apache Parquet"],
    ["TVA grid (via EIA)", "Supply", "Hourly generation by fuel type", "FERC Order 830 reporting",
     "EIA REST API (JSON)"],
], [2.7*cm, 1.5*cm, 4.4*cm, 4*cm, 3.4*cm])
story.append(Paragraph("Table 1 — The two data sources, stated explicitly.", CAP))

# Dataset brief / columns
story.append(Paragraph("The two datasets in brief", H2))
tbl([
    ["Dataset", "Granularity", "Key columns used"],
    ["ORNL Summit\n(Parquet — 12 of 71 cols)", "per node,\nper minute",
     "timestamp · hostname · node_state · 6× GPU power "
     "(p0_gpu0…p1_gpu2_power) · 2× PSU input (ps0/ps1_input_power)"],
    ["TVA via EIA\n(long format)", "per fuel,\nper hour",
     "period · fueltype (COL, NG, NUC, OIL, SUN, WAT, WND, OTH) · value (MWh) · value-units"],
], [3.7*cm, 2.6*cm, 10.7*cm])
story.append(Paragraph("Table 2 — The fields actually used from each dataset.", CAP))

# Reliability
story.append(Paragraph("Evaluating source reliability", H2))
story.append(Paragraph(
    "Both primary sources are highly authoritative — a U.S. national laboratory (peer-reviewed) "
    "and a federal agency reporting under legal mandate — and come from direct measurement rather "
    "than estimates, with completeness of 99.98% (ORNL) and 99.6% (EIA), cross-validated against "
    "the source paper and TVA's own reports.", BODY))

# Options & data-first
story.append(Paragraph("Options considered and chosen approach", H2))
story.append(Paragraph(
    "For demand, synthetic, NERSC and cloud data were rejected as unrepresentative, unavailable at "
    "resolution, or not public at node level; ORNL alone offered peer-reviewed per-node, per-minute "
    "power. For supply, paid APIs and other grids were rejected on cost, reproducibility and "
    "geography, so the free official EIA API was chosen (Table&nbsp;3). A <b>data-first discipline</b> "
    "is maintained: raw data is never modified, every load is validated, and anomalies are logged, "
    "not dropped.", BODY))
tbl([
    ["Data", "Options rejected", "Why rejected", "Chosen"],
    ["Demand", "Synthetic / NERSC / cloud",
     "Unrepresentative · unavailable at resolution · not public at node level", "ORNL Summit"],
    ["Supply", "Electricity Maps / WattTime / other grids",
     "Paid · not reproducible · wrong geography", "EIA API (TVA)"],
], [2.3*cm, 4.6*cm, 6.6*cm, 3.5*cm])
story.append(Paragraph("Table 3 — Alternatives weighed against the chosen sources.", CAP))

SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                  topMargin=1.6*cm, bottomMargin=1.6*cm).build(story)
print("PDF written →", OUT, f"({OUT.stat().st_size//1024} KB)")
