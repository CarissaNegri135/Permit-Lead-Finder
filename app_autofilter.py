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

up = st.file_uploader("Upload CSV or Excel", type=["csv","xlsx"])
if not up:
    st.info("Upload permits_clean_v3.csv or .xlsx to begin.")
    st.stop()

df = read_any(up)
st.subheader("Preview of Data")
st.dataframe(df.head(20), use_container_width=True)

st.subheader("Filters")
query = st.text_input("Search any text (any column)")
if query:
    mask = df.astype(str).apply(lambda s: s.str.contains(query, case=False, na=False))
    df = df[mask.any(axis=1)]

st.write(f"Rows after filters: {len(df)}")
st.dataframe(df, use_container_width=True)

@st.cache_data
def to_csv_bytes(d): return d.to_csv(index=False).encode("utf-8")

@st.cache_data
def to_xlsx_bytes(d):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        d.to_excel(w, index=False, sheet_name = "Sheet1")
        w.sheets["Sheet1"].freeze_panes(1,0)
    return buf.getvalue()

st.download_button("Download CSV", to_csv_byets(df), "permits_filtered.csv", "text/csv")
st.download_button("Download Excel", to_xlsx_byets(df), "permits_filtered.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
