# syntax=docker/dockerfile:1

FROM debian:bookworm-slim AS stockfish-builder
ARG STOCKFISH_TAG=sf_19
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential && \
    rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${STOCKFISH_TAG}" \
    https://github.com/official-stockfish/Stockfish.git /src/Stockfish
WORKDIR /src/Stockfish/src
RUN make -j"$(nproc)" build ARCH=x86-64-universal && strip stockfish

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STOCKFISH_PATH=/usr/local/bin/stockfish \
    STOCKFISH_THREADS=2 \
    STOCKFISH_HASH_MB=512 \
    MAX_ANALYSIS_MS=15000 \
    MAX_MULTIPV=8 \
    MAX_DEPTH=40 \
    MAX_NODES=50000000 \
    PORT=8080

RUN useradd --create-home --uid 10001 appuser
COPY --from=stockfish-builder /src/Stockfish/src/stockfish /usr/local/bin/stockfish
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .
USER appuser
EXPOSE 8080
CMD ["python", "-m", "app.server"]
