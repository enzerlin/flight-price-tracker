import os
import mysql.connector
import pandas as pd
from transform import (
    transform_routings,
    transform_sectors,
    generate_itinerary_key
)
from config import (
    ORIGIN,
    DESTINATION,
    DEPARTURE_DATE,
    ADULT_COUNT,
    CHILD_COUNT,
    INFANT_COUNT,
)

# =========================
# MySQL connection
# =========================

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST", "localhost"),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DATABASE", "flight_price")
)

cursor = conn.cursor()

print("MySQL connected!")


# =========================
# Load & Transform
# =========================

raw_file = os.getenv("FLIGHT_RAW_FILE")

if not raw_file:
    raise RuntimeError("FLIGHT_RAW_FILE is not set")

print("Loading raw file:", raw_file)

with open(raw_file, "r", encoding="utf-8") as f:
    import json
    data = json.load(f) 
    
routing_df = transform_routings(data)
sector_df = transform_sectors(data)

print(routing_df[["itinerary_key", "flight_key"]].head())

print("Routing rows:", len(routing_df))
print("Sector rows:", len(sector_df))


# =========================
# 1. Insert flight_searches
# =========================

search_key = data["data"].get("searchKey")

# 目前這次搜尋條件
# flight_searches describes the whole trip; routes under it can include both
# the outbound and reversed return direction (each stored from its own API result).
origin = os.getenv("FLIGHT_ORIGIN", ORIGIN)
destination = os.getenv("FLIGHT_DESTINATION", DESTINATION)

outbound_date = os.getenv("FLIGHT_TRIP_OUTBOUND_DATE", DEPARTURE_DATE)
inbound_date = os.getenv("FLIGHT_RETURN_DATE") or None

adult_count = ADULT_COUNT
child_count = CHILD_COUNT
infant_count = INFANT_COUNT

sql = """
INSERT INTO flight_searches (
    search_key,
    origin_city_code,
    destination_city_code,
    outbound_date,
    inbound_date,
    adult_count,
    child_count,
    infant_count
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

cursor.execute(
    sql,
    (
        search_key,
        origin,
        destination,
        outbound_date,
        inbound_date,
        adult_count,
        child_count,
        infant_count
    )
)

search_id = cursor.lastrowid

print("Created search_id:", search_id)


# =========================
# 2. Insert routes
# =========================

route_id_map = {}

# 同一個 itinerary 只建立一個 route
route_df = (
    routing_df
    .drop_duplicates(subset=["itinerary_key"])
    .reset_index(drop=True)
)

for _, row in route_df.iterrows():

    # 找到這個 itinerary 對應的原始 routing
    routing = next(
        r for r in data["data"]["routings"]
        if r.get("flightKey") == row["flight_key"]
        and generate_itinerary_key(r) == row["itinerary_key"]
    )

    first_sector = routing["sectors"][0]
    last_sector = routing["sectors"][-1]

    departure_datetime = (
        first_sector["departureDate"]
        + " "
        + first_sector["departureTime"]
    )

    arrival_datetime = (
        last_sector["arrivalDate"]
        + " "
        + last_sector["arrivalTime"]
    )

    sql = """
    INSERT INTO flight_routes (
        search_id,
        itinerary_key,
        flight_key,
        departure_datetime,
        arrival_datetime,
        departure_airport_code,
        arrival_airport_code,
        departure_airport_name,
        arrival_airport_name
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    cursor.execute(
        sql,
        (
            search_id,
            row["itinerary_key"],
            row["flight_key"],
            departure_datetime,
            arrival_datetime,
            row["departure_airport_code"],
            row["arrival_airport_code"],
            row["departure_airport_name"],
            row["arrival_airport_name"]
        )
    )

    route_id = cursor.lastrowid

    # itinerary_key → route_id
    route_id_map[row["itinerary_key"]] = route_id


print("Routes inserted:", len(route_id_map))


# =========================
# 3. Insert sectors
# =========================

sql = """
INSERT INTO flight_sectors (
    route_id,
    sequence,
    flight_no,
    airline_code,
    airline,
    operating_airline_code,
    operating_airline,
    departure_datetime,
    arrival_datetime,
    departure_airport_code,
    departure_airport_name,
    arrival_airport_code,
    arrival_airport_name,
    duration_minutes,
    transfer_stay_minutes,
    cabin_type,
    cabin_desc,
    booking_class,
    craft_type,
    craft_name
)
VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
"""

for _, row in sector_df.iterrows():

    row = row.where(pd.notna(row), None)

    route_id = route_id_map[row["itinerary_key"]]
    departure_datetime = (
        row["departure_date"]
        + " "
        + row["departure_time"]
    )

    arrival_datetime = (
        row["arrival_date"]
        + " "
        + row["arrival_time"]
    )

    cursor.execute(
        sql,
        (
            route_id,
            row["sequence"],
            row["flight_no"],
            row["airline_code"],
            row["airline"],
            row["operating_airline_code"],
            row["operating_airline"],
            departure_datetime,
            arrival_datetime,
            row["departure_airport_code"],
            row["departure_airport_name"],
            row["arrival_airport_code"],
            row["arrival_airport_name"],
            row["duration_minutes"],
            row["transfer_stay_minutes"],
            row["cabin_type"],
            row["cabin_desc"],
            row["booking_class"],
            row["craft_type"],
            row["craft_name"]
        )
    )

print("Sectors inserted:", len(sector_df))


# =========================
# 4. Insert prices
# =========================

sql = """
INSERT INTO flight_prices (
    route_id,
    price,
    price_without_tax,
    tax,
    seat_count,
    cabin_class,
    free_baggage,
    engine_type,
    product_desc,
    ticketing_desc
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
for _, row in routing_df.iterrows():

    route_id = route_id_map[row["itinerary_key"]]

    cursor.execute(
        sql,
        (
            route_id,
            row["price"],
            row["price_without_tax"],
            row["tax"],
            row["seat_count"],
            row["cabin_class"],
            row["free_baggage"],
            row["engine_type"],
            row["product_desc"],
            row["ticketing_desc"]
        )
    )

print("Prices inserted:", len(routing_df))


# =========================
# Commit
# =========================

conn.commit()

print("\n========== LOAD COMPLETE ==========")

cursor.close()
conn.close()

print("MySQL connection closed.")
