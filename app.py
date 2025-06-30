import streamlit as st
import leafmap.foliumap as leafmap
import geemap.foliumap as geemap
import ee

# Earth Engine authentication
try:
    ee.Initialize()
except Exception as e:
    ee.Authenticate()
    ee.Initialize()

st.set_page_config(layout="wide")
st.title("🛰️ Soil Moisture Intelligence Dashboard")

# Sidebar
with st.sidebar:
    st.header("🔧 Controls")
    ndvi_layer = st.checkbox("🛰️ Show NDVI (GEE - Sentinel-2)")
    ndwi_layer = st.checkbox("💧 Show NDWI")
    sar_layer = st.checkbox("📡 Show SAR Soil Moisture")
    show_soil = st.checkbox("🌱 Show Soil Data")
    show_chat = st.checkbox("🤖 Open Assistant")

# Main map (using geemap if NDVI requested, else leafmap)
if ndvi_layer:
    m = geemap.Map(center=[37.5, -120], zoom=9, draw_control=True, measure_control=True)
else:
    m = leafmap.Map(center=[37.5, -120], zoom=9, draw_control=True, measure_control=True)

m.add_basemap("HYBRID")

# NDVI logic (only works locally)
def add_gee_ndvi(map_object, geojson_roi):
    ee_roi = ee.Geometry.Polygon(geojson_roi["geometry"]["coordinates"])

    # Sentinel-2 SR
    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR")
        .filterBounds(ee_roi)
        .filterDate("2024-05-01", "2024-06-01")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .median()
        .clip(ee_roi)
    )

    ndvi = s2.normalizedDifference(["B8", "B4"]).rename("NDVI")

    ndvi_params = {
        "min": 0.1,
        "max": 0.9,
        "palette": ["brown", "yellow", "green"],
    }

    map_object.addLayer(ndvi, ndvi_params, "NDVI (Sentinel-2)")

# NDVI toggle
if ndvi_layer:
    roi_geojson = m.user_roi_geojson()
    if roi_geojson:
        add_gee_ndvi(m, roi_geojson)
        st.success("✅ NDVI added from real Sentinel-2 data.")
    else:
        st.warning("Draw an AOI to load NDVI.")

# Map interaction
m.to_streamlit(height=600)

# Display bounding box if drawn
if m.user_roi_bounds():
    bounds = m.user_roi_bounds()
    st.info(f"📐 AOI Bounds: {bounds}")

# Click info
clicked_coords = m.user_click()
if clicked_coords:
    st.success(f"🖱️ You clicked at: {clicked_coords}")

# Simulated vegetation data
if m.user_roi_bounds():
    st.subheader("🌿 Estimated Vegetation Cover (Simulated)")
    veg_types = {
        "Orchard Canopy": 32,
        "Dead Grass": 14,
        "Weeds": 24,
        "Bare Ground": 30,
    }
    st.json(veg_types)

# AI Assistant placeholder
if show_chat:
    st.subheader("🤖 SoilBot Assistant")
    user_input = st.chat_input("Ask something about this field...")
    if user_input:
        st.chat_message("assistant").write(
            f"You asked: *{user_input}*. I'll analyze your AOI soon!"
        )
