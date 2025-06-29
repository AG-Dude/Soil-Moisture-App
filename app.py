import streamlit as st
import leafmap.streamlit as leafmap

st.set_page_config(layout="wide")
st.title("Soil Moisture Estimation App")

with st.sidebar:
    st.info("Draw an Area of Interest (AOI) on the map to estimate vegetation and moisture conditions.")

m = leafmap.Map(center=[37.5, -120.9], zoom=8)
m.add_basemap("SATELLITE")
m.add_draw_control()

output = st.empty()
m.to_streamlit(height=700)

if m.user_roi_bounds():
    bounds = m.user_roi_bounds()
    output.info(f"AOI Bounds: {bounds}")
else:
    output.warning("Draw a rectangle or polygon on the map.")
