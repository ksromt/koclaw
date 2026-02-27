# Koclaw Gateway - Multi-stage Rust build
# Usage: docker build -t koclaw-gateway .

# --- Build stage ---
FROM rust:1.93-bookworm AS builder

WORKDIR /app
COPY Cargo.toml Cargo.lock* ./
COPY common/ common/
COPY gateway/ gateway/
COPY channels/ channels/

RUN cargo build --release --bin koclaw

# --- Runtime stage ---
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Run as non-root user
RUN useradd -m -s /bin/bash koclaw
USER koclaw
WORKDIR /home/koclaw

COPY --from=builder /app/target/release/koclaw /usr/local/bin/koclaw
COPY config.example.toml ./config.toml

# Create workspace directory
RUN mkdir -p workspace

EXPOSE 18789

ENTRYPOINT ["koclaw"]
