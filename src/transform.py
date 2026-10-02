import json
import os
import pandas as pd
import hashlib
from pathlib import Path
import sys


RAW_DIR = Path("data/raw")


def load_raw_data(raw_file):
    print("Loading raw file:", raw_file)

    with open(raw_file, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_itinerary_key(routing):
    parts = []

    for sector in routing.get("sectors", []):
        parts.extend([
            sector.get("departureDate", ""),
            sector.get("departureTime", ""),
            sector.get("arrivalDate", ""),
            sector.get("arrivalTime", ""),
            sector.get("departureAirportCode", ""),
            sector.get("arrivalAirportCode", ""),
            sector.get("flightNo", ""),
            sector.get("airlineCode", ""),
        ])

    raw_key = "|".join(parts)

    return hashlib.sha256(
        raw_key.encode("utf-8")
    ).hexdigest()


def transform_routings(data):
    rows = []
    routings = data["data"]["routings"]

    for routing in routings:

        # 排除轉機
        if any(
            sector.get("transferStayMinutes", 0) > 0
            for sector in routing.get("sectors", [])
        ):
            continue

        sectors = routing.get("sectors", [])

        if not sectors:
            continue

        prices = routing.get("prices", [])

        # 沒有價格就跳過
        if not prices:
            continue

        # 找最低價格方案
        lowest_price = min(
            prices,
            key=lambda x: x.get("price", float("inf"))
        )

        first_sector = sectors[0]
        last_sector = sectors[-1]

        itinerary_key = generate_itinerary_key(routing)

        row = {
            "itinerary_key": itinerary_key,
            "flight_key": routing.get("flightKey"),

            "departure_date": first_sector.get("departureDate"),
            "departure_time": first_sector.get("departureTime"),
            "arrival_date": last_sector.get("arrivalDate"),
            "arrival_time": last_sector.get("arrivalTime"),

            "departure_city_code": first_sector.get("departureCityCode"),
            "departure_city_name": first_sector.get("departureCityName"),
            "arrival_city_code": last_sector.get("arrivalCityCode"),
            "arrival_city_name": last_sector.get("arrivalCityName"),

            "departure_airport_code": first_sector.get("departureAirportCode"),
            "departure_airport_name": first_sector.get("departureAirportName"),
            "arrival_airport_code": last_sector.get("arrivalAirportCode"),
            "arrival_airport_name": last_sector.get("arrivalAirportName"),

            # 最低價格方案
            "price": lowest_price.get("price"),
            "price_without_tax": lowest_price.get("priceWithoutTax"),
            "tax": lowest_price.get("adultTax"),
            "seat_count": lowest_price.get("seatCount"),
            "cabin_class": lowest_price.get("classType"),
            "free_baggage": lowest_price.get("freeBaggage"),
            "engine_type": lowest_price.get("engineType"),
            "product_desc": lowest_price.get("productDesc"),
            "ticketing_desc": lowest_price.get("ticketingDesc"),
        }

        rows.append(row)

    return pd.DataFrame(rows)


def transform_sectors(data):
    rows = []
    routings = data["data"]["routings"]

    for routing in routings:

        # 排除轉機航班
        if any(
            sector.get("transferStayMinutes", 0) > 0
            for sector in routing.get("sectors", [])
        ):
            continue

        flight_key = routing.get("flightKey")
        itinerary_key = generate_itinerary_key(routing)

        for sector in routing.get("sectors", []):

            row = {
                "itinerary_key": itinerary_key,

                "flight_key": flight_key,

                "sequence": sector.get("sequenceNo"),

                "flight_no": sector.get("flightNo"),

                "airline_code": sector.get("airlineCode"),
                "airline": sector.get("airline"),

                "operating_airline_code":
                    sector.get("operatingAirlineCode"),

                "operating_airline":
                    sector.get("operatingAirline"),

                "departure_date":
                    sector.get("departureDate"),

                "departure_time":
                    sector.get("departureTime"),

                "arrival_date":
                    sector.get("arrivalDate"),

                "arrival_time":
                    sector.get("arrivalTime"),

                "departure_airport_code":
                    sector.get("departureAirportCode"),

                "departure_airport_name":
                    sector.get("departureAirportName"),

                "arrival_airport_code":
                    sector.get("arrivalAirportCode"),

                "arrival_airport_name":
                    sector.get("arrivalAirportName"),

                "duration_minutes":
                    sector.get("durationMinutes"),

                "transfer_stay_minutes":
                    sector.get("transferStayMinutes"),

                "cabin_type":
                    sector.get("cabinType"),

                "cabin_desc":
                    sector.get("cabinDesc"),

                "booking_class":
                    sector.get("bookingClass"),

                "craft_type": (sector.get("craft") or {}).get("craftType"),
                "craft_name": (sector.get("craft") or {}).get("craftName"),
            }

            rows.append(row)

    return pd.DataFrame(rows)


if __name__ == "__main__":
    raw_file = sys.argv[1]

    data = load_raw_data(raw_file)

    routing_df = transform_routings(data)
    sector_df = transform_sectors(data)

    print("\n========== ROUTINGS ==========\n")
    print(routing_df.head().to_string())
    print("\nShape:", routing_df.shape)

    print("\n========== SECTORS ==========\n")
    print(sector_df.head(10).to_string())
    print("\nShape:", sector_df.shape)
