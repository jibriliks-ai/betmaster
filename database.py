from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, date
import json, os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./betmaster.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True)
    username = Column(String, default="")
    daily_count = Column(Integer, default=0)
    last_reset = Column(String, default=str(date.today())) # YYYY-MM-DD
    total_chats = Column(Integer, default=0)
    is_vip = Column(Boolean, default=False)
    vip_expiry = Column(String, default="") # YYYY-MM-DD
    favorite_league = Column(String, default="Premier League")
    league_history = Column(Text, default="{}") # json {"Premier League": 5}
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_user(db, user_id, username=""):
    user = db.query(User).filter(User.user_id == user_id).first()
    today_str = str(date.today())

    if not user:
        user = User(user_id=user_id, username=username, last_reset=today_str)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    # Reset daily count if new day
    if user.last_reset!= today_str:
        user.daily_count = 0
        user.last_reset = today_str
        db.commit()

    # Check VIP expiry
    if user.is_vip and user.vip_expiry:
        if user.vip_expiry < today_str:
            user.is_vip = False
            db.commit()

    if username and user.username!= username:
        user.username = username
        db.commit()

    return user

def update_league_history(db, user, league):
    try:
        hist = json.loads(user.league_history or "{}")
    except:
        hist = {}
    hist[league] = hist.get(league, 0) + 1
    user.league_history = json.dumps(hist)
    # Set favorite = most chatted league
    if hist:
        user.favorite_league = max(hist, key=hist.get)
    user.total_chats += 1
    db.commit()

def get_all_users(db):
    return db.query(User).all()
