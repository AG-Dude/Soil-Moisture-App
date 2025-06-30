import os
import json
import streamlit as st
import leafmap.foliumap as leafmap
import ee
import openai
import pandas as pd
import requests
from datetime import datetime, timedelta
import altair as alt

st.set_page_config(layout="wide")
st.title("🛰️ Soil Moisture, NDVI & Soil Explorer")

# --- Authenticate Earth Engine ---
gee_key = os.getenv("EE_PRIVATE_KEY")
if not gee_key:
    st.error("EE_PRIVATE_KEY not found in environment.")
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

# --- OpenAI Setup ---
openai.api_key = os.getenv("OPENAI_API_KEY")
use_ai = openai.api_key is not None

# --- Dates ---
today = datetime.utcnow().date()
start_10 = today - timedelta(days=10)
start_30 = today - timedelta(days=30)

# --- Map ---
m = leafmap.Map(center=(37.5, -120.8), zoom=10)
if "clicked" not in st.session_state:
    st.session_state.clicked = None

def handle_click(**kwargs):
    if "latlng" in kwargs:
        st.session_state.clicked = kwargs["latlng"]
        st.info(f"📍 Clicked at: {kwargs['latlng']}")

m.on_click(handle_click)

# --- Optional: Overlay NDVI and SAR layers ---
with st.sidebar:
    st.subheader("🗺️ Map Layers")
    show_ndvi = st.checkbox("Show NDVI overlay", value=True)
    show_sar = st.checkbox("Show SAR VV overlay", value=False)

if show_ndvi:
    ndvi_layer = ee.ImageCollection("COPERNICUS/S2") \
        .filterDate(str(start_10), str(today)) \
        .median().normalizedDifference(["B8", "B4"])
    vis = {"min": 0, "max": 1, "palette": ["white", "green"]}
    m.add_ee_layer(ndvi_layer, vis, "NDVI")

if show_sar:
    sar_layer = ee.ImageCollection("COPERNICUS/S1_GRD") \
        .filterDate(str(start_10), str(today)) \
        .filter(ee.Filter.eq("instrumentMode", "IW")) \
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
        .select("VV") \
        .mean()
    vis = {"min": -25, "max": 0, "palette": ["purple", "blue", "white"]}
    m.add_ee_layer(sar_layer, vis, "SAR VV")

m.to_streamlit(height=700)

# --- Data on Click ---
if st.session_state.clicked:
    lat, lon = st.session_state.clicked
    point = ee.Geometry.Point([lon, lat])

    # NDVI/SAR single values
    try:
        ndvi_img = ee.ImageCollection("COPERNICUS/S2") \
            .filterBounds(point).filterDate(str(start_10), str(today)) \
            .median().normalizedDifference(["B8", "B4"])
        ndvi_val = ndvi_img.reduceRegion(ee.Reducer.mean(), point, 10).getInfo().get("nd")
    except:
        ndvi_val = None

    try:
        sar_img = ee.ImageCollection("COPERNICUS/S1_GRD") \
            .filterBounds(point).filterDate(str(start_10), str(today)) \
            .filter(ee.Filter.eq("instrumentMode", "IW")) \
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
            .select("VV").mean()
        sar_val = sar_img.reduceRegion(ee.Reducer.mean(), point, 10).getInfo().get("VV")
    except:
        sar_val = None

    # SoilGrids
    try:
        sg_url = f"https://rest.soilgrids.org/query?lon={lon}&lat={lat}"
        sg = requests.get(sg_url).json()
        layers = sg['properties']['layers']
        ph = layers['phh2o']['depths'][0]['values']['mean']
        carbon = layers['ocd']['depths'][0]['values']['mean']
        sand = layers['sand']['depths'][0]['values']['mean']
        silt = layers['silt']['depths'][0]['values']['mean']
        clay = layers['clay']['depths'][0]['values']['mean']
    except:
        ph = carbon = sand = silt = clay = None

    # SSURGO
    try:
        sw_url = f"https://casoilresource.lawr.ucdavis.edu/soilweb/rest/soils?lon={lon}&lat={lat}"
        r = requests.get(sw_url).json()
        comp = r['soil']['components'][0]
        ssurgo_series = comp.get("compname")
        ssurgo_drainage = comp.get("drainagecl")
        ssurgo_taxorder = comp.get("taxorder")
        map_unit_name = r['soil'].get("muname")
        map_unit_symbol = r['soil'].get("musym")
    except:
        ssurgo_series = ssurgo_drainage = ssurgo_taxorder = map_unit_name = map_unit_symbol = None

    # Infiltration
    try:
        if clay and sand and carbon:
            if clay > 40 or sand < 30:
                infiltration = "Low" if carbon < 10 else "Medium"
            elif sand > 60 and carbon > 10:
                infiltration = "High"
            else:
                infiltration = "Medium"
        else:
            infiltration = "Unknown"
    except:
        infiltration = "Unknown"

    # Display Summary
    st.subheader("🧪 Data at Point")
    st.write({
        "Latitude": lat,
        "Longitude": lon,
        "NDVI": ndvi_val,
        "SAR VV": sar_val,
        "pH": ph,
        "Organic C (g/kg)": carbon,
        "Sand %": sand,
        "Silt %": silt,
        "Clay %": clay,
        "Infiltration Class": infiltration,
        "SSURGO Series": ssurgo_series,
        "Drainage": ssurgo_drainage,
        "Tax Order": ssurgo_taxorder,
        "Map Unit": map_unit_name,
        "Map Symbol": map_unit_symbol
    })

    # Download CSV
    df = pd.DataFrame([{
        "Latitude": lat, "Longitude": lon, "NDVI": ndvi_val, "SAR_VV": sar_val,
        "pH": ph, "OC_gkg": carbon, "Sand": sand, "Silt": silt, "Clay": clay,
        "Infiltration": infiltration, "SSURGO_Series": ssurgo_series,
        "Drainage": ssurgo_drainage, "TaxOrder": ssurgo_taxorder,
        "MapUnit": map_unit_name, "MapSymbol": map_unit_symbol
    }])
    st.download_button("📥 Download CSV Report", df.to_csv(index=False), file_name="soil_data_report.csv")

    # --- Time Series Chart (NDVI + SAR) ---
    st.subheader("📈 NDVI & SAR Time Series (30 Days)")

    def extract_series(collection, band):
        ic = collection.filterBounds(point).filterDate(str(start_30), str(today)) \
            .sort("system:time_start").select(band)
        dates, values = [], []
        for img in ic.toList(ic.size()).getInfo():
            t = datetime.utcfromtimestamp(img['properties']['system:time_start'] / 1000).date()
            v = img['properties'].get('system:index', None)
            geom = ee.Image(img['id']).reduceRegion(ee.Reducer.mean(), point, 10).getInfo()
            val = geom.get(band) if geom else None
            if val is not None:
                dates.append(str(t))
                values.append(val)
        return pd.DataFrame({"Date": dates, band: values})

    try:
        ndvi_series = extract_series(
            ee.ImageCollection("COPERNICUS/S2").map(lambda img: img.normalizedDifference(["B8", "B4"]).rename("NDVI")),
            "NDVI"
        )
        sar_series = extract_series(
            ee.ImageCollection("COPERNICUS/S1_GRD") \
                .filter(ee.Filter.eq("instrumentMode", "IW")) \
                .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
                .select("VV"),
            "VV"
        )

        chart = alt.Chart(pd.merge(ndvi_series, sar_series, on="Date", how="outer").dropna()).transform_fold(
            ["NDVI", "VV"], as_=["Type", "Value"]
        ).mark_line().encode(
            x="Date:T", y="Value:Q", color="Type:N"
        ).properties(height=300)
        st.altair_chart(chart, use_container_width=True)
    except:
        st.warning("⚠️ Time series data could not be retrieved.")

    # --- AI Assistant ---
    if use_ai:
        st.sidebar.header("💬 Ask the AI")
        question = st.sidebar.text_area("Ask about this data:")
        if st.sidebar.button("Ask") and question.strip():
            prompt = f"""
NDVI: {ndvi_val}, SAR: {sar_val}, pH: {ph}, OC: {carbon}, sand: {sand}, silt: {silt}, clay: {clay}
SSURGO: {ssurgo_series}, {ssurgo_drainage}, {ssurgo_taxorder}, {map_unit_name}
Infiltration: {infiltration}
Question: {question}
"""
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a soil, remote sensing, and irrigation assistant."},
                        {"role": "user", "content": prompt}
                    ]
                )
                st.sidebar.write("**Response:**")
                st.sidebar.write(response.choices[0].message.content)
            except Exception as e:
                st.sidebar.error(f"OpenAI error: {e}")
