import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import pydeck as pdk

# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(
    page_title="Understanding US Urban Areas",
    page_icon="🗺️",
    layout="wide"
)

DATA_PATH = "data/Urban_Areas.csv"

SIZE_BINS = [-np.inf, 50, 500, 2000, np.inf]
SIZE_LABELS = [
    "Small (<50 km²)",
    "Medium (50–500 km²)",
    "Large (500–2000 km²)",
    "Mega (>2000 km²)"
]

SIZE_COLORS = {
    "Small (<50 km²)": [198, 219, 239, 180],
    "Medium (50–500 km²)": [158, 202, 225, 180],
    "Large (500–2000 km²)": [107, 174, 214, 200],
    "Mega (>2000 km²)": [33, 113, 181, 220],
}

MAP_STYLE = "mapbox://styles/mapbox/dark-v11"

# -----------------------------
# Load data
# -----------------------------
@st.cache_data
def load_data():
    df = pd.read_csv(DATA_PATH)
    df.columns = df.columns.str.upper()

    df["ALAND10"] = pd.to_numeric(df["ALAND10"], errors="coerce")
    df["AWATER10"] = pd.to_numeric(df["AWATER10"], errors="coerce")

    df = df.dropna(subset=["INTPTLAT10", "INTPTLON10", "ALAND10", "AWATER10"])

    df["LAND_KM2"] = df["ALAND10"] / 1_000_000
    df["WATER_KM2"] = df["AWATER10"] / 1_000_000
    df["TOTAL_AREA_KM2"] = df["LAND_KM2"] + df["WATER_KM2"]

    df["WATER_SHARE_PCT"] = (df["WATER_KM2"] / df["TOTAL_AREA_KM2"]) * 100

    df["UACE10"] = df["UACE10"].astype(str).str.zfill(5)
    df["URBAN_TYPE"] = np.where(
        df["UACE10"].str.startswith("9"),
        "Urban Cluster (UC)",
        "Urbanized Area (UA)"
    )

    df["SIZE_CLASS"] = pd.cut(df["LAND_KM2"], SIZE_BINS, labels=SIZE_LABELS)

    p99 = df["LAND_KM2"].quantile(0.99)
    df["IS_OUTLIER"] = df["LAND_KM2"] >= p99

    return df, p99


df, p99 = load_data()

# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.title("Filters")

urban_type = st.sidebar.multiselect(
    "Urban Area Type",
    df["URBAN_TYPE"].unique(),
    default=df["URBAN_TYPE"].unique()
)

size_class = st.sidebar.multiselect(
    "Size Class",
    SIZE_LABELS,
    default=SIZE_LABELS
)

show_outliers = st.sidebar.toggle("Show only extreme-scale urban areas (top 1%)")

filtered = df[
    df["URBAN_TYPE"].isin(urban_type) &
    df["SIZE_CLASS"].isin(size_class)
]

if show_outliers:
    filtered = filtered[filtered["IS_OUTLIER"]]

# -----------------------------
# Header
# -----------------------------
st.title("Understanding US Urban Areas")
st.markdown(
    """
    **Visual analytics of Census-defined urban areas**, focusing on scale, spatial structure,
    and the dominance of a small number of extremely large urban footprints.
    """
)

# -----------------------------
# KPIs
# -----------------------------
c1, c2, c3, c4 = st.columns(4)

c1.metric("Urban Areas", f"{len(filtered):,}")
c2.metric("Total Land (km²)", f"{filtered['LAND_KM2'].sum():,.0f}")
c3.metric("Avg. Urban Size (km²)", f"{filtered['LAND_KM2'].mean():.1f}")
c4.metric("Outlier Threshold (km²)", f"{p99:,.0f}")

# -----------------------------
# MAP — size-class dominant hexes
# -----------------------------
st.subheader("Spatial Structure of Urban Scale")
st.caption("Hexagons are colored by the **dominant urban size class** within each cell.")

# Make mapping robust (categorical-safe)
filtered["SIZE_CLASS_STR"] = filtered["SIZE_CLASS"].astype(str)

filtered["COLOR"] = filtered["SIZE_CLASS_STR"].map(SIZE_COLORS)

# Fallback color if anything unexpected appears
filtered["COLOR"] = filtered["COLOR"].apply(
    lambda v: v if isinstance(v, (list, tuple)) and len(v) == 4 else [160, 160, 160, 140]
)


hex_layer = pdk.Layer(
    "HexagonLayer",
    data=filtered,
    get_position=["INTPTLON10", "INTPTLAT10"],
    radius=70000,
    coverage=0.95,
    extruded=False,
    pickable=True,
    get_fill_color="COLOR"
)

st.pydeck_chart(
    pdk.Deck(
        map_style=MAP_STYLE,
        layers=[hex_layer],
        initial_view_state=pdk.ViewState(latitude=39.5, longitude=-98.35, zoom=3.6),
        tooltip={"html": "Urban scale concentration"}
    ),
    use_container_width=True
)

# -----------------------------
# SIZE TYPOLOGY — ordered + cumulative
# -----------------------------
st.subheader("Urban Size Typology")

size_counts = (
    filtered["SIZE_CLASS"]
    .value_counts()
    .reindex(SIZE_LABELS)
    .reset_index()
)
size_counts.columns = ["Size Class", "Count"]
size_counts["Share (%)"] = size_counts["Count"] / size_counts["Count"].sum() * 100
size_counts["Cumulative Share (%)"] = size_counts["Share (%)"].cumsum()

left, right = st.columns([1, 1])

with left:
    fig_bar = px.bar(
        size_counts,
        x="Size Class",
        y="Count",
        title="Urban Areas by Size Class",
        text="Count"
    )
    fig_bar.update_layout(xaxis_tickangle=-15)
    st.plotly_chart(fig_bar, use_container_width=True)

with right:
    fig_cum = px.line(
        size_counts,
        x="Size Class",
        y="Cumulative Share (%)",
        markers=True,
        title="Cumulative Share of Urban Areas by Size"
    )
    fig_cum.update_yaxes(range=[0, 100])
    st.plotly_chart(fig_cum, use_container_width=True)

# -----------------------------
# UA vs UC — violin + interpretation
# -----------------------------
st.subheader("Urbanized Areas vs Urban Clusters")

fig_violin = px.violin(
    filtered,
    x="URBAN_TYPE",
    y="LAND_KM2",
    box=True,
    points=False,
    log_y=True,
    title="Distribution of Urban Land Area (log scale)"
)

st.plotly_chart(fig_violin, use_container_width=True)

summary = (
    filtered.groupby("URBAN_TYPE")
    .agg(
        count=("NAME10", "count"),
        mean_land=("LAND_KM2", "mean"),
        median_land=("LAND_KM2", "median")
    )
    .reset_index()
)

st.dataframe(
    summary.style.format({
        "mean_land": "{:.1f}",
        "median_land": "{:.1f}"
    }),
    use_container_width=True
)

st.markdown(
    """
    **Interpretation:**  
    Urbanized Areas are fewer in number but dominate total land coverage.
    Urban Clusters are numerous but overwhelmingly small in spatial footprint.
    """
)

# -----------------------------
# OUTLIERS — ranked + spatial meaning
# -----------------------------
st.subheader("Extreme-Scale Urban Areas (Top 1%)")

outliers = df[df["IS_OUTLIER"]].sort_values("LAND_KM2", ascending=False)

st.dataframe(
    outliers[
        ["NAME10", "URBAN_TYPE", "LAND_KM2", "WATER_SHARE_PCT"]
    ].head(15).style.format({
        "LAND_KM2": "{:,.1f}",
        "WATER_SHARE_PCT": "{:.1f}%"
    }),
    use_container_width=True
)

st.markdown(
    """
    These urban areas **dominate national urban land coverage** and
    should be treated separately in planning, infrastructure, and policy analysis.
    """
)

# -----------------------------
# FOOTER
# -----------------------------
st.markdown("---")
st.caption(
    "Data: United States Urban Areas Dataset (Homeland Infrastructure Foundation). "
    "Coordinates represent interior reference points, not full urban boundaries."
)
