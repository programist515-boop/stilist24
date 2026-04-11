from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Stylist API"
    debug: bool = True
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/aistylist"
    redis_url: str = "redis://redis:6379/0"

    # --- Storage backend ---------------------------------------------------
    # Explicit backend switch. "memory" keeps tests and local sandboxes free
    # of MinIO/boto3 while "s3" is used against MinIO (dev) and S3 (prod).
    storage_backend: str = "s3"

    # S3 / MinIO connection
    s3_endpoint_url: str = "http://minio:9000"
    s3_region: str = "us-east-1"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "ai-stylist"
    s3_force_path_style: bool = True
    s3_public_base_url: str | None = None
    s3_presign_expires: int = 3600

    # Storage validation
    storage_max_bytes: int = 8 * 1024 * 1024  # 8 MB
    storage_allowed_mime: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
    )
    storage_allowed_ext: tuple[str, ...] = (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    )

    # --- FASHN / Auth (unchanged) -----------------------------------------
    fashn_api_key: str = ""
    fashn_base_url: str = "https://api.fashn.ai"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_minutes: int = 60
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
