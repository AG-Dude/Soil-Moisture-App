import os
import sys
import json
from datetime import date, timedelta

import streamlit as st

# ── MUST be the first Streamlit command ────────────────────────────────────────
st.set_page_config(layout="wide", page_title="🌱 Soil & Crop Scout")
# ───────────────────────────────────────────────────────────────────────────────

st.caption(f"Python runtime: {sys.version}")
st.title("🛰️ Soil & Crop Scout")
st.caption("Sentinel-2 NDVI + Sentinel-1 SAR moisture proxy (baseline).")

# ── Robust Earth Engine init (handles pretty JSON, single-line JSON, stray quotes, and \\n) ──
def init_ee_from_env():
    try:
        import ee  # import inside so we can show a friendly error if missing
    except Exception as e:
        st.error(f"Earth Engine package not available: {e}. "
                 "Make sure 'earthengine-api' is pinned in requirements.txt.")
        st.stop()

    key = os.getenv("EE_PRIVATE_KEY")
    # Treat empty or whitespace-only as missing
    if not key or not key.strip():
        st.error("EE_PRIVATE_KEY is missing or empty.\n\n"
                 "In Render → Environment, add EE_PRIVATE_KEY with your full service-account JSON.")
        st.stop()

    key_str = key.strip()

    # If the JSON was pasted wrapped in a single pair of quotes, strip them once
    if (key_str.startswith('"') and key_str.endswith('"')) or (key_str.startswith("'") and key_str.endswith("'")):
        key_str = key_str[1:-1].strip()

    # Quick heuristics before json.loads
    if not key_str.lstrip().startswith("{"):
        if key_str.lstrip().startswith("-----BEGIN"):
            st.error("You pasted only the PEM block. "
                     "Paste the ENTIRE service-account **JSON** (includes client_email, token_uri, etc.).")
        else:
            st.error("EE_PRIVATE_KEY does not start with '{'. "
                     "Paste the EXACT JSON you downloaded from Google (no extra quotes/backticks).")
        st.stop()

    try:
        info = json.loads(key_str)
    except json.JSONDecodeError as e:
        st.error(f"EE_PRIVATE_KEY is not valid JSON: {e}\n\n"
                 "Paste the EXACT file contents from IAM → Service Accounts → Keys → Create new key (JSON).")
        st.stop()

    # Minimal sanity checks
    required = ("type", "client_email", "private_key", "token_uri")
    missing = [f for f in required if f not in info]
    if missing:
        st.error(f"Service-account JSON is missing fields: {missing}. "
                 "Create a fresh JSON key in IAM → Service Accounts → Keys.")
        st.stop()

    # Normalize private_key newlines if it came through with escaped \n
    pk = info["private_key"]
    if "\\n" in pk and "-----BEGIN" in pk:
        info["private_key"] = pk.replace("\\n", "\n")
        key_str = json.dumps(info)

    try:
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=key_str)
        ee.Initialize(creds)
        # Quick test call to verify auth
        _ = ee.Number(1).getInfo()
        st.caption(f"✅ Earth Engine initialized as {info['client_email']}")
        return ee
    except Exception as e:
        st.error(
            "❌ Earth Engine init failed: " + str(e) +
            "\n\nCommon causes:\n"
            "• Earth Engine API not enabled for this GCP project\n"
            "• Service account missing roles: earthengine.viewer, serviceusage.serviceUsageConsumer\n"
            "• Key pasted incorrectly (extra quotes / missing newlines)"
        )
        st.stop()

ee = init_ee_from_env()

# ── Map UI ─────────────────────────────────────────────────────────────────────
try:
    import leafmap.foliumap as leafmap  # correct import (not 'streamlitmap')
except Exception as e:
    st.error(f"Leafmap import failed: {e}. "
             "Pin leafmap to a compatible version (e.g., 0.50.0 or 0.49.3) in requirements.txt.")
    st.stop()

# Sidebar date controls
today = date.today()
start_default = today - timedelta(days=30)
with st.sidebar:
    st.header("Date Range")
    start_date = st.date_input("Start", start_default)
    end_date = st.date_input("End", today)
    if start_date >= end_date:
        st.error("Start must be before End.")
        st.stop()
    st.write("Tip: Use the layer control on the map to toggle NDVI/SAR.")

# Create map
m = leafmap.Map(center=[37.60, -120.90], zoom=10)
m.add_basemap("HYBRID")

# ── Sentinel-2 NDVI ────────────────────────────────────────────────────────────
try:
    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterDate(str(start_date), str(end_date))
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
        .median()
    )
    ndvi = s2.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndvi_vis = {"min": 0.0, "max": 1.0, "palette": ["#8b4513", "#ffff00", "#00ff00"]}
    m.addLayer(ndvi, ndvi_vis, f"NDVI {start_date}→{end_date}")
except Exception as e:
    st.warning(f"Sentinel-2 NDVI layer failed: {e}")

# ── Sentinel-1 SAR (VV) moisture proxy ────────────────────────────────────────
try:
    s1 = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterDate(str(start_date), str(end_date))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        # Use listContains because this property is an array in S1 metadata
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .mean()
    )
    sar_vv_vis = {"min": -20, "max": -2}
    m.addLayer(s1.select("VV"), sar_vv_vis, f"SAR VV {start_date}→{end_date}")
except Exception as e:
    st.warning(f"Sentinel-1 SAR layer failed: {e}")

# Render map
m.to_streamlit(height=720)

# Footer helper
st.markdown(
    "<div style='opacity:.7;font-size:0.9rem'>Next steps: add drone GeoTIFF upload + Sentek CSV upload and AI field report.</div>",
    unsafe_allow_html=True,
)
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
