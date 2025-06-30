import streamlit as st
import leafmap.foliumap as leafmap

st.set_page_config(layout="wide")
st.title("🛰️ Soil Moisture Intelligence Dashboard")

# ---- SIDEBAR CONTROLS ----
with st.sidebar:
    st.header("🔧 Controls")
    ndvi_layer = st.checkbox("🛰️ NDVI (Sentinel-2 Tiles)", value=True)
    sar_layer = st.checkbox("💧 Simulated SAR Soil Moisture")
    veg_layer = st.checkbox("🌿 Vegetation Classification")
    soil_layer = st.checkbox("🗺️ SSURGO Soil Map")
    show_chat = st.checkbox("🤖 SoilBot Assistant")

# ---- INIT MAP ----
m = leafmap.Map(center=[37.5, -120], zoom=9, draw_control=True, measure_control=True)
m.add_basemap("HYBRID")

# ---- NDVI TILE OVERLAY (PRE-EXPORTED TILESET) ----
if ndvi_layer:
    ndvi_tiles = "https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}.png"  # Replace w/ your NDVI tile URL
    m.add_tile_layer(
        url=ndvi_tiles,
        name="NDVI (XYZ Tiles)",
        attribution="Sentinel-2 NDVI",
        opacity=0.7,
        shown=True,
    )

# ---- SAR MOISTURE OVERLAY (SIMULATED) ----
if sar_layer:
    sar_url = "https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}.png"  # Simulated SAR-style look
    m.add_tile_layer(
        url=sar_url,
        name="Simulated SAR Moisture",
        attribution="Simulated SAR",
        opacity=0.6,
        shown=True,
    )

# ---- VEGETATION CLASSIFICATION (SIMULATED BASED ON DRAWN AOI) ----
if veg_layer:
    if m.user_roi_bounds():
        st.subheader("🌱 Vegetation Classification")
        st.info("Classified based on NDVI thresholds (simulated).")
        st.json({
            "Orchard Canopy": "NDVI > 0.6",
            "Green Weeds": "NDVI 0.4–0.6",
            "Dry Grass": "NDVI 0.2–0.4",
            "Bare Soil": "NDVI < 0.2"
        })
    else:
        st.warning("Draw an AOI to enable classification.")

# ---- SOILWEB / SSURGO WMS OVERLAY ----
if soil_layer:
    m.add_wms_layer(
        url="https://casoilresource.lawr.ucdavis.edu/arcgis/services/CA/SSURGO/MapServer/WMSServer?",
        layers="0",
        name="SSURGO Soil Units",
        format="image/png",
        transparent=True,
        attribution="UC Davis Soil Resource Lab",
    )

# ---- AOI + COORDINATE INTERACTION ----
m.to_streamlit(height=600)

if m.user_roi_bounds():
    st.success(f"📐 AOI Bounds: {m.user_roi_bounds()}")

if m.user_click():
    st.success(f"🖱️ You clicked: {m.user_click()}")

# ---- AI ASSISTANT PANEL ----
if show_chat:
    st.subheader("🤖 SoilBot Assistant")
    user_input = st.chat_input("Ask something about this field...")
    if user_input:
        response = "This is a placeholder. Future AI will analyze soil, NDVI, SAR, and vegetation based on AOI."
        st.chat_message("user").write(user_input)
        st.chat_message("assistant").write(response)
