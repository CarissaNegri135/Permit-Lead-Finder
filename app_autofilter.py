
import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Permit Lead Finder — Auto Filter", layout="wide")

# ======= CONFIG (edit these to your real targets) =======
DEFAULT_MAX_MONTHS = 4
DEFAULT_COUNTIES   = ["Nevada", "Placer", "Yuba", "Sacramento"]   # <-- change to your 4 counties
DEFAULT_STATUSES   = ["Issued", "In Progress"]
EXCLUDE_ROOFING    = True   # exclude permits that already look roofing-related
# ========================================================

st.title("🏗️ Permit Lead Finder — Auto Filter")
st.caption("Uploads your public permit file and automatically filters to your outreach-ready leads.")

with st.expander("How this is set up", expanded=False):
    st.markdown(
        """
        This app auto-filters by:
        - **Months remaining ≤ {mn}**
        - **County ∈ {ctys}**
        - **Status ∈ {sts}**
        - **Exclude roofing-related permits** (by description/permit type)

        You can tweak these defaults in the sidebar or by editing the config block at the top of the file.
        """.format(mn=DEFAULT_MAX_MONTHS, ctys=', '.join(DEFAULT_COUNTIES), sts=', '.join(DEFAULT_STATUSES))
    )

uploaded = st.file_uploader("Upload a CSV or Excel file", type=["csv","xlsx"])

# Sidebar controls (optional override without touching code)
st.sidebar.header("Filters (override defaults)")
max_months = st.sidebar.number_input("Max months remaining", value=DEFAULT_MAX_MONTHS, min_value=-12, max_value=60, step=1)
target_counties = st.sidebar.text_input("Target counties (comma-separated)", value=", ".join(DEFAULT_COUNTIES))
target_counties = [c.strip() for c in target_counties.split(",") if c.strip()]
target_statuses = st.sidebar.text_input("Statuses to include (comma-separated)", value=", ".join(DEFAULT_STATUSES))
target_statuses = [s.strip() for s in target_statuses.split(",") if s.strip()]
exclude_roofing = st.sidebar.checkbox("Exclude roofing permits", value=EXCLUDE_ROOFING)

def coerce_date(series):
    return pd.to_datetime(series, errors="coerce", infer_datetime_format=True)

def months_remaining(expire_dates):
    today = pd.Timestamp.today().normalize()
    m = (expire_dates.dt.year - today.year) * 12 + (expire_dates.dt.month - today.month)
    day_adjust = (expire_dates.dt.day < today.day).astype(int)
    return (m - day_adjust)

if uploaded is not None:
    # Read file
    if uploaded.name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded)
    else:
        df = pd.read_excel(uploaded)

    st.subheader("1) Map your columns")
    cols = list(df.columns)

    # Try smart defaults for dropdowns
    def guess_index(keyword, fallback=0):
        for i,c in enumerate(cols):
            if keyword in c.lower():
                return i
        return fallback

    col_issue = st.selectbox("Issue Date column", options=cols, index=guess_index("issue"))
    col_exp   = st.selectbox("Expiration Date column", options=cols, index=guess_index("exp"))
    col_desc  = st.selectbox("Project Description column (for roofing detection)", options=["(none)"] + cols, index=guess_index("desc")+1)
    col_county= st.selectbox("County column (optional)", options=["(none)"] + cols, index=guess_index("county")+1)
    col_city  = st.selectbox("City column (optional)", options=["(none)"] + cols, index=guess_index("city")+1)
    col_zip   = st.selectbox("ZIP column (optional)", options=["(none)"] + cols, index=guess_index("zip")+1)
    col_status= st.selectbox("Status column (optional)", options=["(none)"] + cols, index=guess_index("status")+1)
    col_type  = st.selectbox("Permit Type column (optional)", options=["(none)"] + cols, index=guess_index("type")+1)

    # Working copy + helpers
    work = df.copy()
    work["_issue_dt"] = coerce_date(work[col_issue])
    work["_exp_dt"]   = coerce_date(work[col_exp])
    work["_months_remaining"] = months_remaining(work["_exp_dt"])

    if col_desc != "(none)":
        work["_roofing_related"] = work[col_desc].astype(str).str.contains("roof", case=False, na=False)
    else:
        work["_roofing_related"] = False

    # Auto apply filters
    mask = pd.Series(True, index=work.index)

    # months
    mask &= (work["_months_remaining"] <= max_months)

    # status
    if col_status != "(none)" and len(target_statuses) > 0:
        mask &= work[col_status].astype(str).isin(target_statuses)

    # county/city/zip
    if col_county != "(none)" and len(target_counties) > 0:
        mask &= work[col_county].astype(str).isin(target_counties)
    elif col_city != "(none)" and len(target_counties) > 0:
        # fallback: if your "counties" list actually contains city names, it will still work
        mask &= work[col_city].astype(str).isin(target_counties)
    elif col_zip != "(none)" and len(target_counties) > 0:
        mask &= work[col_zip].astype(str).isin(target_counties)

    # exclude roofing
    if exclude_roofing:
        type_is_roof = False
        if col_type != "(none)":
            type_is_roof = work[col_type].astype(str).str.contains("roof", case=False, na=False)
        mask &= ~(work["_roofing_related"] | type_is_roof)

    leads = work.loc[mask].copy()

    st.subheader("2) Results (auto-filtered)")
    st.caption(f"Showing {len(leads):,} of {len(work):,} rows after auto-filter.")
    # Pick reasonable columns to display first
    display_cols = []
    # prioritize common columns if present
    for key in ["Permit #","Owner Name","County","City","ZIP","Status","Permit Type","Project Description","Issue Date","Expiration Date"]:
        if key in leads.columns:
            display_cols.append(key)
    # then add anything we didn't include yet
    display_cols += [c for c in leads.columns if c not in display_cols and not c.startswith("_")]

    # show helpers as needed
    show_helpers = st.toggle("Show helper columns (months remaining / roofing detected)", value=False)
    if show_helpers:
        display_cols += ["_months_remaining","_roofing_related"]

    if len(leads) == 0:
        st.warning("No rows matched your filters. Try widening months, adding statuses, or adjusting county names.")
    else:
        st.dataframe(leads[display_cols], use_container_width=True, hide_index=True)

    # Downloads
    st.subheader("3) Download")
    csv_data = leads[display_cols].to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download CSV", data=csv_data, file_name="permit_leads.csv", mime="text/csv")

    import io
    try:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            leads[display_cols].to_excel(writer, index=False, sheet_name="Leads")
            ws = writer.sheets["Leads"]
            ws.autofilter(0, 0, leads[display_cols].shape[0], leads[display_cols].shape[1]-1)
            ws.freeze_panes(1,0)
        st.download_button("⬇️ Download Excel", data=buffer.getvalue(),
                           file_name="permit_leads.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        st.info("Excel export requires 'xlsxwriter'. If download fails, use CSV or add xlsxwriter to requirements.")

else:
    st.info("Upload a CSV or Excel file to get started. Map columns once, and the app will auto-filter using your defaults.")


    # PDF download
    import io
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    styles = getSampleStyleSheet()

    # Convert DataFrame to list of lists
    data = [list(leads[display_cols].columns)] + leads[display_cols].astype(str).values.tolist()

    # Create table
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))

    doc.build([Paragraph("Permit Leads Report", styles["Title"]), table])
    st.download_button(
        "⬇️ Download PDF",
        data=pdf_buffer.getvalue(),
        file_name="permit_leads.pdf",
        mime="application/pdf",
    )

