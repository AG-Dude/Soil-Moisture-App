import streamlit as st
from datetime import date
import leafmap
import planetary_computer
import pystac_client
import stackstac
import shapely.geometry
import xarray as xr
import matplotlib.pyplot as plt
import numpy as np

st.set_page_config(layout="wide")
st.title("🛰️ Soil Moisture Estimator (Sentinel-2 + Sentinel-1)")

# Sidebar Inputs
st.sidebar.header("User Inputs")
start_date = st.sidebar.date_input("Start Date", date(2024, 6, 1))
end_date = st.sidebar.date_input("End Date", date(2024, 6, 30))
st.sidebar.markdown("Draw your Area of Interest on the map")

# Interactive map
m = leafmap.Map(draw_control=True, measure_control=False)
m.to_streamlit(height=500)

# Run button
if st.sidebar.button("🚀 Run Analysis"):
    try:
        geojson = m.user_roi_geojson
        if not geojson:
            st.error("Please draw a rectangle on the map.")
        else:
            shape = shapely.geometry.shape(geojson["features"][0]["geometry"])
            bounds = shape.bounds

            catalog = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
            s2_search = catalog.search(
                collections=["sentinel-2-l2a"],
                bbox=bounds,
                datetime=f"{start_date}/{end_date}",
                query={"eo:cloud_cover": {"lt": 20}},
            )
            s2_items = list(s2_search.get_all_items())
            if not s2_items:
                st.warning("No Sentinel-2 imagery found.")
            else:
                s2_items = [planetary_computer.sign(item) for item in s2_items]
                s2_data = stackstac.stack(s2_items, assets=["B04", "B08", "B11", "B03"], resolution=10)
                s2_data = s2_data.sel(band=["B04", "B08", "B11", "B03"]).mean(dim="time")

                red = s2_data.sel(band="B04")
                nir = s2_data.sel(band="B08")
                swir = s2_data.sel(band="B11")

                ndvi = (nir - red) / (nir + red)
                ndwi = (nir - swir) / (nir + swir)

                s1_search = catalog.search(
                    collections=["sentinel-1-grd"],
                    bbox=bounds,
                    datetime=f"{start_date}/{end_date}",
                    query={"sar:polarizations": {"in": ["VV"]}, "instrument_mode": {"eq": "IW"}}
                )
                s1_items = list(s1_search.get_all_items())
                if s1_items:
                    s1_items = [planetary_computer.sign(item) for item in s1_items]
                    s1_data = stackstac.stack(s1_items, assets=["vv"], resolution=10).mean(dim="time")
                    s1_vv = s1_data.sel(band="vv")
                else:
                    s1_vv = xr.zeros_like(ndvi)

                soil_moisture_proxy = (ndwi + s1_vv) / 2

                fig, axes = plt.subplots(1, 3, figsize=(18, 6))
                ndvi.plot(ax=axes[0], cmap="YlGn", vmin=0, vmax=1)
                axes[0].set_title("NDVI")
                ndwi.plot(ax=axes[1], cmap="Blues", vmin=-1, vmax=1)
                axes[1].set_title("NDWI")
                soil_moisture_proxy.plot(ax=axes[2], cmap="YlGnBu", vmin=-1, vmax=1)
                axes[2].set_title("Soil Moisture Proxy")
                st.pyplot(fig)

    except Exception as e:
        st.error(f"Error: {str(e)}")

