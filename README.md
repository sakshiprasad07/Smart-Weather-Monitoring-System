# Smart Weather Monitoring System — Phase II

Live weather data, historical trends, and short-term forecasting — built as
two independently deployable pieces connected over REST:

```
┌─────────────────────┐      HTTP/JSON      ┌──────────────────────────┐
│  Streamlit Dashboard │ ───────────────────▶│  FastAPI ML Microservice │
│  (dashboard/app.py)  │◀─────────────────── │   (microservice/main.py) │
└──────────┬───────────┘                     └──────────────────────────┘
           │
           ▼
   MySQL (local or AWS RDS)
```

## Project layout

```
weather-project/
├── dashboard/              # Streamlit UI — fetches live weather, shows trends/forecast
│   ├── app.py
│   └── requirements.txt
├── microservice/            # FastAPI service — trains a model on demand, returns forecast
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── schema.sql               # MySQL schema (run manually on RDS if not using auto-create)
└── .github/workflows/       # CI: builds + pushes the microservice Docker image
    └── docker-build.yml
```

## Run locally (before touching AWS)

1. **Microservice**
   ```bash
   cd microservice
   pip install -r requirements.txt
   python main.py            # runs on http://localhost:8000
   ```
   Or via Docker:
   ```bash
   cd microservice
   docker build -t weather-forecast-service .
   docker run -p 8000:8000 weather-forecast-service
   ```

2. **MySQL** — either run locally or point straight at RDS once it exists.
   ```bash
   mysql -u root -p < schema.sql
   ```

3. **Dashboard**
   ```bash
   cd dashboard
   pip install -r requirements.txt
   export OPENWEATHER_API_KEY=your_key_here
   export MICROSERVICE_URL=http://localhost:8000
   export DB_HOST=localhost
   export DB_USER=root
   export DB_PASSWORD=your_password
   export DB_NAME=weather_monitor
   streamlit run app.py
   ```

## Moving to the cloud

Once EC2 + RDS are provisioned, only the environment variables change —
no code changes needed:

- `MICROSERVICE_URL` → `http://<EC2_PUBLIC_IP>:8000`
- `DB_HOST` → `<RDS_ENDPOINT>`

Deploying the microservice to EC2:
```bash
# on the EC2 instance, with Docker installed:
docker pull <your_dockerhub_username>/weather-forecast-service:latest
docker run -d -p 8000:8000 <your_dockerhub_username>/weather-forecast-service:latest
```

## CI/CD

`.github/workflows/docker-build.yml` builds and pushes the microservice
image to Docker Hub on every push to `main` that touches `microservice/`.
Requires two repo secrets: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.

## API reference (microservice)

| Endpoint     | Method | Purpose                                   |
|--------------|--------|--------------------------------------------|
| `/health`    | GET    | Liveness check                            |
| `/forecast`  | POST   | Returns next-N-step forecast for a metric |
| `/stats`     | POST   | Returns average/min/max for a metric      |

Get an OpenWeatherMap API key (free tier) at https://openweathermap.org/api
