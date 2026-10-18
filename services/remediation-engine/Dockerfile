FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# NB : ce service a besoin du socket Docker (restart de conteneurs, reload WAF).
# Il tourne donc avec les droits requis mais sur un réseau `control` isolé et
# sans interface d'administration exposée (durcissement documenté).
EXPOSE 9000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
