import os
import json
import pandas as pd
import requests
import altair as alt
from datetime import datetime, timedelta
from google.oauth2 import service_account

try:
    import streamlit as st
    import leafmap.foliumap as leafmap
    import ee
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(f"Required module missing: {e.name}. Ensure all dependencies are installed, e.g., `pip install streamlit leafmap earthengine-api`.")

st.set_page_config(layout="wide")
st.title("🛰️ Soil Health & Remote Sensing Explorer")

# ✅ Fixed service account loader for Render or local
def load_service_account_info():
    env_key = os.getenv("EE_PRIVATE_KEY")
    if env_key:
        try:
            # Properly convert escaped newlines to actual newlines
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
            raise FileNotFoundError("No EE_PRIVATE_KEY found in env and no local JSON key file found.")

# ✅ Earth Engine Auth
try:
    service_account_info = load_service_account_info()
    credentials = service_account.Credentials.from_service_account_info(service_account_info)
    ee.Initialize(credentials)
except Exception as e:
    st.error(f"Earth Engine initialization error: {e}")
    st.stop()

# Dates
today = datetime.utcnow().date()
start_10 = today - timedelta(days=10)
start_30 = today - timedelta(days=30)

# Interactive map
m = leafmap.Map(draw_control=True, measure_control=True)
if "clicked" not in st.session_state:
    st.session_state.clicked = None
if "aoi" not in st.session_state:
    st.session_state.aoi = None

# Map overlays
try:
    ndvi_img = ee.ImageCollection("COPERNICUS/S2").filterDate(str(start_10), str(today)).median()
    ndvi = ndvi_img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndvi_vis = {"min": 0.0, "max": 1.0, "palette": ["white", "green"]}
    m.addLayer(ndvi, ndvi_vis, "NDVI Layer")

    ndwi = ndvi_img.normalizedDifference(["B3", "B11"]).rename("NDWI")
    ndwi_vis = {"min": -1.0, "max": 1.0, "palette": ["brown", "blue"]}
    m.addLayer(ndwi, ndwi_vis, "NDWI Soil Moisture")

    sar_img = ee.ImageCollection("COPERNICUS/S1_GRD").filterDate(str(start_10), str(today)) \
        .filter(ee.Filter.eq("instrumentMode", "IW")) \
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
        .select("VV").mean()
    sar_vis = {"min": -25, "max": 0, "palette": ["blue", "white"]}
    m.addLayer(sar_img, sar_vis, "SAR VV Layer")
except Exception as e:
    st.warning(f"Could not load map overlays: {e}")

# AOI polygon analysis
@st.cache_data(show_spinner=False)
def extract_polygon_data(geom):
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
        stats = composite.reduceRegion(reducer=ee.Reducer.mean(), geometry=point, scale=10, bestEffort=True).getInfo()

        if "SAR_stdDev" in stats:
            value = stats["SAR_stdDev"]
            stats["Compaction Index"] = round(min(max((value - 0.5) / 1.5, 0), 1), 3)

        latlon = point.centroid().coordinates().getInfo()[::-1]
        ssurgo_resp = requests.get(f"https://rest.soilgrids.org/query?lon={latlon[1]}&lat={latlon[0]}")
        if ssurgo_resp.status_code == 200:
            sdata = ssurgo_resp.json()
            clay = sdata['properties']['CLYPPT']['mean']
            silt = sdata['properties']['SLTPPT']['mean']
            stats["Clay %"] = round(clay, 1)
            stats["Silt %"] = round(silt, 1)
        else:
            stats["Clay %"] = "Unavailable"
            stats["Silt %"] = "Unavailable"

        return stats
    except Exception as e:
        st.error(f"AOI extraction error: {e}")
        return {}

# Point time series analysis
def get_point_time_series(lat, lon):
    try:
        geom = ee.Geometry.Point([lon, lat])
        ndvi_series = ee.ImageCollection("COPERNICUS/S2") \
            .filterDate(str(start_30), str(today)) \
            .filterBounds(geom) \
            .map(lambda img: img.set("date", img.date().format("YYYY-MM-dd"))) \
            .map(lambda img: img.normalizedDifference(["B8", "B4"]).rename("NDVI").copyProperties(img, ["date"]))

        ndwi_series = ee.ImageCollection("COPERNICUS/S2") \
            .filterDate(str(start_30), str(today)) \
            .filterBounds(geom) \
            .map(lambda img: img.set("date", img.date().format("YYYY-MM-dd"))) \
            .map(lambda img: img.normalizedDifference(["B3", "B11"]).rename("NDWI").copyProperties(img, ["date"]))

        sar_series = ee.ImageCollection("COPERNICUS/S1_GRD") \
            .filterDate(str(start_30), str(today)) \
            .filterBounds(geom) \
            .filter(ee.Filter.eq("instrumentMode", "IW")) \
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
            .select("VV") \
            .map(lambda img: img.set("date", img.date().format("YYYY-MM-dd")))

        def extract_series(imgcol, band):
            values = imgcol.map(lambda img: ee.Feature(None, {
                "date": img.get("date"),
                band: img.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=geom,
                    scale=10,
                    bestEffort=True
                ).get(band)
            }))
            return values.aggregate_array("date"), values.aggregate_array(band)

        dates, ndvi_vals = extract_series(ndvi_series, "NDVI")
        _, ndwi_vals = extract_series(ndwi_series, "NDWI")
        _, sar_vals = extract_series(sar_series, "VV")

        return pd.DataFrame({
            "Date": dates.getInfo(),
            "NDVI": ndvi_vals.getInfo(),
            "NDWI": ndwi_vals.getInfo(),
            "SAR_VV": sar_vals.getInfo()
        })
    except Exception as e:
        st.warning(f"Time series extraction failed: {e}")
        return pd.DataFrame()

# Hook up map interactions
m.on_click(lambda **kwargs: st.session_state.update({"clicked": kwargs.get("latlng")}))
m.on_draw(lambda action, geo_json: st.session_state.update({"aoi": geo_json}))

# Map display
st.subheader("🌍 Interactive Map")
with st.spinner("Loading map..."):
    m.to_streamlit(height=600)

# AOI analysis output
if st.session_state.aoi:
    with st.spinner("Analyzing AOI..."):
        data = extract_polygon_data(st.session_state.aoi)
        if data:
            st.success("AOI analysis complete")
            st.write(data)
            df = pd.DataFrame([data])
            st.download_button("📥 Download AOI CSV", df.to_csv(index=False), file_name="aoi_analysis.csv")

# Point time series output
if st.session_state.clicked:
    lat, lon = st.session_state.clicked['lat'], st.session_state.clicked['lng']
    with st.spinner("Loading time series..."):
        ts_df = get_point_time_series(lat, lon)
        if not ts_df.empty:
            st.subheader("📈 NDVI, NDWI and SAR Time Series")
            chart = alt.Chart(ts_df).transform_fold(["NDVI", "NDWI", "SAR_VV"]).mark_line().encode(
                x="Date:T", y="value:Q", color="key:N"
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No time series data found at this location.")

# Sidebar display
st.sidebar.markdown("---")
st.sidebar.subheader("🧱 Compaction Index")
st.sidebar.caption("0 = loose, 1 = highly compacted")
st.sidebar.caption("Derived from SAR VV variability")
