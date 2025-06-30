import streamlit as st
from streamlit_folium import st_folium
import leafmap.foliumap as leafmap
import requests
import openai

# --- CONFIG ---
st.set_page_config(layout="wide")
openai.api_key = st.secrets.get("OPENAI_API_KEY")  # Add key to Render Secrets tab

# --- SIDEBAR AI CHAT ---
with st.sidebar:
    st.title("🌾 Field Assistant")
    user_input = st.text_area("Ask about the clicked area:", "")
    if st.button("Ask AI"):
        if "last_coords" in st.session_state:
            prompt = f"You clicked at {st.session_state['last_coords']}. {user_input}"
        else:
            prompt = user_input
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "system", "content": "You are a soil and crop health assistant."},
                      {"role": "user", "content": prompt}]
        )
        st.markdown("**AI Response:**")
        st.write(response['choices'][0]['message']['content'])

# --- MAIN PAGE ---
st.title("🛰️ Soil Moisture & NDVI Viewer")
st.markdown("Click on the map to view NDVI, SAR soil moisture, and soil info.")

# --- LEAFMAP SETUP ---
m = leafmap.Map(center=[37.5, -120.9], zoom=10, draw_export=True)
m.clear_controls()  # Remove default controls to prevent duplication
m.add_draw_control()  # Add only one draw toolbar

# --- ADD LAYERS ---
m.add_tile_layer(
    url="https://services.sentinel-hub.com/ogc/wms/YOUR_INSTANCE_ID?LAYERS=NDVI&FORMAT=image/png&TRANSPARENT=true",
    name="Sentinel NDVI",
    attribution="Sentinel Hub",
    opacity=0.6
)

m.add_tile_layer(
    url="https://some-sar-provider.com/tiles/{z}/{x}/{y}.png",
    name="SAR Soil Moisture",
    attribution="SAR Provider",
    opacity=0.5
)

m.add_basemap("SATELLITE")
m.add_click_marker()

# --- STREAMLIT-FOLIUM RENDER ---
output = st_folium(m, height=600, width=1200)

# --- HANDLE MAP CLICK ---
if output and output.get("last_clicked"):
    coords = output["last_clicked"]
    lat, lon = coords["lat"], coords["lng"]
    st.session_state["last_coords"] = f"Lat: {lat:.4f}, Lon: {lon:.4f}"

    st.markdown(f"### 📍 Clicked Coordinates: {lat:.4f}, {lon:.4f}")

    # MOCKUP DATA PULLS (Replace with real API requests)
    ndvi_val = 0.72  # Replace with lookup from raster or API
    sar_val = 0.34   # Replace with lookup from SAR service
    soil_type = "Montpelier Loam"  # Replace with SoilWeb or SSURGO

    st.info(f"🟢 **NDVI**: {ndvi_val}")
    st.info(f"💧 **Soil Moisture (SAR)**: {sar_val}")
    st.info(f"🧱 **Soil Type**: {soil_type}")

    # Show popup content inline
    st.markdown(f"**Popup Content:**\n- NDVI: {ndvi_val}\n- SAR Moisture: {sar_val}\n- Soil: {soil_type}")

