import streamlit as st
import leafmap.foliumap as leafmap
import requests
import json
from datetime import datetime, timedelta
import openai
import os

# --- UI Setup ---
st.set_page_config(layout="wide")
st.title("🌱 Soil Moisture & Vegetation Intelligence")

with st.sidebar:
    st.header("Assistant")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    user_input = st.text_input("Ask about this point...")
    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        if "OPENAI_API_KEY" in st.secrets:
            openai.api_key = st.secrets["OPENAI_API_KEY"]
            try:
                chat = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[{"role": "system", "content": "You are a helpful assistant for interpreting satellite and soil data."}] + st.session_state.chat_history
                )
                reply = chat.choices[0].message.content
                st.session_state.chat_history.append({"role": "assistant", "content": reply})
            except Exception as e:
                reply = f"OpenAI error: {str(e)}"
                st.session_state.chat_history.append({"role": "assistant", "content": reply})
        else:
            reply = "OpenAI key not set in secrets.toml"
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
    for msg in st.session_state.chat_history:
        st.markdown(f"**{msg['role'].capitalize()}:** {msg['content']}")

# --- Map ---
m = leafmap.Map(center=[37.5, -120.8], zoom=8)
m.add_basemap("HYBRID")
m.add_layer_control()
m.to_streamlit(height=600)

# --- Capture Click ---
click_info = m.user_click()
if click_info:
    lat = click_info["lat"]
    lon = click_info["lng"]
    st.success(f"📍 You clicked: {lat:.4f}, {lon:.4f}")

    # --- SoilWeb (via SoilGrids)
    try:
        soil_url = f"https://rest.soilgrids.org/query?lon={lon}&lat={lat}"
        soil_res = requests.get(soil_url)
        if soil_res.ok:
            soil_data = soil_res.json()
            st.subheader("🧱 Soil Type")
            st.json(soil_data)
        else:
            st.warning("Failed to retrieve soil data.")
    except Exception as e:
        st.warning(f"Soil data error: {e}")

    # --- Weather Data (Open-Meteo)
    try:
        today = datetime.utcnow().date()
        past = today - timedelta(days=7)
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
            f"&timezone=auto&start_date={past}&end_date={today}"
        )
        weather_res = requests.get(weather_url)
        if weather_res.ok:
            weather = weather_res.json()
            st.subheader("🌦️ Weather (Past 7 Days)")
            st.json(weather["daily"])
        else:
            st.warning("Failed to retrieve weather.")
    except Exception as e:
        st.warning(f"Weather error: {e}")

    # --- Earth Engine (NDVI + SAR links)
    try:
        ndvi_url = f"https://soil-moisture-app-464506.projects.earthengine.app/view/ndvi-point?lat={lat}&lon={lon}"
        ts_url = f"https://soil-moisture-app-464506.projects.earthengine.app/view/time-series?lat={lat}&lon={lon}"
        st.subheader("🛰️ Remote Sensing")
        st.markdown(f"[📊 NDVI Value Viewer]({ndvi_url})")
        st.markdown(f"[📈 Time Series NDVI + SAR]({ts_url})")
    except Exception as e:
        st.warning(f"Earth Engine link error: {e}")

    st.session_state["last_clicked"] = {"lat": lat, "lon": lon}

else:
    st.info("Click on the map to load data for a specific location.")
