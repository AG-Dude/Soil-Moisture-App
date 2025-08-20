import os
import sys
import json
import math
from datetime import date, timedelta

import streamlit as st
import altair as alt
import pandas as pd

# ---------------------------------------------------------------------
# MUST be the first Streamlit command
# ---------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="🌱 Soil & Crop Scout")

st.caption(f"Python runtime: {sys.version}")
st.title("🛰️ Soil & Crop Scout")
st.caption("Sentinel-2 NDVI + Sentinel-1 SAR moisture proxy with field stats & exports.")

# ---------------------------------------------------------------------
# Robust Earth Engine init (service-account via env var)
# ---------------------------------------------------------------------
def ee_init():
    try:
        import ee
    except Exception as e:
        st.error(f"Earth Engine package not available: {e}. Make sure 'earthengine-api' is in requirements.txt.")
        st.stop()

    key = os.getenv("EE_PRIVATE_KEY", "").strip()
    if not key:
        st.error("EE_PRIVATE_KEY is missing or empty. In Render → Environment, add EE_PRIVATE_KEY with your full service-account JSON.")
        st.stop()

    # If someone pasted the JSON wrapped in quotes, strip once
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()

    # Must be full JSON, not just the PEM block
    if not key.lstrip().startswith("{"):
        st.error("EE_PRIVATE_KEY does not start with '{'. Paste the ENTIRE service-account JSON (from IAM → Service Accounts → Keys).")
        st.stop()

    try:
        info = json.loads(key)
    except Exception as e:
        st.error(f"EE_PRIVATE_KEY is not valid JSON: {e}. Paste the exact file contents of the downloaded key JSON.")
        st.stop()

    # Normalize private_key newlines if they arrived as '\\n'
    pk = info.get("private_key", "")
    if "\\n" in pk and "-----BEGIN" in pk:
        info["private_key"] = pk.replace("\\n", "\n")
        key = json.dumps(info)

    # Minimal field check
    for f in ("type", "client_email", "private_key", "token_uri"):
        if f not in info:
            st.error(f"Service-account JSON missing field: {f}. Create a fresh key JSON in IAM → Service Accounts → Keys.")
            st.stop()

    try:
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=key)
        ee.Initialize(creds)
        _ = ee.Number(1).getInfo()  # sanity call
        st.caption(f"✅ Earth Engine initialized as {info['client_email']}")
        return ee
    except Exception as e:
        st.error("❌ Earth Engine init failed: " + str(e) +
                 "\
