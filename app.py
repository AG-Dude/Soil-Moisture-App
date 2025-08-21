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
st.caption("NDVI • NDWI • SAR • Water • Soil Texture • Erosion Risk | AOI-aware stats, time-series, export, AI helper")
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
# Imports that depend on the EE/leafmap ecosystem
# ─────────────────────────────────────────────────────────────────────
try:
    import leafmap.foliumap as leafmap
except Exception as e:
    st.error(f"Leafmap import failed: {e}. Pin leafmap==0.50.0 (or 0.49.3).")
    st.stop()

# ─────────────────────────────────────────────────────────────────────
# Sidebar controls
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
    show_erosion = st.checkbox("Erosion risk (relative)", False)

    st.info("Draw your AOI with the rectangle or polygon tool on the map. The app will auto-update.")

# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
def default_aoi_geojson():
    # ~0.5 km box near Central Valley
    return {
        "type": "Polygon",
        "coordinates": [[
            [-120.903, 37.598],
            [-120.903, 37.602],
            [-120.897, 37.602],
            [-120.897, 37.598],
            [-120.903, 37.598],
        ]]
    }

def geojson_equal(a, b):
    try:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    except Exception:
        return False

def parse_drawn_geojson(draw_ret):
    """Extract a GeoJSON geometry from the draw return dict of m.to_streamlit()."""
    if not isinstance(draw_ret, dict):
        return None
    # streamlit-folium returns these keys; leafmap forwards them
    last = draw_ret.get("last_active_drawing")
    if last and isinstance(last, dict) and "geometry" in last:
        return last["geometry"]
    all_feats = draw_ret.get("all_drawings")
    if all_feats and isinstance(all_feats, list):
        # take the last drawn shape
        try:
            geom = all_feats[-1].get("geometry")
            if geom:
                return geom
        except Exception:
            pass
    return None

# Ensure we have persistent AOI in session
if "aoi_geojson" not in st.session_state:
    st.session_state["aoi_geojson"] = default_aoi_geojson()

# Convenience: EE geometry from session AOI
def ee_geom_from_session():
    return ee.Geometry(st.session_state["aoi_geojson"])

# ─────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────
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

# Erosion risk (relative): S * K * C, normalized to 0–1
def erosion_risk_layer(aoi_geom, ndvi_img):
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

@st.cache_data(show_spinner=False)
def compute_ndvi_timeseries(aoi_geom, start_str, end_str, cloud_max, limit_n=20):
    import ee
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
          .filterDate(start_str, end_str)
          .filterBounds(aoi_geom)
          .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", int(cloud_max)))
          .sort("system:time_start")
          .limit(int(limit_n)))
    def per_img(img):
        nd = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
        mean = nd.reduceRegion(ee.Reducer.mean(), aoi_geom, 10, bestEffort=True)
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

# ─────────────────────────────────────────────────────────────────────
# MAP BUILD (uses AOI from session) → render → capture drawing → rerun if changed
# ─────────────────────────────────────────────────────────────────────
def build_and_render_map():
    AOI = ee_geom_from_session()

    # Build map fresh on each rerun
    m = leafmap.Map(center=[37.60, -120.90], zoom=12)
    m.add_basemap("HYBRID")

    # Draw control so user can create/edit the AOI
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

    # Visual outline of current AOI
    try:
        aoi_outline = ee.Image().byte().paint(AOI, 1, 2).visualize(palette=["#00FFFF"])
        m.add_ee_layer(aoi_outline, {}, "AOI outline")
    except Exception:
        pass

    # Scene counts so user sees whether data exists
    try:
        s2_count = int(s2_collection(AOI, str(start_date), str(end_date), cloud_thresh).size().getInfo())
    except Exception:
        s2_count = 0
    try:
        s1_count = int(s1_collection(AOI, str(start_date), str(end_date)).size().getInfo())
    except Exception:
        s1_count = 0

    # Base composites
    s2_img = None
    if s2_count > 0:
        try:
            s2_img = s2_median(AOI, str(start_date), str(end_date), cloud_thresh)
        except Exception as e:
            st.warning(f"S2 retrieval failed: {e}")

    # Overlays (conditionally added)
    ndvi_img = None
    ndwi_img = None
    sar_vv_img = None

    if s2_img is not None and show_ndvi:
        try:
            ndvi_img = s2_img.normalizedDifference(["B8", "B4"]).rename("NDVI")
            m.add_ee_layer(ndvi_img, {"min": 0, "max": 1, "palette": ["#8b4513","#ffff00","#00ff00"], "opacity": 0.8},
                           f"NDVI {start_date}→{end_date}")
        except Exception as e:
            st.warning(f"NDVI layer failed: {e}")

    if s2_img is not None and (show_ndwi or show_water):
        try:
            ndwi_img = s2_img.normalizedDifference(["B3", "B8"]).rename("NDWI")
            if show_ndwi:
                m.add_ee_layer(ndwi_img, {"min": -1, "max": 1, "palette": ["#654321","#ffffff","#00bfff"], "opacity": 0.7},
                               f"NDWI {start_date}→{end_date}")
            if show_water:
                water = ndwi_img.gt(0.2).selfMask()
                m.add_ee_layer(water, {"palette": ["#00aaff"], "opacity": 0.9}, "Water mask (NDWI>0.2)")
        except Exception as e:
            st.warning(f"NDWI/Water layer failed: {e}")

    if show_sar_vv:
        if s1_count == 0:
            pass  # no SAR scenes
        else:
            try:
                sar_vv_img = s1_mean_vv(AOI, str(start_date), str(end_date))
                m.add_ee_layer(sar_vv_img, {"min": -20, "max": -2, "opacity": 0.75}, f"SAR VV {start_date}→{end_date}")
            except Exception as e:
                st.warning(f"SAR VV failed: {e}")

    if show_soil_texture:
        try:
            tex = soil_texture_12(AOI)
            palette12 = ["#fef0d9","#fdcc8a","#fc8d59","#e34a33","#b30000","#31a354","#2b8cbe","#a6bddb",
                         "#1c9099","#c7e9b4","#7fcdbb","#df65b0"]
            m.add_ee_layer(tex, {"min": 1, "max": 12, "palette": palette12, "opacity": 0.7}, "Soil texture (USDA 12)")
        except Exception as e:
            st.warning(f"Soil texture layer failed: {e}")

    risk_img = None
    if show_erosion and (ndvi_img is not None):
        try:
            risk_img = erosion_risk_layer(AOI, ndvi_img)
            risk_vis = {"min": 0, "max": 1,
                        "palette": ["#ffffb2","#fecc5c","#fd8d3c","#f03b20","#bd0026"], "opacity": 0.85}
            m.add_ee_layer(risk_img, risk_vis, "Erosion risk (relative)")
        except Exception as e:
            st.warning(f"Erosion risk layer failed: {e}")

    # Layer control
    try:
        m.add_layer_control()
    except Exception:
        try:
            m.add_layers_control()
        except Exception:
            pass

    # Render map and capture draw state
    draw_ret = m.to_streamlit(height=600)

    # Status bar (AOI area + scene counts)
    try:
        area_m2 = ee.Image.pixelArea().reduceRegion(ee.Reducer.sum(), AOI, 10, bestEffort=True).getInfo().get("area", 0)
        area_ha = round(float(area_m2) / 10000.0, 2)
    except Exception:
        area_ha = None
    left, right = st.columns(2)
    left.success(f"AOI area: {area_ha} ha" if area_ha is not None else "AOI area: n/a")
    right.info(f"🛰️ S2: {s2_count} • 📡 S1: {s1_count}")

    return draw_ret, AOI, ndvi_img, ndwi_img, risk_img

# Build + render + get draw state
draw_ret, AOI, ndvi_img, ndwi_img, risk_img = build_and_render_map()

# If user drew/edited a polygon, update AOI in session and rerun immediately
new_geom = parse_drawn_geojson(draw_ret)
if new_geom and not geojson_equal(new_geom, st.session_state["aoi_geojson"]):
    st.session_state["aoi_geojson"] = new_geom
    st.rerun()

# ─────────────────────────────────────────────────────────────────────
# Quick previews (prove tiles exist even if browser cached map)
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
    # For SAR preview we’d need the image again; keep map as source of truth.

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
    water_pct = compute_water_pct(ndwi_img, AOI, thresh=0.2, scale=10)
    if water_pct is not None:
        rows.append(["Water % (NDWI>0.2)", water_pct])

if risk_img is not None:
    try:
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
    st.info("Turn on NDVI/NDWI and draw an AOI to see summary metrics.")

# ─────────────────────────────────────────────────────────────────────
# NDVI time-series + citation
# ─────────────────────────────────────────────────────────────────────
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
elif ndvi_img is None:
    st.info("Enable NDVI to export.")

# ─────────────────────────────────────────────────────────────────────
# Sidebar AI helper (optional)
# ─────────────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.header("🤖 AI helper")
assistant_ready = bool(os.getenv("OPENAI_API_KEY", "").strip())
user_q = st.sidebar.text_area("Ask about your field, crops, irrigation, sensors, indices…", height=100)
if st.sidebar.button("Ask"):
    if not assistant_ready:
        st.sidebar.error("Set OPENAI_API_KEY in Render → Environment.")
    elif not user_q.strip():
        st.sidebar.info("Type a question first.")
    else:
        try:
            from openai import OpenAI
            client = OpenAI()
            # Minimal context
            ctx = []
            if ndvi_img is not None:
                try:
                    vals = reduce_stats(ndvi_img, ee_geom_from_session(), scale=10).getInfo()
                    if vals:
                        ctx.append(f"NDVI mean={vals.get('NDVI_mean')}, median={vals.get('NDVI_p50')}")
                except Exception:
                    pass
            prompt = (
                "You are an agronomy & remote sensing assistant for California fields. "
                f"Date window {start_date}..{end_date}. "
                f"Context: {'; '.join(ctx) if ctx else 'no context'} "
                f"Question: {user_q}"
            )
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=600,
            )
            st.sidebar.success(resp.choices[0].message.content.strip())
        except Exception as e:
            st.sidebar.error(f"Assistant error: {e}")
