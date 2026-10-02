import mysql.connector
import os

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST", "localhost"),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DATABASE", "flight_price")
)

cursor = conn.cursor(dictionary=True)


# =========================
# Get latest search
# =========================

cursor.execute("""
    SELECT search_id
    FROM flight_searches
    ORDER BY search_id DESC
    LIMIT 1
""")

latest_search = cursor.fetchone()

if not latest_search:
    raise Exception("No flight search data found.")

search_id = latest_search["search_id"]

print(f"Checking search_id: {search_id}")


# =========================
# Check route / price count
# =========================

cursor.execute("""
    SELECT
        COUNT(DISTINCT fr.route_id) AS route_count,
        COUNT(DISTINCT fp.price_id) AS price_count
    FROM flight_routes fr
    LEFT JOIN flight_prices fp
        ON fr.route_id = fp.route_id
    WHERE fr.search_id = %s
""", (search_id,))

result = cursor.fetchone()

route_count = result["route_count"]
price_count = result["price_count"]

print(f"Routes: {route_count}")
print(f"Prices: {price_count}")


# =========================
# Data quality check
# =========================

if route_count == 0:
    raise Exception("Data quality check failed: no routes found.")

if route_count != price_count:
    raise Exception(
        f"Data quality check failed: "
        f"{route_count} routes but {price_count} prices."
    )


print("DATA QUALITY CHECK PASSED")


cursor.close()
conn.close()
