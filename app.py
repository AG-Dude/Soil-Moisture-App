import os
import sys
import json
from datetime import date, timedelta

import streamlit as st

# ---------------------------------------------------------------------
# MUST be the first Streamlit command
# ---------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="🌱 Crop & Soil Scout")

st.caption(f"Python runtime: {sys.version}")
st.title("🛰️ Soil Scout")
st.caption("Sentinel-2 NDVI + Sentinel-1 SAR moisture proxy (baseline).")

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
                 "\n\nCommon causes:\n"
                 "• Earth Engine API not enabled for the project\n"
                 "• Service account missing roles: earthengine.viewer, serviceusage.serviceUsageConsumer\n"
                 "• Key pasted incorrectly (extra quotes / missing newlines)")
        st.stop()

ee = ee_init()

# ---------------------------------------------------------------------
# Map UI
# ---------------------------------------------------------------------
try:
    import leafmap.foliumap as leafmap
except Exception as e:
    st.error(f"Leafmap import failed: {e}. Pin leafmap==0.50.0 (or 0.49.3) in requirements.txt.")
    st.stop()

today = date.today()
default_start = today - timedelta(days=30)
with st.sidebar:
    st.header("Date Range")
    start_date = st.date_input("Start", default_start)
    end_date = st.date_input("End", today)
    if start_date >= end_date:
        st.error("Start must be before End.")
        st.stop()
    st.write("Tip: use the layer control on the map to toggle NDVI/SAR.")

# Create map
m = leafmap.Map(center=[37.60, -120.90], zoom=10)
m.add_basemap("HYBRID")

# Sentinel-2 NDVI
try:
    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterDate(str(start_date), str(end_date))
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
        .median()
    )
    ndvi = s2.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndvi_vis = {"min": 0.0, "max": 1.0, "palette": ["#8b4513", "#ffff00", "#00ff00"]}
    # ✅ leafmap uses add_ee_layer for EE images
    m.add_ee_layer(ndvi, ndvi_vis, f"NDVI {start_date}→{end_date}")
except Exception as e:
    st.warning(f"Sentinel-2 NDVI layer failed: {e}")

# Sentinel-1 SAR (VV)
try:
    s1 = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterDate(str(start_date), str(end_date))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        # 'transmitterReceiverPolarisation' is an array; use listContains
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .mean()
    )
    sar_vv_vis = {"min": -20, "max": -2}
    # ✅ use add_ee_layer here as well
    m.add_ee_layer(s1.select("VV"), sar_vv_vis, f"SAR VV {start_date}→{end_date}")
except Exception as e:
    st.warning(f"Sentinel-1 SAR layer failed: {e}")

# Render map
m.to_streamlit(height=720)

st.markdown(
    "<div style='opacity:.7;font-size:0.9rem'>Next: drone GeoTIFF + Sentek CSV upload and AI field report.</div>",
    unsafe_allow_html=True,
)
