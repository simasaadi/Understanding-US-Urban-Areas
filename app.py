import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import pydeck as pdk

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(
    page_title="Understanding US Urban Areas",
    page_icon="🗺️",
    layout="wide"
)

# -----------------------------
# Constants
# -----------------------------
DATA_PATH = "data/Urban_Areas.csv"

SIZE_BINS = [-np.inf, 50, 500, 2000, np.inf]
SIZE_LABELS = ["Small (<50 km²)", "Medium (50–500 km²)", "Large (500–2000 km²)", "Mega (>2000 km²)"]

# A basemap that is light but not washed out
MAP_STYLE = "mapbox://styles/mapbox/light-v10"  # if you want slightly darker: "mapbox://styles/mapbox/streets-v12"


# -----------------------------
# Load + prepare data
# -----------------------------
@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = df.columns.str.upper().str.strip()

    # Required columns check (fail loudly, not silently)
    required = {"NAME10", "UACE10", "FUNCSTAT10", "ALAND10", "AWATER10", "INTPTLAT10", "INTPTLON10"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")

    # Coerce numerics
    for c in ["ALAND10", "AWATER10", "INTPTLAT10", "INTPTLON10"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Drop unusable rows
    df = df.dropna(subset=["INTPTLAT10", "INTPTLON10", "ALAND10", "AWATER10"]).copy()

    # Derived metrics (m² -> km²)
    df["LAND_KM2"] = df["ALAND10"] / 1_000_000
    df["WATER_KM2"] = df["AWATER10"] / 1_000_000
    df["TOTAL_AREA_KM2"] = df["LAND_KM2"] + df["WATER_KM2"]

    df["WATER_SHARE_PCT"] = np.where(
        df["TOTAL_AREA_KM2"] > 0,
        (df["WATER_KM2"] / df["TOTAL_AREA_KM2"]) * 100,
        np.nan
    )

    # UA vs UC (defensive: treat UACE10 as string)
    df["UACE10"] = df["UACE10"].astype(str).str.zfill(5)
    df["URBAN_TYPE"] = np.where(df["UACE10"].str.startswith("9"), "Urban Cluster (UC)", "Urbanized Area (UA)")

    # Size typology
    df["SIZE_CLASS"] = pd.cut(df["LAND_KM2"], bins=SIZE_BINS, labels=SIZE_LABELS)

    # Outliers: top 1% by LAND_KM2
    p99 = df["LAND_KM2"].quantile(0.99)
    df["IS_OUTLIER_TOP1PCT"] = df["LAND_KM2"] >= p99
    df["OUTLIER_THRESHOLD_KM2"] = p99  # for display

    return df


df = load_data(DATA_PATH)

# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.title("Filters")

urban_type_filter = st.sidebar.multiselect(
    "Urban Area Type",
    options=sorted(df["URBAN_TYPE"].unique()),
    default=sorted(df["URBAN_TYPE"].unique())
)

funcstat_filter = st.sidebar.multiselect(
    "Functional Status (FUNCSTAT10)",
    options=sorted(df["FUNCSTAT10"].dropna().unique()),
    default=sorted(df["FUNCSTAT10"].dropna().unique())
)

size_class_filter = st.sidebar.multiselect(
    "Size Class (Land Area)",
    options=[c for c in SIZE_LABELS if c in df["SIZE_CLASS"].astype(str).unique()],
    default=[c for c in SIZE_LABELS if c in df["SIZE_CLASS"].astype(str).unique()]
)

min_land = st.sidebar.slider(
    "Minimum land area (km²)",
    min_value=0.0,
    max_value=float(np.nanmax(df["LAND_KM2"])),
    value=0.0
)

show_only_outliers = st.sidebar.toggle(
    "Show only outliers (top 1% land area)",
    value=False
)

# Map controls
st.sidebar.subheader("Map settings")
map_mode = st.sidebar.radio(
    "Map layer",
    options=["Hex density (recommended)", "Points (outliers only)"],
    index=0
)

hex_radius = st.sidebar.slider(
    "Hex radius (meters)",
    min_value=30000,
    max_value=120000,
    value=60000,
    step=10000,
    help="Bigger radius = smoother pattern; smaller = more detail."
)

# -----------------------------
# Apply filters
# -----------------------------
filtered = df[
    (df["URBAN_TYPE"].isin(urban_type_filter)) &
    (df["FUNCSTAT10"].isin(funcstat_filter)) &
    (df["SIZE_CLASS"].astype(str).isin(size_class_filter)) &
    (df["LAND_KM2"] >= min_land)
].copy()

if show_only_outliers:
    filtered = filtered[filtered["IS_OUTLIER_TOP1PCT"]].copy()

# -----------------------------
# Header
# -----------------------------
st.title("Understanding US Urban Areas")
st.markdown(
    """
    This dashboard explores Census-defined **Urbanized Areas (UAs)** and **Urban Clusters (UCs)** using land/water area
    and interior-point coordinates. Key emphasis: **scale typology**, **UA vs UC contrasts**, and **outlier identification**.
    """
)

# -----------------------------
# KPIs
# -----------------------------
k1, k2, k3, k4, k5 = st.columns(5)

k1.metric("Urban Areas", f"{len(filtered):,}")

k2.metric("Total Land (km²)", f"{filtered['LAND_KM2'].sum():,.0f}")
k3.metric("Total Water (km²)", f"{filtered['WATER_KM2'].sum():,.0f}")
k4.metric("Avg Water Share (%)", f"{filtered['WATER_SHARE_PCT'].mean():.1f}")

# show threshold even when not toggled (this is a real analytic signal)
p99 = df["LAND_KM2"].quantile(0.99)
k5.metric("Outlier threshold (top 1%)", f"{p99:,.0f} km²")

# -----------------------------
# Section 1: Map (fixed)
# -----------------------------
st.subheader("Spatial Patterns")
st.caption(
    "The default map uses a hexagon density layer to avoid unreadable point clouds. "
    "Switch to points to inspect outliers."
)

# Base view (continental US)
view_state = pdk.ViewState(latitude=39.5, longitude=-98.35, zoom=3.5)

layers = []

if map_mode == "Hex density (recommended)":
    # Use hexagon aggregation; weight by LAND_KM2 to show "where large urban footprint concentrates"
    hex_layer = pdk.Layer(
        "HexagonLayer",
        data=filtered,
        get_position=["INTPTLON10", "INTPTLAT10"],
        radius=hex_radius,
        elevation_scale=30,
        elevation_range=[0, 3000],
        extruded=True,
        coverage=0.9,
        pickable=True,
        # This is key: show not just counts, but weighted land area signal
        get_weight="LAND_KM2"
    )
    layers.append(hex_layer)

    deck = pdk.Deck(
        map_style=MAP_STYLE,
        initial_view_state=view_state,
        layers=layers,
        tooltip={
            "html": "<b>Hex cell</b><br/>Aggregated land-area signal (weighted)<br/>Zoom in for more detail.",
            "style": {"color": "black"}
        }
    )
    st.pydeck_chart(deck, use_container_width=True)

else:
    # Points only makes sense when limited; enforce outliers for clarity
    outliers = filtered[filtered["IS_OUTLIER_TOP1PCT"]].copy()
    if outliers.empty:
        st.info("No outliers in the current filter selection. Turn off 'Show only outliers' or broaden filters.")
    else:
        # Color by size class using RGBA arrays
        color_map = {
            "Small (<50 km²)": [49, 130, 189, 160],
            "Medium (50–500 km²)": [107, 174, 214, 160],
            "Large (500–2000 km²)": [239, 138, 98, 170],
            "Mega (>2000 km²)": [203, 24, 29, 190],
        }
        outliers["COLOR"] = outliers["SIZE_CLASS"].astype(str).map(color_map).fillna([0, 0, 0, 140])

        point_layer = pdk.Layer(
            "ScatterplotLayer",
            data=outliers,
            get_position=["INTPTLON10", "INTPTLAT10"],
            get_fill_color="COLOR",
            get_radius=60000,
            pickable=True,
            stroked=True,
            get_line_color=[0, 0, 0, 120],
            line_width_min_pixels=1
        )
        st.pydeck_chart(
            pdk.Deck(
                map_style=MAP_STYLE,
                initial_view_state=view_state,
                layers=[point_layer],
                tooltip={
                    "html": (
                        "<b>{NAME10}</b><br/>"
                        "{URBAN_TYPE}<br/>"
                        "Land: {LAND_KM2:.1f} km²<br/>"
                        "Water: {WATER_KM2:.1f} km²<br/>"
                        "Water share: {WATER_SHARE_PCT:.1f}%<br/>"
                        "<i>{SIZE_CLASS}</i>"
                    ),
                    "style": {"color": "black"}
                }
            ),
            use_container_width=True
        )

# -----------------------------
# Section 2: Size typology (bins + bar chart)
# -----------------------------
st.subheader("Urban Size Typology")
left, right = st.columns([1, 1])

size_counts = (
    filtered["SIZE_CLASS"]
    .astype(str)
    .value_counts()
    .reindex(SIZE_LABELS)
    .dropna()
    .reset_index()
)
size_counts.columns = ["SIZE_CLASS", "COUNT"]

with left:
    fig_typology = px.bar(
        size_counts,
        x="SIZE_CLASS",
        y="COUNT",
        title="Count of Urban Areas by Size Class (Land Area)",
        labels={"SIZE_CLASS": "Size class", "COUNT": "Urban areas"}
    )
    fig_typology.update_layout(xaxis_tickangle=-15)
    st.plotly_chart(fig_typology, use_container_width=True)

with right:
    fig_land_dist = px.histogram(
        filtered,
        x="LAND_KM2",
        nbins=50,
        title="Distribution of Land Area (km²) — Long-tail",
        labels={"LAND_KM2": "Land Area (km²)"}
    )
    st.plotly_chart(fig_land_dist, use_container_width=True)

# -----------------------------
# Section 3: UA vs UC comparative analytics
# -----------------------------
st.subheader("UA vs UC Comparison")

c1, c2 = st.columns([1, 1])

with c1:
    fig_box = px.box(
        filtered,
        x="URBAN_TYPE",
        y="LAND_KM2",
        points=False,
        title="Land Area (km²) by Urban Type (UA vs UC)",
        labels={"URBAN_TYPE": "", "LAND_KM2": "Land Area (km²)"}
    )
    # Log scale helps long-tail readability without hiding structure
    fig_box.update_yaxes(type="log")
    st.plotly_chart(fig_box, use_container_width=True)

with c2:
    summary_by_type = (
        filtered.groupby("URBAN_TYPE", as_index=False)
        .agg(
            count=("NAME10", "count"),
            mean_land_km2=("LAND_KM2", "mean"),
            median_land_km2=("LAND_KM2", "median"),
            mean_water_share=("WATER_SHARE_PCT", "mean")
        )
    )
    fig_summary = px.bar(
        summary_by_type,
        x="URBAN_TYPE",
        y="mean_land_km2",
        title="Mean Land Area (km²) by Urban Type",
        labels={"URBAN_TYPE": "", "mean_land_km2": "Mean land area (km²)"}
    )
    st.plotly_chart(fig_summary, use_container_width=True)

st.dataframe(
    summary_by_type.style.format({
        "mean_land_km2": "{:,.1f}",
        "median_land_km2": "{:,.1f}",
        "mean_water_share": "{:.1f}%",
    }),
    use_container_width=True
)

# -----------------------------
# Section 4: Outlier analysis (top 1%)
# -----------------------------
st.subheader("Outlier Analysis (Top 1% by Land Area)")

outliers_all = df[df["IS_OUTLIER_TOP1PCT"]].sort_values("LAND_KM2", ascending=False).copy()
outliers_filtered = filtered[filtered["IS_OUTLIER_TOP1PCT"]].sort_values("LAND_KM2", ascending=False).copy()

o1, o2 = st.columns([1, 1])

with o1:
    st.markdown("**Outliers across the full dataset**")
    st.dataframe(
        outliers_all.loc[:, ["NAME10", "URBAN_TYPE", "FUNCSTAT10", "LAND_KM2", "WATER_KM2", "WATER_SHARE_PCT", "SIZE_CLASS"]]
        .head(20)
        .style.format({
            "LAND_KM2": "{:,.1f}",
            "WATER_KM2": "{:,.1f}",
            "WATER_SHARE_PCT": "{:.1f}%"
        }),
        use_container_width=True
    )

with o2:
    st.markdown("**Outliers within your current filter selection**")
    if outliers_filtered.empty:
        st.info("No outliers under current filters. Broaden filters or turn off 'Show only outliers'.")
    else:
        st.dataframe(
            outliers_filtered.loc[:, ["NAME10", "URBAN_TYPE", "FUNCSTAT10", "LAND_KM2", "WATER_KM2", "WATER_SHARE_PCT", "SIZE_CLASS"]]
            .head(20)
            .style.format({
                "LAND_KM2": "{:,.1f}",
                "WATER_KM2": "{:,.1f}",
                "WATER_SHARE_PCT": "{:.1f}%"
            }),
            use_container_width=True
        )

# -----------------------------
# Section 5: Functional status storytelling
# -----------------------------
st.subheader("Functional Status (FUNCSTAT10)")

fs_left, fs_right = st.columns([1, 1])

func_counts = (
    filtered["FUNCSTAT10"]
    .astype(str)
    .value_counts()
    .reset_index()
)
func_counts.columns = ["FUNCSTAT10", "COUNT"]

with fs_left:
    fig_fs = px.bar(
        func_counts,
        x="FUNCSTAT10",
        y="COUNT",
        title="Urban Areas by Functional Status",
        labels={"FUNCSTAT10": "FUNCSTAT10", "COUNT": "Urban areas"}
    )
    st.plotly_chart(fig_fs, use_container_width=True)

with fs_right:
    func_means = (
        filtered.groupby("FUNCSTAT10", as_index=False)
        .agg(
            count=("NAME10", "count"),
            mean_land_km2=("LAND_KM2", "mean"),
            mean_water_share=("WATER_SHARE_PCT", "mean")
        )
        .sort_values("mean_land_km2", ascending=False)
    )

    fig_fs_mean = px.bar(
        func_means,
        x="FUNCSTAT10",
        y="mean_land_km2",
        title="Mean Land Area (km²) by Functional Status",
        labels={"FUNCSTAT10": "FUNCSTAT10", "mean_land_km2": "Mean land area (km²)"}
    )
    st.plotly_chart(fig_fs_mean, use_container_width=True)

st.dataframe(
    func_means.style.format({
        "mean_land_km2": "{:,.1f}",
        "mean_water_share": "{:.1f}%"
    }),
    use_container_width=True
)

# -----------------------------
# Appendix: Top table
# -----------------------------
st.subheader("Largest Urban Areas (Current Filters)")

top_n = st.slider("Show top N", min_value=10, max_value=100, value=25, step=5)

top_table = (
    filtered.sort_values("LAND_KM2", ascending=False)
    .loc[:, ["NAME10", "URBAN_TYPE", "FUNCSTAT10", "LAND_KM2", "WATER_KM2", "WATER_SHARE_PCT", "SIZE_CLASS"]]
    .head(top_n)
)

st.dataframe(
    top_table.style.format({
        "LAND_KM2": "{:,.1f}",
        "WATER_KM2": "{:,.1f}",
        "WATER_SHARE_PCT": "{:.1f}%"
    }),
    use_container_width=True
)

st.markdown("---")
st.caption(
    "Notes: Coordinates represent interior points for each urban area, not full boundaries. "
    "Hexagon map aggregates urban areas spatially and weights by land area to reduce point clutter and surface spatial patterns."
)
