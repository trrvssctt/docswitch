FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORK_ROOT=/tmp \
    LIBREOFFICE_PROFILE=/tmp/lo-profile \
    HOME=/tmp

# LibreOffice Writer sans interface + polices :
# - Carlito / Caladea : métriques de Calibri / Cambria (documents Word récents)
# - Liberation : métriques d'Arial / Times New Roman / Courier New
# - Noto : arabe et autres écritures
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui \
        fonts-crosextra-carlito fonts-crosextra-caladea \
        fonts-liberation2 fonts-dejavu-core \
        fonts-noto-core fonts-noto-ui-core \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py converters.py ./

RUN useradd --uid 10001 --no-create-home docswitch
USER docswitch

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--no-server-header", "--no-access-log"]
