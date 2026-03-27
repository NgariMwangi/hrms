"""
Job positions and grades.
"""
from app.extensions import db
from app.models.base import BaseModel


class JobTitle(BaseModel):
    """Job title / position."""
    __tablename__ = 'job_titles'
    __table_args__ = (db.Index('ix_job_titles_code', 'code'),)

    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    grade = db.Column(db.String(50), nullable=True)  # e.g. G5, G6
