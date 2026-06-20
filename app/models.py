import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, JSON
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
    mobile_owner = Column(String(50))

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
    suggested_thumbnail_text_fi = Column(String(255))
    suggested_thumbnail_text_en = Column(String(255))
    caption_highlight_color = Column(String(7))
    thumbnail_text_color = Column(String(7))

    # Output
    output_video_path = Column(String(500))
    thumbnail_path = Column(String(500))
    thumbnail_path_fi = Column(String(500))
    thumbnail_path_en = Column(String(500))
    thumbnail_candidates = Column(JSON)  # List of {path, timestamp, index} for user to choose from
    selected_thumbnail_index = Column(String(10))  # Which candidate the user picked

    # Auto-posting
    youtube_autopost = Column(String(10), default="false")  # "true" or "false"
    youtube_video_id = Column(String(50))  # YouTube video ID after upload
    youtube_url = Column(String(200))  # YouTube URL after upload
    youtube_content_type = Column(String(20))
    youtube_thumbnail_status = Column(String(50))
    youtube_thumbnail_error = Column(Text)
    instagram_autopost = Column(String(10), default="false")
    instagram_media_id = Column(String(100))
    instagram_url = Column(String(300))
    instagram_status = Column(Text)
    facebook_autopost = Column(String(10), default="false")
    facebook_video_id = Column(String(100))
    facebook_url = Column(String(300))
    facebook_status = Column(Text)
    tiktok_autopost = Column(String(10), default="false")
    tiktok_publish_id = Column(String(100))
    tiktok_url = Column(String(300))
    tiktok_status = Column(Text)
    publish_queue_id = Column(String(100))
    publish_status = Column(JSON)

    # User edits
    final_title = Column(String(255))
    final_description = Column(Text)
    notes = Column(Text)

    # Error tracking
    error_message = Column(Text)
    current_step = Column(String(200))

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
            "suggested_thumbnail_text_fi": self.suggested_thumbnail_text_fi,
            "suggested_thumbnail_text_en": self.suggested_thumbnail_text_en,
            "output_video_path": self.output_video_path,
            "thumbnail_path": self.thumbnail_path,
            "thumbnail_path_fi": self.thumbnail_path_fi,
            "thumbnail_path_en": self.thumbnail_path_en,
            "youtube_autopost": self.youtube_autopost,
            "youtube_video_id": self.youtube_video_id,
            "youtube_url": self.youtube_url,
            "youtube_content_type": self.youtube_content_type,
            "youtube_thumbnail_status": self.youtube_thumbnail_status,
            "youtube_thumbnail_error": self.youtube_thumbnail_error,
            "instagram_autopost": self.instagram_autopost,
            "instagram_media_id": self.instagram_media_id,
            "instagram_url": self.instagram_url,
            "instagram_status": self.instagram_status,
            "facebook_autopost": self.facebook_autopost,
            "facebook_video_id": self.facebook_video_id,
            "facebook_url": self.facebook_url,
            "facebook_status": self.facebook_status,
            "tiktok_autopost": self.tiktok_autopost,
            "tiktok_publish_id": self.tiktok_publish_id,
            "tiktok_url": self.tiktok_url,
            "tiktok_status": self.tiktok_status,
            "publish_queue_id": self.publish_queue_id,
            "publish_status": self.publish_status,
            "final_title": self.final_title,
            "final_description": self.final_description,
            "notes": self.notes,
            "error_message": self.error_message,
            "current_step": self.current_step,
        }


class MobileAccess(Base):
    __tablename__ = "mobile_access"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    installation_id = Column(String(64), unique=True, index=True)
    label = Column(String(100), nullable=False)
    owner = Column(String(50), unique=True, nullable=False, index=True)
    account_id = Column(String(50), index=True)
    role = Column(String(20), default="friend", nullable=False)
    publishing_enabled = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime)
    google_subject = Column(String(255), unique=True, index=True)
    email = Column(String(255), index=True)
    display_name = Column(String(255))
    admin_unlimited = Column(Boolean, default=False, nullable=False)
    subscription_status = Column(String(30), default="free", nullable=False)
    subscription_product_id = Column(String(100))
    subscription_purchase_token_hash = Column(String(64), unique=True)
    subscription_purchase_token_encrypted = Column(Text)
    subscription_checked_at = Column(DateTime)
    subscription_expires_at = Column(DateTime)
    subscription_grace_until = Column(DateTime)
    monthly_job_limit = Column(Integer)
    deleted_at = Column(DateTime)
    fcm_token = Column(String(255))


class OAuthConnection(Base):
    __tablename__ = "oauth_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mobile_access_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    provider = Column(String(30), nullable=False)
    encrypted_credentials = Column(Text, nullable=False)
    account_label = Column(String(255))
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state_hash = Column(String(64), unique=True, nullable=False, index=True)
    mobile_access_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    provider = Column(String(30), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class MobileUsage(Base):
    __tablename__ = "mobile_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mobile_access_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    period = Column(String(7), nullable=False, index=True)
    jobs_started = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
