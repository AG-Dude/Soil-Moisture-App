import streamlit as st
import leafmap.foliumap as leafmap
import requests
import json

# ------------------ PAGE SETUP ------------------
st.set_page_config(layout="wide")
st.title("🛰️ Soil Moisture Intelligence Dashboard")

# ------------------ SIDEBAR ------------------
with st.sidebar:
    st.header("🔧 Map Layers")
    ndvi_layer = st.checkbox("🛰️ Sentinel-2 NDVI", value=True)
    sar_layer = st.checkbox("📡 Sentinel-1 SAR Moisture", value=True)
    veg_layer = st.checkbox("🌿 Vegetation Classification", value=True)
    soil_layer = st.checkbox("🗺️ SSURGO Soil Map", value=True)
    show_ai = st.checkbox("🤖 AI Assistant", value=True)

# ------------------ INIT MAP ------------------
m = leafmap.Map(center=[37.5, -120], zoom=9, draw_control=True, measure_control=True)
m.add_basemap("HYBRID")

# ------------------ NDVI TILE LAYER (Real) ------------------
if ndvi_layer:
    ndvi_tiles = "https://tiles.maps.eox.at/wms?layers=s2truecolor&styles=&service=WMS&request=GetMap&version=1.1.1&format=image/png&transparent=true&srs=EPSG:3857&bbox={xmin},{ymin},{xmax},{ymax}&width=256&height=256"
    m.add_tile_layer(
        url="https://services.sentinel-hub.com/ogc/wms/<your_instance_id>?layer=NDVI&style=default&format=image/png&TileMatrixSet=GoogleMapsCompatible&TileMatrix={z}&TileRow={y}&TileCol={x}",
        name="Real NDVI",
        attribution="Sentinel-2 EO Browser",
        opacity=0.75,
    )

# ------------------ SAR TILE LAYER (Real) ------------------
if sar_layer:
    m.add_tile_layer(
        url="https://tiles.maps.eox.at/wms?layers=sentinel1&styles=&service=WMS&request=GetMap&version=1.1.1&format=image/png&transparent=true&srs=EPSG:3857&bbox={xmin},{ymin},{xmax},{ymax}&width=256&height=256",
        name="Sentinel-1 SAR",
        attribution="Sentinel-1 VV",
        opacity=0.5,
    )

# ------------------ SSURGO SOIL LAYER ------------------
if soil_layer:
    m.add_wms_layer(
        url="https://casoilresource.lawr.ucdavis.edu/arcgis/services/CA/SSURGO/MapServer/WMSServer?",
        layers="0",
        name="SSURGO Soils",
        format="image/png",
        transparent=True,
        attribution="UC Davis Soil Lab",
    )

# ------------------ VEGETATION CLASSIFICATION ------------------
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

# ------------------ AI ASSISTANT ------------------
if show_ai:
    st.subheader("🤖 SoilBot AI Assistant")

    aoi = m.user_roi_bounds()
    prompt = st.chat_input("Ask anything about this field or map...")

    if prompt:
        # Compose contextual prompt
        context = f"""
        You are an AI agronomist. The user has drawn an AOI with bounds: {aoi}.
        They are viewing NDVI, SAR moisture, and soil layers.
        Answer their question with clarity and useful recommendations.
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
            st.error("⚠️ Failed to connect to AI assistant. Check your API key in `.streamlit/secrets.toml`.")
