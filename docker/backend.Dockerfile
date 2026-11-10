# Backend : API Flask servie par gunicorn. Contexte de build : la racine du dépôt.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Paris

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "gunicorn>=22,<24"

COPY *.py ./
COPY migrations ./migrations
COPY static ./static

# Compte non privilégié ; les pièces jointes vivent dans un volume dédié (/data), hors du code.
RUN useradd --system --uid 10001 conges \
    && mkdir -p /data/uploads \
    && chown -R conges /data
USER conges

ENV CONGES_HOST=0.0.0.0 \
    CONGES_PORT=8110 \
    CONGES_UPLOAD_DIR=/data/uploads/requests

EXPOSE 8110

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8110/api/status', timeout=4).status == 200 else 1)"

CMD ["gunicorn", "-b", "0.0.0.0:8110", "--workers", "1", "--threads", "8", "--timeout", "60", \
     "--access-logfile", "-", "--error-logfile", "-", "wsgi:application"]
