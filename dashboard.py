import streamlit as st
import mysql.connector
import pandas as pd
import os 


# =========================
# MySQL
# =========================
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST", "localhost"),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DATABASE", "flight_price")
)


# =========================
# Load flight history
# =========================

query = """
SELECT
    fr.itinerary_key,
    fs.flight_no,
    fs.airline,
    fr.departure_datetime,
    fr.arrival_datetime,
    fp.price,
    fp.collected_at,
    fse.search_id,
    fse.origin_city_code,
    fse.destination_city_code,
    fse.outbound_date
FROM flight_routes fr
JOIN flight_sectors fs
    ON fr.route_id = fs.route_id
JOIN flight_prices fp
    ON fr.route_id = fp.route_id
JOIN flight_searches fse
    ON fr.search_id = fse.search_id
ORDER BY fp.collected_at
"""

df = pd.read_sql(query, conn)

conn.close()


# =========================
# Page
# =========================

st.set_page_config(
    page_title="Flight Price Tracker",
    layout="wide"
)

st.title("✈️ Flight Price Tracker")


# =========================
# Route selector
# =========================

destination_map = {
    "東京": "TYO",
    "大阪": "KIX",
    "首爾": "ICN",
    "曼谷": "BKK",
    "香港": "HKG"
}

destination_name = st.selectbox(
    "選擇目的地",
    list(destination_map.keys())
)

destination = destination_map[destination_name]


direction = st.selectbox(
    "選擇方向",
    ["去程", "回程"]
)

flight_dates = (
    pd.to_datetime(df["departure_datetime"])
    .dt.strftime("%Y-%m-%d")
    .drop_duplicates()
    .sort_values()
    .tolist()
)

selected_date = st.selectbox(
    "選擇航班日期",
    flight_dates
)


if direction == "去程":

    df = df[
        (df["origin_city_code"] == "TPE") &
        (df["destination_city_code"] == destination) &
        (pd.to_datetime(df["departure_datetime"]).dt.strftime("%Y-%m-%d") == selected_date)
    ].copy()

else:

    df = df[
        (df["origin_city_code"] == destination) &
        (df["destination_city_code"] == "TPE") &
        (pd.to_datetime(df["departure_datetime"]).dt.strftime("%Y-%m-%d") == selected_date)
    ].copy()


if df.empty:
    st.warning("目前沒有此路線的航班資料。")
    st.stop()

latest_search_id = df["search_id"].max()

latest_df = df[
    df["search_id"] == latest_search_id
].copy()

if latest_df.empty:
    st.warning("目前沒有最新的航班資料。")
    st.stop()
# =========================
# Route information
# =========================

origin = df.iloc[0]["origin_city_code"]
destination = df.iloc[0]["destination_city_code"]
flight_date = df.iloc[0]["departure_datetime"]

st.caption(
    f"{origin} → {destination}｜"
    f"{pd.to_datetime(flight_date).strftime('%Y-%m-%d')}"
)


# =========================
# Flight selector
# =========================
latest_collected_at = df["collected_at"].max()

latest_df = df[
    df["collected_at"] == latest_collected_at
].copy()

flight_options_df = (
    latest_df[
        [
            "flight_no",
            "airline",
            "departure_datetime",
            "arrival_datetime",
            "itinerary_key"
        ]
    ]
    .drop_duplicates(subset=["itinerary_key"])
    .reset_index(drop=True)
)


flight_options_df["departure_time"] = (
    pd.to_datetime(
        flight_options_df["departure_datetime"]
    ).dt.strftime("%H:%M")
)

flight_options_df["arrival_time"] = (
    pd.to_datetime(
        flight_options_df["arrival_datetime"]
    ).dt.strftime("%H:%M")
)


flight_options_df["flight_date"] = (
    pd.to_datetime(
        flight_options_df["departure_datetime"]
    ).dt.strftime("%Y-%m-%d")
)

flight_options_df["flight_label"] = (
    flight_options_df["flight_no"]
    + " - "
    + flight_options_df["airline"]
    + "｜"
    + flight_options_df["departure_time"]
    + " → "
    + flight_options_df["arrival_time"]
    + "｜"
    + flight_options_df["flight_date"]
)


selected_flight = st.selectbox(
    "選擇航班",
    flight_options_df["flight_label"].tolist()
)


selected_option = flight_options_df[
    flight_options_df["flight_label"] == selected_flight
].iloc[0]

departure_time = pd.to_datetime(
    selected_option["departure_datetime"]
).strftime("%Y-%m-%d %H:%M")

arrival_time = pd.to_datetime(
    selected_option["arrival_datetime"]
).strftime("%Y-%m-%d %H:%M")

duration = (
    pd.to_datetime(selected_option["arrival_datetime"])
    - pd.to_datetime(selected_option["departure_datetime"])
)

duration_minutes = int(duration.total_seconds() / 60)

hours = duration_minutes // 60
minutes = duration_minutes % 60

# =========================
# Selected flight history
# =========================

selected_df = df[
    df["itinerary_key"] == selected_option["itinerary_key"]
].copy()


selected_df = selected_df.sort_values(
    "collected_at"
)

selected_df["collected_date"] = (
    pd.to_datetime(selected_df["collected_at"]).dt.date
)

# ==============================
# Daily price aggregation
# ==============================

selected_df["collected_date"] = (
    pd.to_datetime(selected_df["collected_at"]).dt.date
)

daily_price_df = (
    selected_df
    .groupby("collected_date", as_index=False)["price"]
    .min()
    .sort_values("collected_date")
)

# ==============================
# Price metrics
# ==============================

current_price = daily_price_df.iloc[-1]["price"]
lowest_price = daily_price_df["price"].min()

if len(daily_price_df) >= 2:
    previous_price = daily_price_df.iloc[-2]["price"]

    price_change = current_price - previous_price

    change_percent = (
        price_change / previous_price * 100
    )
else:
    price_change = None
    change_percent = None

# =========================
# Metrics
# =========================

st.subheader("航班資訊")

info_col1, info_col2, info_col3, _ = st.columns([1, 1, 1, 2]) 

with info_col1:
    st.write("**出發**")
    st.write(departure_time)

with info_col2:
    st.write("**抵達**")
    st.write(arrival_time)

with info_col3:
    st.write("**飛行時間**")
    st.write(f"{hours} 小時 {minutes} 分鐘")

col1, col2, col3, col4, col5 = st.columns(5)


with col1:

    st.metric(
        "航班",
        selected_option["flight_no"]
    )


with col2:

    st.metric(
        "航空公司",
        selected_option["airline"]
    )


with col3:

    if price_change is not None:
        st.metric(
            "目前價格",
            f"NT$ {current_price:,}",
            delta=f"{price_change:+,} NT$ ({change_percent:+.2f}%)"
        )

        st.caption(
            f"上次查詢：NT$ {previous_price:,}"
        )

    else:
        st.metric(
            "目前價格",
            f"NT$ {current_price:,}"
        )

        st.caption("上次查詢：—")


with col4:

    if len(daily_price_df) >= 2:
        st.metric(
            "上次查詢",
            f"NT$ {previous_price:,}"
        )
    else:
        st.metric(
            "上次查詢",
            "—"
        )


with col5:

    st.metric(
        "歷史最低價",
        f"NT$ {lowest_price:,}"
    )
# =========================
# Historical price list
# =========================

st.subheader("歷史價格紀錄")

history_list_df = selected_df[
    [
        "collected_at",
        "price"
    ]
].copy()

history_list_df["collected_at"] = pd.to_datetime(
    history_list_df["collected_at"]
)

history_list_df = (
    history_list_df
    .sort_values("collected_at", ascending=False)
    .rename(
        columns={
            "collected_at": "查詢時間",
            "price": "價格"
        }
    )
)

history_list_df["價格"] = (
    history_list_df["價格"]
    .apply(lambda x: f"NT$ {x:,}")
)

st.dataframe(
    history_list_df,
    use_container_width=True,
    hide_index=True
)
# =========================
# All flight minimum prices
# =========================

st.subheader("所有航班最低價格比較")

comparison_df = (
    df.groupby(
        [
            "itinerary_key",
            "flight_no",
            "airline",
            "departure_datetime",
            "arrival_datetime"
        ],
        as_index=False
    )["price"]
    .min()
)

comparison_df = comparison_df.sort_values(
    "price"
).reset_index(drop=True)

comparison_df["出發"] = pd.to_datetime(
    comparison_df["departure_datetime"]
).dt.strftime("%H:%M")

comparison_df["抵達"] = pd.to_datetime(
    comparison_df["arrival_datetime"]
).dt.strftime("%H:%M")

comparison_df["最低價格"] = comparison_df["price"].apply(
    lambda x: f"NT$ {x:,}"
)

comparison_display_df = comparison_df[
    [
        "flight_no",
        "airline",
        "出發",
        "抵達",
        "最低價格"
    ]
].copy()

comparison_display_df = comparison_display_df.rename(
    columns={
        "flight_no": "航班",
        "airline": "航空公司"
    }
)

st.dataframe(
    comparison_display_df,
    use_container_width=True,
    hide_index=True
)

# =========================
# Price history
# =========================

st.subheader("價格歷史")

chart_df = daily_price_df.copy()

chart_df["collected_date"] = pd.to_datetime(
    chart_df["collected_date"]
)

date_range = st.selectbox(
    "時間範圍",
    ["最近 7 天", "最近 30 天", "全部"]
)

if date_range == "最近 7 天":
    start_date = chart_df["collected_date"].max() - pd.Timedelta(days=6)
    chart_df = chart_df[
        chart_df["collected_date"] >= start_date
    ]

elif date_range == "最近 30 天":
    start_date = chart_df["collected_date"].max() - pd.Timedelta(days=29)
    chart_df = chart_df[
        chart_df["collected_date"] >= start_date
    ]

chart_df = chart_df.set_index("collected_date")

st.line_chart(
    chart_df["price"],
    y_label="價格（NT$）"
)
