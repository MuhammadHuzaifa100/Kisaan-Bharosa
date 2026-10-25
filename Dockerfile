FROM python:3.13-slim

WORKDIR /app

# Pillow/bcrypt ship wheels, but keep the toolchain so the build survives a
# platform without one.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The container has no reason to run as root, and the writable paths must be owned
# by the account it drops to.
RUN useradd --create-home --uid 10001 kisaan \
    && mkdir -p /app/static/uploads \
    && chown -R kisaan:kisaan /app
USER kisaan

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
