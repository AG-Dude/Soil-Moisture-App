import os
import json
import pandas as pd
import requests
import altair as alt
from datetime import datetime, timedelta
from google.oauth2 import service_account

try:
    import streamlit as st
    import leafmap.streamlitmap as leafmap  # ✅ switch to streamlitmap for on_click/on_draw
    import ee
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(f"Required module missing: {e.name}. Run: pip install streamlit leafmap earthengine-api")

st.set_page_config(layout="wide")
st.title("🛰️ Soil Health & Remote Sensing Explorer")

debug_mode = st.sidebar.checkbox("🧪 Debug Mode (disable Earth Engine)", value=False)

def load_service_account_info():
    env_key = os.getenv("EE_PRIVATE_KEY")
    if env_key:
        try:
            env_key = env_key.replace("\\n", "\n")
            return json.loads(env_key)
        except Exception as e:
            raise ValueError("EE_PRIVATE_KEY exists but could not be parsed as JSON: " + str(e))
    else:
        local_path = "soil-moisture-app-464506-85ef7849f949.json"
        if os.path.exists(local_path):
            with open(local_path) as f:
                return json.load(f)
        else:
            raise FileNotFoundError("No EE_PRIVATE_KEY found in env and no local key file found.")

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
