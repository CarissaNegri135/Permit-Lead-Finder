import streamlit as st
import pandas as pd
import numpy as np
import io
from datetime import date
# --- page ---
st.set_page_config(page_title="Permit Lead Finder", layout="wide")

# ===== Defaults you can tweak =====
DEFAULT_MAX_MONTHS = 4
DEFAULT_STATUSES   = ["Issued", "In Progress"]
ROOF_KEYWORDS      = ["roof", "re-roof", "reroof", "re roof", "roof repl", "roof mount"]
# ==================================

st.title("🏗️ Permit Lead Finder — PDF/CSV/XLSX")
st.caption("Upload a county report (PDF/CSV/XLSX), tag the county, map columns, and get outreach leads + roofing summaries.")

# ------------------ Upload ------------------
uploaded = st.file_uploader("Upload a CSV, Excel, or PDF file", type=["csv", "xlsx", "pdf"])
county = st.selectbox("Select County for this file", ["Placer", "El Dorado", "Nevada", "Yuba", "Other"])

if uploaded is None:
    st.info("Upload a file to begin.")
    st.stop()

# ------------------ Read file ------------------
def read_any(uploaded):
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded)
    if name.endswith(".xlsx"):
        return pd.read_excel(uploaded)
    if name.endswith(".pdf"):
        import pdfplumber
        frames = []
        with pdfplumber.open(uploaded) as pdf:
            for p in pdf.pages:
                for t in (p.extract_tables() or []):
                    if not t or len(t) < 2:
                        continue
                    header = [("" if h is None else str(h).strip()) for h in t[0]]
                    rows   = [[("" if c is None else str(c).strip()) for c in r] for r in t[1:]]
                    if not any(header):
                        continue
                    frames.append(pd.DataFrame(rows, columns=header))
        if not frames:
            st.error("No tables found in the PDF. If it’s a scanned image, export CSV/XLSX from the county site.")
            st.stop()
        df = pd.concat(frames, ignore_index=True)
        df.columns = [c.strip() for c in df.columns]
        return df
    st.error("Unsupported file type.")
    st.stop()

df = read_any(uploaded)
df["County"] = county  # tag the whole file with the selected county

# ------------------ Column mapping ------------------
st.subheader("1) Map columns")
cols = df.columns.tolist()

def guess(cols, needle):
    idx = 0
    for i, c in enumerate(cols):
        if needle in c.lower():
            return i
    return idx

col_issue   = st.selectbox("Issue/Date Pulled", options=cols, index=guess(cols,"issue"))
col_exp     = st.selectbox("Expiration Date", options=cols, index=guess(cols,"exp"))
col_desc    = st.selectbox("Description", options=["(none)"]+cols, index=guess(cols,"desc")+1)
col_type    = st.selectbox("Permit Type", options=["(none)"]+cols, index=guess(cols,"type")+1)
col_status  = st.selectbox("Status", options=["(none)"]+cols, index=guess(cols,"status")+1)
col_contr   = st.selectbox("Contractor / Applicant", options=["(none)"]+cols, index=guess(cols,"contract")+1)
col_addr    = st.selectbox("Site Address", options=["(none)"]+cols, index=guess(cols,"address")+1)
col_city    = st.selectbox("City (optional)", options=["(none)"]+cols, index=guess(cols,"city")+1)
col_zip     = st.selectbox("ZIP (optional)", options=["(none)"]+cols, index=guess(cols,"zip")+1)

# ------------------ Helpers ------------------
to_dt = lambda s: pd.to_datetime(s, errors="coerce", infer_datetime_format=True)
work = df.copy()
work["_issue_dt"] = to_dt(work[col_issue])
work["_exp_dt"]   = to_dt(work[col_exp])

def months_remaining(exp):
    today = pd.Timestamp.today().normalize()
    m = (exp.dt.year - today.year)*12 + (exp.dt.month - today.month)
    adj = (exp.dt.day < today.day).astype(int)
    return m - adj

work["_months_remaining"] = months_remaining(work["_exp_dt"])

def has_roof(x: str) -> bool:
    s = str(x).lower()
    return any(k in s for k in ROOF_KEYWORDS)

work["_is_roofing"] = False
if col_desc != "(none)":
    work["_is_roofing"] |= work[col_desc].apply(has_roof)
if col_type != "(none)":
    work["_is_roofing"] |= work[col_type].apply(has_roof)

# ------------------ Filters ------------------
st.subheader("2) Filters")
max_months = st.number_input("Max months remaining (leads view)", value=DEFAULT_MAX_MONTHS, min_value=0, max_value=60)

# status filter (optional)
status_vals = sorted(work[col_status].dropna().astype(str).unique()) if col_status!="(none)" else []
pick_status = st.multiselect("Statuses to include (optional)", status_vals,
                             default=[s for s in DEFAULT_STATUSES if s in status_vals] if status_vals else [])

exclude_roof = st.checkbox("Exclude roofing permits from leads", value=True)

mask = pd.Series(True, index=work.index)
mask &= (work["_months_remaining"] <= max_months)
if pick_status:
    mask &= work[col_status].astype(str).isin(pick_status)
if exclude_roof:
    mask &= ~work["_is_roofing"]

leads = work.loc[mask].copy()

# Nice columns to show
lead_cols = []
for c in ["County", col_issue, col_exp, col_contr, col_addr, col_city, col_zip, col_status, col_type, col_desc]:
    if c != "(none)" and c in leads.columns and c not in lead_cols:
        lead_cols.append(c)
lead_cols += [c for c in leads.columns if c not in lead_cols and not c.startswith("_")]

st.subheader("3) Leads (auto-filtered)")
st.caption(f"{len(leads):,} of {len(work):,} rows after filters.")
st.dataframe(leads[lead_cols], use_container_width=True, hide_index=True)

# ------------------ Roofing summary (what he asked) ------------------
st.subheader("4) Roofing activity summary")
gran = st.radio("Group by", ["Month","Week"], horizontal=True)

# choose date range based on issue date
min_d = pd.to_datetime(work["_issue_dt"].min()).date() if work["_issue_dt"].notna().any() else date.today()
max_d = pd.to_datetime(work["_issue_dt"].max()).date() if work["_issue_dt"].notna().any() else date.today()
start, end = st.date_input("Date pulled range", value=(max(min_d, max_d.replace(day=1)), max_d))

in_range = work[(work["_issue_dt"] >= pd.Timestamp(start)) & (work["_issue_dt"] <= pd.Timestamp(end))]
roof = in_range[in_range["_is_roofing"]].copy()

c1, c2, c3 = st.columns(3)
c1.metric("Permits in range", f"{len(in_range):,}")
c2.metric("Roofing permits", f"{len(roof):,}")
c3.metric("Roofing contractors",
          f"{roof[col_contr].nunique():,}" if col_contr!="(none)" and col_contr in roof.columns else "—")

# group by period
if gran == "Month":
    roof["_period"] = roof["_issue_dt"].dt.to_period("M").dt.to_timestamp()
else:
    roof["_period"] = roof["_issue_dt"].dt.to_period("W").dt.start_time

by_period = roof.groupby("_period").size().reset_index(name="Re-roof count")
st.write(f"**Re-roof permits by {gran.lower()}**")
st.bar_chart(by_period.set_index("_period"))

# top roofing contractors + addresses table
if col_contr != "(none)" and col_contr in roof.columns:
    top_con = roof.groupby(col_contr, dropna=False).size().sort_values(ascending=False).reset_index(name="Count")
    st.write("**Top roofing contractors in range**")
    st.dataframe(top_con.head(20), hide_index=True, use_container_width=True)

detail_cols = [c for c in [col_contr, col_addr, col_city, col_zip, col_issue, col_type, col_desc] if c!="(none)" and c in roof.columns]
st.write("**Reroof details (who pulled it & site address)**")
st.dataframe(roof[detail_cols] if detail_cols else roof, hide_index=True, use_container_width=True)

# ------------------ Downloads ------------------
st.subheader("5) Download")

# Leads CSV
csv_leads = leads[lead_cols].to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download Leads (CSV)", data=csv_leads, file_name="permit_leads.csv", mime="text/csv")

# Excel (Leads + Summary sheets)
try:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as w:
        leads[lead_cols].to_excel(w, index=False, sheet_name="Leads")
        by_period.to_excel(w, index=False, sheet_name=f"Roof_By_{gran}")
        if col_contr!="(none)" and col_contr in roof.columns:
            top_con.to_excel(w, index=False, sheet_name="Top_Roof_Contractors")
        (roof[detail_cols] if detail_cols else roof).to_excel(w, index=False, sheet_name="Roof_Detail")
        for ws in w.sheets.values(): ws.freeze_panes(1,0)
    st.download_button("⬇️ Download Excel (Leads + Summary)",
        data=buffer.getvalue(),
        file_name="permit_leads_summary.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
except Exception:
    st.info("Excel export needs xlsxwriter (already in requirements).")

# PDF summary
try:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(letter),
                            leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)
    styles = getSampleStyleSheet()

    elems = [
        Paragraph("Permit Leads — Summary", styles["Title"]),
        Paragraph(f"County: {county} | Leads: {len(leads):,} | Range: {start} → {end}", styles["Normal"]),
        Spacer(1, 8),
    ]
    # compact leads snapshot (first 10 cols to fit)
    cols_pdf = lead_cols[:10]
    td = [leads[cols_pdf].columns.tolist()] + leads[cols_pdf].astype(str).values.tolist()
    tbl = Table(td, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EEEEEE")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.whitesmoke]),
    ]))
    elems += [Paragraph("Leads (snapshot)", styles["Heading2"]), tbl, Spacer(1,8)]

    # top contractors
    if col_contr!="(none)" and col_contr in roof.columns:
        td2 = [top_con.columns.tolist()] + top_con.astype(str).values.tolist()
        tbl2 = Table(td2, repeatRows=1)
        tbl2.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EEEEEE")),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),8),
            ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ]))
        elems += [Paragraph("Top Roofing Contractors", styles["Heading2"]), tbl2]

    doc.build(elems)
    st.download_button("⬇️ Download PDF (summary)", data=pdf_buffer.getvalue(),
                       file_name="permit_summary.pdf", mime="application/pdf")
except Exception:
    st.info("PDF export needs 'reportlab' in requirements.")
