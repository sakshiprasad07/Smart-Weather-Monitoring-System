"""
Smart Weather Monitoring System — Phase II Dashboard
------------------------------------------------------
Streamlit dashboard that:
  1. Fetches live weather for a chosen city from OpenWeatherMap.
  2. Stores/reads historical readings from MySQL (local or RDS).
  3. Calls the forecasting microservice to get a short-term prediction.
  4. Displays current conditions, historical trend, and forecast.

Config is read from environment variables so the same code works
locally and once deployed against RDS/EC2 -- no code changes needed,
just different env vars.
"""

import os
from datetime import datetime, timezone

import mysql.connector
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from dotenv import load_dotenv

# Loads variables from a .env file in this folder into os.environ, if present.
# Explicit path (rather than plain load_dotenv()) avoids ambiguity about
# where the search starts when run under different launchers (streamlit vs
# python directly).
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ---------------------------------------------------------------------------
# Configuration (env vars -- swap these when moving from local to cloud)
# ---------------------------------------------------------------------------
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
MICROSERVICE_URL = os.getenv("MICROSERVICE_URL", "http://localhost:8000")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "weather_monitor"),
}

st.set_page_config(page_title="Smart Weather Monitoring — Phase II", page_icon="⛅", layout="wide")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def init_db():
    """Creates the weather_records table if it doesn't exist yet."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weather_records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            location VARCHAR(100) NOT NULL,
            metric VARCHAR(50) NOT NULL,
            value FLOAT NOT NULL,
            recorded_at DATETIME NOT NULL,
            INDEX idx_location_metric (location, metric, recorded_at)
        )
        """
    )
    conn.commit()
    cur.close()
    conn.close()


def save_reading(location: str, metric: str, value: float):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO weather_records (location, metric, value, recorded_at) VALUES (%s, %s, %s, %s)",
        (location, metric, value, datetime.now(timezone.utc)),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_history(location: str, metric: str, limit: int = 30):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT recorded_at AS timestamp, value
        FROM weather_records
        WHERE location = %s AND metric = %s
        ORDER BY recorded_at DESC
        LIMIT %s
        """,
        (location, metric, limit),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    rows.reverse()  # chronological order
    return rows


# ---------------------------------------------------------------------------
# External API + microservice calls
# ---------------------------------------------------------------------------
def fetch_live_weather(city: str):
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric"}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_forecast(location: str, metric: str, history: list, steps_ahead: int = 3):
    payload = {
        "location": location,
        "metric": metric,
        "history": [{"timestamp": str(h["timestamp"]), "value": h["value"]} for h in history],
        "steps_ahead": steps_ahead,
    }
    resp = requests.post(f"{MICROSERVICE_URL}/forecast", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_stats(location: str, metric: str, history: list):
    payload = {
        "location": location,
        "metric": metric,
        "history": [{"timestamp": str(h["timestamp"]), "value": h["value"]} for h in history],
        "steps_ahead": 1,
    }
    resp = requests.post(f"{MICROSERVICE_URL}/stats", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("⛅ Smart Weather Monitoring System — Phase II")
st.caption("Live data · Historical trends · Short-term forecast — powered by a Dockerized microservice")

with st.sidebar:
    st.header("Settings")
    city = st.text_input("City / Location", value="Gurugram")
    fetch_clicked = st.button("Fetch live weather", type="primary", use_container_width=True)
    st.divider()
    st.caption(f"Microservice: `{MICROSERVICE_URL}`")
    st.caption(f"DB host: `{DB_CONFIG['host']}`")

if "history_cache" not in st.session_state:
    st.session_state.history_cache = []

col1, col2 = st.columns([1, 2])

if fetch_clicked:
    if not OPENWEATHER_API_KEY:
        st.error("Set the OPENWEATHER_API_KEY environment variable to fetch live data.")
    else:
        try:
            with st.spinner(f"Fetching live weather for {city}..."):
                data = fetch_live_weather(city)
                temp = data["main"]["temp"]
                humidity = data["main"]["humidity"]
                condition = data["weather"][0]["description"]

            try:
                init_db()
                save_reading(city, "temperature", temp)
            except Exception as db_err:
                st.warning(f"Fetched live data, but couldn't save to DB: {db_err}")

            with col1:
                st.metric("Temperature", f"{temp} °C")
                st.metric("Humidity", f"{humidity}%")
                st.write(f"**Condition:** {condition.title()}")

            try:
                history = get_history(city, "temperature", limit=30)
            except Exception:
                history = []

            with col2:
                if len(history) >= 3:
                    df = pd.DataFrame(history)
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df["timestamp"], y=df["value"], mode="lines+markers", name="Temperature"))
                    fig.update_layout(title=f"Temperature trend — {city}", xaxis_title="Time", yaxis_title="°C", height=350)
                    st.plotly_chart(fig, use_container_width=True)

                    try:
                        forecast = get_forecast(city, "temperature", history, steps_ahead=3)
                        stats = get_stats(city, "temperature", history)

                        st.subheader("📈 Forecast (next 3 readings)")
                        fcols = st.columns(3)
                        for i, point in enumerate(forecast["forecast"]):
                            fcols[i].metric(f"Step +{point['step']}", f"{point['predicted_value']} °C")
                        st.caption(f"Trend: **{forecast['summary']['trend']}** · Model: {forecast['model']}")

                        st.subheader("📊 Historical stats")
                        s1, s2, s3 = st.columns(3)
                        s1.metric("Average", f"{stats['average']} °C")
                        s2.metric("Min", f"{stats['minimum']} °C")
                        s3.metric("Max", f"{stats['maximum']} °C")
                    except Exception as ms_err:
                        st.warning(f"Microservice unreachable ({MICROSERVICE_URL}): {ms_err}")
                else:
                    st.info("Not enough historical data yet for a trend/forecast — fetch a few more times to build history.")

        except Exception as e:
            st.error(f"Failed to fetch weather: {e}")
else:
    st.info("Enter a city and click **Fetch live weather** to get started.")