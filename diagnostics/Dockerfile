ARG DIAG_BASE_IMAGE=python:3.12.12-slim-bookworm@sha256:b919342376872123c5dc149e0e76d2931ef8875baf0b43775a0e1e5b43fecd22
FROM ${DIAG_BASE_IMAGE}

WORKDIR /app
COPY app /app

EXPOSE 8765
CMD ["python", "/app/server.py"]
