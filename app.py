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
st.title("🛰️ Soil Scout")
st.caption(" NDVI • NDWI • SAR • Water")

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

    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()

    if not key.lstrip().startswith("{"):
        st.error("EE_PRIVATE_KEY does not start with '{'. Paste the ENTIRE service-account JSON (IAM → Service Accounts → Keys).")
        st.stop()

    try:
        info = json.loads(key)
    except Exception as e:
        st.error(f"EE_PRIVATE_KEY is not valid JSON: {e}. Paste the exact file contents of the downloaded key JSON.")
        st.stop()

    pk = info.get("private_key", "")
    if "\\n" in pk and "-----BEGIN" in pk:
        info["private_key"] = pk.replace("\\n", "\n")
        key = json.dumps(info)

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
# Map UI + controls
# ---------------------------------------------------------------------
try:
    import leafmap.foliumap as leafmap
except Exception as e:
    st.error(f"Leafmap import failed: {e}. Pin leafmap==0.50.0 (or 0.49.3) in requirements.txt.")
    st.stop()

today = date.today()
default_start = today - timedelta(days=30)

with st.sidebar:
    st.header("Date & Layers")
    start_date = st.date_input("Start", default_start)
    end_date = st.date_input("End", today)
    if start_date >= end_date:
        st.error("Start must be before End.")
        st.stop()

    cloud_thresh = st.slider("Max cloud % (S2 filter)", 0, 80, 40, 5)

    st.markdown("**Overlays**")
    show_ndvi = st.checkbox("NDVI (S2)", True)
    show_ndwi = st.checkbox("NDWI Water Index (S2)", False)
    show_sar_vv = st.checkbox("SAR VV (S1)", True)
    show_water = st.checkbox("Water Mask (NDWI>0.2)", False)
    show_fallow = st.checkbox("Fallow (CDL)", False)
    show_cdl = st.checkbox("California Crops (CDL codes)", False)
    show_soil_texture = st.checkbox("Soil Texture (USDA 12-class)", False)

    st.markdown("---")
    st.header("Area of Interest (AOI)")
    lat = st.number_input("Center latitude", value=37.600000, format="%.6f")
    lon = st.number_input("Center longitude", value=-120.900000, format="%.6f")
    size_ha = st.number_input("Approx. field size (ha)", value=40.0, min_value=1.0, step=1.0)
    st.caption("We build a square AOI around that point using the area.")

    st.markdown("---")
    st.header("CDL Crop Codes (optional)")
    cdl_codes_text = st.text_input(
        "Comma-separated CDL codes to overlay (e.g., 36,52,3,59,57)",
        value="36,52,3,59,57"  # Alfalfa, Grapes, Rice, Other Tree Nuts, Citrus (common CA)
    )
    max_imgs = st.slider("Max images for NDVI time-series", 5, 60, 25, 5)
    compute_btn = st.button("Compute AOI Summary")

# Build AOI square from center + area
area_m2 = float(size_ha) * 10000.0
side_m = math.sqrt(area_m2)
radius_m = side_m / 2.0
aoi = ee.Geometry.Point([lon, lat]).buffer(radius_m).bounds()

# Create map
m = leafmap.Map(center=[lat, lon], zoom=14)
m.add_basemap("HYBRID")
try:
    m.add_marker(location=[lat, lon], popup="AOI center")
except Exception:
    pass

# AOI outline
try:
    aoi_outline = ee.Image().byte().paint(aoi, 1, 2)
    m.add_ee_layer(aoi_outline.visualize(palette=["#00FFFF"]), {}, "AOI outline")
except Exception as e:
    st.warning(f"AOI outline failed: {e}")

# -------------------- Sentinel-2 base and indices --------------------
def s2_median(aoi_geom, start_str, end_str, cloud_max):
    return (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterDate(start_str, end_str)
            .filterBounds(aoi_geom)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", int(cloud_max)))
            .median())

s2 = None
ndvi = None
ndwi = None
try:
    s2 = s2_median(aoi, str(start_date), str(end_date), cloud_thresh)
except Exception as e:
    st.warning(f"S2 retrieval failed: {e}")

if s2 is not None:
    if show_ndvi:
        try:
            ndvi = s2.normalizedDifference(["B8", "B4"]).rename("NDVI").clip(aoi)
            ndvi_vis = {"min": 0.0, "max": 1.0, "palette": ["#8b4513", "#ffff00", "#00ff00"]}
            m.add_ee_layer(ndvi, ndvi_vis, f"NDVI {start_date}→{end_date}")
        except Exception as e:
            st.warning(f"NDVI layer failed: {e}")

    if show_ndwi or show_water:
        try:
            # NDWI = (Green - NIR) / (Green + NIR) = (B3 - B8) / (B3 + B8)
            ndwi = s2.normalizedDifference(["B3", "B8"]).rename("NDWI").clip(aoi)
            if show_ndwi:
                ndwi_vis = {"min": -1.0, "max": 1.0, "palette": ["#654321", "#ffffff", "#00bfff"]}
                m.add_ee_layer(ndwi, ndwi_vis, f"NDWI {start_date}→{end_date}")
            if show_water:
                water = ndwi.gt(0.2).selfMask()
                water_vis = {"palette": ["#00aaff"]}
                m.add_ee_layer(water, water_vis, "Water Mask (NDWI>0.2)")
        except Exception as e:
            st.warning(f"NDWI/Water layer failed: {e}")

# -------------------- Sentinel-1 SAR --------------------
sar_vv_img = None
if show_sar_vv:
    try:
        s1 = (ee.ImageCollection("COPERNICUS/S1_GRD")
              .filterDate(str(start_date), str(end_date))
              .filterBounds(aoi)
              .filter(ee.Filter.eq("instrumentMode", "IW"))
              .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
              .mean()
              .clip(aoi))
        sar_vv_img = s1.select("VV")
        sar_vv_vis = {"min": -20, "max": -2}
        m.add_ee_layer(sar_vv_img, sar_vv_vis, f"SAR VV {start_date}→{end_date}")
    except Exception as e:
        st.warning(f"SAR VV failed: {e}")

# -------------------- Fallow + Crops (CDL) --------------------
cdl_img = None
if show_fallow or show_cdl:
    try:
        # Use the year of 'end_date'
        year = end_date.year
        cdl_img = (ee.ImageCollection("USDA/NASS/CDL")
                   .filterDate(f"{year}-01-01", f"{year}-12-31")
                   .first()
                   .select("cropland")
                   .clip(aoi))
        if show_fallow:
            # CDL class 61 is Fallow/Idle Cropland in NASS CDL legend
            fallow = cdl_img.eq(61).selfMask()
            m.add_ee_layer(fallow, {"palette": ["#ff8800"]}, f"Fallow (CDL {year})")

        if show_cdl:
            # Parse user codes and map each code to a color
            try:
                codes = [int(v.strip()) for v in cdl_codes_text.split(",") if v.strip()]
            except Exception:
                codes = []
            # simple repeating color list
            colors = [
                "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff",
                "#00ffff", "#ff8800", "#8800ff", "#00ff88", "#888888"
            ]
            for i, code in enumerate(codes[:10]):  # cap to 10 layers for performance
                mask = cdl_img.eq(code).selfMask()
                m.add_ee_layer(mask, {"palette": [colors[i % len(colors)]]}, f"CDL code {code} ({year})")
    except Exception as e:
        st.warning(f"CDL layer failed: {e}")

# -------------------- Soil Texture (USDA 12-class) --------------------
if show_soil_texture:
    try:
        # OpenLandMap USDA soil texture class (12 categories), global
        tex = ee.Image("OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-12A1C_M/v02").select("b0").clip(aoi)
        # Palette for 12 classes (arbitrary, but distinct):
        palette12 = [
            "#fef0d9", "#fdcc8a", "#fc8d59", "#e34a33",
            "#b30000", "#31a354", "#2b8cbe", "#a
