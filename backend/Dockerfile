FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements-bootstrap.txt requirements-campus.txt requirements-knowledge.txt ./
RUN pip install --no-cache-dir -r requirements-campus.txt -r requirements-knowledge.txt
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd --create-home --uid 10001 campus
USER campus
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
USER campus
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
