# The Achalara backend: FastAPI, with the scheduler running inside the process.
#
# Run exactly one container of this image. The daily jobs (sheet sync,
# brokerage sync, daily capture, index history) are started by the app itself,
# so a second copy would run every job twice.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHON_ENV=production

# Pango renders the PDF performance report; Liberation stands in for the
# report's Helvetica/Arial, which a slim image does not carry.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

RUN useradd --create-home --uid 1000 achalara
USER achalara

EXPOSE 8000

# Bring the database up to date, then serve. One worker: see the note above.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
