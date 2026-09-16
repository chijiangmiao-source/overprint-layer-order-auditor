# Build context for this image is the repository root (see docker-compose.yml).
# The verifier runs BOTH the exhaustive backend unit tests and the live
# end-to-end acceptance checks against the running web + api services.
FROM python:3.11-slim

WORKDIR /verify

COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY backend/app ./app
COPY backend/tests ./tests
COPY backend/pytest.ini ./pytest.ini
COPY verify/entrypoint.sh /verify/acceptance.py ./
RUN chmod +x ./entrypoint.sh ./acceptance.py

# No service is exposed; the container runs once and exits 0/1.
CMD ["./entrypoint.sh"]
