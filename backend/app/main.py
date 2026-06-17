from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", DATA_DIR / "uploads"))
DEFAULT_SQLITE = f"sqlite:///{Path(os.getenv('DATABASE_PATH', DATA_DIR / 'mmotors.sqlite3'))}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

SECRET = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
ALERT_LOG = DATA_DIR / "alerts.log"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mmotors")

engine_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

REQUEST_COUNT = 0
ERROR_COUNT = 0

class UserModel(Base):
    __tablename__ = "users"
    email = Column(String(180), primary_key=True)
    full_name = Column(String(80), nullable=False)
    role = Column(String(20), nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    applications = relationship("ApplicationModel", back_populates="user")

class VehicleModel(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True, index=True)
    brand = Column(String(40), nullable=False)
    model = Column(String(40), nullable=False)
    year = Column(Integer, nullable=False)
    mileage = Column(Integer, nullable=False)
    price = Column(Integer, nullable=False)
    mode = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    applications = relationship("ApplicationModel", back_populates="vehicle")

class ApplicationModel(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    user_email = Column(String(180), ForeignKey("users.email"), nullable=False)
    mode = Column(String(20), nullable=False)
    message = Column(Text, default="")
    status = Column(String(20), nullable=False, default="pending")
    admin_comment = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    vehicle = relationship("VehicleModel", back_populates="applications")
    user = relationship("UserModel", back_populates="applications")
    documents = relationship("DocumentModel", back_populates="application", cascade="all, delete-orphan")

class DocumentModel(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    stored_name = Column(String(400), nullable=False)
    content_type = Column(String(100), nullable=False)
    size = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    application = relationship("ApplicationModel", back_populates="documents")

class Role(str, Enum):
    user = "user"
    admin = "admin"

class Mode(str, Enum):
    sale = "sale"
    rental = "rental"

class Status(str, Enum):
    pending = "pending"
    accepted = "accepted"
    refused = "refused"

class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=2, max_length=80)
    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.lower().strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
            raise ValueError("Email invalide")
        return value

class Login(BaseModel):
    email: str
    password: str
    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower().strip()

class VehicleIn(BaseModel):
    brand: str = Field(min_length=2, max_length=40)
    model: str = Field(min_length=1, max_length=40)
    year: int = Field(ge=1990, le=2035)
    mileage: int = Field(ge=0)
    price: int = Field(gt=0)
    mode: Mode

class Vehicle(VehicleIn):
    id: int
    created_at: str

class ApplicationIn(BaseModel):
    vehicle_id: int
    mode: Mode
    message: Optional[str] = Field(default="", max_length=500)

class Application(BaseModel):
    id: int
    vehicle_id: int
    mode: Mode
    message: str = ""
    user_email: str
    status: Status
    admin_comment: Optional[str] = None
    created_at: str
    documents_count: int = 0

class Decision(BaseModel):
    status: Status
    admin_comment: Optional[str] = Field(default=None, max_length=500)

class DocumentOut(BaseModel):
    id: int
    application_id: int
    filename: str
    content_type: str
    size: int
    uploaded_at: str

def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def now_dt() -> datetime:
    return datetime.utcnow().replace(microsecond=0)

def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))

def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or _b64(os.urandom(16))
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 140_000)
    return f"pbkdf2_sha256${salt}${_b64(digest)}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        _, salt, expected = hashed.split("$", 2)
    except ValueError:
        return False
    candidate = hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(candidate, expected)

def create_token(email: str, role: str) -> str:
    payload = {"sub": email, "role": role, "exp": (datetime.utcnow() + timedelta(hours=8)).timestamp()}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"

def decode_token(raw_token: str) -> dict:
    try:
        body, signature = raw_token.split(".", 1)
        expected = _b64(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(_unb64(body))
        if datetime.utcnow().timestamp() > payload["exp"]:
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré") from exc

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def current_user(raw_token: str = Depends(oauth2_scheme)):
    return decode_token(raw_token)

def admin_only(user=Depends(current_user)):
    if user.get("role") != Role.admin.value:
        raise HTTPException(status_code=403, detail="Accès admin requis")
    return user

def vehicle_to_schema(v: VehicleModel) -> dict:
    return {"id": v.id, "brand": v.brand, "model": v.model, "year": v.year, "mileage": v.mileage, "price": v.price, "mode": v.mode, "created_at": iso(v.created_at)}

def application_to_schema(a: ApplicationModel) -> dict:
    return {
        "id": a.id, "vehicle_id": a.vehicle_id, "mode": a.mode, "message": a.message or "", "user_email": a.user_email,
        "status": a.status, "admin_comment": a.admin_comment, "created_at": iso(a.created_at), "documents_count": len(a.documents or []),
    }

def document_to_schema(d: DocumentModel) -> dict:
    return {"id": d.id, "application_id": d.application_id, "filename": d.filename, "content_type": d.content_type, "size": d.size, "uploaded_at": iso(d.uploaded_at)}

def init_db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        if session.query(UserModel).count() == 0:
            session.add_all([
                UserModel(email="admin@mmotors.fr", full_name="Admin M-Motors", role=Role.admin.value, password_hash=hash_password("Admin123!"), created_at=now_dt()),
                UserModel(email="user@mmotors.fr", full_name="Client Démo", role=Role.user.value, password_hash=hash_password("User123!"), created_at=now_dt()),
            ])
        if session.query(VehicleModel).count() == 0:
            session.add_all([
                VehicleModel(brand="Peugeot", model="308", year=2020, mileage=48000, price=15900, mode=Mode.sale.value, created_at=now_dt()),
                VehicleModel(brand="Renault", model="Clio", year=2021, mileage=35000, price=299, mode=Mode.rental.value, created_at=now_dt()),
                VehicleModel(brand="Toyota", model="Yaris", year=2019, mileage=62000, price=13900, mode=Mode.sale.value, created_at=now_dt()),
                VehicleModel(brand="Volkswagen", model="Golf", year=2022, mileage=22000, price=389, mode=Mode.rental.value, created_at=now_dt()),
                VehicleModel(brand="Citroën", model="C3", year=2023, mileage=12000, price=249, mode=Mode.rental.value, created_at=now_dt()),
            ])
        session.commit()
    finally:
        session.close()

app = FastAPI(title="M-Motors API", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
init_db()

@app.middleware("http")
async def log_requests(request: Request, call_next):
    global REQUEST_COUNT, ERROR_COUNT
    REQUEST_COUNT += 1
    start = datetime.utcnow()
    try:
        response = await call_next(request)
    except Exception:
        ERROR_COUNT += 1
        logger.exception("Erreur serveur non gérée")
        ALERT_LOG.parent.mkdir(exist_ok=True)
        with ALERT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{iso(now_dt())} ERREUR SERVEUR NON GEREE\n")
        raise
    if response.status_code >= 500:
        ERROR_COUNT += 1
    duration = (datetime.utcnow() - start).total_seconds() * 1000
    logger.info("%s %s %s %.2fms", request.method, request.url.path, response.status_code, duration)
    return response

@app.get("/health")
def health(db_session: Session = Depends(get_db)):
    db_session.execute(func.count(UserModel.email).select())
    database = "postgresql" if DATABASE_URL.startswith("postgresql") else "sqlite"
    return {"status": "ok", "database": database, "rpo": "15 minutes", "rto": "1 heure", "uploads": str(UPLOAD_DIR)}

@app.get("/metrics", response_class=PlainTextResponse)
def metrics(db_session: Session = Depends(get_db)):
    vehicles = db_session.query(VehicleModel).count()
    applications = db_session.query(ApplicationModel).count()
    docs = db_session.query(DocumentModel).count()
    content = f"""# HELP mmotors_requests_total Total HTTP requests seen by the API\n# TYPE mmotors_requests_total counter\nmmotors_requests_total {REQUEST_COUNT}\n# HELP mmotors_errors_total Total 5xx or unhandled errors\n# TYPE mmotors_errors_total counter\nmmotors_errors_total {ERROR_COUNT}\n# HELP mmotors_vehicles_total Vehicles in catalog\n# TYPE mmotors_vehicles_total gauge\nmmotors_vehicles_total {vehicles}\n# HELP mmotors_applications_total Client applications\n# TYPE mmotors_applications_total gauge\nmmotors_applications_total {applications}\n# HELP mmotors_documents_total Uploaded documents\n# TYPE mmotors_documents_total gauge\nmmotors_documents_total {docs}\n"""
    return content

@app.post("/health/alert-test")
def alert_test(user=Depends(admin_only)):
    line = f"{iso(now_dt())} ALERTE TEST déclenchée par {user['sub']}"
    with ALERT_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    logger.warning(line)
    return {"alert": "simulated", "sent": True, "log_file": str(ALERT_LOG)}

@app.post("/auth/register")
def register(data: UserCreate, db_session: Session = Depends(get_db)):
    if db_session.get(UserModel, data.email):
        raise HTTPException(status_code=409, detail="Email déjà utilisé")
    user = UserModel(email=data.email, full_name=data.full_name, role=Role.user.value, password_hash=hash_password(data.password), created_at=now_dt())
    db_session.add(user); db_session.commit()
    return {"access_token": create_token(data.email, Role.user.value), "token_type": "bearer", "role": Role.user.value}

@app.post("/auth/login")
def login(data: Login, db_session: Session = Depends(get_db)):
    user = db_session.get(UserModel, data.email)
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    return {"access_token": create_token(user.email, user.role), "token_type": "bearer", "role": user.role}

@app.get("/vehicles", response_model=list[Vehicle])
def list_vehicles(mode: Optional[Mode] = None, db_session: Session = Depends(get_db)):
    query = db_session.query(VehicleModel)
    if mode:
        query = query.filter(VehicleModel.mode == mode.value)
    return [vehicle_to_schema(v) for v in query.order_by(VehicleModel.id.desc()).all()]

@app.post("/vehicles", response_model=Vehicle)
def add_vehicle(data: VehicleIn, user=Depends(admin_only), db_session: Session = Depends(get_db)):
    vehicle = VehicleModel(brand=data.brand, model=data.model, year=data.year, mileage=data.mileage, price=data.price, mode=data.mode.value, created_at=now_dt())
    db_session.add(vehicle); db_session.commit(); db_session.refresh(vehicle)
    return vehicle_to_schema(vehicle)

@app.patch("/vehicles/{vehicle_id}/switch", response_model=Vehicle)
def switch_vehicle(vehicle_id: int, user=Depends(admin_only), db_session: Session = Depends(get_db)):
    vehicle = db_session.get(VehicleModel, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Véhicule introuvable")
    vehicle.mode = Mode.rental.value if vehicle.mode == Mode.sale.value else Mode.sale.value
    db_session.commit(); db_session.refresh(vehicle)
    return vehicle_to_schema(vehicle)

@app.post("/applications", response_model=Application)
def create_application(data: ApplicationIn, user=Depends(current_user), db_session: Session = Depends(get_db)):
    if not db_session.get(VehicleModel, data.vehicle_id):
        raise HTTPException(status_code=404, detail="Véhicule introuvable")
    app_row = ApplicationModel(vehicle_id=data.vehicle_id, user_email=user["sub"], mode=data.mode.value, message=data.message or "", status=Status.pending.value, created_at=now_dt())
    db_session.add(app_row); db_session.commit(); db_session.refresh(app_row)
    return application_to_schema(app_row)

@app.get("/applications", response_model=list[Application])
def list_applications(user=Depends(current_user), db_session: Session = Depends(get_db)):
    query = db_session.query(ApplicationModel)
    if user["role"] != Role.admin.value:
        query = query.filter(ApplicationModel.user_email == user["sub"])
    return [application_to_schema(a) for a in query.order_by(ApplicationModel.id.desc()).all()]

@app.patch("/applications/{application_id}/decision", response_model=Application)
def decide_application(application_id: int, data: Decision, user=Depends(admin_only), db_session: Session = Depends(get_db)):
    app_row = db_session.get(ApplicationModel, application_id)
    if not app_row:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    app_row.status = data.status.value
    app_row.admin_comment = data.admin_comment
    db_session.commit(); db_session.refresh(app_row)
    return application_to_schema(app_row)

@app.post("/applications/{application_id}/documents", response_model=DocumentOut)
async def upload_document(application_id: int, file: UploadFile = File(...), user=Depends(current_user), db_session: Session = Depends(get_db)):
    app_row = db_session.get(ApplicationModel, application_id)
    if not app_row:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    if user["role"] != Role.admin.value and app_row.user_email != user["sub"]:
        raise HTTPException(status_code=403, detail="Accès au dossier refusé")
    allowed = {"application/pdf", "image/png", "image/jpeg"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Format refusé : PDF, PNG ou JPG uniquement")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux, maximum 5 Mo")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename or "document")
    stored_name = f"{application_id}_{uuid.uuid4().hex}_{safe_name}"
    (UPLOAD_DIR / stored_name).write_bytes(content)
    doc = DocumentModel(application_id=application_id, filename=safe_name, stored_name=stored_name, content_type=file.content_type, size=len(content), uploaded_at=now_dt())
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)
    logger.info("Document stocké dossier=%s fichier=%s taille=%s", application_id, safe_name, len(content))
    return document_to_schema(doc)

@app.get("/applications/{application_id}/documents", response_model=list[DocumentOut])
def list_documents(application_id: int, user=Depends(current_user), db_session: Session = Depends(get_db)):
    app_row = db_session.get(ApplicationModel, application_id)
    if not app_row:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    if user["role"] != Role.admin.value and app_row.user_email != user["sub"]:
        raise HTTPException(status_code=403, detail="Accès au dossier refusé")
    return [document_to_schema(d) for d in db_session.query(DocumentModel).filter(DocumentModel.application_id == application_id).order_by(DocumentModel.id.desc()).all()]

@app.get("/admin/logs")
def admin_logs(user=Depends(admin_only)):
    if not ALERT_LOG.exists():
        return {"logs": [], "message": "Aucune alerte enregistrée pour le moment."}
    lines = ALERT_LOG.read_text(encoding="utf-8").splitlines()[-50:]
    return {"logs": lines, "count": len(lines)}

@app.get("/documents/{document_id}")
def download_document(document_id: int, token: Optional[str] = None, db_session: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="Token requis")
    user = decode_token(token)
    row = db_session.get(DocumentModel, document_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document introuvable")
    app_row = db_session.get(ApplicationModel, row.application_id)
    if user["role"] != Role.admin.value and app_row.user_email != user["sub"]:
        raise HTTPException(status_code=403, detail="Accès au document refusé")
    path = UPLOAD_DIR / row.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier manquant sur le serveur")
    return FileResponse(path, media_type=row.content_type, filename=row.filename)
