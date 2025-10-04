import streamlit as st

st.set_page_config(page_title="Wonkyung's Python Portfolio", layout="wide")

st.title("🎓 Wonkyung's Python Portfolio")
st.write("A collection of my Python projects focusing on data visualization, APIs, and dashboards.")

# --- Project 1: Pittsburgh Crime Dashboard ---
st.header("📊 Pittsburgh Crime Dashboard")
st.write("""
An interactive dashboard analyzing Pittsburgh crime data using the WPRDC API.  
It visualizes crime density and risk levels for CMU neighborhoods.
""")

st.markdown("[🔗 View on GitHub](https://github.com/lisawkchung/pittsburgh-crime-dashboard)")

# Optional placeholder image (you can replace later with your actual screenshot)
st.image("https://raw.githubusercontent.com/lisawkchung/pittsburgh-crime-dashboard/main/example.png",
         caption="Pittsburgh Crime Dashboard", use_container_width=True)

st.divider()

st.header("🧠 More Projects Coming Soon...")
st.write("Stay tuned for new dashboards and data-driven apps.")
