"""Generate the CSRD "Methodology & Audit Trail" reference as a PDF."""
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle)

OUT = Path(__file__).parent.parent / "docs" / "report" / "CSRD_Methodology_Audit_Trail.pdf"
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

hb = Table([[Paragraph("CSRD Compliance — Methodology &amp; Audit Trail", H1)]], colWidths=[17*cm])
hb.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), NAVY), ("TOPPADDING", (0,0), (-1,-1), 10),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 10), ("LEFTPADDING", (0,0), (-1,-1), 12)]))
story += [hb, Spacer(1, 4)]
story.append(Paragraph(
    "Companion reference &middot; reporting boundary, emission factors, data quality &middot; "
    "IS6611 &middot; Group 11", CAP))


def tbl(data, widths, font=8.8):
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


# ── Reporting boundary ──────────────────────────────────────────────────────
story.append(Paragraph("Reporting Boundary", H2))
story.append(Paragraph(
    "<b>Scope:</b> Scope 2 (purchased electricity), location-based method only — no "
    "market-based instruments (PPAs/RECs) are in scope. <b>Facility:</b> single facility "
    "(ORNL Summit) — no multi-site consolidation. <b>Excluded:</b> Scope 1 (none applicable — "
    "no on-site combustion at a data centre) and Scope 3 (not modelled — no supply-chain or "
    "embodied-hardware data available). <b>Period:</b> the annual saving figure is a "
    "<b>projection</b> from a 5-day observed operational sample matched against 4 years of "
    "grid data, not a full-year direct measurement.", BODY))

# ── Savings hierarchy reference ─────────────────────────────────────────────
story.append(Paragraph("Savings Hierarchy — Reference Figures", H2))
tbl([
    ["Tier", "Value (tCO2/yr)", "Basis"],
    ["Unconstrained potential", "314  (sensitivity 209–418)", "20–40% flexible-workload range around the 30% central assumption"],
    ["Capacity-aware ceiling", "87", "Adds cluster node-capacity constraints (4,626 nodes)"],
    ["Realistic, forecast-driven", "34", "Adds real 48h forecast error vs. perfect hindsight"],
], [4.6*cm, 4.6*cm, 7.8*cm])
story.append(Paragraph(
    "Table 1 — The sensitivity range (209–418) applies to the unconstrained tier only; the "
    "capacity-aware and realistic tiers use the central 30% assumption throughout, as re-running "
    "the full capacity-aware/forecast-driven pipeline at each sensitivity level was out of scope.",
    CAP))

# ── Emission factors ─────────────────────────────────────────────────────────
story.append(Paragraph("Emission Factors Used", H2))
tbl([
    ["Fuel", "Emission Factor (gCO2/kWh)", "Category"],
    ["Coal", "1000", "Fossil"],
    ["Petroleum", "800", "Fossil"],
    ["Natural Gas", "450", "Fossil"],
    ["Other", "500", "Mixed"],
    ["Nuclear", "0", "Zero-carbon"],
    ["Hydro", "0", "Zero-carbon"],
    ["Wind", "0", "Zero-carbon"],
    ["Solar", "0", "Zero-carbon"],
], [5*cm, 6*cm, 6*cm])
story.append(Paragraph(
    "Table 2 — IPCC AR5-style operational (generation-point) emission factors, applied to "
    "TVA's hourly generation-by-fuel mix to compute grid carbon intensity.", CAP))

# ── Data quality ──────────────────────────────────────────────────────────────
story.append(Paragraph("Data Quality &amp; Provenance", H2))
story.append(Paragraph(
    "<b>ORNL Summit telemetry:</b> ~99.98% complete, direct hardware measurement (NVIDIA DCGM "
    "for GPU power, Baseboard Management Controller for PSU draw) — not estimated. "
    "<b>TVA/EIA generation data:</b> ~99.6% complete, mandatory FERC Order 830 regulatory "
    "reporting — a legal obligation, not a voluntary estimate. Both sources were cross-validated "
    "against their own published documentation before use.", BODY))

# ── Methodology summary ────────────────────────────────────────────────────
story.append(Paragraph("Methodology Summary", H2))
story.append(Paragraph(
    "Carbon intensity is computed as the generation-weighted average of the emission factors "
    "above, applied hourly to TVA's actual fuel mix. Facility emissions are computed by pairing "
    "ORNL Summit's per-node power draw (active/idle classified at a 250 W threshold) with the "
    "matching hour's grid carbon intensity. Savings are produced by a capacity-aware "
    "load-shifting optimiser (validated against a linear-programming benchmark) under a 30% "
    "flexible-workload central assumption, with 20–40% shown as a sensitivity range on the "
    "unconstrained tier above.", BODY))

story.append(Spacer(1, 10))
story.append(Paragraph(
    "Carbon-Aware Scheduling for Data Centres &middot; Group 11 &middot; Companion to the CSRD "
    "Compliance dashboard view", CAP))

SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                  topMargin=1.6*cm, bottomMargin=1.6*cm).build(story)
print("PDF written →", OUT, f"({OUT.stat().st_size//1024} KB)")
