FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10004 raguser
USER raguser

EXPOSE 8200

# Assistant opérateur : aucun accès privilégié au système (sujet §3.3).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
