# syntax=docker/dockerfile:1

# ─── Stage 1 : builder ───────────────────────────────────────────────────────
# Installe les dépendances Python dans un venv isolé. gcc n'existe QUE dans ce
# stage : il sert à compiler d'éventuels sdists, jamais à l'exécution → exclu de
# l'image finale.
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# venv relocatable : même chemin /opt/venv dans les deux stages → copie directe.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 1) torch en CPU-only : la roue PyPI par défaut embarque CUDA (~2,5 Go de libs
#    nvidia inutiles sur un VPS CPU) ; la roue CPU fait ~190 Mo. sentence-transformers
#    réutilise ensuite ce torch déjà installé au lieu d'en retélécharger un.
# 2) --mount=type=cache : cache pip partagé entre builds (BuildKit) → rebuilds
#    rapides SANS gonfler l'image (le cache n'est pas une couche du résultat).
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
      --index-url https://download.pytorch.org/whl/cpu \
      --extra-index-url https://pypi.org/simple \
      torch \
    && pip install -r requirements.txt

# ─── Stage 2 : runtime ───────────────────────────────────────────────────────
# Image finale : uniquement les libs SYSTÈME de runtime (pas de gcc/toolchain).
FROM python:3.12-slim AS runtime

# Dépendances système d'exécution : tesseract (OCR) + libgl/libglib (pymupdf/opencv).
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Récupère le venv tout prêt depuis le builder (sans gcc ni caches de build).
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copier le code
COPY . .

# Créer les dossiers de données (montés via volume en prod)
RUN mkdir -p /app/data/ged /app/data/chromadb /app/data/bm25_index \
              /app/data/local_db /app/data/uploads /app/data/templates

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
