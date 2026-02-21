import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID, ARRAY

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String(20), default="pending")  # pending, transcribing, analyzing, rendering, review, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Input
    original_filename = Column(String(255))
    upload_path = Column(String(500))
    upload_paths = Column(Text)  # JSON array of paths if multiple files
    context_description = Column(Text)  # User-provided context about the video
    minimal_cuts = Column(String(10), default="false")  # "true" or "false"
    burn_captions = Column(String(10), default="false")  # "true" or "false"
    precaptioned = Column(String(10), default="false")  # "true" if video already has captions (e.g. from CapCut)
    remove_outro_seconds = Column(String(10), default="3")  # Seconds to trim from end (CapCut outro)

    # Transcription
    transcript = Column(Text)
    srt_content = Column(Text)

    # LLM Analysis
    cut_plan = Column(JSON)  # {segments: [{start, end, keep, reason}]}
    suggested_title_fi = Column(String(255))
    suggested_title_en = Column(String(255))
    suggested_description_fi = Column(Text)
    suggested_description_en = Column(Text)
    suggested_hashtags = Column(ARRAY(String))
    suggested_hook_fi = Column(String(500))
    suggested_hook_en = Column(String(500))

    # Output
    output_video_path = Column(String(500))
    thumbnail_path = Column(String(500))
    thumbnail_path_fi = Column(String(500))
    thumbnail_path_en = Column(String(500))

    # Auto-posting
    youtube_autopost = Column(String(10), default="false")  # "true" or "false"
    youtube_video_id = Column(String(50))  # YouTube video ID after upload
    youtube_url = Column(String(200))  # YouTube URL after upload

    # User edits
    final_title = Column(String(255))
    final_description = Column(Text)
    notes = Column(Text)

    # Error tracking
    error_message = Column(Text)
    current_step = Column(String(50))

    def to_dict(self):
        return {
            "id": str(self.id),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "original_filename": self.original_filename,
            "transcript": self.transcript,
            "srt_content": self.srt_content,
            "cut_plan": self.cut_plan,
            "suggested_title_fi": self.suggested_title_fi,
            "suggested_title_en": self.suggested_title_en,
            "suggested_description_fi": self.suggested_description_fi,
            "suggested_description_en": self.suggested_description_en,
            "suggested_hashtags": self.suggested_hashtags,
            "suggested_hook_fi": self.suggested_hook_fi,
            "suggested_hook_en": self.suggested_hook_en,
            "output_video_path": self.output_video_path,
            "thumbnail_path": self.thumbnail_path,
            "thumbnail_path_fi": self.thumbnail_path_fi,
            "thumbnail_path_en": self.thumbnail_path_en,
            "youtube_autopost": self.youtube_autopost,
            "youtube_video_id": self.youtube_video_id,
            "youtube_url": self.youtube_url,
            "final_title": self.final_title,
            "final_description": self.final_description,
            "notes": self.notes,
            "error_message": self.error_message,
            "current_step": self.current_step,
        }
