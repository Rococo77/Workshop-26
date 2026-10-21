# API de reconnaissance faciale = API Flask officielle de DeepFace
# (github.com/serengil/deepface, deepface/api/src), servie par gunicorn.
#
# Écarts assumés avec le Dockerfile amont (python:3.8, TensorFlow) :
#   - moteur ONNX : Facenet512, YuNet et l'anti-spoofing FasNet existent en
#     ONNX -> image ~5x plus légère, sans la surface CVE de TensorFlow ;
#   - poids embarqués au build : le conteneur tourne sur un réseau interne,
#     sans Internet ;
#   - utilisateur non root.

# ---------------------------------------------------------------- sources
# Tag épinglé ET commit vérifié : un tag déplacé côté amont fait échouer le build
# (intégrité de la chaîne d'approvisionnement).
FROM python:3.12-slim AS source
ARG DEEPFACE_REF=v0.0.102
ARG DEEPFACE_COMMIT=7a58e76621291a7024df3eb5379b822f7520883d
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${DEEPFACE_REF}" https://github.com/serengil/deepface.git /src \
    && test "$(git -C /src rev-parse HEAD)" = "${DEEPFACE_COMMIT}" \
    && rm -rf /src/.git /src/tests /src/benchmarks /src/experiments /src/icon

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEEPFACE_BACKEND_ENGINE=onnx \
    DEEPFACE_HOME=/models \
    FACE_MODEL=Facenet512 \
    FACE_DETECTOR=yunet

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=source /src /tmp/deepface-src
RUN pip install --no-cache-dir --no-deps /tmp/deepface-src && rm -rf /tmp/deepface-src

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /models && chown appuser /models
USER appuser

COPY prefetch.py .
RUN python prefetch.py

EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:5000/').status==200 else 1)"

# 1 worker (modèles en mémoire une seule fois), 2 threads : une vérification
# lente ne bloque pas la sonde de santé.
CMD ["gunicorn", "--workers=1", "--threads=2", "--timeout=60", "--bind=0.0.0.0:5000", \
     "--access-logfile=-", "deepface.api.src.app:create_app()"]
