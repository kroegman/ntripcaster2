#!/usr/bin/env bash
set -euo pipefail

# One-click installer for ntripcaster
# Defaults can be overridden via environment variables:
#   IMAGE           - container image (default ghcr.io/kroegman/ntripcaster2:latest)
#   HTTP_PORT       - admin UI port on host (default 8000)
#   NTRIP_PORT      - NTRIP caster port on host (default 2101)
#   DB_PATH         - path to SQLite DB on host (default ./ntripcaster.db)
#   OVERWRITE_DB    - if set to 1/true, sets NTRIP_OVERWRITE_DB=true in container (default false)
#   EXTRA_PORTS     - extra "-p host:container" mappings for raw TCP sources (optional)

IMAGE=${IMAGE:-ghcr.io/kroegman/ntripcaster2:latest}
HTTP_PORT=${HTTP_PORT:-8000}
NTRIP_PORT=${NTRIP_PORT:-2101}
DB_PATH=${DB_PATH:-$(pwd)/ntripcaster.db}
OVERWRITE_DB=${OVERWRITE_DB:-}
EXTRA_PORTS=${EXTRA_PORTS:-}
CONTAINER_NAME=${CONTAINER_NAME:-ntripcaster}

need_sudo() {
  if command -v sudo >/dev/null 2>&1; then echo sudo; else echo; fi
}

log() { echo "[install] $*"; }

ensure_docker() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker found: $(docker --version)"
    return
  fi
  log "Docker not found. Installing Docker using the official convenience script..."
  local SUDO
  SUDO=$(need_sudo)
  ${SUDO} apt-get update -y
  ${SUDO} apt-get install -y ca-certificates curl
  curl -fsSL https://get.docker.com | ${SUDO} sh
  ${SUDO} systemctl enable docker || true
  ${SUDO} systemctl start docker || true
  log "Docker installed: $(docker --version)"
}

prepare_db() {
  if [ ! -f "$DB_PATH" ]; then
    log "Creating DB file at $DB_PATH"
    mkdir -p "$(dirname "$DB_PATH")"
    touch "$DB_PATH"
  fi
}

run_container() {
  local SUDO
  SUDO=$(need_sudo)

  # Stop and remove existing container if running
  if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log "Container ${CONTAINER_NAME} exists, replacing it..."
    ${SUDO} docker rm -f "${CONTAINER_NAME}" || true
  fi

  local ENV_FLAGS=""
  if [ -n "$OVERWRITE_DB" ]; then
    case "${OVERWRITE_DB,,}" in
      1|true|yes|y) ENV_FLAGS="-e NTRIP_OVERWRITE_DB=true" ;; 
      *) ;; 
    esac
  fi

  # Build port flags
  local PORT_FLAGS="-p ${HTTP_PORT}:8000 -p ${NTRIP_PORT}:2101"
  if [ -n "$EXTRA_PORTS" ]; then
    PORT_FLAGS="${PORT_FLAGS} ${EXTRA_PORTS}"
  fi

  log "Pulling image ${IMAGE}"
  ${SUDO} docker pull "${IMAGE}"

  log "Starting container ${CONTAINER_NAME}"
  ${SUDO} docker run -d \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    ${ENV_FLAGS} \
    ${PORT_FLAGS} \
    -v "${DB_PATH}:/app/ntripcaster.db" \
    "${IMAGE}"

  log "Container started."
  log "Admin UI:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):${HTTP_PORT} (or server's public IP)"
  log "NTRIP port: $(hostname -I 2>/dev/null | awk '{print $1}'):${NTRIP_PORT}"
}

main() {
  ensure_docker
  prepare_db
  run_container
}

main "$@"
