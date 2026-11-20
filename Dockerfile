FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The python:3.12-slim base image already includes ca-certificates, so no apt step is needed.

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source only; .env / .venv / secrets are never included in the image.
COPY bot.py crafty.py ./

RUN useradd --create-home --shell /usr/sbin/nologin botuser \
    && chown -R botuser:botuser /app
USER botuser

CMD ["python", "bot.py"]
