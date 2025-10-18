### NTRIP Caster (Minimal Implementation)

This repository contains a minimal NTRIP caster with a simple admin UI. It supports:

- Receiving data from base stations via NTRIP v1 or v2 (HTTP-based) and a simple TCP/IP raw mode.
- Creating users with a per-user client connection limit.
- Creating mountpoints; each mountpoint has a unique username and password (used for both v1 and v2).
- Detecting base online/offline state based on data flow.
- A special virtual mountpoint named NEAREST to automatically connect clients to the nearest online base after receiving a GGA sentence.
- Clear web UI to create/delete users and mountpoints and inspect status.

Note: This is a minimal, single-process implementation suitable for demos/dev only. For production, consider robust auth, TLS, persistent connection tracking, logging, and horizontal scalability.


Getting started

One-click install on a fresh remote server (Ubuntu/Debian)

- This command installs Docker if missing, pulls the prebuilt image from GHCR, and runs the service with ports 8000 and 2101. You can customize ports and other options via env vars.

```bash
curl -fsSL https://raw.githubusercontent.com/kroegman/ntripcaster2/main/scripts/install.sh | bash
```

Optional overrides (example):

```bash
HTTP_PORT=8080 NTRIP_PORT=2201 OVERWRITE_DB=true \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/kroegman/ntripcaster2/main/scripts/install.sh)"
```

Option A: Docker (recommended)

1) Build the image:

```bash
docker build -t ntripcaster:latest .
```

2) Run with Docker directly:

```bash
docker run -it --rm \
  -p 8000:8000 \
  -p 2101:2101 \
  -v $(pwd)/ntripcaster.db:/app/ntripcaster.db \
  --name ntripcaster \
  ntripcaster:latest
```

- Admin UI: http://localhost:8000/
- NTRIP caster TCP server: localhost:2101
- If you plan to use TCP/IP raw sources on dedicated ports (e.g., 5001), also publish those ports with additional -p flags, e.g. `-p 5001:5001`.
- On Linux, you can alternatively use host networking to avoid publishing many ports: `--network host`

3) Run with the published image (no local build):

```bash
docker run -it --rm \
  -p 8000:8000 \
  -p 2101:2101 \
  -v $(pwd)/ntripcaster.db:/app/ntripcaster.db \
  --name ntripcaster \
  ghcr.io/kroegman/ntripcaster2:latest
```

4) Or use Docker Compose (pulls the image automatically):

```bash
docker compose up -d
```

- Edit docker-compose.yml to add extra ports for TCP/IP raw sources (see comments inside file).

Option B: Local (without Docker)

1) Install dependencies (Python 3.10+ recommended):

- Create a virtualenv and install requirements.txt

```bash
pip install -r requirements.txt
```

2) Run the service:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- The admin UI will be at http://localhost:8000/
- The NTRIP caster TCP server listens on port 2101 by default.


Creating users and mountpoints

- In the UI, create a user (set a connection limit; this limits total concurrent client GET connections for all mountpoints owned by that user).
- Create a mountpoint with a unique name, source username, and source password. Choose source protocol: NTRIP (auto-detects v1 or v2) or TCP/IP (raw). If TCP/IP is selected, specify the dedicated TCP port to receive data for that base. Optionally set base latitude/longitude for NEAREST routing.


Connecting a base (source)

- NTRIP v1 server (encoder) example:

```text
SOURCE password /MOUNT
```

- NTRIP v2 server (encoder) example (HTTP/1.1):

```http
POST /MOUNT HTTP/1.1
Ntrip-Version: Ntrip/2.0
Authorization: Basic base64(source_username:source_password)
```

- TCP raw mode (simple preface):

```text
AUTH source_username:source_password MOUNT\r\n
```
Then stream GNSS data (RTCM) bytes. The caster will respond with ICY 200 OK.


Connecting a client (rover)

- NTRIP v1 client example:

```http
GET /MOUNT HTTP/1.0
User-Agent: NTRIP myclient
Authorization: Basic base64(source_username:source_password)
```

- NTRIP v2 client example:

```http
GET /MOUNT HTTP/1.1
Ntrip-Version: Ntrip/2.0
Authorization: Basic base64(source_username:source_password)
```

- NEAREST virtual mountpoint:

```http
GET /NEAREST HTTP/1.0
Authorization: Basic base64(source_username:source_password)
```

After the 200 OK response, send a GGA sentence (e.g., `$GPGGA...`) so the caster can route you to the nearest online base with known coordinates. The stream will be proxied from that base.


Notes on behavior and limitations

- Protocol detection: The caster looks at the request headers; presence of `Ntrip-Version: Ntrip/2.x` indicates v2. Otherwise v1 is assumed; responses use `ICY 200 OK` for v1 and `HTTP/1.1 200 OK` for v2.
- Password reuse: The mountpoint source password is used for both v1 and v2, meeting the requirement.
- Online/offline: A mountpoint is marked online when source data is flowing and is set offline if stale for ~15 seconds.
- Per-user connection limits: Enforced for client GET connections across all that user’s mountpoints. If exceeded, the request is rejected with Unauthorized.
- Security: Passwords are stored plain-text in this minimal build; in production, hash them and use HTTPS/TLS termination.
- Sourcetable: Not implemented here; 404/SOURCETABLE 0 is returned when a mountpoint is not found.


Project layout

- app/db.py – DB engine and session factory
- app/models.py – SQLAlchemy models (User, Mountpoint)
- app/services/mountpoint_manager.py – In-memory hubs, online status, nearest selection
- app/ntrip/protocol.py – NTRIP request parsing and response builders
- app/ntrip/caster.py – Async TCP server implementing NTRIP v1/v2 and raw AUTH mode
- app/main.py – FastAPI admin app and startup wiring for the caster
- templates/dashboard.html – Admin UI
- static/style.css – Basic styling
- requirements.txt – Python dependencies


License

- MIT (or adapt as needed)



Before you begin

- Make sure you are inside the repository directory (the one that contains Dockerfile) before building or running with Docker:

```bash
cd /path/to/ntripcaster2
```

Quick run (single line)

- If you prefer a single command you can paste directly to start the container after building the image:

```bash
docker run -it --rm -p 8000:8000 -p 2101:2101 -v $(pwd)/ntripcaster.db:/app/ntripcaster.db --name ntripcaster ntripcaster:latest
```

Troubleshooting

- Error: Unable to find image 'ntripcaster:latest' locally / pull access denied
  Cause: You tried to run the container before building the image locally (there is no public registry image for this tag).
  Fix A (build then run):

```bash
cd /path/to/ntripcaster2
docker build -t ntripcaster:latest .
docker run -it --rm -p 8000:8000 -p 2101:2101 -v $(pwd)/ntripcaster.db:/app/ntripcaster.db --name ntripcaster ntripcaster:latest
```

  Fix B (Compose, builds automatically):

```bash
cd /path/to/ntripcaster2
docker compose up --build -d
```

- Error: failed to read dockerfile: open Dockerfile: no such file or directory
  Cause: You executed docker build in a directory that doesn’t contain the project’s Dockerfile.
  Fix: cd into the repository directory first (where Dockerfile is), then run:

```bash
cd /path/to/ntripcaster2
docker build -t ntripcaster:latest .
```

- Error: docker run requires at least 1 argument, and/or each -p/-v line is treated as a separate shell command (-p: command not found)
  Cause: You split the docker run command across multiple lines without using trailing backslashes, so the shell interprets each line as a separate command.
  Fix A (recommended): Use the single-line command above.
  Fix B (multi-line): Ensure each line ends with a backslash (\) like this:

```bash
docker run -it --rm \
  -p 8000:8000 \
  -p 2101:2101 \
  -v $(pwd)/ntripcaster.db:/app/ntripcaster.db \
  --name ntripcaster \
  ntripcaster:latest
```

- Raw TCP sources on dedicated ports
  If you create mountpoints with source protocol TCP/IP (raw), you must also publish those ports when running the container, e.g.:

```bash
-p 5001:5001 -p 5002:5002
```

  On Linux you can instead use host networking to avoid publishing many ports:

```bash
--network host
```

- Resetting the database on next start
  By default, the app keeps your existing ntripcaster.db. To force a one-time reset (with a timestamped backup), set the environment variable when running:

```bash
docker run -it --rm -e NTRIP_OVERWRITE_DB=true -p 8000:8000 -p 2101:2101 -v $(pwd)/ntripcaster.db:/app/ntripcaster.db --name ntripcaster ntripcaster:latest
```

  In docker-compose.yml, temporarily set `NTRIP_OVERWRITE_DB: "true"` and restart once.

### CI/CD (Container Image Publishing)

- This repository publishes multi-arch Docker images (linux/amd64, linux/arm64) to GitHub Container Registry on every push to the default branch and on tags.
- Image reference: `ghcr.io/kroegman/ntripcaster2:latest` (or a specific tag/SHA created by the workflow).
- You can use Docker Compose (included) or the one-click installer to pull and run this image directly without a local build.

Workflow summary:
- Triggers: push to main/master, tags, or manual dispatch.
- Uses Buildx with QEMU to build multi-arch images.
- Authenticates to GHCR using the built-in GITHUB_TOKEN with packages:write permission.

If you fork the repo:
- The workflow should work without extra secrets; ensure Actions permissions allow packages: write for the repository.
- Your image path will be `ghcr.io/<your-github-username-or-org>/ntripcaster2`.
