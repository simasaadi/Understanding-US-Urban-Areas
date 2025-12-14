import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# ------------------------------------------------------------
# Page setup
# ------------------------------------------------------------
st.set_page_config(page_title="Understanding US Urban Areas", page_icon="🗺️", layout="wide")

DATA_PATH = "data/Urban_Areas.csv"

SIZE_BINS = [-np.inf, 50, 500, 2000, np.inf]
SIZE_LABELS = ["Small (<50 km²)", "Medium (50–500 km²)", "Large (500–2000 km²)", "Mega (>2000 km²)"]

# Plotly map style that doesn't require tokens and has contrast
MAP_STYLE = "carto-positron"  # good light basemap with readable boundaries


# ------------------------------------------------------------
# Load + prepare data
# ------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_data(path: str):
    df = pd.read_csv(path)
    df.columns = df.columns.str.upper().str.strip()

    required = {"NAME10", "UACE10", "FUNCSTAT10", "ALAND10", "AWATER10", "INTPTLAT10", "INTPTLON10"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    for c in ["ALAND10", "AWATER10", "INTPTLAT10", "INTPTLON10"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["INTPTLAT10", "INTPTLON10", "ALAND10", "AWATER10"]).copy()

    df["LAND_KM2"] = df["ALAND10"] / 1_000_000
    df["WATER_KM2"] = df["AWATER10"] / 1_000_000
    df["TOTAL_AREA_KM2"] = df["LAND_KM2"] + df["WATER_KM2"]

    df["WATER_SHARE_PCT"] = np.where(df["TOTAL_AREA_KM2"] > 0, (df["WATER_KM2"] / df["TOTAL_AREA_KM2"]) * 100, np.nan)

    df["UACE10"] = df["UACE10"].astype(str).str.zfill(5)
    df["URBAN_TYPE"] = np.where(df["UACE10"].str.startswith("9"), "Urban Cluster (UC)", "Urbanized Area (UA)")

    # Size class as STRING (avoids pandas categorical mapping issues on Streamlit Cloud)
    df["SIZE_CLASS"] = pd.cut(df["LAND_KM2"], bins=SIZE_BINS, labels=SIZE_LABELS).astype(str)

    # Outliers: top 1% by land area
    p99 = df["LAND_KM2"].quantile(0.99)
    df["IS_OUTLIER_TOP1PCT"] = df["LAND_KM2"] >= p99

    return df, p99


df, p99 = load_data(DATA_PATH)

# ------------------------------------------------------------
# Sidebar filters
# ------------------------------------------------------------
st.sidebar.title("Filters")

urban_type_filter = st.sidebar.multiselect(
    "Urban Area Type",
    options=sorted(df["URBAN_TYPE"].unique()),
    default=sorted(df["URBAN_TYPE"].unique())
)

funcstat_values = sorted(df["FUNCSTAT10"].dropna().unique())
funcstat_filter = st.sidebar.multiselect(
    "Functional Status (FUNCSTAT10)",
    options=funcstat_values,
    default=funcstat_values
)

size_filter = st.sidebar.multiselect(
    "Size Class (Land Area)",
    options=SIZE_LABELS,
    default=SIZE_LABELS
)

min_land = st.sidebar.slider(
    "Minimum land area (km²)",
    min_value=0.0,
    max_value=float(df["LAND_KM2"].max()),
    value=0.0
)

show_only_outliers = st.sidebar.toggle("Show only extreme-scale (top 1%)", value=False)

filtered = df[
    (df["URBAN_TYPE"].isin(urban_type_filter)) &
    (df["FUNCSTAT10"].isin(funcstat_filter)) &
    (df["SIZE_CLASS"].isin(size_filter)) &
    (df["LAND_KM2"] >= min_land)
].copy()

if show_only_outliers:
    filtered = filtered[filtered["IS_OUTLIER_TOP1PCT"]].copy()

# ------------------------------------------------------------
# Header + KPIs
# ------------------------------------------------------------
st.title("Understanding US Urban Areas")
st.markdown(
    "A GIS-first dashboard using Census-defined urban areas. This view prioritizes **defensible spatial encodings** "
    "(density + weighted intensity), **long-tail distributions**, and **explicit outlier handling**."
)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Urban Areas", f"{len(filtered):,}")
k2.metric("Total Land (km²)", f"{filtered['LAND_KM2'].sum():,.0f}")
k3.metric("Total Water (km²)", f"{filtered['WATER_KM2'].sum():,.0f}")
k4.metric("Avg Water Share (%)", f"{filtered['WATER_SHARE_PCT'].mean():.2f}")
k5.metric("Top 1% threshold", f"{p99:,.0f} km²")

st.markdown("---")

# ------------------------------------------------------------
# 1) GIS MAPS (advanced + meaningful)
# ------------------------------------------------------------
st.subheader("Spatial Patterns (GIS-first)")

tab1, tab2 = st.tabs(["Weighted density (urban footprint intensity)", "Outliers as points (inspect the extremes)"])

with tab1:
    st.caption(
        "This is the correct map for thousands of points: a density surface. "
        "It is **weighted by land area (km²)**, so it represents *urban footprint intensity*, not just point counts."
    )

    # density_mapbox: weight by LAND_KM2 (the key upgrade)
    fig_density = px.density_mapbox(
        filtered,
        lat="INTPTLAT10",
        lon="INTPTLON10",
        z="LAND_KM2",
        radius=18,
        zoom=3.3,
        height=520,
        mapbox_style=MAP_STYLE,
        hover_name="NAME10",
        hover_data={"LAND_KM2": ":.1f", "WATER_SHARE_PCT": ":.1f", "URBAN_TYPE": True, "SIZE_CLASS": True}
    )
    fig_density.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig_density, use_container_width=True)

with tab2:
    st.caption(
        "Points only make sense when we reduce them to a meaningful subset. "
        "Here we show the **top 1%** as points, sized by land area."
    )

    outliers = filtered[filtered["IS_OUTLIER_TOP1PCT"]].sort_values("LAND_KM2", ascending=False).copy()
    if outliers.empty:
        st.info("No outliers under current filters. Turn off the outlier toggle or broaden filters.")
    else:
        fig_outliers = px.scatter_mapbox(
            outliers,
            lat="INTPTLAT10",
            lon="INTPTLON10",
            size=np.clip(outliers["LAND_KM2"], 1, outliers["LAND_KM2"].quantile(0.95)),
            color="SIZE_CLASS",
            hover_name="NAME10",
            hover_data={"LAND_KM2": ":.1f", "WATER_KM2": ":.1f", "WATER_SHARE_PCT": ":.1f", "URBAN_TYPE": True},
            zoom=3.3,
            height=520,
            mapbox_style=MAP_STYLE
        )
        fig_outliers.update_layout(margin=dict(l=0, r=0, t=0, b=0), legend_title_text="Size class")
        st.plotly_chart(fig_outliers, use_container_width=True)

st.markdown("---")

# ------------------------------------------------------------
# 2) SIZE TYPOLOGY (bar + ECDF = senior-level for long-tail)
# ------------------------------------------------------------
st.subheader("Urban Size Typology (Long-tail aware)")

left, right = st.columns(2)

size_counts = (
    filtered["SIZE_CLASS"].value_counts().reindex(SIZE_LABELS).fillna(0).astype(int).reset_index()
)
size_counts.columns = ["SIZE_CLASS", "COUNT"]
size_counts["SHARE_PCT"] = (size_counts["COUNT"] / size_counts["COUNT"].sum()) * 100

with left:
    fig_size_bar = px.bar(
        size_counts,
        x="SIZE_CLASS",
        y="COUNT",
        text="COUNT",
        title="Counts by size class (Land Area bins)",
        labels={"SIZE_CLASS": "Size class", "COUNT": "Urban areas"}
    )
    fig_size_bar.update_layout(xaxis_tickangle=-15)
    st.plotly_chart(fig_size_bar, use_container_width=True)

with right:
    # ECDF: best practice for skewed continuous distributions
    fig_ecdf = px.ecdf(
        filtered,
        x="LAND_KM2",
        color="URBAN_TYPE",
        title="ECDF of land area (km²) — shows the long-tail clearly",
        labels={"LAND_KM2": "Land Area (km²)", "y": "Cumulative share"}
    )
    fig_ecdf.update_xaxes(type="log")
    st.plotly_chart(fig_ecdf, use_container_width=True)

st.markdown("---")

# ------------------------------------------------------------
# 3) UA vs UC (bring back the strong chart: box + violin on log scale)
# ------------------------------------------------------------
st.subheader("Urbanized Areas vs Urban Clusters (Distribution + summary)")

c1, c2 = st.columns([1.2, 1])

with c1:
    fig_violin_box = px.violin(
        filtered,
        x="URBAN_TYPE",
        y="LAND_KM2",
        color="URBAN_TYPE",
        box=True,
        points="outliers",
        title="Land Area (km²): violin + box (log scale) for UA vs UC",
        labels={"URBAN_TYPE": "", "LAND_KM2": "Land Area (km²)"}
    )
    fig_violin_box.update_yaxes(type="log")
    fig_violin_box.update_layout(showlegend=False)
    st.plotly_chart(fig_violin_box, use_container_width=True)

with c2:
    summary = (
        filtered.groupby("URBAN_TYPE", as_index=False)
        .agg(
            count=("NAME10", "count"),
            mean_land=("LAND_KM2", "mean"),
            median_land=("LAND_KM2", "median"),
            mean_water_share=("WATER_SHARE_PCT", "mean")
        )
    )

    fig_compare = px.bar(
        summary,
        x="URBAN_TYPE",
        y="mean_land",
        text=summary["mean_land"].map(lambda v: f"{v:.1f}"),
        title="Mean land area by type",
        labels={"URBAN_TYPE": "", "mean_land": "Mean land area (km²)"}
    )
    st.plotly_chart(fig_compare, use_container_width=True)

st.dataframe(
    summary.style.format({"mean_land": "{:.1f}", "median_land": "{:.1f}", "mean_water_share": "{:.2f}%"}),
    use_container_width=True
)

st.markdown("---")

# ------------------------------------------------------------
# 4) OUTLIER ANALYSIS (ranked + contribution = actually insightful)
# ------------------------------------------------------------
st.subheader("Outlier Analysis (Top 1% by land area)")

out_all = df[df["IS_OUTLIER_TOP1PCT"]].copy()
out_all = out_all.sort_values("LAND_KM2", ascending=False)

topN = st.slider("Top N outliers", 10, 50, 20, step=5)

top_out = out_all.head(topN).copy()
top_out["LAND_SHARE_PCT_OF_ALL"] = (top_out["LAND_KM2"] / df["LAND_KM2"].sum()) * 100

o1, o2 = st.columns(2)

with o1:
    fig_top = px.bar(
        top_out[::-1],
        x="LAND_KM2",
        y="NAME10",
        orientation="h",
        title=f"Top {topN} urban areas by land area (km²)",
        labels={"LAND_KM2": "Land Area (km²)", "NAME10": ""}
    )
    st.plotly_chart(fig_top, use_container_width=True)

with o2:
    fig_share = px.bar(
        top_out[::-1],
        x="LAND_SHARE_PCT_OF_ALL",
        y="NAME10",
        orientation="h",
        title=f"Contribution to total US urban land (Top {topN})",
        labels={"LAND_SHARE_PCT_OF_ALL": "Share of total land (%)", "NAME10": ""}
    )
    st.plotly_chart(fig_share, use_container_width=True)

st.dataframe(
    top_out[["NAME10", "URBAN_TYPE", "FUNCSTAT10", "LAND_KM2", "WATER_KM2", "WATER_SHARE_PCT"]]
    .style.format({"LAND_KM2": "{:,.1f}", "WATER_KM2": "{:,.1f}", "WATER_SHARE_PCT": "{:.1f}%"}),
    use_container_width=True
)

st.markdown("---")

# ------------------------------------------------------------
# 5) Functional status (don’t force charts if the data is single-class)
# ------------------------------------------------------------
st.subheader("Functional Status (FUNCSTAT10)")

fs_unique = sorted(filtered["FUNCSTAT10"].dropna().unique())
if len(fs_unique) <= 1:
    st.info(
        f"Under current filters, FUNCSTAT10 has a single value: **{fs_unique[0] if fs_unique else 'None'}**. "
        "A bar chart would be noise here, so this section is intentionally summarized."
    )
else:
    fs_counts = filtered["FUNCSTAT10"].value_counts().reset_index()
    fs_counts.columns = ["FUNCSTAT10", "COUNT"]

    fig_fs = px.bar(
        fs_counts,
        x="FUNCSTAT10",
        y="COUNT",
        title="Urban areas by functional status",
        labels={"FUNCSTAT10": "FUNCSTAT10", "COUNT": "Urban areas"}
    )
    st.plotly_chart(fig_fs, use_container_width=True)

    fs_means = (
        filtered.groupby("FUNCSTAT10", as_index=False)
        .agg(mean_land=("LAND_KM2", "mean"), mean_water_share=("WATER_SHARE_PCT", "mean"))
        .sort_values("mean_land", ascending=False)
    )

    fig_fs2 = px.bar(
        fs_means,
        x="FUNCSTAT10",
        y="mean_land",
        title="Mean land area by functional status",
        labels={"FUNCSTAT10": "FUNCSTAT10", "mean_land": "Mean land area (km²)"}
    )
    st.plotly_chart(fig_fs2, use_container_width=True)

st.markdown("---")
st.caption(
    "Note: coordinates are interior reference points for each urban area (not boundaries). "
    "The density map is weighted by land area to represent spatial concentration of urban footprint."
)
