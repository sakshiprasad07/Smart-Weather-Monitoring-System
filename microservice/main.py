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

from datetime import datetime
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
        X = np.arange(len(sorted_history)).reshape(-1, 1)
        y = np.array([r.value for r in sorted_history])

        model = LinearRegression()
        model.fit(X, y)

        future_idx = np.arange(len(sorted_history), len(sorted_history) + req.steps_ahead).reshape(-1, 1)
        predictions = model.predict(future_idx)

        forecast_points = [
            ForecastPoint(step=i + 1, predicted_value=round(float(p), 2))
            for i, p in enumerate(predictions)
        ]

        return ForecastResponse(
            location=req.location,
            metric=req.metric,
            model="LinearRegression (time-index based)",
            training_points=len(sorted_history),
            forecast=forecast_points,
            summary={
                "trend": "rising" if model.coef_[0] > 0 else "falling" if model.coef_[0] < 0 else "flat",
                "slope_per_step": round(float(model.coef_[0]), 4),
            },
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Forecast failed: {exc}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)