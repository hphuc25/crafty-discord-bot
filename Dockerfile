FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# CA certs are needed if you set CRAFTY_VERIFY_SSL=true.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source only; .env / .venv / secrets are never included in the image.
COPY bot.py crafty.py ./

RUN useradd --create-home --shell /usr/sbin/nologin botuser \
    && chown -R botuser:botuser /app
USER botuser

CMD ["python", "bot.py"]
