import os
import json
import streamlit as st
import leafmap.foliumap as leafmap
import ee
import openai
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- Setup ---
st.set_page_config(layout="wide")
st.title("🛰️ Soil Moisture, NDVI & Soil Profile Explorer")

# --- Earth Engine Auth ---
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

# --- Date Range (last 10 days) ---
today = datetime.utcnow().date()
start = today - timedelta(days=10)

# --- Map Setup ---
m = leafmap.Map(center=(37.5, -120.8), zoom=10)
if "clicked" not in st.session_state:
    st.session_state.clicked = None

def handle_click(**kwargs):
    if "latlng" in kwargs:
        st.session_state.clicked = kwargs["latlng"]
        st.info(f"📍 Clicked at: {kwargs['latlng']}")

m.on_click(handle_click)
m.to_streamlit(height=700)

# --- Process Click ---
if st.session_state.clicked:
    lat, lon = st.session_state.clicked
    point = ee.Geometry.Point([lon, lat])

    # NDVI
    try:
        s2 = ee.ImageCollection("COPERNICUS/S2") \
            .filterBounds(point) \
            .filterDate(str(start), str(today)) \
            .median()
        ndvi_img = s2.normalizedDifference(["B8", "B4"])
        ndvi_val = ndvi_img.reduceRegion(ee.Reducer.mean(), point, 10).getInfo().get("nd")
        ndvi_date = s2.get("system:time_start").getInfo()
        ndvi_date_fmt = str(today)  # fallback, EE doesn't always return date
    except:
        ndvi_val = ndvi_date_fmt = None

    # SAR VV
    try:
        s1 = ee.ImageCollection("COPERNICUS/S1_GRD") \
            .filterBounds(point) \
            .filterDate(str(start), str(today)) \
            .filter(ee.Filter.eq("instrumentMode", "IW")) \
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")) \
            .select("VV") \
            .mean()
        sar_val = s1.reduceRegion(ee.Reducer.mean(), point, 10).getInfo().get("VV")
    except:
        sar_val = None

    # SoilGrids API
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

    # SSURGO API (SoilWeb)
    try:
        ssurgo_url = f"https://casoilresource.lawr.ucdavis.edu/soilweb/rest/soils?lon={lon}&lat={lat}"
        s = requests.get(ssurgo_url).json()
        comp = s['soil']['components'][0]
        ssurgo_series = comp.get("compname")
        ssurgo_drainage = comp.get("drainagecl")
        ssurgo_taxorder = comp.get("taxorder")
        map_unit_name = s['soil'].get("muname")
        map_unit_symbol = s['soil'].get("musym")
    except:
        ssurgo_series = ssurgo_drainage = ssurgo_taxorder = map_unit_name = map_unit_symbol = None

    # Infiltration Estimation
    try:
        if clay is not None and sand is not None and carbon is not None:
            if clay > 40 or sand < 30:
                infiltration_class = "Low" if carbon < 10 else "Medium"
            elif sand >= 60 and carbon > 10:
                infiltration_class = "High"
            else:
                infiltration_class = "Medium"
        else:
            infiltration_class = "Unknown"
    except:
        infiltration_class = "Unknown"

    # Display All Results
    st.subheader("🧪 Data at Selected Point")
    st.write({
        "Latitude": lat,
        "Longitude": lon,
        "NDVI (recent)": ndvi_val,
        "SAR VV (recent)": sar_val,
        "NDVI Date Range": f"{start} → {today}",
        "Soil pH": ph,
        "Organic Carbon (g/kg)": carbon,
        "Sand (%)": sand,
        "Silt (%)": silt,
        "Clay (%)": clay,
        "Infiltration Class": infiltration_class,
        "SSURGO Soil Series": ssurgo_series,
        "SSURGO Drainage Class": ssurgo_drainage,
        "SSURGO Taxonomic Order": ssurgo_taxorder,
        "SSURGO Map Unit Name": map_unit_name,
        "SSURGO Map Unit Symbol": map_unit_symbol
    })

    # CSV Export
    df = pd.DataFrame([{
        "Latitude": lat,
        "Longitude": lon,
        "NDVI": ndvi_val,
        "SAR_VV": sar_val,
        "NDVI_Date_Start": str(start),
        "NDVI_Date_End": str(today),
        "Soil_pH": ph,
        "OrganicCarbon_gkg": carbon,
        "Sand_%": sand,
        "Silt_%": silt,
        "Clay_%": clay,
        "Infiltration_Class": infiltration_class,
        "SSURGO_Soil_Series": ssurgo_series,
        "SSURGO_Drainage": ssurgo_drainage,
        "SSURGO_Tax_Order": ssurgo_taxorder,
        "SSURGO_Map_Unit": map_unit_name,
        "SSURGO_Map_Symbol": map_unit_symbol
    }])
    st.download_button("📥 Download CSV Report", df.to_csv(index=False), file_name="soil_data_report.csv")

    # AI Assistant
    if use_ai:
        st.sidebar.header("💬 AI Assistant")
        q = st.sidebar.text_area("Ask a question about this site or values:")
        if st.sidebar.button("Ask") and q.strip():
            prompt = f"""You are an expert in soil, agronomy, and remote sensing.
The clicked point has these values:
- NDVI: {ndvi_val}
- SAR VV: {sar_val}
- pH: {ph}, OC: {carbon}, Sand: {sand}, Silt: {silt}, Clay: {clay}
- Infiltration: {infiltration_class}
- SSURGO: {ssurgo_series}, {ssurgo_drainage}, {ssurgo_taxorder}, {map_unit_name}

Answer this user question:
{q}
"""
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a soil, water, crop and satellite assistant for farmers and scientists."},
                        {"role": "user", "content": prompt}
                    ]
                )
                st.sidebar.write("**Assistant Response:**")
                st.sidebar.write(response.choices[0].message.content)
            except Exception as e:
                st.sidebar.error(f"OpenAI API error: {e}")
