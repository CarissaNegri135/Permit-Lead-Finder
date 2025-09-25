import streamlit as st
import pandas as pd
import numpy as np
import io
from datetime import datetime

st.set_page_config(page_title="Permit Lead Finder — Auto Filter", layout="wide")

# ========= DEFAULTS YOU CAN CHANGE =========
DEFAULT_MAX_MONTHS = 4
DEFAULT_COUNTIES   = ["Nevada", "Placer", "Yuba", "Sacramento"]
DEFAULT_STATUSES   = ["Issued", "In Progress"]
EXCLUDE_ROOFING    = True
# ==========================================

st.title("🏗️ Permit Lead Finder — Auto Filter")
st.caption("Upload your public permit file, map columns once, and the app auto-filters to outreach-ready leads.")

with st.expander("How this is set up", expanded=False):
    st.markdown(
        f"""
        **Auto filters:**
        - Months remaining ≤ **{DEFAULT_MAX_MONTHS}**
        - County ∈ **{', '.join(DEFAULT_COUNTIES)}**
        - Status ∈ **{', '.join(DEFAULT_STATUSES)}**
        - Exclude roofing permits (type/description)

        You can override all of these from the sidebar.
        """
    )

uploaded = st.file_uploader("Upload a CSV or Excel file", type=["csv", "xlsx"])

# Sidebar controls (optional overrides)
st.sidebar.header("Filters (override defaults)")
max_months = st.sidebar.number_input("Max months remaining", value=DEFAULT_MAX_MONTHS, min_value=0, max_value=60, step=1)
target_counties = st.sidebar.text_input("Target counties (comma-separated)", value=", ".join(DEFAULT_COUNTIES))
target_counties = [c.strip() for c in target_counties.split(",") if c.strip()]
target_statuses = st.sidebar.text_input("Statuses to include (comma-separated)", value=", ".join(DEFAULT_STATUSES))
target_statuses = [s.strip() for s in target_statuses.split(",") if s.strip()]
exclude_roofing = st.sidebar.checkbox("Exclude roofing permits", value=EXCLUDE_ROOFING)

def coerce_date(series):
    return pd.to_datetime(series, errors="coerce", infer_datetime_format=True)

def months_remaining(expire_dates: pd.Series) -> pd.Series:
    today = pd.Timestamp.today().normalize()
    m = (expire_dates.dt.year - today.year) * 12 + (expire_dates.dt.month - today.month)
    day_adjust = (expire_dates.dt.day < today.day).astype(int)
    return m - day_adjust

# Early exit until a file is uploaded
if uploaded is None:
    st.info("Upload a CSV or Excel file to get started. (You can use the sidebar to set your defaults now.)")
    st.stop()

# ---------- Read file ----------
if uploaded.name.lower().endswith(".csv"):
    df = pd.read_csv(uploaded)
else:
    df = pd.read_excel(uploaded)

st.subheader("1) Map your columns")

cols = list(df.columns)

def guess_index(keyword, fallback=0):
    for i, c in enumerate(cols):
        if keyword in c.lower():
            return i
    return fallback

col_issue  = st.selectbox("Issue Date column", options=cols, index=guess_index("issue"))
col_exp    = st.selectbox("Expiration Date column", options=cols, index=guess_index("exp"))
col_desc   = st.selectbox("Project Description column (for roofing detection)", options=["(none)"] + cols, index=guess_index("desc")+1)
col_county = st.selectbox("County column (optional)", options=["(none)"] + cols, index=guess_index("county")+1)
col_city   = st.selectbox("City column (optional)", options=["(none)"] + cols, index=guess_index("city")+1)
col_zip    = st.selectbox("ZIP column (optional)", options=["(none)"] + cols, index=guess_index("zip")+1)
col_status = st.selectbox("Status column (optional)", options=["(none)"] + cols, index=guess_index("status")+1)
col_type   = st.selectbox("Permit Type column (optional)", options=["(none)"] + cols, index=guess_index("type")+1)

# ---------- Helpers ----------
work = df.copy()
work["_issue_dt"] = coerce_date(work[col_issue])
work["_exp_dt"]   = coerce_date(work[col_exp])
work["_months_remaining"] = months_remaining(work["_exp_dt"])

if col_desc != "(none)":
    work["_roofing_related"] = work[col_desc].astype(str).str.contains("roof", case=False, na=False)
else:
    work["_roofing_related"] = False

# ---------- Auto apply filters ----------
mask = pd.Series(True, index=work.index)
mask &= (work["_months_remaining"] <= max_months)

if col_status != "(none)" and len(target_statuses) > 0:
    mask &= work[col_status].astype(str).isin(target_statuses)

if col_county != "(none)" and len(target_counties) > 0:
    mask &= work[col_county].astype(str).isin(target_counties)
elif col_city != "(none)" and len(target_counties) > 0:
    mask &= work[col_city].astype(str).isin(target_counties)
elif col_zip != "(none)" and len(target_counties) > 0:
    mask &= work[col_zip].astype(str).isin(target_counties)

if exclude_roofing:
    type_is_roof = False
    if col_type != "(none)":
        type_is_roof = work[col_type].astype(str).str.contains("roof", case=False, na=False)
    mask &= ~(work["_roofing_related"] | type_is_roof)

leads = work.loc[mask].copy()

st.subheader("2) Results (auto-filtered)")
st.caption(f"Showing {len(leads):,} of {len(work):,} rows after filters.")

# Choose columns to display first
display_cols = []
for key in ["Permit #","Owner Name","County","City","ZIP","Status","Permit Type","Project Description","Issue Date","Expiration Date"]:
    if key in leads.columns:
        display_cols.append(key)
display_cols += [c for c in leads.columns if c not in display_cols and not c.startswith("_")]

show_helpers = st.toggle("Show helper columns (months remaining / roofing detected)", value=False)
if show_helpers:
    display_cols += ["_months_remaining","_roofing_related"]

if len(leads) == 0:
    st.warning("No rows matched your filters. Try widening months, statuses, or county list.")
else:
    st.dataframe(leads[display_cols], use_container_width=True, hide_index=True)

# ---------- Downloads ----------
st.subheader("3) Download")

# CSV
csv_data = leads[display_cols].to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download CSV", data=csv_data, file_name="permit_leads.csv", mime="text/csv")

# Excel
try:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        leads[display_cols].to_excel(writer, index=False, sheet_name="Leads")
        ws = writer.sheets["Leads"]
        ws.autofilter(0, 0, leads[display_cols].shape[0], leads[display_cols].shape[1]-1)
        ws.freeze_panes(1, 0)
    st.download_button("⬇️ Download Excel", data=buffer.getvalue(),
                       file_name="permit_leads.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
except Exception as e:
    st.info("Excel export needs xlsxwriter. If this fails, use CSV or add xlsxwriter to requirements.")

# PDF
try:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(letter), leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)
    styles = getSampleStyleSheet()

    elems = [Paragraph("Permit Leads (filtered)", styles["Title"]), Spacer(1, 6)]
    table_data = [leads[display_cols].columns.tolist()] + leads[display_cols].astype(str).values.tolist()
    tbl = Table(table_data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
    ]))
    elems.append(tbl)
    doc.build(elems)

    st.download_button("⬇️ Download PDF",
                       data=pdf_buffer.getvalue(),
                       file_name="permit_leads.pdf",
                       mime="application/pdf")
except Exception:
    st.info("PDF export needs 'reportlab' in requirements.txt. Add it if the button doesn't appear.")



