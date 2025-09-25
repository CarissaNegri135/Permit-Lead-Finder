import re
import io
from typing import Optional, List

import streamlit as st
import pandas as pd

# -------------- Page setup --------------
st.set_page_config(page_title="Permit Lead Finder — PDF/CSV/XLSX", layout="wide")
st.title("🏗️ Permit Lead Finder — PDF/CSV/XLSX")
st.caption("Upload a county report (PDF/CSV/XLSX), map columns (once), filter, and download outreach-ready leads.")

ROOF_WORDS = ["roof", "re-roof", "reroof", "re roof", "roof repl", "roofing"]


# -------------- Robust PDF readers --------------
def _try_pdf_tables(uploaded_file) -> Optional[pd.DataFrame]:
    """Try multiple pdfplumber strategies to get tables."""
    import pdfplumber

    frames = []
    strategies = [
        dict(vertical_strategy="lines",    horizontal_strategy="lines"),
        dict(vertical_strategy="lines",    horizontal_strategy="text"),
        dict(vertical_strategy="text",     horizontal_strategy="lines"),
        dict(vertical_strategy="text",     horizontal_strategy="text"),
        dict(vertical_strategy="explicit", horizontal_strategy="text"),
    ]
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            for ts in strategies:
                try:
                    tables = page.extract_tables(table_settings=ts) or []
                except Exception:
                    tables = []
                for t in tables:
                    if not t or len(t) < 2:
                        continue
                    header = ["" if h is None else str(h).strip() for h in t[0]]
                    rows   = [[("" if c is None else str(c).strip()) for c in r] for r in t[1:]]
                    if any(header) and rows:
                        df = pd.DataFrame(rows, columns=header)
                        frames.append(df)
    if frames:
        out = pd.concat(frames, ignore_index=True)
        out.columns = [c.strip() or f"col_{i}" for i, c in enumerate(out.columns)]
        return out
    return None


def _fallback_fixed_width(uploaded_file) -> Optional[pd.DataFrame]:
    """
    Parse fixed-width text for rows that look like:

    BLD24-02314  06/05/2025  APPLEGATE GAS STATION ...  [Scope]  [APN]  [Address]  [$]  [Contractor]
    """
    import pdfplumber

    def looks_like_header(line: str) -> bool:
        l = line.lower()
        return ("permit" in l and "issued" in l) or ("permit" in l and "date" in l)

    def split_cols(line: str) -> List[str]:
        # split on 2+ spaces; keeps words inside columns intact
        return re.split(r"\s{2,}", line.strip())

    with pdfplumber.open(uploaded_file) as pdf:
        header: List[str] = []
        all_rows: List[List[str]] = []
        width = None

        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = [ln for ln in (ln.strip() for ln in text.splitlines()) if ln]

            for ln in lines:
                # Skip page headers/footers
                if re.match(r"^Page\s+\d+\s+of\s+\d+$", ln, flags=re.I):
                    continue

                # Identify header once
                if not header and looks_like_header(ln):
                    header = split_cols(ln)
                    width = len(header)
                    continue

                # Identify data rows by permit pattern BLDxx-xxxxx at start
                if re.match(r"^BLD\d{2}-\d+", ln):
                    parts = split_cols(ln)
                    if width is None:
                        width = len(parts)
                        header = [f"col_{i}" for i in range(width)]
                    # Sometimes the Description spills onto next line: capture extra short lines
                    if len(parts) < width:
                        # try to stitch with next lines if needed — handled lightly here
                        pass
                    if len(parts) == width:
                        all_rows.append(parts)

        if header and all_rows:
            df = pd.DataFrame(all_rows, columns=header)
            # Standardize likely column names if present
            rename_map = {}
            for c in list(df.columns):
                lc = c.lower()
                if lc.startswith("permit"):
                    rename_map[c] = "Permit"
                elif "issue" in lc or "date" in lc:
                    rename_map[c] = "Issued"
                elif "desc" in lc:
                    rename_map[c] = "Description"
                elif "scope" in lc:
                    rename_map[c] = "Scope"
                elif lc in ("apn",) or "apn" in lc:
                    rename_map[c] = "APN"
                elif "address" in lc:
                    rename_map[c] = "Address"
                elif "valu" in lc or "$" in lc:
                    rename_map[c] = "Valuation"
                elif "contract" in lc or "applicant" in lc:
                    rename_map[c] = "Contractor"
            df = df.rename(columns=rename_map)
            return df

    return None


def read_pdf(uploaded_file) -> pd.DataFrame:
    df = _try_pdf_tables(uploaded_file)
    if df is not None and len(df):
        return df
    df = _fallback_fixed_width(uploaded_file)
    if df is not None and len(df):
        return df
    st.error("No tables detected and fixed-width parsing failed. If this is a scanned PDF, OCR it first, then retry.")
    st.stop()


# -------------- Universal reader --------------
def read_any(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if name.endswith(".xlsx"):
        return pd.read_excel(uploaded_file)
    if name.endswith(".pdf"):
        return read_pdf(uploaded_file)
    st.error("Unsupported file type. Upload a PDF, CSV, or XLSX.")
    st.stop()


# -------------- UI: upload + county tag --------------
uploaded = st.file_uploader("Upload a PDF, CSV, or XLSX", type=["pdf", "csv", "xlsx"])
county = st.selectbox("Select county tag to apply to this file", ["Placer", "El Dorado", "Nevada", "Yuba", "Sacramento", "Other"], index=0)

if not uploaded:
    st.info("Upload a file to begin.")
    st.stop()

raw = read_any(uploaded).copy()
raw["County"] = county

st.write("**Preview (first 25 rows)**")
st.dataframe(raw.head(25), use_container_width=True)


# -------------- Column mapping --------------
st.subheader("Map columns (only needed once per county format)")
cols = raw.columns.tolist()

def guess(name_part: str) -> int:
    name_part = name_part.lower()
    for i, c in enumerate(cols):
        if name_part in str(c).lower():
            return i
    return 0

c_permit = st.selectbox("Permit #", options=cols, index=guess("permit"))
c_issued = st.selectbox("Issued / Date", options=cols, index=guess("issue"))
c_desc   = st.selectbox("Description", options=cols, index=guess("desc"))
c_scope  = st.selectbox("Scope (optional)", options=["(none)"] + cols, index=(guess("scope")+1 if guess("scope") else 0))
c_apn    = st.selectbox("APN (optional)", options=["(none)"] + cols, index=(guess("apn")+1 if guess("apn") else 0))
c_addr   = st.selectbox("Address", options=cols, index=guess("address"))
c_val    = st.selectbox("Valuation (optional)", options=["(none)"] + cols, index=(guess("valu")+1 if guess("valu") else 0))
c_con    = st.selectbox("Contractor / Applicant (optional)", options=["(none)"] + cols, index=(guess("contract")+1 if guess("contract") else 0))

work = raw.rename(columns={
    c_permit: "Permit",
    c_issued: "Issued",
    c_desc:   "Description",
    c_addr:   "Address",
})
if c_scope != "(none)": work = work.rename(columns={c_scope: "Scope"})
if c_apn   != "(none)": work = work.rename(columns={c_apn: "APN"})
if c_val   != "(none)": work = work.rename(columns={c_val: "Valuation"})
if c_con   != "(none)": work = work.rename(columns={c_con: "Contractor"})

# Normalize Issued to datetime (best-effort)
work["Issued_dt"] = pd.to_datetime(work["Issued"], errors="coerce", infer_datetime_format=True)


# -------------- Filters --------------
st.subheader("Filters")

q = st.text_input("Search (matches Description / Scope / Address / Contractor)", "")
exclude_roof = st.checkbox("Exclude roofing projects", value=True)

mask = pd.Series(True, index=work.index)

if q.strip():
    pat = re.escape(q.strip())
    any_cols = ["Description", "Scope", "Address", "Contractor"]
    sub = work[any_cols].astype(str).apply(lambda s: s.str.contains(pat, case=False, na=False))
    mask &= sub.any(axis=1)

if exclude_roof:
    def is_roof(row):
        s = (" ".join([str(row.get(c, "")) for c in ["Description", "Scope"]])).lower()
        return any(k in s for k in ROOF_WORDS)
    mask &= ~work.apply(is_roof, axis=1)

filtered = work[mask].copy()
display_cols = [c for c in ["County","Permit","Issued","Description","Scope","APN","Address","Valuation","Contractor"] if c in filtered.columns]

st.write(f"**Results: {len(filtered):,} rows**")
st.dataframe(filtered[display_cols] if len(filtered) else filtered, use_container_width=True, hide_index=True)


# -------------- Downloads --------------
@st.cache_data
def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

@st.cache_data
def df_to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="Permits")
        # Freeze header row
        ws = w.sheets["Permits"]
        ws.freeze_panes(1, 0)
    return buf.getvalue()

st.download_button(
    "⬇️ Download CSV",
    data=df_to_csv_bytes(filtered[display_cols] if len(filtered) else filtered),
    file_name="permits_filtered.csv",
    mime="text/csv",
    disabled=len(filtered)==0,
)

st.download_button(
    "⬇️ Download Excel",
    data=df_to_xlsx_bytes(filtered[display_cols] if len(filtered) else filtered),
    file_name="permits_filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    disabled=len(filtered)==0,
)
