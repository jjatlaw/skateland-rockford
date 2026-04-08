from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, func
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
import qrcode
from io import BytesIO
import base64
from apscheduler.schedulers.background import BackgroundScheduler
import secrets

app = FastAPI(title="Skateland Rockford Song Requests")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ====================== PASSWORD PROTECTION ======================
security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, "dj")
    correct_password = secrets.compare_digest(credentials.password, "skatelandrocks")  # CHANGE THIS PASSWORD!
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Database setup
Base = declarative_base()
engine = create_engine("sqlite:///requests.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

class SongRequest(Base):
    __tablename__ = "song_requests"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    artist = Column(String)
    votes = Column(Integer, default=0)
    is_played = Column(Boolean, default=False)
    is_flagged = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# Midnight clear
def clear_nightly():
    db = SessionLocal()
    db.query(SongRequest).filter(SongRequest.is_played == False).delete()
    db.commit()
    db.close()
    print("✅ Nightly song list cleared")

scheduler = BackgroundScheduler()
scheduler.add_job(clear_nightly, 'cron', hour=5, minute=0)
scheduler.start()

# ====================== GUEST PAGE (No Password) ======================
@app.get("/", response_class=HTMLResponse)
async def guest_page(request: Request):
    db = SessionLocal()
    songs = db.query(SongRequest).filter(
        SongRequest.is_played == False,
        SongRequest.is_flagged == False
    ).order_by(SongRequest.votes.desc()).all()
    db.close()
    return templates.TemplateResponse(
        request=request,
        name="guest.html",
        context={"songs": songs}
    )

@app.post("/request")
async def add_request(title: str = Form(...), artist: str = Form(...)):
    db = SessionLocal()
    song = SongRequest(title=title.strip(), artist=artist.strip())
    db.add(song)
    db.commit()
    db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/vote/{song_id}")
async def vote(song_id: int):
    db = SessionLocal()
    song = db.query(SongRequest).filter(SongRequest.id == song_id).first()
    if song and not song.is_played and not song.is_flagged:
        song.votes += 1
        db.commit()
    db.close()
    return {"success": True}

# ====================== DJ & ADMIN (Password Protected) ======================
@app.get("/dj", response_class=HTMLResponse)
async def dj_page(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    songs = db.query(SongRequest).order_by(SongRequest.votes.desc()).all()
    db.close()
    return templates.TemplateResponse(
        request=request,
        name="dj.html",
        context={"songs": songs}
    )

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    stats = db.query(
        SongRequest.title, 
        SongRequest.artist, 
        func.count(SongRequest.id).label("request_count")
    ).group_by(SongRequest.title, SongRequest.artist)\
     .order_by(func.count(SongRequest.id).desc()).limit(10).all()
    db.close()
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={"stats": stats}
    )

# DJ Actions
@app.post("/dj/mark-played/{song_id}")
async def mark_played(song_id: int, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    song = db.query(SongRequest).filter(SongRequest.id == song_id).first()
    if song:
        song.is_played = True
        db.commit()
    db.close()
    return RedirectResponse("/dj", status_code=303)

@app.post("/dj/flag/{song_id}")
async def flag_song(song_id: int, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    song = db.query(SongRequest).filter(SongRequest.id == song_id).first()
    if song:
        song.is_flagged = True
        db.commit()
    db.close()
    return RedirectResponse("/dj", status_code=303)

# QR Code
@app.get("/qr")
async def generate_qr():
    url = "https://skateland-rockford.onrender.com"   # We'll update this after deployment
    qr = qrcode.make(url)
    buffered = BytesIO()
    qr.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return {"qr_base64": img_str}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)