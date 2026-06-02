from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

engine = create_engine(f"sqlite:///{os.environ['DB_PATH']}")
Session = sessionmaker(bind=engine)
