"""
Weather Forecast Microservice
------------------------------
A small FastAPI service that trains a lightweight regression model on
recent historical weather readings and returns a short-term forecast
(next-value prediction) for a given metric (temperature, humidity, etc).

Design notes:
- Model is trained on-the-fly per request from the history the caller
  sends (no persisted model file needed for this scope).
- Kept intentionally simple (linear regression on a time index) since
  the ML piece is not the main focus of this project -- the goal here
  is a real, working, deployable service, not model sophistication.
- Talks to the dashboard over plain JSON/HTTP so either side can be
  swapped independently.
"""

from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sklearn.linear_model import LinearRegression

app = FastAPI(
    title="Weather Forecast Microservice",
    description="Trains a small regression model on recent readings and predicts the next value.",
    version="1.0.0",
)


class WeatherReading(BaseModel):
    timestamp: str = Field(..., description="ISO-8601 timestamp, e.g. 2026-09-10T12:00:00")
    value: float = Field(..., description="Metric value at this timestamp (e.g. temperature in C)")


class ForecastRequest(BaseModel):
    location: str = Field(..., description="City/location name, for logging/response context")
    metric: str = Field("temperature", description="Which metric is being forecast")
    history: List[WeatherReading] = Field(
        ..., min_length=3, description="Chronologically ordered historical readings (>=3 points)"
    )
    steps_ahead: int = Field(1, ge=1, le=7, description="How many future steps to predict")


class ForecastPoint(BaseModel):
    step: int
    predicted_value: float
    predicted_time: str


class ForecastResponse(BaseModel):
    location: str
    metric: str
    model: str
    training_points: int
    forecast: List[ForecastPoint]
    summary: dict


class StatsResponse(BaseModel):
    location: str
    metric: str
    count: int
    average: float
    minimum: float
    maximum: float


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/stats", response_model=StatsResponse)
def compute_stats(req: ForecastRequest):
    """Basic statistical summary of a location's historical readings."""
    values = [r.value for r in req.history]
    return StatsResponse(
        location=req.location,
        metric=req.metric,
        count=len(values),
        average=round(float(np.mean(values)), 2),
        minimum=round(float(np.min(values)), 2),
        maximum=round(float(np.max(values)), 2),
    )


@app.post("/forecast", response_model=ForecastResponse)
def forecast(req: ForecastRequest):
    """
    Trains a simple linear regression (value ~ time index) on the
    supplied history and predicts the next `steps_ahead` values.
    """
    if len(req.history) < 3:
        raise HTTPException(status_code=400, detail="Need at least 3 historical points to forecast.")

    try:
        # Sort defensively by timestamp in case the caller didn't.
        sorted_history = sorted(req.history, key=lambda r: r.timestamp)

        # Use REAL elapsed seconds since the first reading as the regression
        # feature, instead of a plain position index. This means the model
        # actually learns from the true time gaps between readings, rather
        # than assuming every reading is evenly spaced.
        timestamps = [datetime.fromisoformat(r.timestamp) for r in sorted_history]
        t0 = timestamps[0]
        elapsed_seconds = np.array([(t - t0).total_seconds() for t in timestamps])
        X = elapsed_seconds.reshape(-1, 1)
        y = np.array([r.value for r in sorted_history])

        model = LinearRegression()
        model.fit(X, y)

        # Estimate the typical interval between readings from the actual
        # data, then project future points at that same spacing -- rather
        # than a hardcoded "+1 step" that ignores real elapsed time.
        if len(elapsed_seconds) > 1:
            avg_interval = float(np.mean(np.diff(elapsed_seconds)))
        else:
            avg_interval = 60.0  # fallback, shouldn't happen given the >=3 check above
        avg_interval = max(avg_interval, 1.0)  # guard against zero/negative gaps

        last_elapsed = elapsed_seconds[-1]
        future_elapsed = np.array(
            [last_elapsed + avg_interval * (i + 1) for i in range(req.steps_ahead)]
        ).reshape(-1, 1)
        predictions = model.predict(future_elapsed)

        forecast_points = [
            ForecastPoint(
                step=i + 1,
                predicted_value=round(float(p), 2),
                predicted_time=(t0 + timedelta(seconds=float(future_elapsed[i][0]))).isoformat(),
            )
            for i, p in enumerate(predictions)
        ]

        return ForecastResponse(
            location=req.location,
            metric=req.metric,
            model="LinearRegression (elapsed-time based)",
            training_points=len(sorted_history),
            forecast=forecast_points,
            summary={
                "trend": "rising" if model.coef_[0] > 0 else "falling" if model.coef_[0] < 0 else "flat",
                "slope_per_second": round(float(model.coef_[0]), 6),
                "avg_interval_seconds": round(avg_interval, 1),
            },
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Forecast failed: {exc}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)