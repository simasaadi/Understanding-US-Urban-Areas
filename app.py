import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import pydeck as pdk

# --------------------------------------------------
# Page config
# --------------------------------------------------
st.set_page_config(
    page_title="Understanding US Urban Areas",
    page_icon="🗺️",
    layout="wide"
)

# --------------------------------------------------
# Load data
# --------------------------------------------------
@st.cache_data
def load_data():
    df = pd.read_csv("data/Urban_Areas.csv")

    # Standardize column names (defensive programming)
    df.columns = df.columns.str.upper()

    # Ensure numeric fields
    numeric_cols = ["ALAND10", "AWATER10", "INTPTLAT10", "INTPTLON10"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop rows without coordinates
    df = df.dropna(subset=["INTPTLAT10", "INTPTLON10"])

    # Derived metrics
    df["LAND_KM2"] = df["ALAND10"] / 1_000_000
    df["WATER_KM2"] = df["AWATER10"] / 1_000_000
    df["TOTAL_AREA_KM2"] = df["LAND_KM2"] + df["WATER_KM2"]

    df["WATER_SHARE_PCT"] = np.where(
        df["TOTAL_AREA_KM2"] > 0,
        (df["WATER_KM2"] / df["TOTAL_AREA_KM2"]) * 100,
        0
    )

    # Urban area type
    df["URBAN_TYPE"] = df["UACE10"].astype(str).str.startswith("9") \
        .map({True: "Urban Cluster (UC)", False: "Urbanized Area (UA)"})

    return df


df = load_data()

# --------------------------------------------------
# Sidebar filters
# --------------------------------------------------
st.sidebar.title("Filters")

urban_type_filter = st.sidebar.multiselect(
    "Urban Area Type",
    options=df["URBAN_TYPE"].unique(),
    default=df["URBAN_TYPE"].unique()
)

funcstat_filter = st.sidebar.multiselect(
    "Functional Status (FUNCSTAT10)",
    options=sorted(df["FUNCSTAT10"].dropna().unique()),
    default=sorted(df["FUNCSTAT10"].dropna().unique())
)

min_land_area = st.sidebar.slider(
    "Minimum land area (km²)",
    min_value=0.0,
    max_value=float(df["LAND_KM2"].max()),
    value=0.0
)

filtered = df[
    (df["URBAN_TYPE"].isin(urban_type_filter)) &
    (df["FUNCSTAT10"].isin(funcstat_filter)) &
    (df["LAND_KM2"] >= min_land_area)
]

# --------------------------------------------------
# Header
# --------------------------------------------------
st.title("Understanding US Urban Areas")
st.markdown(
    """
    An interactive spatial and analytical overview of **Urbanized Areas (UAs)** and
    **Urban Clusters (UCs)** in the United States, based on Census-defined geography.
    """
)

# --------------------------------------------------
# KPI metrics
# --------------------------------------------------
col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Urban Areas",
    f"{filtered.shape[0]:,}"
)

col2.metric(
    "Total Land Area (km²)",
    f"{filtered['LAND_KM2'].sum():,.0f}"
)

col3.metric(
    "Total Water Area (km²)",
    f"{filtered['WATER_KM2'].sum():,.0f}"
)

col4.metric(
    "Avg. Water Share (%)",
    f"{filtered['WATER_SHARE_PCT'].mean():.1f}"
)

# --------------------------------------------------
# Map
# --------------------------------------------------
st.subheader("Spatial Distribution of Urban Areas")

map_layer = pdk.Layer(
    "ScatterplotLayer",
    data=filtered,
    get_position=["INTPTLON10", "INTPTLAT10"],
    get_radius=3000,
    get_fill_color="[200, 30, 0, 120]",
    pickable=True
)

view_state = pdk.ViewState(
    latitude=39.5,
    longitude=-98.35,
    zoom=3.5
)

st.pydeck_chart(
    pdk.Deck(
        map_style="mapbox://styles/mapbox/light-v10",
        layers=[map_layer],
        initial_view_state=view_state,
        tooltip={
            "html": "<b>{NAME10}</b><br/>Land: {LAND_KM2:.1f} km²<br/>Water: {WATER_KM2:.1f} km²",
            "style": {"color": "black"}
        }
    )
)


# --------------------------------------------------
# Analytical charts
# --------------------------------------------------
st.subheader("Urban Area Characteristics")

col_left, col_right = st.columns(2)

with col_left:
    fig_land = px.histogram(
        filtered,
        x="LAND_KM2",
        nbins=40,
        title="Distribution of Urban Land Area (km²)",
        labels={"LAND_KM2": "Land Area (km²)"}
    )
    st.plotly_chart(fig_land, use_container_width=True)

with col_right:
    fig_water = px.box(
        filtered,
        y="WATER_SHARE_PCT",
        title="Water Share Across Urban Areas (%)",
        labels={"WATER_SHARE_PCT": "Water Share (%)"}
    )
    st.plotly_chart(fig_water, use_container_width=True)

# --------------------------------------------------
# Top-ranked table
# --------------------------------------------------
st.subheader("Largest Urban Areas by Land Area")

top_areas = (
    filtered
    .sort_values("LAND_KM2", ascending=False)
    .loc[:, [
        "NAME10",
        "URBAN_TYPE",
        "FUNCSTAT10",
        "LAND_KM2",
        "WATER_KM2",
        "WATER_SHARE_PCT"
    ]]
    .head(15)
)

st.dataframe(
    top_areas.style.format({
        "LAND_KM2": "{:,.1f}",
        "WATER_KM2": "{:,.1f}",
        "WATER_SHARE_PCT": "{:.1f}%"
    }),
    use_container_width=True
)

# --------------------------------------------------
# Footer
# --------------------------------------------------
st.markdown("---")
st.caption(
    "Data source: United States Urban Areas Dataset (Homeland Infrastructure Foundation). "
    "All spatial points represent interior reference locations, not full urban boundaries."
)

