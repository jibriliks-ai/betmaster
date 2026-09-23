import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Date
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import date

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./betmaster.db"
    print("Using SQLite fallback - no DATABASE_URL set")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True)
    username = Column(String, default="")
    is_vip = Column(Boolean, default=False)
    vip_expiry = Column(Date, nullable=True)
    daily_count = Column(Integer, default=0)
    last_date = Column(Date, default=date.today)

Base.metadata.create_all(bind=engine)

def get_user(db, telegram_id: int):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, daily_count=0, last_date=date.today())
        db.add(user)
        db.commit()
        db.refresh(user)
    if user.last_date != date.today():
        user.daily_count = 0
        user.last_date = date.today()
        db.commit()
    if user.vip_expiry and user.vip_expiry < date.today():
        user.is_vip = False
        db.commit()
    return user