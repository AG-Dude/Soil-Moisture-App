import os
import json
from datetime import date, timedelta

import streamlit as st
import leafmap.foliumap as leafmap  # ✅ use foliumap, NOT "streamlitmap"
import ee

# ---------- Page ----------
st.set_page_config(layout="wide", page_title="🌱 Soil & Crop Scout")
st.title("🛰️ Soil & Crop Scout")
st.caption("Sentinel-2 NDVI + Sentinel-1 SAR moisture proxy, ready for extension (drone & probes).")

# ---------- Earth Engine init ----------
def init_ee_from_env():
    gee_key = os.getenv("EE_PRIVATE_KEY")
    if not gee_key:
        st.error("EE_PRIVATE_KEY not found. In Render → Environment → add EE_PRIVATE_KEY with your service account JSON.")
        st.stop()

    # Accepts either a pretty-printed JSON (with newlines) or a single-line JSON
    try:
        service_account_info = json.loads(gee_key)
    except json.JSONDecodeError as e:
        st.error(f"EE_PRIVATE_KEY is not valid JSON ({e}). Paste the full service account JSON.")
        st.stop()

    client_email = service_account_info.get("client_email")
    if not client_email:
        st.error("Service account JSON missing 'client_email'. Paste the exact JSON from Google Cloud → IAM → Service Accounts → Keys.")
        st.stop()

    try:
        # ee.ServiceAccountCredentials can take the JSON string directly as key_data
        credentials = ee.ServiceAccountCredentials(client_email, key_data=gee_key)
        ee.Initialize(credentials)
        return True
    except Exception as e:
        st.error(f"Earth Engine init failed: {e}")
        st.stop()

_ = init_ee_from_env()

# ---------- Date widgets ----------
today = date.today()
start_default = today - timedelta(days=30)
st.sidebar.header("Date Range")
start_date = st.sidebar.date_input("Start", start_default)
end_date = st.sidebar.date_input("End", today)
if start_date >= end_date:
    st.sidebar.error("Start must be before End.")
    st.stop()

# ---------- Map ----------
m = leafmap.Map(center=[37.60, -120.90], zoom=10)
m.add_basemap("HYBRID")

# ---------- Sentinel-2 NDVI ----------
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

# ---------- Sentinel-1 SAR (VV) ----------
try:
    s1 = (ee.ImageCollection("COPERNICUS/S1_GRD")
          .filterDate(str(start_date), str(end_date))
          .filter(ee.Filter.eq("instrumentMode", "IW"))
          .filter(ee.Filter.eq("resolution_meters", 10))
          .filter(ee.Filter.eq("orbitProperties_pass", "DESCENDING"))
          .filter(ee.Filter.eq("polarization", "VV"))
          .mean())

    sar_vv_vis = {"min": -20, "max": -2}
    m.addLayer(s1.select("VV"), sar_vv_vis, f"SAR VV {start_date}→{end_date}")
except Exception as e:
    st.warning(f"Sentinel-1 SAR layer failed: {e}")

# ---------- Optional: click help ----------
st.sidebar.write("Tip: use the Layer Control on the map to toggle NDVI / SAR.")
st.sidebar.write("Next: add drone upload + Sentek CSV and AI report generation.")

m.to_streamlit(height=720)
# Earth Engine safe init
ee_initialized = False
if not debug_mode:
    try:
        service_account_info = load_service_account_info()
        credentials = service_account.Credentials.from_service_account_info(service_account_info)
        ee.Initialize(credentials)
        ee_initialized = True
    except Exception as e:
        st.warning(f"⚠️ Earth Engine init failed. Features disabled.\n\nDetails: {e}")
else:
    st.info("🧪 Debug mode: Earth Engine disabled.")

# Time window
today = datetime.utcnow().date()
start_10 = today - timedelta(days=10)
start_30 = today - timedelta(days=30)

# Leafmap with session state
m = leafmap.Map(center=[37.5, -120.8], zoom=6, draw_control=True, measure_control=True)
if "clicked" not in st.session_state:
    st.session_state.clicked = None
if "aoi" not in st.session_state:
    st.session_state.aoi = None

# Map click/draw listeners
m.on_click(lambda **kwargs: st.session_state.update({"clicked": kwargs.get("latlng")}))
m.on_draw(lambda action, geo_json: st.session_state.update({"aoi": geo_json}))

# Add EE overlays
if ee_initialized:
    try:
        ndvi_img = ee.ImageCollection("COPERNICUS/S2").filterDate(str(start_10), str(today)).median()
        ndvi = ndvi_img.normalizedDifference(["B8", "B4"]).rename("NDVI")
        ndvi_vis = {"min": 0.0, "max": 1.0, "palette": ["white", "green"]}
        m.addLayer(ndvi, ndvi_vis, "NDVI Layer")

        ndwi = ndvi_img.normalizedDifference(["B3", "B11"]).rename("NDWI")
        ndwi_vis = {"min": -1.0, "max": 1.0, "palette": ["brown", "blue"]}
        m.addLayer(ndwi, ndwi_vis, "NDWI Layer")

        sar_img = ee.ImageCollection("COPERNICUS/S1_GRD") \
            .filterDate(str(start_10), str(today)) \
            .filter(ee.Filter.eq("instrumentMode", "IW")) \
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
            .select("VV").mean()
        sar_vis = {"min": -25, "max": 0, "palette": ["blue", "white"]}
        m.addLayer(sar_img, sar_vis, "SAR VV Layer")
    except Exception as e:
        st.warning(f"🛰️ Failed to load overlays: {e}")
else:
    st.info("🛰️ NDVI/SAR overlays disabled (Earth Engine inactive)")

# AOI analysis
@st.cache_data(show_spinner=False)
def extract_polygon_data(geom):
    if not ee_initialized:
        return {"Error": "Earth Engine not initialized"}
    try:
        point = ee.Geometry(geom['geometry'])
        img = ee.ImageCollection("COPERNICUS/S2").filterDate(str(start_10), str(today)).median()
        ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
        ndwi = img.normalizedDifference(["B3", "B11"]).rename("NDWI")
        s1 = ee.ImageCollection("COPERNICUS/S1_GRD").filterDate(str(start_10), str(today)) \
            .filter(ee.Filter.eq("instrumentMode", "IW")) \
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
            .select("VV")
        sar_mean = s1.mean().rename("SAR_VV")
        sar_std = s1.reduce(ee.Reducer.stdDev()).rename("SAR_stdDev")

        composite = ndvi.addBands(ndwi).addBands(sar_mean).addBands(sar_std)
        stats = composite.reduceRegion(ee.Reducer.mean(), point, 10, bestEffort=True).getInfo()

        if "SAR_stdDev" in stats:
            stats["Compaction Index"] = round(min(max((stats["SAR_stdDev"] - 0.5) / 1.5, 0), 1), 3)

        latlon = point.centroid().coordinates().getInfo()[::-1]
        ssurgo = requests.get(f"https://rest.soilgrids.org/query?lon={latlon[1]}&lat={latlon[0]}")
        if ssurgo.ok:
            sdata = ssurgo.json()
            stats["Clay %"] = round(sdata['properties']['CLYPPT']['mean'], 1)
            stats["Silt %"] = round(sdata['properties']['SLTPPT']['mean'], 1)
        else:
            stats["Clay %"] = "Unavailable"
            stats["Silt %"] = "Unavailable"

        return stats
    except Exception as e:
        st.error(f"AOI error: {e}")
        return {}

# Time series
def get_point_time_series(lat, lon):
    if not ee_initialized:
        return pd.DataFrame()
    try:
        geom = ee.Geometry.Point([lon, lat])
        def series(col, band):
            col = col.map(lambda img: img.set("date", img.date().format("YYYY-MM-dd")))
            col = col.map(lambda img: img.normalizedDifference(band).rename("val").copyProperties(img, ["date"]))
            val = col.map(lambda img: ee.Feature(None, {
                "date": img.get("date"),
                "val": img.reduceRegion(ee.Reducer.mean(), geom, 10, bestEffort=True).get("val")
            }))
            return val.aggregate_array("date"), val.aggregate_array("val")

        ndvi_d, ndvi_v = series(ee.ImageCollection("COPERNICUS/S2").filterBounds(geom).filterDate(str(start_30), str(today)), ["B8", "B4"])
        ndwi_d, ndwi_v = series(ee.ImageCollection("COPERNICUS/S2").filterBounds(geom).filterDate(str(start_30), str(today)), ["B3", "B11"])
        sar = ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(geom).filterDate(str(start_30), str(today)) \
            .filter(ee.Filter.eq("instrumentMode", "IW")) \
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
            .select("VV") \
            .map(lambda img: img.set("date", img.date().format("YYYY-MM-dd")))

        sar_val = sar.map(lambda img: ee.Feature(None, {
            "date": img.get("date"),
            "val": img.reduceRegion(ee.Reducer.mean(), geom, 10, bestEffort=True).get("VV")
        }))
        sar_d = sar_val.aggregate_array("date")
        sar_v = sar_val.aggregate_array("val")

        return pd.DataFrame({
            "Date": ndvi_d.getInfo(),
            "NDVI": ndvi_v.getInfo(),
            "NDWI": ndwi_v.getInfo(),
            "SAR_VV": sar_v.getInfo()
        })
    except Exception as e:
        st.warning(f"⏱️ Time series error: {e}")
        return pd.DataFrame()

# Map rendering
st.subheader("🌍 Interactive Map")
with st.spinner("Loading map..."):
    m.to_streamlit(height=600)

# AOI results
if st.session_state.aoi and ee_initialized:
    with st.spinner("Analyzing AOI..."):
        data = extract_polygon_data(st.session_state.aoi)
        if data:
            st.success("AOI analysis complete")
            st.write(data)
            df = pd.DataFrame([data])
            st.download_button("📥 Download AOI CSV", df.to_csv(index=False), file_name="aoi_analysis.csv")

elif st.session_state.aoi:
    st.info("AOI selected, but Earth Engine is disabled.")

# Time series results
if st.session_state.clicked and ee_initialized:
    lat, lon = st.session_state.clicked["lat"], st.session_state.clicked["lng"]
    with st.spinner("Loading time series..."):
        ts_df = get_point_time_series(lat, lon)
        if not ts_df.empty:
            st.subheader("📈 NDVI, NDWI, SAR VV Time Series")
            chart = alt.Chart(ts_df).transform_fold(["NDVI", "NDWI", "SAR_VV"]).mark_line().encode(
                x="Date:T", y="value:Q", color="key:N"
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No satellite data at this location.")

elif st.session_state.clicked:
    st.info("Time series requires Earth Engine (currently disabled).")

# Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("🧱 Compaction Index")
st.sidebar.caption("0 = loose, 1 = highly compacted (SAR-based)")
