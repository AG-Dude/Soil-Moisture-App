import streamlit as st
import leafmap.foliumap as leafmap  # ✅ Supported module

st.set_page_config(layout="wide")
st.title("🌍 Soil Moisture Viewer (Stable Build)")

m = leafmap.Map(center=[37.7749, -122.4194], zoom=10)
m.add_basemap('HYBRID')
m.to_streamlit(height=600)
