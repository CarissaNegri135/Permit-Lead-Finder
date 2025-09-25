import io
import pandas as pd
import numpy as np
import streamlit as st

st.set_page_config(page_title="Permit Lead Finder — CSV/XLSX", layout="wide")
st.title("Permit Lead Finder — CSV/XLSX")
st.caption("Upload a CSV or Excel, filter, and download outreach-ready leads.")

# ---------- helpers ----------
@st.cache_data
def read_any(file):
    name = file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)

@st.cache_data
def to_csv_bytes(df: pd.DataFrame):
    return df.to_csv(index=False).encode("utf-8")

@st.cache_data
def to_xlsx_bytes(df: pd.DataFrame):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="Leads")
        w.sheets["Leads"].freeze_panes(1, 0)
    return buf.getvalue()

def has(col):  # small helper to check col exists (case-insensitive)
    return col in df.columns

# ---------- upload ----------
up = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])
if not up:
    st.info("Tip: use the cleaned file you just made (CSV or XLSX).")
    st.stop()

df = read_any(up)
# normalize common column names (makes the app tolerant to headers)
rename = {}
for c in df.columns:
    lc = c.strip().lower()
    if lc.startswith("permit"): rename[c] = "Permit"
    elif "issue" in lc or "date" in lc: rename[c] = "Issued"
    elif "desc" in lc: rename[c] = "Description"
    elif "apn" == lc or "apn" in lc: rename[c] = "APN"
    elif "address" in lc: rename[c] = "Address"
    elif "valu" in lc: rename[c] = "Valuation"
    elif "contract" in lc or "applicant" in lc: rename[c] = "Contractor"
    elif "county" in lc: rename[c] = "County"
    elif "expir" in lc: rename[c] = "Expiration"
df = df.rename(columns=rename)

st.subheader("1) Preview")
st.dataframe(df.head(50), use_container_width=True)

# ---------- filters ----------
st.subheader("2) Filter")

left, mid, right = st.columns([1,1,1.2])

with left:
    # free text search across all columns
    query = st.text_input("Search (any column)")
with mid:
    # exclude roofing permits
    exclude_roofing = st.checkbox("Exclude roofing-related", value=False,
        help="Filters rows whose Description or Scope contains: roof, reroof, re-roof, roofing.")
with right:
    # month threshold if Expiration exists
    months_ui = None
    if "Expiration" in df.columns:
        months_ui = st.slider("Months remaining ≤", 0, 24, 4,
                              help="Requires an 'Expiration' column (MM/DD/YYYY).")

# optional county filter if County column exists
if "County" in df.columns:
    counties = sorted([c for c in df["County"].dropna().astype(str).unique()])
    chosen = st.multiselect("County", counties, default=counties[:0])
else:
    chosen = []

# apply filters
out = df.copy()

# search
if query.strip():
    mask = out.astype(str).apply(lambda s: s.str.contains(query, case=False, na=False))
    out = out[mask.any(axis=1)]

# exclude roofing
if exclude_roofing:
    cols_to_check = [c for c in ["Description", "Scope"] if c in out.columns]
    if cols_to_check:
        pat = r"\broof|\bre-roof|\breroof|\broofing"
        keep = ~out[cols_to_check].astype(str).apply(
            lambda s: s.str.contains(pat, case=False, na=False, regex=True)
        ).any(axis=1)
        out = out[keep]

# county filter
if chosen:
    out = out[out["County"].astype(str).isin(chosen)]

# months remaining (if Expiration present)
if months_ui is not None:
    # parse dates
    issued_col = "Issued" if "Issued" in out.columns else None
    out["_exp"] = pd.to_datetime(out["Expiration"], errors="coerce")
    today = pd.Timestamp.today().normalize()
    # months difference (approx): years*12 + months, then adjust by day
    months = (out["_exp"].dt.year - today.year) * 12 + (out["_exp"].dt.month - today.month)
    months -= (out["_exp"].dt.day < today.day).astype("Int64")
    out["Months Remaining"] = months
    out = out[out["Months Remaining"] <= months_ui]
    out = out.drop(columns=["_exp"])

st.write(f"Rows after filters: **{len(out):,}**")
st.dataframe(out, use_container_width=True)

# ---------- download ----------
st.subheader("3) Download")
st.download_button("⬇️ Download CSV", to_csv_bytes(out), file_name="permits_filtered.csv", mime="text/csv")
st.download_button("⬇️ Download Excel", to_xlsx_bytes(out),
                   file_name="permits_filtered.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
