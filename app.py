import streamlit as st
import leafmap.foliumap as leafmap

st.set_page_config(layout="wide")
st.title("🌿 Soil Moisture Monitor ")

# Initialize interactive map
m = leafmap.Map(center=[37.5, -120], zoom=9, draw_control=True, measure_control=True)

# Add basemap options
m.add_basemap("HYBRID")   # Can change to 'ROADMAP', 'TERRAIN', etc.

# Display map
m.to_streamlit(height=600)

# Drawn area bounding box
if m.user_roi_bounds():
    bounds = m.user_roi_bounds()
    st.info(f"📐 AOI Bounds: {bounds}")

# Popup info when clicking on map (optional example)
clicked_coords = m.user_click()
if clicked_coords:
    st.success(f"🖱️ You clicked at: {clicked_coords}")

with st.sidebar:
    st.header("🔧 Controls")
    st.markdown("Toggle remote sensing layers:")

    ndvi_layer = st.checkbox("🛰️ Show NDVI (vegetation health)")
    ndwi_layer = st.checkbox("💧 Show NDWI (moisture)")
    sar_layer = st.checkbox("📡 Show SAR Soil Moisture")
    show_soil = st.checkbox("🌱 Show Soil Data")
    show_chat = st.checkbox("🤖 Open Assistant")
  if m.user_roi_bounds():
    st.subheader("🌿 Estimated Vegetation Cover (Simulated)")

    veg_types = {
        "Orchard Canopy": 32,
        "Dead Grass": 14,
        "Weeds": 24,
        "Bare Ground": 30,
    }

    st.json(veg_types)
if show_chat:
    st.subheader("🤖 SoilBot Assistant")
    user_input = st.chat_input("Ask something about this field...")

    if user_input:
        # Placeholder response for now
        st.chat_message("assistant").write(f"You asked: *{user_input}*. I'll analyze your AOI soon!")

