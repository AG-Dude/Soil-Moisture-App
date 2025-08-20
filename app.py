import os
import sys
import json
from datetime import date, timedelta

import streamlit as st  # Import first…

# 👇 MUST be the first Streamlit command on the page
st.set_page_config(layout="wide", page_title="🌱 Soil & Crop Scout")

# (Now it’s safe to use other st.* calls)
st.caption(f"Python runtime: {sys.version}")
st.title("🛰️ Soil & Crop Scout")
st.caption("Sentinel-2 NDVI + Sentinel-1 SAR moisture proxy (baseline).")

# ---- Robust Earth Engine init (handles pretty JSON, single-line JSON, stray quotes, and \\n) ----
def init_ee_from_env():
    try:
        import ee
    except Exception as e:
        st.error(f"Earth Engine package not available: {e}")
        st.stop()

    key = os.getenv("EE_PRIVATE_KEY")
    if not key:
        st.error("EE_PRIVATE_KEY is missing. In Render → Environment, add EE_PRIVATE_KEY with your full service-account JSON.")
        st.stop()

    key_str = key.strip()
    if (key_str.startswith('"') and key_str.endswith('"')) or (key_str.startswith("'") and key_str.endswith("'")):
        key_str = key_str[1:-1]

    try:
        info = json.loads(key_str)
    except json.JSONDecodeError as e:
        st.error(f"EE_PRIVATE_KEY is not valid JSON: {e}\n\nPaste the EXACT JSON you downloaded from Google (no extra quotes).")
        st.stop()

    required = ("type", "client_email", "private_key", "token_uri")
    missing = [f for f in required if f not in info]
    if missing:
        st.error(f"Service-account JSON is missing fields: {missing}. Create a new key in IAM → Service Accounts → Keys.")
        st.stop()

    pk = info.get("private_key", "")
    if "\\n" in pk and "-----BEGIN" in pk:
        info["private_key"] = pk.replace("\\n", "\n")
        key_str = json.dumps(info)

    try:
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=key_str)
        ee.Initialize(creds)
        _ = ee.Number(1).getInfo()  # quick test
        st.caption(f"✅ Earth Engine initialized as {info['client_email']}")
        return ee
    except Exception as e:
        st.error(
            "❌ Earth Engine init failed: "
            + str(e)
            + "\n\nCommon causes:\n"
              "• EE API not enabled for the GCP project\n"
              "• Service account missing roles: earthengine.viewer, serviceusage.serviceUsageConsumer\n"
              "• Key pasted incorrectly (extra quotes / missing newlines)"
        )
        st.stop()

ee = init_ee_from_env()

# Leafmap import
try:
    import leafmap.foliumap as leafmap
except Exception as e:
    st.error(f"Leafmap import failed: {e}. Pin leafmap==0.50.0 (or 0.49.3) in requirements.txt.")
    st.stop()
