import streamlit as st
import leafmap.foliumap as leafmap
import requests
import openai

st.set_page_config(layout="wide")
st.title("Soil Moisture & NDVI Explorer")

# Sidebar chat input
st.sidebar.title("Field Assistant")
user_input = st.sidebar.text_area("Ask about this location, crop status, or soil:", height=200)
chat_response = ""

# Initialize OpenAI client
client = openai.OpenAI()
if user_input:
    try:
        chat = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful field agronomist assistant."},
                {"role": "user", "content": user_input},
            ]
        )
        chat_response = chat.choices[0].message.content
        st.sidebar.markdown("**Response:**")
        st.sidebar.write(chat_response)
    except Exception as e:
        st.sidebar.error(f"OpenAI error: {e}")

# Initialize map
m = leafmap.Map(center=(37.5, -120), zoom=7, draw_control=True)

# Handle click location
click_info = m.user_clicked_coordinates
if click_info:
    lat, lon = click_info
    st.session_state["click_coords"] = (lat, lon)

    st.subheader("Selected Point Data")
    st.write(f"Latitude: {lat:.4f}, Longitude: {lon:.4f}")

    # NDVI from Earth Engine App
    ndvi_url = f"https://soil-moisture-app-464506.projects.earthengine.app/view/ndvi-point?lat={lat}&lon={lon}"
    st.markdown(f"[🌿 View NDVI at Point]({ndvi_url})", unsafe_allow_html=True)

    # Time Series Chart from Earth Engine
    ts_url = f"https://soil-moisture-app-464506.projects.earthengine.app/view/time-series?lat={lat}&lon={lon}"
    st.markdown(f"[📈 NDVI + SAR Time Series]({ts_url})", unsafe_allow_html=True)

else:
    st.write("Click on the map to load vegetation and moisture data.")

# Display map
m.to_streamlit(height=600)
