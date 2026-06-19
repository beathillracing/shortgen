from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # API Keys
    openai_api_key: str = ""
    openai_admin_key: str = ""
    anthropic_api_key: str = ""
    anthropic_admin_key: str = ""
    groq_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_fallback_models: str = "claude-sonnet-4-5-20250929,claude-haiku-4-5-20251001"
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_configuration_id: str = ""
    meta_graph_version: str = "v25.0"
    meta_page_id: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_post_mode: str = "draft"

    # Database
    database_url: str = "postgresql://shortgen:shortgen_pwd_2024@localhost/shortgen"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # App
    secret_key: str = "change-me"
    storage_path: Path = Path("/var/www/shortgen/storage")
    base_url: str = "http://localhost:8000"
    public_media_secret: str = ""
    mobile_api_token: str = ""
    mobile_creator_api_token: str = ""
    mobile_upload_chunk_size_mb: int = 8
    google_web_client_id: str = ""
    google_play_service_account_file: str = ""
    google_play_package_name: str = "beathill.studio"
    google_play_subscription_product_id: str = "beathill_studio_pro"
    free_monthly_job_limit: int = 3
    outro_duration_seconds: float = 1.0
    thumbnail_duration_seconds: float = 1.0
    openai_monthly_budget_usd: float = 0.0
    anthropic_monthly_budget_usd: float = 0.0
    groq_monthly_budget_usd: float = 0.0

    # Paths
    assets_path: Path = Path("/var/www/shortgen/assets")

    # Auth
    admin_password: str = ""

    class Config:
        env_file = "/var/www/shortgen/.env"
        extra = "ignore"


settings = Settings()

# Ensure storage directories exist
for subdir in ["uploads", "processing", "exports"]:
    (settings.storage_path / subdir).mkdir(parents=True, exist_ok=True)
