import streamlit as st
import leafmap.foliumap as leafmap
import requests
import json
import io
import pandas as pd
from datetime import datetime

st.set_page_config(layout="wide")
st.title("🛰️ Soil & Crop Intelligence Dashboard")

# ------------------ SIDEBAR ------------------
with st.sidebar:
    st.header("🔧 Map Layers")
    ndvi_layer = st.checkbox("🛰️ Sentinel-2 NDVI", value=True)
    sar_layer = st.checkbox("📡 Sentinel-1 SAR Moisture", value=True)
    ndwi_layer = st.checkbox("💧 NDWI (Water Index)", value=True)
    veg_layer = st.checkbox("🌿 Vegetation Classification", value=True)
    soil_layer = st.checkbox("🗺️ SSURGO Soil Map", value=True)
    show_ai = st.checkbox("🤖 AI Assistant", value=True)
    show_export = st.checkbox("⬇️ Export AOI Data", value=True)

# ------------------ INIT MAP ------------------
m = leafmap.Map(center=[37.5, -120], zoom=9, draw_control=True, measure_control=True)
m.add_basemap("HYBRID")

# ------------------ TILE LAYERS ------------------
if ndvi_layer:
    m.add_tile_layer(
        url="https://services.sentinel-hub.com/ogc/wms/0f12e2d6-fake-ndvi-instance/layer=NDVI&style=default&format=image/png&TileMatrixSet=GoogleMapsCompatible&TileMatrix={z}&TileRow={y}&TileCol={x}",
        name="NDVI",
        attribution="SentinelHub",
        opacity=0.75,
    )

if sar_layer:
    m.add_tile_layer(
        url="https://tiles.maps.eox.at/wms?layers=sentinel1&styles=&service=WMS&request=GetMap&version=1.1.1&format=image/png&transparent=true&srs=EPSG:3857&bbox={xmin},{ymin},{xmax},{ymax}&width=256&height=256",
        name="Sentinel-1 SAR",
        attribution="EOX",
        opacity=0.5,
    )

if ndwi_layer:
    m.add_tile_layer(
        url="https://tiles.maps.eox.at/wms?layers=ndwi&styles=&service=WMS&request=GetMap&version=1.1.1&format=image/png&transparent=true&srs=EPSG:3857&bbox={xmin},{ymin},{xmax},{ymax}&width=256&height=256",
        name="NDWI",
        attribution="EOX NDWI",
        opacity=0.6,
    )

if soil_layer:
    m.add_wms_layer(
        url="https://casoilresource.lawr.ucdavis.edu/arcgis/services/CA/SSURGO/MapServer/WMSServer?",
        layers="0",
        name="SSURGO Soils",
        format="image/png",
        transparent=True,
        attribution="UC Davis Soil Lab",
    )

# ------------------ VEGETATION CLASS ------------------
if veg_layer and m.user_roi_bounds():
    st.subheader("🌱 Vegetation Classification (based on NDVI)")
    veg_data = {
        "Orchard Canopy": "NDVI > 0.6",
        "Green Weeds": "NDVI 0.4–0.6",
        "Dry Grass": "NDVI 0.2–0.4",
        "Bare Soil": "NDVI < 0.2"
    }
    st.json(veg_data)

# ------------------ INTERACTION ------------------
m.to_streamlit(height=600)

if m.user_roi_bounds():
    st.success(f"📐 AOI Bounds: {m.user_roi_bounds()}")

if m.user_click():
    st.info(f"🖱️ You clicked at: {m.user_click()}")

# ------------------ EXPORT AOI DATA ------------------
if show_export and m.user_roi_bounds():
    st.subheader("⬇️ AOI Export")
    # Example CSV Summary (replace with real values if desired)
    stats = {
        "Average NDVI": [0.52],
        "Estimated Moisture (SAR)": [0.33],
        "Vegetation Type": ["Mixed Vegetation"]
    }
    df = pd.DataFrame(stats)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    st.download_button("Download Summary CSV", csv_buffer.getvalue(), file_name="aoi_summary.csv", mime="text/csv")

    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": m.user_roi_bounds(as_geojson=True),
            "properties": {"name": "AOI Export", "date": datetime.today().isoformat()}
        }]
    }
    geojson_bytes = io.BytesIO(json.dumps(geojson).encode())
    st.download_button("Download AOI GeoJSON", geojson_bytes, file_name="aoi.geojson", mime="application/json")

# ------------------ AI ASSISTANT ------------------
if show_ai:
    st.subheader("🤖 SoilBot AI Assistant")

    aoi = m.user_roi_bounds()
    prompt = st.chat_input("Ask anything about the map, soil, or field conditions...")

    if prompt:
        context = f"""
        You are an expert agronomist. The user has drawn an AOI with bounds: {aoi}.
        They are viewing layers: NDVI, SAR soil moisture, NDWI, SSURGO soil, and vegetation classification.
        Respond to their question with field-specific insights, irrigation guidance, or data interpretation.
        """

        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "system", "content": context},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.4
        }

        headers = {
            "Authorization": f"Bearer {st.secrets['OPENAI_API_KEY']}",
            "Content-Type": "application/json"
        }

        try:
            res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, data=json.dumps(payload))
            reply = res.json()["choices"][0]["message"]["content"]
            st.chat_message("assistant").write(reply)
        except Exception as e:
            st.error("⚠️ AI Assistant error: check API key or network.")
