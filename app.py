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

# --- Earth Engine App URLs ---
NDVI_API = "https://soil-moisture-app-464506.projects.earthengine.app/view/ndvi-point"
SAR_API = "https://soil-moisture-app-464506.projects.earthengine.app/view/sar-vv"  # Replace this with yours
TS_API = "https://soil-moisture-app-464506.projects.earthengine.app/view/time-series"

# --- SoilWeb Lookup ---
def get_soilweb_info(lat, lon):
    try:
        url = f"https://casoilresource.lawr.ucdavis.edu/soil_web_api/soil_series.php?lat={lat}&lon={lon}"
        data = requests.get(url, timeout=5).json()
        return data.get("soil_series_name", "Unknown")
    except Exception:
        return "Lookup failed"

# --- Real SAR Moisture ---
def get_sar_vv(lat, lon):
    try:
        url = f"{SAR_API}?lat={lat}&lon={lon}"
        res = requests.get(url, timeout=10)
        if res.ok and "vv" in res.text:
            return float(res.text.split(":")[1].replace("}", "").strip())
    except Exception:
        pass
    return None

# --- Real NDVI ---
def get_ndvi(lat, lon):
    try:
        url = f"{NDVI_API}?lat={lat}&lon={lon}"
        res = requests.get(url, timeout=10)
        if res.ok and "ndvi" in res.text:
            ndvi_val = res.text.split(":")[1].replace("}", "").strip()
            return None if "null" in ndvi_val else float(ndvi_val)
    except Exception:
        pass
    return None

# --- Time Series from GEE App ---
def get_time_series(lat, lon):
    try:
        url = f"{TS_API}?lat={lat}&lon={lon}"
        res = requests.get(url, timeout=15)
        data = res.json()
        records = []
        for item in data:
            date = item[0]
            vv = item[1] if isinstance(item[1], (int, float)) else None
            ndvi = item[2] if isinstance(item[2], (int, float)) else None
            if vv or ndvi:
                records.append({"date": date, "VV": vv, "NDVI": ndvi})
        return records
    except Exception:
        return []

# --- AI Assistant ---
with st.sidebar:
    st.title("🧠 AI Field Assistant")
    question = st.text_area("Ask about the clicked spot:")
    if st.button("Ask AI"):
        coords = st.session_state.get("last_coords", (None, None))
        soil = st.session_state.get("soil_type", "unknown")
        sar = st.session_state.get("sar_val", "unknown")
        ndvi = st.session_state.get("ndvi_val", "unknown")
        prompt = f"""
        Location: Lat {coords[0]}, Lon {coords[1]}
        Soil Type: {soil}
        SAR Moisture (VV): {sar}
        NDVI: {ndvi}
        Question: {question}
        """
        reply = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful agricultural field assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        st.markdown("**AI Response:**")
        st.write(reply['choices'][0]['message']['content'])

# --- Map Setup ---
m = leafmap.Map(center=[37.5, -120.9], zoom=10)
m.clear_controls()
m.add_draw_control()
m.add_click_marker()

# Add base tile
m.add_tile_layer(
    url="https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg",
    name="EOX Cloudless",
    attribution="EOX",
    opacity=0.7
)

# --- Show Map ---
st.markdown("## 🗺️ Interactive Field Tool")
output = st_folium(m, height=600, width=1200)

# --- Handle Click Event ---
if output and output.get("last_clicked"):
    lat = output["last_clicked"]["lat"]
    lon = output["last_clicked"]["lng"]
    st.session_state["last_coords"] = (lat, lon)

    st.markdown(f"### 📍 Clicked Location: {lat:.4f}, {lon:.4f}")

    soil = get_soilweb_info(lat, lon)
    st.session_state["soil_type"] = soil
    st.success(f"🧱 **Soil Type**: {soil}")

    sar = get_sar_vv(lat, lon)
    st.session_state["sar_val"] = sar
    if sar is not None:
        st.info(f"💧 **SAR Moisture (VV)**: {sar:.2f} dB")
    else:
        st.warning("⚠️ SAR data unavailable.")

    ndvi = get_ndvi(lat, lon)
    st.session_state["ndvi_val"] = ndvi
    if ndvi is not None:
        st.info(f"🌿 **NDVI**: {ndvi:.3f}")
    else:
        st.warning("⚠️ NDVI data unavailable.")

    # --- Time Series Chart ---
    series = get_time_series(lat, lon)
    if series:
        st.markdown("### 📈 NDVI + SAR Time Series (90 days)")
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

# --- AOI Download (placeholder for now) ---
st.markdown("### 📤 AOI Export Coming Soon")
st.caption("This will let you download your drawn polygon as a PNG and data table.")
