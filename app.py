import os
import sys
import json
from datetime import date, timedelta

import streamlit as st

# Show runtime up top (helps confirm 3.11 is actually used)
st.caption(f"Python runtime: {sys.version}")

# ---- Robust Earth Engine init (handles pretty JSON, single-line JSON, stray quotes, and \\n) ----
def init_ee_from_env():
    try:
        import ee  # import inside so we can fail gracefully if deps not installed yet
    except Exception as e:
        st.error(f"Earth Engine package not available: {e}")
        st.stop()

    key = os.getenv("EE_PRIVATE_KEY")
    if not key:
        st.error("EE_PRIVATE_KEY is missing. In Render → Environment, add EE_PRIVATE_KEY with your full service-account JSON.")
        st.stop()

    key_str = key.strip()
    # If someone pasted the JSON wrapped in quotes, strip them once
    if (key_str.startswith('"') and key_str.endswith('"')) or (key_str.startswith("'") and key_str.endswith("'")):
        key_str = key_str[1:-1]

    try:
        info = json.loads(key_str)
    except json.JSONDecodeError as e:
        st.error(f"EE_PRIVATE_KEY is not valid JSON: {e}\n\nPaste the EXACT JSON file you downloaded from Google (no extra quotes).")
        st.stop()

    required = ("type", "client_email", "private_key", "token_uri")
    missing = [f for f in required if f not in info]
    if missing:
        st.error(f"Service-account JSON is missing fields: {missing}. Use the key JSON from IAM → Service Accounts → Keys.")
        st.stop()

    # Normalize private_key newlines if it came in as escaped \n
    pk = info.get("private_key", "")
    if "\\n" in pk and "-----BEGIN" in pk:
        info["private_key"] = pk.replace("\\n", "\n")
        key_str = json.dumps(info)

    try:
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=key_str)
        ee.Initialize(creds)
        # Quick test call
        _ = ee.Number(1).getInfo()
        st.caption(f"✅ Earth Engine initialized as {info['client_email']}")
        return ee
    except Exception as e:
        st.error(f"❌ Earth Engine init failed: {e}\n\nCommon causes:\n"
                 f"• EE API not enabled for the GCP project\n"
                 f"• Service account missing roles: earthengine.viewer, serviceusage.serviceUsageConsumer\n"
                 f"• Key pasted incorrectly (extra quotes / missing newlines)")
        st.stop()

# ---- UI + Map ----
st.set_page_config(layout="wide", page_title="🌱 Soil & Crop Scout")
st.title("🛰️ Soil & Crop Scout")
st.caption("Sentinel-2 NDVI + Sentinel-1 SAR moisture proxy (baseline).")

# Initialize EE (and import only after)
ee = init_ee_from_env()

# Leafmap import (correct module)
try:
    import leafmap.foliumap as leafmap
except Exception as e:
    st.error(f"Leafmap import failed: {e}. Try pinning leafmap==0.50.0 (or 0.49.3) in requirements.txt.")
    st.stop()

from datetime import timedelta

today = date.today()
start_default = today - timedelta(days=30)
with st.sidebar:
    st.header("Date Range")
    start_date = st.date_input("Start", start_default)
    end_date = st.date_input("End", today)
    if start_date >= end_date:
        st.error("Start must be before End.")
        st.stop()

m = leafmap.Map(center=[37.60, -120.90], zoom=10)
m.add_basemap("HYBRID")

# Sentinel-2 NDVI
try:
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
          .filterDate(str(start_date), str(end_date))
          .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40))
          .median())
    ndvi = s2.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndvi_vis = {"min": 0.0, "max": 1.0, "palette": ["#8b4513", "#ffff00", "#00ff00"]}
    m.addLayer(ndvi, ndvi_vis, f"NDVI {start_date}→{end_date}")
except Exception as e:
    st.warning(f"Sentinel-2 NDVI layer failed: {e}")

# Sentinel-1 SAR VV
try:
    s1 = (ee.ImageCollection("COPERNICUS/S1_GRD")
          .filterDate(str(start_date), str(end_date))
          .filter(ee.Filter.eq("instrumentMode", "IW"))
          .filter(ee.Filter.eq("polarization", "VV"))
          .filter(ee.Filter.eq("orbitProperties_pass", "DESCENDING"))
          .mean())
    sar_vv_vis = {"min": -20, "max": -2}
    m.addLayer(s1.select("VV"), sar_vv_vis, f"SAR VV {start_date}→{end_date}")
except Exception as e:
    st.warning(f"Sentinel-1 SAR layer failed: {e}")

st.sidebar.write("Tip: use the layer control to toggle NDVI/SAR.")
m.to_streamlit(height=720)
