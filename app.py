import os
import sys
import json
import math
from datetime import date, timedelta, datetime, timezone

import streamlit as st
import altair as alt
import pandas as pd

# ─────────────────────────────────────────────────────────────────────
# Page setup (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="🛰️ Soil Scout")

st.title("🛰️ Soil Scout")
st.caption("NDVI • NDWI • SAR • Water • Fallow (CDL) • Soil Texture • Erosion Risk | AOI stats, time-series, export, AI helper")
st.caption(f"Python runtime: {sys.version}")

# ─────────────────────────────────────────────────────────────────────
# Earth Engine init (service account JSON in EE_PRIVATE_KEY)
# ─────────────────────────────────────────────────────────────────────
def ee_init():
    try:
        import ee
    except Exception as e:
        st.error(f"Earth Engine package not available: {e}. Ensure 'earthengine-api' is in requirements.txt.")
        st.stop()

    key = os.getenv("EE_PRIVATE_KEY", "").strip()
    if not key:
        st.error("EE_PRIVATE_KEY is missing/empty. Add FULL service-account JSON in Render → Environment.")
        st.stop()

    # If the JSON was pasted wrapped in one pair of quotes, strip once
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()

    if not key.lstrip().startswith("{"):
        st.error("EE_PRIVATE_KEY must be the ENTIRE service-account JSON (not just the PEM).")
        st.stop()

    try:
        info = json.loads(key)
    except Exception as e:
        st.error(f"EE_PRIVATE_KEY is not valid JSON: {e}")
        st.stop()

    # Normalize private key newlines if they arrived as '\\n'
    pk = info.get("private_key", "")
    if "\\n" in pk and "-----BEGIN" in pk:
        info["private_key"] = pk.replace("\\n", "\n")
        key = json.dumps(info)

    for f in ("type", "client_email", "private_key", "token_uri"):
        if f not in info:
            st.error(f"Service-account JSON missing field: {f}")
            st.stop()

    try:
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=key)
        ee.Initialize(creds)
        _ = ee.Number(1).getInfo()  # sanity
        return ee
    except Exception as e:
        st.error(
            "Earth Engine init failed: " + str(e) +
            "\nCommon causes:\n"
            "• Earth Engine API not enabled\n"
            "• Service account lacks roles: earthengine.viewer, serviceusage.serviceUsageConsumer\n"
            "• Key pasted incorrectly (extra quotes / missing newlines)"
        )
        st.stop()

ee = ee_init()

# ─────────────────────────────────────────────────────────────────────
# Map + controls
# ─────────────────────────────────────────────────────────────────────
try:
    import leafmap.foliumap as leafmap
except Exception as e:
    st.error(f"Leafmap import failed: {e}. Pin leafmap==0.50.0 (or 0.49.3).")
    st.stop()

today = date.today()
default_start = today - timedelta(days=30)

with st.sidebar:
    st.header("Date window")
    start_date = st.date_input("Start", default_start)
    end_date = st.date_input("End", today)
    if start_date >= end_date:
        st.error("Start must be before End.")
        st.stop()

    cloud_thresh = st.slider("Max cloud % (Sentinel-2)", 0, 80, 40, 5)

    st.header("Overlays")
    show_ndvi = st.checkbox("NDVI (S2)", True)
    show_ndwi = st.checkbox("NDWI (S2)", False)
    show_water = st.checkbox("Water mask (NDWI>0.2)", False)
    show_sar_vv = st.checkbox("SAR VV (S1)", True)
    show_fallow = st.checkbox("Fallow (CDL)", False)
    show_cdl = st.checkbox("CA crops (CDL classes)", False)
    show_soil_texture = st.checkbox("Soil texture (USDA 12-class)", False)
    show_erosion = st.checkbox("Erosion risk (relative)", False)

    st.info("Draw your AOI on the map using the square or polygon tool. If you don’t draw one, a small default box is used.")

# Create map with draw tools (default center = Central Valley; pan anywhere)
center_lat, center_lon = 37.60, -120.90
m = leafmap.Map(center=[center_lat, center_lon], zoom=12)
m.add_basemap("HYBRID")

# Add draw control (rectangle/polygon)
try:
    m.add_draw_control()
except Exception:
    try:
        m.add_draw_control(
            draw_marker=False, draw_circle=False, draw_circlemarker=False,
            draw_polyline=False, draw_rectangle=True, draw_polygon=True, edit=True, remove=True
        )
    except Exception:
        pass

# Default AOI outline (~0.5 km box) as a hint
ee_aoi_default = ee.Geometry.Point([center_lon, center_lat]).buffer(250).bounds()
try:
    aoi_outline = ee.Image().byte().paint(ee_aoi_default, 1, 2)
    m.add_ee_layer(aoi_outline.visualize(palette=["#00FFFF"]), {}, "Default AOI (outline)")
except Exception:
    pass

def resolve_aoi():
    """Use user-drawn ROI if available (leafmap stores it on rerun), else default."""
    try:
        roi = getattr(m, "user_roi", None)
        if roi:
            return ee.Geometry(roi)
    except Exception:
        pass
    return ee_aoi_default

# Helper datasets & functions
def s2_collection(aoi_geom, start_str, end_str, cloud_max):
    return (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterDate(start_str, end_str)
            .filterBounds(aoi_geom)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", int(cloud_max))))

def s2_median(aoi_geom, start_str, end_str, cloud_max):
    return s2_collection(aoi_geom, start_str, end_str, cloud_max).median().clip(aoi_geom)

def s1_collection(aoi_geom, start_str, end_str):
    return (ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterDate(start_str, end_str)
            .filterBounds(aoi_geom)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")))

def s1_mean_vv(aoi_geom, start_str, end_str):
    return s1_collection(aoi_geom, start_str, end_str).mean().clip(aoi_geom).select("VV")

def get_cdl_year_image(aoi_geom, year):
    return (ee.ImageCollection("USDA/NASS/CDL")
            .filterDate(f"{year}-01-01", f"{year}-12-31")
            .first()
            .select("cropland")
            .clip(aoi_geom))

def soil_texture_12(aoi_geom):
    return ee.Image("OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-12A1C_M/v02").select("b0").clip(aoi_geom)

def reduce_stats(image, geom, scale=10):
    reducer = (ee.Reducer.mean()
               .combine(ee.Reducer.stdDev(), sharedInputs=True)
               .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True))
    return image.reduceRegion(reducer=reducer, geometry=geom, scale=scale, bestEffort=True, maxPixels=1e9)

def compute_water_pct(ndwi_img, geom, thresh=0.2, scale=10):
    water = ndwi_img.gt(thresh)
    area_img = ee.Image.pixelArea()
    w = area_img.updateMask(water).reduceRegion(ee.Reducer.sum(), geom, scale, bestEffort=True)
    a = area_img.reduceRegion(ee.Reducer.sum(), geom, scale, bestEffort=True)
    try:
        w_val = (w.getInfo() or {}).get("area", None)
        a_val = (a.getInfo() or {}).get("area", None)
        if w_val and a_val and a_val > 0:
            return round(100.0 * float(w_val) / float(a_val), 2)
    except Exception:
        pass
    return None

def compute_cdl_histogram(cdl_img, geom, scale=30):
    try:
        hist = cdl_img.reduceRegion(ee.Reducer.frequencyHistogram(), geom, scale, bestEffort=True).get("cropland").getInfo()
        return hist or {}
    except Exception:
        return {}

def cdl_names_lookup(cdl_img):
    try:
        props = (cdl_img.getInfo() or {}).get("properties", {})
        values = props.get("cropland_class_values") or props.get("Class_values")
        names = props.get("cropland_class_names") or props.get("Class_names")
        if values and names and len(values) == len(names):
            return {int(v): n for v, n in zip(values, names)}
    except Exception:
        pass
    return {}

# Erosion risk (relative): risk = normalize( S * K * C )
def erosion_risk_layer(aoi_geom, ndvi_img):
    # S factor from slope (SRTM 30 m)
    dem = ee.Image("USGS/SRTMGL1_003").clip(aoi_geom)
    slope_deg = ee.Terrain.slope(dem)  # degrees
    theta = slope_deg.multiply(math.pi / 180.0).sin()
    # 9% slope threshold in degrees (~5.14°)
    s_low = theta.multiply(10.8).add(0.03)
    s_high = theta.multiply(16.8).subtract(0.50)
    S = s_low.where(slope_deg.gte(ee.Image.constant(5.14)), s_high).rename("S").max(0)

    # K factor from USDA 12-class texture (approximate typical K values)
    # 1..12 -> K in [0.02..0.40] (typical RUSLE K t·ha·h/ha·MJ·mm range; scaled)
    tex = soil_texture_12(aoi_geom)
    k_values = [0.28,0.20,0.15,0.32,0.38,0.40,0.25,0.22,0.26,0.17,0.20,0.15]  # generic mapping by class index
    K = tex.remap(list(range(1,13)), k_values).rename("K")

    # C factor from NDVI (more cover => lower C). Simple proxy: C = 1 - NDVI
    ndvi_clamped = ndvi_img.where(ndvi_img.lt(0), 0).where(ndvi_img.gt(1), 1)
    C = ee.Image(1).subtract(ndvi_clamped).rename("C")

    risk = S.multiply(K).multiply(C).rename("risk")
    # Normalize by 95th percentile within AOI -> 0..1
    p95 = ee.Number(risk.reduceRegion(ee.Reducer.percentile([95]), aoi_geom, 30, bestEffort=True).get("risk"))
    risk_norm = risk.divide(p95.max(ee.Number(1e-6))).clamp(0, 1).rename("risk")

    return risk_norm

# Resolve AOI (user-drawn on previous interaction), then build layers
AOI = resolve_aoi()

# Image counts (debug so you know data exists)
try:
    s2_count = int(s2_collection(AOI, str(start_date), str(end_date), cloud_thresh).size().getInfo())
except Exception:
    s2_count = 0
try:
    s1_count = int(s1_collection(AOI, str(start_date), str(end_date)).size().getInfo())
except Exception:
    s1_count = 0

st.sidebar.caption(f"🛰️ S2 scenes found: {s2_count}")
st.sidebar.caption(f"📡 S1 (SAR) scenes found: {s1_count}")

s2_img = None
ndvi_img = None
ndwi_img = None
sar_vv_img = None
cdl_img = None

# Sentinel-2 composite & indices
if s2_count > 0:
    try:
        s2_img = s2_median(AOI, str(start_date), str(end_date), cloud_thresh)
    except Exception as e:
        st.warning(f"S2 retrieval failed: {e}")

if s2_img is not None and show_ndvi:
    try:
        ndvi_img = s2_img.normalizedDifference(["B8", "B4"]).rename("NDVI")
        m.add_ee_layer(
            ndvi_img, {"min": 0.0, "max": 1.0, "palette": ["#8b4513", "#ffff00", "#00ff00"], "opacity": 0.8},
            f"NDVI {start_date}→{end_date}",
        )
    except Exception as e:
        st.warning(f"NDVI layer failed: {e}")
elif show_ndvi and s2_count == 0:
    st.warning("No Sentinel-2 images in this window/AOI. Widen the dates or reduce cloud %.")

if s2_img is not None and (show_ndwi or show_water):
    try:
        ndwi_img = s2_img.normalizedDifference(["B3", "B8"]).rename("NDWI")
        if show_ndwi:
            m.add_ee_layer(
                ndwi_img, {"min": -1.0, "max": 1.0, "palette": ["#654321", "#ffffff", "#00bfff"], "opacity": 0.7},
                f"NDWI {start_date}→{end_date}",
            )
        if show_water:
            water = ndwi_img.gt(0.2).selfMask()
            m.add_ee_layer(water, {"palette": ["#00aaff"], "opacity": 0.9}, "Water mask (NDWI>0.2)")
    except Exception as e:
        st.warning(f"NDWI/Water layer failed: {e}")

# Sentinel-1 SAR VV
if show_sar_vv:
    if s1_count == 0:
        st.warning("No Sentinel-1 scenes in this window/AOI.")
    else:
        try:
            sar_vv_img = s1_mean_vv(AOI, str(start_date), str(end_date))
            m.add_ee_layer(sar_vv_img, {"min": -20, "max": -2, "opacity": 0.75}, f"SAR VV {start_date}→{end_date}")
        except Exception as e:
            st.warning(f"SAR VV failed: {e}")

# Fallow + Crops (CDL)
if show_fallow or show_cdl:
    try:
        year = end_date.year
        cdl_img = get_cdl_year_image(AOI, year)
        if show_fallow:
            fallow = cdl_img.eq(61).selfMask()  # 61 = Fallow/Idle cropland
            m.add_ee_layer(fallow, {"palette": ["#ff8800"], "opacity": 0.85}, f"Fallow (CDL {year})")
        if show_cdl:
            m.add_ee_layer(cdl_img.randomVisualizer(), {}, f"CDL cropland classes ({year})")
    except Exception as e:
        st.warning(f"CDL layer failed: {e}")

# Soil texture
if show_soil_texture:
    try:
        tex = soil_texture_12(AOI)
        palette12 = ["#fef0d9","#fdcc8a","#fc8d59","#e34a33","#b30000","#31a354","#2b8cbe","#a6bddb","#1c9099","#c7e9b4","#7fcdbb","#df65b0"]
        m.add_ee_layer(tex, {"min": 1, "max": 12, "palette": palette12, "opacity": 0.7}, "Soil texture (USDA 12)")
    except Exception as e:
        st.warning(f"Soil texture layer failed: {e}")

# Erosion risk (relative)
risk_img = None
if show_erosion:
    if ndvi_img is None:
        st.info("Enable NDVI to compute erosion risk (uses current cover).")
    else:
        try:
            risk_img = erosion_risk_layer(AOI, ndvi_img)
            risk_vis = {"min": 0, "max": 1, "palette": ["#ffffb2","#fecc5c","#fd8d3c","#f03b20","#bd0026"], "opacity": 0.85}
            m.add_ee_layer(risk_img, risk_vis, "Erosion risk (relative)")
        except Exception as e:
            st.warning(f"Erosion risk layer failed: {e}")

# Layer control so you can toggle visibility on-map
try:
    m.add_layer_control()
except Exception:
    try:
        m.add_layers_control()
    except Exception:
        pass

# Render map
m.to_streamlit(height=600)

# ─────────────────────────────────────────────────────────────────────
# Quick previews (ensure you can SEE the data regardless of tile cache)
# ─────────────────────────────────────────────────────────────────────
with st.expander("Quick previews (NDVI / NDWI / SAR)"):
    cols = st.columns(3)
    if ndvi_img is not None:
        try:
            url = ndvi_img.getThumbURL({"region": AOI, "scale": 10, "min": 0, "_
