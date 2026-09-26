from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import date, datetime
import json, os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./betmaster.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, default="")
    daily_count = Column(Integer, default=0)
    last_reset = Column(String, default=str(date.today()))
    total_chats = Column(Integer, default=0)
    is_vip = Column(Boolean, default=False)
    vip_expiry = Column(String, default="")
    favorite_league = Column(String, default="Premier League")
    league_history = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

class PostedHistory(Base):
    __tablename__ = "posted_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_hash = Column(String, unique=True, index=True)
    posted_date = Column(String, default=str(date.today()))

Base.metadata.create_all(bind=engine)

def get_user(db, user_id, username=""):
    today_str = str(date.today())
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        user = User(user_id=user_id, username=username, last_reset=today_str, daily_count=0)
        db.add(user); db.commit(); db.refresh(user); return user
    if user.last_reset!= today_str:
        user.daily_count = 0; user.last_reset = today_str; db.commit()
    if user.is_vip and user.vip_expiry and user.vip_expiry < today_str:
        user.is_vip = False; db.commit()
    if username and user.username!= username:
        user.username = username; db.commit()
    return user

def update_league_history(db, user, league):
    try: hist = json.loads(user.league_history or "{}")
    except: hist = {}
    hist[league] = hist.get(league, 0) + 1
    user.league_history = json.dumps(hist)
    if hist: user.favorite_league = max(hist, key=hist.get)
    user.total_chats += 1; db.commit()

def is_already_posted(db, fixture_hash):
    return bool(db.query(PostedHistory).filter(PostedHistory.fixture_hash == fixture_hash).first())
def mark_as_posted(db, fixture_hash):
    try: db.add(PostedHistory(fixture_hash=fixture_hash, posted_date=str(date.today()))); db.commit()
    except: db.rollback()
