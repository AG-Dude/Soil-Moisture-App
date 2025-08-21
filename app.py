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
st.caption("NDVI • NDWI • Water • SAR • Soil Texture & Boundaries • Erosion Risk | AOI-aware stats + time-series")
st.caption(f"Python runtime: {sys.version}")

# ─────────────────────────────────────────────────────────────────────
# Earth Engine init (service account JSON in EE_PRIVATE_KEY)
# ─────────────────────────────────────────────────────────────────────
def ee_init():
    try:
        import ee
    except Exception as e:
        st.error(f"Earth Engine package not available: {e}. Ensure 'earthengine-api' is pinned in requirements.txt.")
        st.stop()

    key = os.getenv("EE_PRIVATE_KEY", "").strip()
    if not key:
        st.error("EE_PRIVATE_KEY is missing/empty. Add FULL service-account JSON in Render → Environment.")
        st.stop()

    # remove accidental wrapping quotes
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
# Leafmap (folium backend) + robust EE layer add
# ─────────────────────────────────────────────────────────────────────
try:
    import leafmap.foliumap as leafmap
except Exception as e:
    st.error(f"Leafmap import failed: {e}. Pin leafmap==0.50.0.")
    st.stop()

def add_ee_image(m, image, vis, name):
    """Add an EE image to the map regardless of leafmap version."""
    try:
        m.add_ee_layer(image, vis, name)
        return
    except Exception:
        pass
    try:
        tile = leafmap.ee_tile_layer(image, vis, name)
        try:
            m.add_layer(tile)
        except Exception:
            m.add_child(tile)
    except Exception as e:
        st.warning(f"Failed to add '{name}': {e}")

def safe_to_streamlit(m, height=600):
    """Render the map but swallow the StopException that can occur on rerun."""
    try:
        ret = m.to_streamlit(height=height)
        return ret if ret is not None else {}
    except Exception as e:
        # Streamlit uses StopException to abort on rerun. Leafmap re-raises it as Exception.
        if "StopException" in repr(e) or "StopException" in str(e):
            st.stop()
        # one retry (sometimes first render gets interrupted)
        try:
            ret = m.to_streamlit(height=height)
            return ret if ret is not None else {}
        except Exception as e2:
            if "StopException" in repr(e2) or "StopException" in str(e2):
                st.stop()
            st.error(f"Map render failed: {e2}")
            return {}

# ─────────────────────────────────────────────────────────────────────
# Session state defaults
# ─────────────────────────────────────────────────────────────────────
def default_center():
    return (37.60, -120.90)  # Central Valley-ish

def default_aoi_box(center_lat, center_lon, half_m=400):
    lat_deg = half_m / 110540.0
    lon_deg = half_m / (111320.0 * max(0.0001, math.cos(math.radians(center_lat))))
    coords = [
        [center_lon - lon_deg, center_lat - lat_deg],
        [center_lon - lon_deg, center_lat + lat_deg],
        [center_lon + lon_deg, center_lat + lat_deg],
        [center_lon + lon_deg, center_lat - lat_deg],
        [center_lon - lon_deg, center_lat - lat_deg],
    ]
    return {"type": "Polygon", "coordinates": [coords]}

if "center" not in st.session_state:
    st.session_state["center"] = default_center()
if "aoi_geojson" not in st.session_state:
    clat, clon = st.session_state["center"]
    st.session_state["aoi_geojson"] = default_aoi_box(clat, clon, half_m=400)

# ─────────────────────────────────────────────────────────────────────
# Address search + AOI box selection
# ─────────────────────────────────────────────────────────────────────
st.subheader("Find a place & create AOI box")
c1, c2, c3 = st.columns([4, 2, 1])
with c1:
    address = st.text_input("Search address or place", placeholder="e.g., 123 Farm Rd, Merced, CA")
with c2:
    box_m = st.slider("AOI box half-size (meters)", 100, 2000, 400, 50)
with c3:
    go = st.button("🔎 Find & Set AOI", use_container_width=True)

if go and address.strip():
    try:
        latlon = leafmap.geocode(address)  # returns (lat, lon)
        if isinstance(latlon, (list, tuple)) and len(latlon) == 2:
            clat, clon = float(latlon[0]), float(latlon[1])
            st.session_state["center"] = (clat, clon)
            st.session_state["aoi_geojson"] = default_aoi_box(clat, clon, half_m=box_m)
            st.success(f"AOI set at {round(clat,6)}, {round(clon,6)} with half-size {box_m} m.")
            st.experimental_rerun()
        else:
            st.error("Could not geocode that address.")
    except Exception as e:
        st.error(f"Geocoding failed: {e}")

# ─────────────────────────────────────────────────────────────────────
# Sidebar controls (date + overlays)
# ─────────────────────────────────────────────────────────────────────
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
    show_soil_texture = st.checkbox("Soil texture (USDA 12-class)", False)
    show_soil_boundaries = st.checkbox("Soil boundaries (approx.)", False)
    show_erosion = st.checkbox("Erosion risk (relative)", False)

    if st.button("Reset AOI to center box"):
        clat, clon = st.session_state["center"]
        st.session_state["aoi_geojson"] = default_aoi_box(clat, clon, half_m=box_m if "box_m" in locals() else 400)
        st.experimental_rerun()

# ─────────────────────────────────────────────────────────────────────
# EE helpers
# ─────────────────────────────────────────────────────────────────────
def ee_aoi():
    import ee
    return ee.Geometry(st.session_state["aoi_geojson"])

def s2_collection(aoi_geom, start_str, end_str, cloud_max):
    import ee
    return (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterDate(start_str, end_str)
            .filterBounds(aoi_geom)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", int(cloud_max))))

def s2_median(aoi_geom, start_str, end_str, cloud_max):
    return s2_collection(aoi_geom, start_str, end_str, cloud_max).median().clip(aoi_geom)

def s1_collection(aoi_geom, start_str, end_str):
    import ee
    return (ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterDate(start_str, end_str)
            .filterBounds(aoi_geom)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")))

def s1_mean_vv(aoi_geom, start_str, end_str):
    return s1_collection(aoi_geom, start_str, end_str).mean().clip(aoi_geom).select("VV")

def soil_texture_12(aoi_geom):
    import ee
    return ee.Image("OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-12A1C_M/v02").select("b0").clip(aoi_geom)

def soil_texture_edges(tex_img):
    return tex_img.focal_min(1).neq(tex_img).selfMask()

def reduce_stats(image, geom, scale=10):
    import ee
    reducer = (ee.Reducer.mean()
               .combine(ee.Reducer.stdDev(), sharedInputs=True)
               .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True))
    return image.reduceRegion(reducer=reducer, geometry=geom, scale=scale, bestEffort=True, maxPixels=1e9)

def compute_water_pct(ndwi_img, geom, thresh=0.2, scale=10):
    import ee
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

def erosion_risk_layer(aoi_geom, ndvi_img):
    """Relative erosion risk ~ S (slope) * K (soil erodibility) * C (cover from NDVI), normalized 0–1."""
    import ee
    dem = ee.Image("USGS/SRTMGL1_003").clip(aoi_geom)
    slope_deg = ee.Terrain.slope(dem)
    theta = slope_deg.multiply(math.pi / 180.0).sin()
    s_low = theta.multiply(10.8).add(0.03)
    s_high = theta.multiply(16.8).subtract(0.50)
    S = s_low.where(slope_deg.gte(ee.Image.constant(5.14)), s_high).rename("S").max(0)

    tex = soil_texture_12(aoi_geom)
    k_values = [0.28,0.20,0.15,0.32,0.38,0.40,0.25,0.22,0.26,0.17,0.20,0.15]
    K = tex.remap(list(range(1,13)), k_values).rename("K")

    ndvi_clamped = ndvi_img.where(ndvi_img.lt(0), 0).where(ndvi_img.gt(1), 1)
    C = ee.Image(1).subtract(ndvi_clamped).rename("C")

    risk = S.multiply(K).multiply(C).rename("risk")
    p95 = ee.Number(risk.reduceRegion(ee.Reducer.percentile([95]), aoi_geom, 30, bestEffort=True).get("risk"))
    return risk.divide(p95.max(ee.Number(1e-6))).clamp(0, 1).rename("risk")

# ─────────────────────────────────────────────────────────────────────
# Map + layers
# ─────────────────────────────────────────────────────────────────────
def build_map_and_layers():
    AOI = ee_aoi()
    clat, clon = st.session_state["center"]
    m = leafmap.Map(center=[clat, clon], zoom=14)
    m.add_basemap("HYBRID")

    # Rectangle drawing (simple AOI edit)
    try:
        m.add_draw_control(
            draw_marker=False, draw_circle=False, draw_circlemarker=False,
            draw_polyline=False, draw_rectangle=True, draw_polygon=False, edit=True, remove=True
        )
    except Exception:
        pass

    # AOI outline
    try:
        import ee
        aoi_outline = ee.Image().byte().paint(AOI, 1, 2).visualize(palette=["#00FFFF"])
        add_ee_image(m, aoi_outline, {}, "AOI outline")
    except Exception:
        pass

    # Scene counts
    try:
        s2_count = int(s2_collection(AOI, str(start_date), str(end_date), cloud_thresh).size().getInfo())
    except Exception:
        s2_count = 0
    try:
        s1_count = int(s1_collection(AOI, str(start_date), str(end_date)).size().getInfo())
    except Exception:
        s1_count = 0

    # Sentinel-2 composite (median)
    s2_img = None
    if s2_count > 0:
        try:
            s2_img = s2_median(AOI, str(start_date), str(end_date), cloud_thresh)
        except Exception as e:
            st.warning(f"S2 retrieval failed: {e}")

    # Overlays
    ndvi_img = None
    ndwi_img = None
    sar_vv_img = None
    risk_img = None

    if s2_img is not None and show_ndvi:
        try:
            ndvi_img = s2_img.normalizedDifference(["B8", "B4"]).rename("NDVI")
            add_ee_image(m, ndvi_img, {"min": 0, "max": 1,
                                       "palette": ["#8b4513","#ffff00","#00ff00"], "opacity": 0.8},
                         f"NDVI {start_date}→{end_date}")
        except Exception as e:
            st.warning(f"NDVI layer failed: {e}")

    if s2_img is not None and (show_ndwi or show_water):
        try:
            ndwi_img = s2_img.normalizedDifference(["B3", "B8"]).rename("NDWI")
            if show_ndwi:
                add_ee_image(m, ndwi_img, {"min": -1, "max": 1,
                                           "palette": ["#654321","#ffffff","#00bfff"], "opacity": 0.7},
                             f"NDWI {start_date}→{end_date}")
            if show_water:
                water = ndwi_img.gt(0.2).selfMask()
                add_ee_image(m, water, {"palette": ["#00aaff"], "opacity": 0.9}, "Water mask (NDWI>0.2)")
        except Exception as e:
            st.warning(f"NDWI/Water layer failed: {e}")

    if show_sar_vv and s1_count > 0:
        try:
            sar_vv_img = s1_mean_vv(AOI, str(start_date), str(end_date))
            add_ee_image(m, sar_vv_img, {"min": -20, "max": -2, "opacity": 0.75},
                         f"SAR VV {start_date}→{end_date}")
        except Exception as e:
            st.warning(f"SAR VV failed: {e}")

    if show_soil_texture or show_soil_boundaries:
        try:
            tex = soil_texture_12(AOI)
            if show_soil_texture:
                palette12 = ["#fef0d9","#fdcc8a","#fc8d59","#e34a33","#b30000",
                             "#31a354","#2b8cbe","#a6bddb","#1c9099","#c7e9b4",
                             "#7fcdbb","#df65b0"]
                add_ee_image(m, tex, {"min": 1, "max": 12, "palette": palette12, "opacity": 0.7},
                             "Soil texture (USDA 12)")
            if show_soil_boundaries:
                edges = soil_texture_edges(tex)
                add_ee_image(m, edges, {"palette": ["#ff00ff"], "opacity": 0.9}, "Soil boundaries")
        except Exception as e:
            st.warning(f"Soil layers failed: {e}")

    if show_erosion and (ndvi_img is not None):
        try:
            risk_img = erosion_risk_layer(AOI, ndvi_img)
            vis = {"min": 0, "max": 1, "palette": ["#ffffb2","#fecc5c","#fd8d3c","#f03b20","#bd0026"], "opacity": 0.85}
            add_ee_image(m, risk_img, vis, "Erosion risk (relative)")
        except Exception as e:
            st.warning(f"Erosion risk failed: {e}")

    # Layer control
    try:
        m.add_layer_control()
    except Exception:
        try:
            m.add_layers_control()
        except Exception:
            pass

    # Render map (safe) & compute status
    draw_ret = safe_to_streamlit(m, height=600)

    # Status bar
    try:
        import ee
        AOI_area_m2 = ee.Image.pixelArea().reduceRegion(ee.Reducer.sum(), AOI, 10, bestEffort=True).getInfo().get("area", 0)
        AOI_area_ha = round(float(AOI_area_m2) / 10000.0, 2)
    except Exception:
        AOI_area_ha = None
    l, r = st.columns(2)
    l.success(f"AOI area: {AOI_area_ha} ha" if AOI_area_ha is not None else "AOI area: n/a")
    r.info(f"🛰️ S2 scenes: {s2_count} • 📡 S1 scenes: {s1_count}")

    return draw_ret, AOI, ndvi_img, ndwi_img, sar_vv_img, risk_img

# ─────────────────────────────────────────────────────────────────────
# Read draw return (works across streamlit-folium versions)
# ─────────────────────────────────────────────────────────────────────
def parse_draw_geojson(draw_ret):
    if not isinstance(draw_ret, dict):
        return None
    for key in ("last_active_drawing", "last_drawing"):
        obj = draw_ret.get(key)
        if obj and isinstance(obj, dict):
            geom = obj.get("geometry") or obj
            if isinstance(geom, dict):
                if geom.get("type") == "Feature" and "geometry" in geom:
                    geom = geom["geometry"]
                return geom
    all_draw = draw_ret.get("all_drawings")
    if isinstance(all_draw, list) and len(all_draw) > 0:
        cand = all_draw[-1]
        if isinstance(cand, dict):
            g = cand.get("geometry") or cand
            if isinstance(g, dict):
                if g.get("type") == "Feature" and "geometry" in g:
                    g = g["geometry"]
                return g
    return None

def geojson_equal(a, b):
    try:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────────────
# Build → render → capture draw → rerun if AOI changed
# ─────────────────────────────────────────────────────────────────────
draw_ret, AOI, ndvi_img, ndwi_img, sar_vv_img, risk_img = build_map_and_layers()

new_geom = parse_draw_geojson(draw_ret)
if new_geom and not geojson_equal(new_geom, st.session_state["aoi_geojson"]):
    st.session_state["aoi_geojson"] = new_geom
    # Recenter to AOI centroid
    try:
        import ee
        cen = ee.Geometry(new_geom).centroid(1).coordinates().getInfo()
        st.session_state["center"] = (float(cen[1]), float(cen[0]))
    except Exception:
        pass
    st.experimental_rerun()

# ─────────────────────────────────────────────────────────────────────
# Quick previews (prove data exists even if map tiles look cached)
# ─────────────────────────────────────────────────────────────────────
with st.expander("Quick previews (NDVI / NDWI / SAR)"):
    cols = st.columns(3)
    if ndvi_img is not None:
        try:
            url = ndvi_img.getThumbURL({"region": AOI, "scale": 10, "min": 0, "max": 1,
                                        "palette": ["#8b4513","#ffff00","#00ff00"]})
            cols[0].image(url, caption="NDVI preview", use_column_width=True)
        except Exception:
            pass
    if ndwi_img is not None:
        try:
            url = ndwi_img.getThumbURL({"region": AOI, "scale": 10, "min": -1, "max": 1,
                                        "palette": ["#654321","#ffffff","#00bfff"]})
            cols[1].image(url, caption="NDWI preview", use_column_width=True)
        except Exception:
            pass
    if sar_vv_img is not None:
        try:
            url = sar_vv_img.getThumbURL({"region": AOI, "scale": 20, "min": -20, "max": -2})
            cols[2].image(url, caption="SAR VV preview", use_column_width=True)
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────────
# AOI Summary (NDVI stats, water %, erosion rating)
# ─────────────────────────────────────────────────────────────────────
st.subheader("AOI summary")
rows = []

if ndvi_img is not None:
    try:
        vals = reduce_stats(ndvi_img, AOI, scale=10).getInfo()
    except Exception:
        vals = None
    if vals:
        rows.extend([
            ["Mean NDVI", round(float(vals.get("NDVI_mean", float("nan"))), 3)],
            ["StdDev NDVI", round(float(vals.get("NDVI_stdDev", float("nan"))), 3)],
            ["P10 NDVI", round(float(vals.get("NDVI_p10", float("nan"))), 3)],
            ["Median NDVI", round(float(vals.get("NDVI_p50", float("nan"))), 3)],
            ["P90 NDVI", round(float(vals.get("NDVI_p90", float("nan"))), 3)],
        ])

if ndwi_img is not None and show_water:
    wp = compute_water_pct(ndwi_img, AOI, thresh=0.2, scale=10)
    if wp is not None:
        rows.append(["Water % (NDWI>0.2)", wp])

if risk_img is not None:
    try:
        import ee
        mean_risk = risk_img.reduceRegion(ee.Reducer.mean(), AOI, 30, bestEffort=True).getInfo().get("risk", None)
        if mean_risk is not None:
            rating = "Low"
            if mean_risk >= 0.66:
                rating = "High"
            elif mean_risk >= 0.33:
                rating = "Moderate"
            rows.append(["Erosion risk (0–1)", round(float(mean_risk), 2)])
            rows.append(["Erosion rating", rating])
    except Exception:
        pass

if rows:
    st.table(pd.DataFrame(rows, columns=["Metric", "Value"]))
else:
    st.info("Turn on NDVI/NDWI and set an AOI to see summary metrics.")

# ─────────────────────────────────────────────────────────────────────
# NDVI time-series + citation  (CACHE FIX: underscore param)
# ─────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def compute_ndvi_timeseries(_aoi_geom, start_str, end_str, cloud_max, limit_n=20):
    import ee
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
          .filterDate(start_str, end_str)
          .filterBounds(_aoi_geom)
          .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", int(cloud_max)))
          .sort("system:time_start")
          .limit(int(limit_n)))
    def per_img(img):
        nd = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
        mean = nd.reduceRegion(ee.Reducer.mean(), _aoi_geom, 10, bestEffort=True)
        return ee.Feature(None, {"date": img.date().format("YYYY-MM-dd"), "ndvi": mean.get("NDVI")})
    fc = ee.FeatureCollection(s2.map(per_img))
    feats = fc.getInfo().get("features", [])
    rows = [{"date": f["properties"]["date"], "ndvi": f["properties"]["ndvi"]}
            for f in feats if f.get("properties", {}).get("ndvi") is not None]
    df = pd.DataFrame(rows)
    if len(df) == 0:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")

st.subheader("NDVI time-series")
try:
    ts_df = compute_ndvi_timeseries(AOI, str(start_date), str(end_date), cloud_thresh, 20)
    if ts_df.empty:
        st.info("No valid NDVI samples in this window. Try broadening the date range or raising cloud %.")
    else:
        st.dataframe(ts_df, use_container_width=True, hide_index=True)
        chart = alt.Chart(ts_df).mark_line().encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("ndvi:Q", title="NDVI", scale=alt.Scale(domain=[0, 1])),
            tooltip=["date:T", alt.Tooltip("ndvi:Q", format=".3f")]
        ).properties(height=220)
        st.altair_chart(chart, use_container_width=True)

        latest_scene = ts_df["date"].max().strftime("%Y-%m-%d") if not ts_df.empty else "n/a"
        pulled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        st.caption(
            f"Data pulled: {pulled_on} • Latest NDVI scene: {latest_scene} • "
            f"Window: {start_date}→{end_date}"
        )
except Exception as e:
    st.error(f"Time-series failed: {e}")

# ─────────────────────────────────────────────────────────────────────
# Export NDVI
# ─────────────────────────────────────────────────────────────────────
st.markdown("### Export")
if ndvi_img is not None and st.button("Generate NDVI GeoTIFF URL"):
    try:
        ndvi_scaled = ndvi_img.toFloat().multiply(10000).toInt16()
        url = ndvi_scaled.getDownloadURL({"scale": 10, "region": AOI, "crs": "EPSG:4326", "format": "GEO_TIFF"})
        st.success("NDVI GeoTIFF URL ready:")
        st.write(f"[Download NDVI (GeoTIFF)]({url})")
    except Exception as e:
        st.error(f"Export failed: {e}")

# NOTE: AI helper intentionally removed (was causing 'Client.init(...proxies)' errors).
