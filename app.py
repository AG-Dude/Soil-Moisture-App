import streamlit as st
import leafmap.streamlit as leafmap

st.set_page_config(layout="wide")
st.title("✅ Leafmap Streamlit Test")

leafmap.folium_map(center=[37.7749, -122.4194], zoom=10)
