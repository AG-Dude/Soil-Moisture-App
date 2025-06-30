import streamlit as st
from streamlit_folium import st_folium
import leafmap.foliumap as leafmap
import requests
import openai
import matplotlib.pyplot as plt
from datetime import datetime

# --- Streamlit Setup ---
st.set_page_config(layout="wide")
openai.api_key = st.secrets.get("OPENAI_API_KEY")

# --- GEE Endpoints ---
NDVI_API = "https://soil-moisture-app-464506.projects.earthengine.app/view/ndvi-point"
SAR_API = "https://soil-moisture-app-464506.projects.earthengine.app/view/sar-vv"
TS_API = "https://soil-moisture-app-464506.projects.earthengine.app/view/time-series"

# --- SoilWeb Lookup ---
def get_soilweb_info(lat, lon):
    try:
        url = f"https://casoilresource.lawr.ucdavis.edu/soil_web_api/soil_series.php?lat={lat}&lon={lon}"
        r = requests.get(url, timeout=5)
        return r.json().get("soil_series_name", "Unknown")
    except:
        return "Lookup failed"

# --- Open-Meteo Live Weather ---
def get_weather(lat, lon):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        r = requests.get(url, timeout=5)
        if r.ok:
            weather = r.json().get("current_weather", {})
            return f"{weather.get('temperature', '?')}°C, {weather.get('windspeed', '?')} km/h wind"
    except:
        return "Weather unavailable"
    return "Weather unavailable"

# --- NDVI Value ---
def get_ndvi(lat, lon):
    try:
        url = f"{NDVI_API}?lat={lat}&lon={lon}"
        r = requests.get(url, timeout=10)
        if r.ok and "ndvi" in r.text:
            val = r.text.split(":")[1].replace("}", "").strip()
            return None if "null" in val else float(val)
    except:
        pass
    return None

# --- SAR Moisture VV ---
def get_sar_vv(lat, lon):
    try:
        url = f"{SAR_API}?lat={lat}&lon={lon}"
        r = requests.get(url, timeout=10)
        if r.ok and "vv" in r.text:
            return float(r.text.split(":")[1].replace("}", "").strip())
    except:
        pass
    return None

# --- Time Series ---
def get_time_series(lat, lon):
    try:
        url = f"{TS_API}?lat={lat}&lon={lon}"
        r = requests.get(url, timeout=15)
        data = r.json()
        return [
            {
                "date": d[0],
                "VV": d[1] if isinstance(d[1], (int, float)) else None,
                "NDVI": d[2] if isinstance(d[2], (int, float)) else None,
            }
            for d in data if d
        ]
    except:
        return []

# --- Sidebar AI Assistant ---
with st.sidebar:
    st.title("🧠 AI Field Assistant")
    q = st.text_area("Ask about the clicked point:")
    if st.button("Ask AI"):
        lat, lon = st.session_state.get("last_coords", (None, None))
        soil = st.session_state.get("soil_type", "unknown")
        sar = st.session_state.get("sar_val", "unknown")
        ndvi = st.session_state.get("ndvi_val", "unknown")
        weather = st.session_state.get("weather", "unknown")
        prompt = f"""
        Latitude: {lat}, Longitude: {lon}
        Soil Type: {soil}
        SAR Moisture (VV): {sar}
        NDVI: {ndvi}
        Weather: {weather}
        Question: {q}
        """
        try:
            reply = openai.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful agricultural assistant."},
                    {"role": "user", "content": prompt},
                ]
            )
            st.write("**AI Response:**")
            st.write(reply.choices[0].message.content)
        except Exception as e:
            st.error(f"OpenAI error: {e}")

# --- Interactive Map ---
m = leafmap.Map(center=[37.5, -120.9], zoom=10)
m.add_draw_control()
m.add_click_marker()
m.add_tile_layer(
    url="https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg",
    name="EOX Cloudless", attribution="EOX", opacity=0.7
)
st.markdown("## 🗺️ Field Tool")
clicked = st_folium(m, height=600, width=1200)

# --- Handle Click ---
if clicked and clicked.get("last_clicked"):
    lat = clicked["last_clicked"]["lat"]
    lon = clicked["last_clicked"]["lng"]
    st.session_state["last_coords"] = (lat, lon)

    st.markdown(f"### 📍 Location: {lat:.4f}, {lon:.4f}")

    # Fetch Soil
    soil = get_soilweb_info(lat, lon)
    st.session_state["soil_type"] = soil
    st.success(f"🧱 Soil Type: {soil}")

    # Fetch SAR
    sar = get_sar_vv(lat, lon)
    st.session_state["sar_val"] = sar
    if sar is not None:
        st.info(f"💧 SAR VV (Soil Moisture): {sar:.2f} dB")
    else:
        st.warning("SAR VV unavailable")

    # Fetch NDVI
    ndvi = get_ndvi(lat, lon)
    st.session_state["ndvi_val"] = ndvi
    if ndvi is not None:
        st.info(f"🌿 NDVI: {ndvi:.3f}")
    else:
        st.warning("NDVI unavailable")

    # Weather
    weather = get_weather(lat, lon)
    st.session_state["weather"] = weather
    st.info(f"🌤️ Weather: {weather}")

    # --- Chart Time Series ---
    series = get_time_series(lat, lon)
    if series:
        st.markdown("### 📈 NDVI + SAR Time Series")
        dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in series]
        ndvi_vals = [r["NDVI"] for r in series]
        vv_vals = [r["VV"] for r in series]

        fig, ax1 = plt.subplots()
        ax1.set_xlabel("Date")
        ax1.plot(dates, ndvi_vals, "g-", label="NDVI")
        ax1.set_ylabel("NDVI", color="green")

        ax2 = ax1.twinx()
        ax2.plot(dates, vv_vals, "b-", label="VV (SAR)")
        ax2.set_ylabel("VV dB", color="blue")
        st.pyplot(fig)

# --- AOI Export Placeholder ---
st.markdown("### 📤 AOI Export Coming Soon")
