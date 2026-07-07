from app.core.database import Base
from sqlalchemy import Column, String, Integer, Text, ForeignKey


class Review(Base):
    __tablename__ = "reviews"
    id = Column(String, primary_key=True)
    investigation_id = Column(String, ForeignKey("investigations.id"))
    source_name = Column(String)
    source_type = Column(String)
    origin_url = Column(String, nullable=True)
    confidence_tier = Column(Integer)
    sentiment = Column(String)
    quote = Column(Text)
    reviewer_context = Column(String, nullable=True)
