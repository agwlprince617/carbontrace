# Cloud Build produces a Linux image; local credentials and run files are excluded.
FROM python:3.14.5-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    CARBONTRACE_MODE=hosted-preview \
    CARBONTRACE_DATA_DIR=/tmp/carbontrace \
    PORT=8080
COPY requirements-cloudrun.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-cloudrun.txt \
    && useradd --create-home --uid 10001 appuser
COPY src/ ./src/
USER 10001
EXPOSE 8080
CMD ["python", "-m", "carbontrace.server"]
