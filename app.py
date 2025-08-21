import os
import sys
import json
import math
from datetime import date, timedelta, datetime, timezone

import streamlit as st
import altair as alt
import pandas as pd

# ---------------------------------------------------------------------
# MUST be the first Streamlit command
# ---------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="🌱 Soil & Crop Scout")

st.caption(f"Python runtime: {sys.version}")
st.title("🛰️ Soil & Crop Scout")
st.caption("Toggles: NDVI • NDWI • SAR • Water • Fallow (CDL) • CA Crops (CDL) • Soil Texture | AOI stats, time-series, export, and AI helper.")

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

    # If wrapped in a single pair of quotes, strip once
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()

    # Must be full JSON, not just the PEM block
    if not key.lstrip().startswith("{"):
        st.error("EE_PRIVATE_KEY does not start with '{'. Paste the ENTIRE service-account JSON (IAM → Service Accounts → Keys).")
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
    st.caption("A square AOI is built around the center using the area above.")

    st.markdown("---")
    st.header("CDL Crop Codes (optional)")
    cdl_codes_text = st.text_input(
        "Comma-separated CDL codes (e.g., 36,52,3,59,57)",
        value="36,52,3,59,57"  # Alfalfa, Grapes, Rice, Other Tree Nuts, Citrus
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
        year = end_date.year
        cdl_img = (ee.ImageCollection("USDA/NASS/CDL")
                   .filterDate(f"{year}-01-01", f"{year}-12-31")
                   .first()
                   .select("cropland")
                   .clip(aoi))
        if show_fallow:
            # CDL class 61 = Fallow/Idle Cropland
            fallow = cdl_img.eq(61).selfMask()
            m.add_ee_layer(fallow, {"palette": ["#ff8800"]}, f"Fallow (CDL {year})")

        if show_cdl:
            try:
                codes = [int(v.strip()) for v in cdl_codes_text.split(",") if v.strip()]
            except Exception:
                codes = []
            colors = ["#ff0000","#00ff00","#0000ff","#ffff00","#ff00ff","#00ffff","#ff8800","#8800ff","#00ff88","#888888"]
            for i, code in enumerate(codes[:10]):  # cap to 10 layers for perf
                mask = cdl_img.eq(code).selfMask()
                m.add_ee_layer(mask, {"palette": [colors[i % len(colors)]]}, f"CDL code {code} ({year})")
    except Exception as e:
        st.warning(f"CDL layer failed: {e}")

# -------------------- Soil Texture (USDA 12-class) --------------------
if show_soil_texture:
    try:
        tex = ee.Image("OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-12A1C_M/v02").select("b0").clip(aoi)
        # 12-class palette (single line to prevent wrapping issues)
        palette12 = ["#fef0d9","#fdcc8a","#fc8d59","#e34a33","#b30000","#31a354","#2b8cbe","#a6bddb","#1c9099","#c7e9b4","#7fcdbb","#df65b0"]
        m.add_ee_layer(tex, {"min": 1, "max": 12, "palette": palette12}, "Soil Texture (USDA 12)")
    except Exception as e:
        st.warning(f"Soil texture layer failed: {e}")

# Render map
m.to_streamlit(height=600)

# ---------------------------------------------------------------------
# Stats, time-series, export
# ---------------------------------------------------------------------
def reduce_stats(image, geom, scale=10):
    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
    )
    vals = image.reduceRegion(reducer=reducer, geometry=geom, scale=scale, bestEffort=True, maxPixels=1e9)
    return vals

@st.cache_data(show_spinner=False)
def compute_ndvi_timeseries(aoi_geom, start_str, end_str, cloud_max, limit_n):
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
    df = df.sort_values("date")
    return df

c1, c2 = st.columns([1, 1])

with c1:
    st.subheader("AOI Summary")
    if ndvi is None:
        st.info("Turn on NDVI to compute stats and export.")
    else:
        if compute_btn:
            try:
                vals_dict = reduce_stats(ndvi, aoi, scale=10).getInfo()
            except Exception as e:
                st.error(f"Stats failed: {e}")
                vals_dict = None

            water_pct = None
            if show_water and (ndwi is not None):
                try:
                    water = ndwi.gt(0.2)
                    area_img = ee.Image.pixelArea()
                    water_area_dict = area_img.updateMask(water).reduceRegion(ee.Reducer.sum(), aoi, 10, bestEffort=True).getInfo()
                    aoi_area_dict = area_img.reduceRegion(ee.Reducer.sum(), aoi, 10, bestEffort=True).getInfo()
                    w = (water_area_dict or {}).get("area")
                    a = (aoi_area_dict or {}).get("area")
                    if w and a and a > 0:
                        water_pct = round(100.0 * float(w) / float(a), 2)
                except Exception:
                    water_pct = None

            rows = []
            if vals_dict:
                rows.append(["Mean NDVI", round(float(vals_dict.get("NDVI_mean", float("nan"))), 3)])
                rows.append(["StdDev NDVI", round(float(vals_dict.get("NDVI_stdDev", float("nan"))), 3)])
                rows.append(["P10 NDVI", round(float(vals_dict.get("NDVI_p10", float("nan"))), 3)])
                rows.append(["Median NDVI", round(float(vals_dict.get("NDVI_p50", float("nan"))), 3)])
                rows.append(["P90 NDVI", round(float(vals_dict.get("NDVI_p90", float("nan"))), 3)])
            rows.append(["AOI Area (ha)", round(area_m2 / 10000.0, 2)])
            if water_pct is not None:
                rows.append(["Water % (NDWI>0.2)", water_pct])

            st.table(pd.DataFrame(rows, columns=["Metric", "Value"]))

        st.markdown("### Export")
        if st.button("Generate NDVI GeoTIFF download URL"):
            try:
                ndvi_scaled = ndvi.toFloat().multiply(10000).toInt16()
                url = ndvi_scaled.getDownloadURL({"scale": 10, "region": aoi, "crs": "EPSG:4326", "format": "GEO_TIFF"})
                st.success("NDVI GeoTIFF URL ready:")
                st.write(f"[Download NDVI (GeoTIFF)]({url})")
            except Exception as e:
                st.error(f"Export URL failed: {e}")

with c2:
    st.subheader("NDVI Time-Series")
    if st.button("Build NDVI time-series"):
        try:
            df = compute_ndvi_timeseries(aoi, str(start_date), str(end_date), cloud_thresh, max_imgs)
            if df.empty:
                st.info("No valid NDVI samples found. Try widening the date range or lowering the cloud filter.")
            else:
                st.dataframe(df, use_container_width=True, hide_index=True)
                chart = alt.Chart(df).mark_line().encode(
                    x=alt.X("date:T", title="Date"),
                    y=alt.Y("ndvi:Q", title="NDVI", scale=alt.Scale(domain=[0, 1])),
                    tooltip=["date:T", alt.Tooltip("ndvi:Q", format=".3f")]
                ).properties(height=220)
                st.altair_chart(chart, use_container_width=True)

                # Data citation under the chart
                try:
                    latest_scene = df["date"].max().strftime("%Y-%m-%d")
                except Exception:
                    latest_scene = "n/a"
                pulled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                st.caption(
                    f"Data pulled: {pulled_on} • Latest NDVI scene: {latest_scene} • "
                    f"Window: {start_date}→{end_date} • Max images: {max_imgs}"
                )
        except Exception as e:
            st.error(f"Time-series failed: {e}")

# ---------------------------------------------------------------------
# Sidebar AI assistant (optional)
# ---------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.header("🤖 AI Assistant")
assistant_ready = bool(os.getenv("OPENAI_API_KEY", "").strip())
user_q = st.sidebar.text_area("Ask about your data, agronomy, or remote sensing…", height=100)
if st.sidebar.button("Ask"):
    if not assistant_ready:
        st.sidebar.error("Set OPENAI_API_KEY in Render → Environment to enable the assistant.")
    elif not user_q.strip():
        st.sidebar.info("Type a question first.")
    else:
        try:
            from openai import OpenAI
            client = OpenAI()
            context_bits = []
            # Add any computed context we already have
            try:
                if 'vals_dict' in locals() and isinstance(vals_dict, dict) and vals_dict:
                    context_bits.append(
                        f"NDVI stats: mean={vals_dict.get('NDVI_mean')}, p50={vals_dict.get('NDVI_p50')}, p90={vals_dict.get('NDVI_p90')}"
                    )
            except Exception:
                pass
            # You can add more context here if desired
            context = "; ".join(context_bits) if context_bits else "No computed context yet."

            prompt = (
                f"You are an agronomy & remote sensing assistant.\n"
                f"AOI center=({lat},{lon}) size_ha={size_ha}. Date window {start_date}..{end_date}.\n"
                f"Context: {context}\n"
                f"Question: {user_q}\n"
                f"Keep answers concise and actionable for a grower/advisor in California."
            )
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful agronomy and remote sensing expert."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=600,
            )
            st.sidebar.success(resp.choices[0].message.content.strip())
        except Exception as e:
            st.sidebar.error(f"Assistant error: {e}")

# Footer
st.markdown(
    "<div style='opacity:.75;font-size:0.9rem;margin-top:1rem'>"
    "Overlays: NDVI/NDWI/SAR, Water (NDWI>0.2), Fallow (CDL), user-specified CDL crop codes, Soil Texture (USDA 12). "
    "Use the map layer control to toggle visibility. "
    "Tip: adjust AOI center/size to fit your field boundary."
    "</div>",
    unsafe_allow_html=True,
)
