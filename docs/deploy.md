# Deployment notes

The app runs anywhere Python 3.10+ and `pip install -r requirements.txt` work. Nothing is
deployed from this repository automatically.

## Streamlit Community Cloud

1. Sign in at <https://share.streamlit.io> with the GitHub account that owns the repo.
2. "Create app" → repository `DataWithSyed/biomass-heat-dashboard`, branch `main`, main file
   `app.py`.
3. Advanced settings → Python 3.12. The `requirements.txt` installs the four series packages
   from their GitHub URLs, so the first build takes a few minutes.
4. No secrets are needed: all data are in `data/`.

Memory: the live mode holds one year of hourly prices and up to 256 cached chain evaluations.
That fits easily in the Community Cloud limit (about 1 GB). Precomputed mode needs no solver.

## Docker (self-hosted)

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "app.py", "--server.headless=true", "--server.address=0.0.0.0"]
```

```bash
docker build -t biomass-heat-dashboard .
docker run -p 8501:8501 biomass-heat-dashboard
curl http://localhost:8501/_stcore/health     # -> ok
```

## Local headless check (used before release)

```bash
streamlit run app.py --server.headless true --server.port 8517 &
curl -s http://localhost:8517/_stcore/health   # ok
```
