import asyncio
from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import User, Mountpoint
from .ntrip.caster import NtripCaster
from .services.mountpoint_manager import MountpointManager

app = FastAPI(title="NTRIP Caster")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

manager = MountpointManager()
caster = NtripCaster(manager=manager)


@app.on_event("startup")
async def startup():
    # Create tables
    Base.metadata.create_all(bind=engine)
    # Lightweight migration: add tcp_port column if missing
    try:
        with engine.connect() as conn:
            # Check if tcp_port exists
            res = conn.exec_driver_sql("PRAGMA table_info(mountpoints)")
            cols = [row[1] for row in res.fetchall()]
            if 'tcp_port' not in cols:
                conn.exec_driver_sql("ALTER TABLE mountpoints ADD COLUMN tcp_port INTEGER")
    except Exception as e:
        print(f"Migration check failed or skipped: {e}")
    # Start NTRIP server
    asyncio.create_task(caster.start())


@app.on_event("shutdown")
async def shutdown():
    await caster.stop()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    users = db.query(User).all()
    mps = db.query(Mountpoint).all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "users": users, "mountpoints": mps})


@app.post("/users")
async def create_user(username: str = Form(...), password: str = Form(...), connection_limit: int = Form(5), db: Session = Depends(get_db)):
    if db.query(User).filter_by(username=username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    u = User(username=username, password=password, connection_limit=connection_limit)
    db.add(u)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/users/{user_id}/delete")
async def delete_user(user_id: int, db: Session = Depends(get_db)):
    u = db.query(User).get(user_id)
    if u:
        # delete related mountpoints as well
        for mp in list(u.mountpoints):
            db.delete(mp)
        db.delete(u)
        db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/mountpoints")
async def create_mountpoint(
    owner_id: int = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    source_username: str = Form(...),
    source_password: str = Form(...),
    source_protocol: str = Form("ntrip"),
    tcp_port: int | None = Form(None),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    db: Session = Depends(get_db),
):
    if db.query(Mountpoint).filter_by(name=name).first():
        raise HTTPException(status_code=400, detail="Mountpoint name already exists")
    mp = Mountpoint(
        owner_id=owner_id,
        name=name,
        description=description or None,
        source_username=source_username,
        source_password=source_password,
        source_protocol=source_protocol,
        tcp_port=tcp_port,
        latitude=latitude,
        longitude=longitude,
    )
    db.add(mp)
    db.commit()

    # Start dedicated TCP raw listener if requested
    if mp.source_protocol == 'tcp_raw' and mp.tcp_port:
        try:
            await caster.start_tcp_raw_listener(mp.id, mp.name, mp.tcp_port)
        except Exception as e:
            # Rollback listener intent on failure, but keep the mountpoint
            print(f"Failed to start TCP raw listener for {mp.name} on port {mp.tcp_port}: {e}")

    return RedirectResponse(url="/", status_code=303)


@app.post("/mountpoints/{mp_id}/delete")
async def delete_mountpoint(mp_id: int, db: Session = Depends(get_db)):
    mp = db.query(Mountpoint).get(mp_id)
    if mp:
        # Stop any dedicated TCP raw listener
        try:
            await caster.stop_tcp_raw_listener(mp.id)
        except Exception:
            pass
        db.delete(mp)
        db.commit()
    return RedirectResponse(url="/", status_code=303)

