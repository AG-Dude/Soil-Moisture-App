# --- app.py with Full NDVI/SAR, AOI, Time Series, Field Classification, Fallback AI, Spinner, and Compaction Modeling ---

import os
import json
import pandas as pd
import requests
import altair as alt
from datetime import datetime, timedelta

try:
    import streamlit as st
    import leafmap.foliumap as leafmap
    import ee
    import openai
    from openai.error import RateLimitError, ServiceUnavailableError
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(f"Required module missing: {e.name}. Ensure all dependencies are installed, e.g., `pip install streamlit leafmap earthengine-api openai`.")

st.set_page_config(layout="wide")
st.title("🛰️ Soil Health & Remote Sensing Explorer")

gee_key = os.getenv("EE_PRIVATE_KEY")
if not gee_key:
    st.error("EE_PRIVATE_KEY not found. Set in Render environment variables.")
    st.stop()

try:
    service_account_info = json.loads(gee_key)
    credentials = ee.ServiceAccountCredentials(
        email=service_account_info["client_email"],
        key=service_account_info
    )
    ee.Initialize(credentials)
except Exception as e:
    st.error(f"Earth Engine initialization error: {e}")
    st.stop()

openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key or len(openai.api_key) <= 10:
    st.warning("Invalid or missing OpenAI API key. AI assistant features will be disabled or run in offline mode.")
use_ai = openai.api_key is not None and len(openai.api_key) > 10

today = datetime.utcnow().date()
start_10 = today - timedelta(days=10)
start_30 = today - timedelta(days=30)

m = leafmap.Map(draw_control=True, measure_control=True)
if "clicked" not in st.session_state:
    st.session_state.clicked = None
if "aoi" not in st.session_state:
    st.session_state.aoi = None

@st.cache_data(show_spinner=False)
def extract_polygon_data(geom):
    try:
        point = ee.Geometry(geom['geometry'])
        img = ee.ImageCollection("COPERNICUS/S2").filterDate(str(start_10), str(today)).median()
        ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")

        s1 = ee.ImageCollection("COPERNICUS/S1_GRD").filterDate(str(start_10), str(today)) \
            .filter(ee.Filter.eq("instrumentMode", "IW")) \
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
            .select("VV")
        sar_mean = s1.mean().rename("SAR_VV")
        sar_std = s1.reduce(ee.Reducer.stdDev()).rename("SAR_stdDev")

        composite = ndvi.addBands(sar_mean).addBands(sar_std)
        stats = composite.reduceRegion(reducer=ee.Reducer.mean(), geometry=point, scale=10, bestEffort=True).getInfo()

        if "SAR_stdDev" in stats:
            value = stats["SAR_stdDev"]
            stats["Compaction Index"] = round(min(max((value - 0.5) / 1.5, 0), 1), 3)

        return stats
    except Exception as e:
        st.error(f"AOI extraction error: {e}")
        return {}

m.on_click(lambda **kwargs: st.session_state.update({"clicked": kwargs.get("latlng")}))
m.on_draw(lambda action, geo_json: st.session_state.update({"aoi": geo_json}))

st.subheader("🌍 Interactive Map")
with st.spinner("Loading map..."):
    m.to_streamlit(height=600)

if st.session_state.aoi:
    with st.spinner("Analyzing AOI..."):
        data = extract_polygon_data(st.session_state.aoi)
        if data:
            st.success("AOI analysis complete")
            st.write(data)
            df = pd.DataFrame([data])
            st.download_button("📥 Download AOI CSV", df.to_csv(index=False), file_name="aoi_analysis.csv")

if st.session_state.clicked:
    with st.spinner("Getting satellite + soil data..."):
        lat, lon = st.session_state.clicked
        point = ee.Geometry.Point([lon, lat])

        try:
            ndvi_collection = ee.ImageCollection("COPERNICUS/S2").filterBounds(point).filterDate(str(start_30), str(today))
            ndvi_series = ndvi_collection.map(lambda img: img.set('date', img.date().format()).normalizedDifference(["B8", "B4"]).rename("NDVI"))
            chart_data = ndvi_series.map(lambda img: ee.Feature(None, {"NDVI": img.reduceRegion(ee.Reducer.mean(), point, 10).get("NDVI"), "date": img.get("date")})).flatten().getInfo()
            chart_df = pd.DataFrame([f['properties'] for f in chart_data])
            chart_df['date'] = pd.to_datetime(chart_df['date'])
            st.altair_chart(alt.Chart(chart_df).mark_line().encode(x='date:T', y='NDVI:Q').properties(title="NDVI Time Series"), use_container_width=True)
        except Exception as e:
            st.warning(f"Could not generate NDVI time series: {e}")

        try:
            ndvi_img = ndvi_collection.median()
            ndvi = ndvi_img.normalizedDifference(["B8", "B4"]).reduceRegion(ee.Reducer.mean(), point, 10).getInfo()
        except Exception:
            ndvi = {"nd": None}

        try:
            sar_collection = ee.ImageCollection("COPERNICUS/S1_GRD") \
                .filterBounds(point).filterDate(str(start_10), str(today)) \
                .filter(ee.Filter.eq("instrumentMode", "IW")) \
                .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
                .select("VV")
            sar_mean = sar_collection.mean().reduceRegion(ee.Reducer.mean(), point, 10).getInfo()
            sar_std = sar_collection.reduce(ee.Reducer.stdDev()).reduceRegion(ee.Reducer.mean(), point, 10).getInfo()
        except Exception:
            sar_mean = {"VV": None}
            sar_std = {"VV_stdDev": None}

        try:
            sg_url = f"https://rest.soilgrids.org/query?lon={lon}&lat={lat}"
            resp = requests.get(sg_url)
            resp.raise_for_status()
            sg = resp.json()
            clay = sg['properties']['layers']['clay']['depths'][0]['values']['mean']
            silt = sg['properties']['layers']['silt']['depths'][0]['values']['mean']
            sand = sg['properties']['layers']['sand']['depths'][0]['values']['mean']
        except Exception:
            clay = silt = sand = None

        compaction_index = round(min(max((sar_std.get("VV_stdDev", 0) - 0.5) / 1.5, 0), 1), 3) if sar_std.get("VV_stdDev") else None

        st.write({
            "Latitude": lat, "Longitude": lon,
            "NDVI": ndvi.get("nd"),
            "SAR VV": sar_mean.get("VV"),
            "SAR stddev (Compaction Proxy)": sar_std.get("VV_stdDev"),
            "Compaction Index": compaction_index,
            "Clay %": clay, "Silt %": silt, "Sand %": sand
        })

        st.sidebar.header("💬 Ask the AI")
        q = st.sidebar.text_area("Ask something about this soil data:")

        if st.sidebar.button("Ask") and q.strip():
            prompt = f"Lat: {lat}, Lon: {lon}, NDVI: {ndvi.get('nd')}, SAR: {sar_mean.get('VV')}, SAR stddev: {sar_std.get('VV_stdDev')}, Compaction Index: {compaction_index}, Clay: {clay}, Silt: {silt}, Sand: {sand}. Question: {q}"
            try:
                if use_ai:
                    try:
                        with st.spinner("Asking OpenAI..."):
                            res = openai.ChatCompletion.create(
                                model="gpt-4",
                                messages=[
                                    {"role": "system", "content": "You are a soil and crop assistant."},
                                    {"role": "user", "content": prompt}
                                ]
                            )
                        st.sidebar.success(res.choices[0].message.content)
                    except (RateLimitError, ServiceUnavailableError) as api_error:
                        st.sidebar.warning(f"OpenAI API temporarily unavailable: {api_error}")
                        st.sidebar.write("Please try again shortly.")
                else:
                    st.sidebar.info("(Offline mode) GPT disabled — here's a basic response.")
                    st.sidebar.write("This soil appears to have moderate texture. NDVI indicates potential vegetation. Further management may depend on crop type.")
            except Exception as e:
                st.sidebar.error(f"AI failed: {e}")
