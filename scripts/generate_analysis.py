"""Generate the Analysis (Phase 3) section as a PDF with embedded charts (<300 words prose)."""
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                Image, KeepTogether)

ROOT = Path(__file__).parent.parent
CH = ROOT / "data" / "processed"
OUT = ROOT / "docs" / "report" / "Data_Analysis.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

NAVY = colors.HexColor("#0B2545"); BLUE = colors.HexColor("#1565C0")
GREY = colors.HexColor("#5B6B7C"); LIGHT = colors.HexColor("#F4F6FB")
PUR = colors.HexColor("#6A1B9A"); GRN = colors.HexColor("#2E7D32")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", fontSize=17, leading=21, textColor=colors.white, fontName="Helvetica-Bold")
H2 = ParagraphStyle("H2", fontSize=11.5, leading=15, textColor=BLUE, fontName="Helvetica-Bold",
                    spaceBefore=9, spaceAfter=3)
BODY = ParagraphStyle("BODY", parent=ss["BodyText"], fontSize=10, leading=14.5, alignment=TA_JUSTIFY,
                      textColor=colors.HexColor("#1A2733"), spaceAfter=6)
CAP = ParagraphStyle("CAP", fontSize=8.2, leading=10.5, textColor=GREY,
                     fontName="Helvetica-Oblique", spaceBefore=2, spaceAfter=11, alignment=1)
story = []

hb = Table([[Paragraph("Phase 3 — Analysis", H1)]], colWidths=[17*cm])
hb.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), NAVY), ("TOPPADDING", (0,0), (-1,-1), 10),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 10), ("LEFTPADDING", (0,0), (-1,-1), 12)]))
story += [hb, Spacer(1, 10)]


def tbl(data, widths, font=8.4):
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), font), ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#1A2733")), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6), ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D5DCE6")),
        ("BACKGROUND", (0,0), (-1,0), NAVY), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT])]))
    story.append(t)


def fig(name, caption, w=16.4*cm):
    p = CH / name
    iw, ih = ImageReader(str(p)).getSize()
    h = w * ih / iw
    if h > 7.6*cm:
        h = 7.6*cm; w = h * iw / ih
    story.append(KeepTogether([Image(str(p), width=w, height=h), Paragraph(caption, CAP)]))


# Intro
story.append(Paragraph(
    "The analysis follows the three standard analytics layers — descriptive, predictive and "
    "prescriptive — each answering a different question and building on the last.", BODY))
tbl([
    ["Layer", "Question", "In this project"],
    ["Descriptive", "What is happening?", "When is the facility busy, and when is the grid cleanest?"],
    ["Predictive", "What will happen?", "Grid carbon intensity over the next 48 hours"],
    ["Prescriptive", "What should we do?", "When each flexible job should run to cut carbon"],
], [3*cm, 4.3*cm, 9.7*cm])
story.append(Spacer(1, 4))

# Descriptive
story.append(Paragraph("Descriptive — understanding the patterns", H2))
story.append(Paragraph(
    "Using <b>pandas</b> with <b>matplotlib</b> and <b>seaborn</b>, we explored both datasets to "
    "learn when the facility draws the most power and when the grid is at its cleanest. The key "
    "discovery concerns the grid. Averaged across four years, every hour of the day looks almost "
    "equally clean — which would suggest that timing barely matters. But that average is misleading: "
    "on any individual day the gap between the cleanest and dirtiest hour is large (about "
    "51&nbsp;gCO₂/kWh), and the cleanest hour is rarely the same two days in a row, shifting "
    "unpredictably. A fixed rule such as &lsquo;always run overnight&rsquo; would therefore miss the "
    "clean window most of the time — the only way to find it is to <b>forecast</b> it.", BODY))
fig("eda_supply_ci_heatmap_hour_month.png",
    "Grid carbon intensity by hour (columns) and month (rows) — green is clean, red is dirty. "
    "No single hour-of-day stays green all year.")
fig("eda_supply_moving_clean_window.png",
    "Left: how often each hour of the day was the cleanest — no hour dominates. "
    "Right: the cleanest hour plotted over time, scattered with no fixed pattern.")

# Predictive
story.append(Paragraph("Predictive — forecasting carbon intensity", H2))
story.append(Paragraph(
    "To know <i>when</i> the grid will be clean, we forecast its carbon intensity 48 hours ahead, "
    "benchmarking four models against a naive baseline on a held-out four-month test set using MAE, "
    "RMSE and MAPE. <b>XGBoost</b> (with statsmodels, Prophet and scikit-learn as comparators) was "
    "selected as the only model to beat the baseline on all three metrics.", BODY))
fig("fc_metric_comparison.png",
    "Model comparison on held-out data — XGBoost is best on all three error metrics, so it was chosen.")

# Prescriptive
story.append(Paragraph("Prescriptive — optimising the schedule", H2))
story.append(Paragraph(
    "The forecast is turned into scheduling decisions using a greedy heuristic (which powers the "
    "live dashboard) and a Linear Programme (the optimal benchmark), both built with <b>PuLP</b> and "
    "the open-source <b>CBC</b> solver under node-capacity and deadline limits. This layer also keeps "
    "the savings honest: once real cluster capacity and day-ahead forecast error are taken into "
    "account, the achievable saving falls well below the theoretical maximum.", BODY))
fig("opt_savings_hierarchy.png",
    "Savings hierarchy — each real constraint lowers the achievable annual saving (293 → 106 → 51 tCO₂/yr).")

# Options table
story.append(Paragraph("Options considered and chosen approach", H2))
tbl([
    ["Layer", "Options considered", "Chosen approach & why"],
    ["Descriptive", "BI dashboards vs code-based EDA",
     "Code-based EDA (pandas, seaborn) — reproducible and shares the Python pipeline"],
    ["Predictive", "Naive, SARIMA, Prophet, XGBoost, LSTM",
     "XGBoost — best accuracy on held-out data; others retained as honest benchmarks"],
    ["Prescriptive", "Greedy, Linear Programming, stochastic optimisation",
     "Greedy + LP (PuLP/CBC) — fast for live use plus an optimal benchmark; stochastic dropped as disproportionate"],
], [2.5*cm, 5*cm, 9.5*cm])

SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=1.8*cm, rightMargin=1.8*cm,
                  topMargin=1.5*cm, bottomMargin=1.4*cm).build(story)
print("PDF written →", OUT, f"({OUT.stat().st_size//1024} KB)")
