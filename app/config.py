from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # API Keys
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Database
    database_url: str = "postgresql://shortgen:shortgen_pwd_2024@localhost/shortgen"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # App
    secret_key: str = "change-me"
    storage_path: Path = Path("/var/www/shortgen/storage")
    base_url: str = "http://localhost:8000"

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
