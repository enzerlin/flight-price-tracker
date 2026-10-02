from datetime import datetime
import pendulum

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator


ROUTES = [
    ("TPE", "TYO"),
    ("TPE", "KIX"),
    ("TPE", "ICN"),
    ("TPE", "BKK"),
    ("TPE", "HKG"),
]


with DAG(
    dag_id="flight_price_tracker",
    start_date=pendulum.datetime(
        2026, 9, 28, tz="Asia/Taipei"
    ),
    schedule="0 21 * * *",
    catchup=False,
    tags=["flight", "price"],
) as dag:

    for origin, destination in ROUTES:

        run_pipeline = BashOperator(
            task_id=f"run_{origin}_{destination}",

            bash_command=f"""
                cd /Users/Xander/flight_price_tracker

                export PATH="/Users/Xander/flight_price_tracker/.venv/bin:$PATH"

                export FLIGHT_ORIGIN="{origin}"
                export FLIGHT_DESTINATION="{destination}"

                /Users/Xander/flight_price_tracker/.venv/bin/python run_pipeline.py
            """,
        )