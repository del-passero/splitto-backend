import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/splitto"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

from src.models import expense_category, transaction, transaction_share, user, group, group_member, friend



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
