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

Option A: Docker (recommended)

1) Build the image:

  docker build -t ntripcaster:latest .

2) Run with Docker directly:

  docker run -it --rm \
    -p 8000:8000 \
    -p 2101:2101 \
    -v $(pwd)/ntripcaster.db:/app/ntripcaster.db \
    --name ntripcaster \
    ntripcaster:latest

- Admin UI: http://localhost:8000/
- NTRIP caster TCP server: localhost:2101
- If you plan to use TCP/IP raw sources on dedicated ports (e.g., 5001), also publish those ports with additional -p flags, e.g. -p 5001:5001.
- On Linux, you can alternatively use host networking to avoid publishing many ports: --network host

3) Or use Docker Compose:

  docker compose up -d

- Edit docker-compose.yml to add extra ports for TCP/IP raw sources (see comments inside file).

Option B: Local (without Docker)

1) Install dependencies (Python 3.10+ recommended):

- Create a virtualenv and install requirements.txt

  pip install -r requirements.txt

2) Run the service:

  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

- The admin UI will be at http://localhost:8000/
- The NTRIP caster TCP server listens on port 2101 by default.


Creating users and mountpoints

- In the UI, create a user (set a connection limit; this limits total concurrent client GET connections for all mountpoints owned by that user).
- Create a mountpoint with a unique name, source username, and source password. Choose source protocol: NTRIP (auto-detects v1 or v2) or TCP/IP (raw). If TCP/IP is selected, specify the dedicated TCP port to receive data for that base. Optionally set base latitude/longitude for NEAREST routing.


Connecting a base (source)

- NTRIP v1 server (encoder) example:
  SOURCE password /MOUNT


- NTRIP v2 server (encoder) example (HTTP/1.1):
  POST /MOUNT HTTP/1.1
Ntrip-Version: Ntrip/2.0
Authorization: Basic base64(source_username:source_password)


- TCP raw mode (simple preface):
  AUTH source_username:source_password MOUNT\r\n
  Then stream GNSS data (RTCM) bytes. The caster will respond with ICY 200 OK.


Connecting a client (rover)

- NTRIP v1 client example:
  GET /MOUNT HTTP/1.0
User-Agent: NTRIP myclient
Authorization: Basic base64(source_username:source_password)


- NTRIP v2 client example:
  GET /MOUNT HTTP/1.1
Ntrip-Version: Ntrip/2.0
Authorization: Basic base64(source_username:source_password)


- NEAREST virtual mountpoint:
  GET /NEAREST HTTP/1.0
Authorization: Basic base64(source_username:source_password)


  After the 200 OK response, send a GGA sentence (e.g., $GPGGA...) so the caster can route you to the nearest online base with known coordinates. The stream will be proxied from that base.


Notes on behavior and limitations

- Protocol detection: The caster looks at the request headers; presence of Ntrip-Version: Ntrip/2.x indicates v2. Otherwise v1 is assumed; responses use ICY 200 OK for v1 and HTTP/1.1 200 OK for v2.
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
  cd /path/to/ntripcaster2

Quick run (single line)

- If you prefer a single command you can paste directly to start the container after building the image:
  docker run -it --rm -p 8000:8000 -p 2101:2101 -v $(pwd)/ntripcaster.db:/app/ntripcaster.db --name ntripcaster ntripcaster:latest

Troubleshooting

- Error: failed to read dockerfile: open Dockerfile: no such file or directory
  Cause: You executed docker build in a directory that doesn’t contain the project’s Dockerfile.
  Fix: cd into the repository directory first (where Dockerfile is), then run:
    cd /path/to/ntripcaster2
    docker build -t ntripcaster:latest .

- Error: docker run requires at least 1 argument, and/or each -p/-v line is treated as a separate shell command (-p: command not found)
  Cause: You split the docker run command across multiple lines without using trailing backslashes, so the shell interprets each line as a separate command.
  Fix A (recommended): Use the single-line command above.
  Fix B (multi-line): Ensure each line ends with a backslash (\) like this:
    docker run -it --rm \
      -p 8000:8000 \
      -p 2101:2101 \
      -v $(pwd)/ntripcaster.db:/app/ntripcaster.db \
      --name ntripcaster \
      ntripcaster:latest

- Raw TCP sources on dedicated ports
  If you create mountpoints with source protocol TCP/IP (raw), you must also publish those ports when running the container, e.g.:
    -p 5001:5001 -p 5002:5002
  On Linux you can instead use host networking to avoid publishing many ports:
    --network host

- Resetting the database on next start
  By default, the app keeps your existing ntripcaster.db. To force a one-time reset (with a timestamped backup), set the environment variable when running:
    docker run -it --rm -e NTRIP_OVERWRITE_DB=true -p 8000:8000 -p 2101:2101 -v $(pwd)/ntripcaster.db:/app/ntripcaster.db --name ntripcaster ntripcaster:latest
  In docker-compose.yml, temporarily set NTRIP_OVERWRITE_DB: "true" and restart once.
