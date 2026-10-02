import os
import subprocess
import sys

# ==============================
# 取得 Airflow 傳進來的航線
# ==============================

ORIGIN = os.getenv("FLIGHT_ORIGIN")
DESTINATION = os.getenv("FLIGHT_DESTINATION")

OUTBOUND_DATE = "2027-01-28"
RETURN_DATE = "2027-02-01"


def run_route(origin, destination):
    env = os.environ.copy()

    env["FLIGHT_ORIGIN"] = origin
    env["FLIGHT_DESTINATION"] = destination
    env["FLIGHT_DATE"] = OUTBOUND_DATE
    env["FLIGHT_RETURN_DATE"] = RETURN_DATE

    result = subprocess.run(
        [sys.executable, "src/eztravel.py"],
        env=env,
    )

    return result.returncode == 0


def main():

    if not ORIGIN or not DESTINATION:
        print("ERROR: FLIGHT_ORIGIN or FLIGHT_DESTINATION is not set")
        sys.exit(1)

    print("\n==============================")
    print(f"Running: {ORIGIN} ⇄ {DESTINATION}")
    print(f"去程 {OUTBOUND_DATE} | 回程 {RETURN_DATE or '(不搜)'}")
    print("==============================")

    success = run_route(ORIGIN, DESTINATION)

    print("\n==============================")

    if not success:
        print(f"FAILED: {ORIGIN} ⇄ {DESTINATION}")
        print("==============================")
        sys.exit(1)

    print(f"SUCCESS: {ORIGIN} ⇄ {DESTINATION}")
    print("==============================")


if __name__ == "__main__":
    main()
