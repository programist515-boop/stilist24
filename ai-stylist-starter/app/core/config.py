from pydantic import field_validator
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
    # Canned ACL для каждого PUT object. Нужен для провайдеров, где
    # bucket-level public-read недоступен через bucket policy без admin-роли
    # (Yandex Object Storage: storage.editor может ставить per-object ACL,
    # но не bucket policy). Значения: "public-read" — публичные объекты
    # после bucket setting «Чтение объектов: С авторизацией»; None — не
    # передавать ACL (поведение MinIO/AWS с Block Public Access).
    s3_object_acl: str | None = None

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

    # --- CORS --------------------------------------------------------------
    # The browser frontend lives on a different origin than the API (in dev
    # it's Next.js on :3000, the API is on :8000). Every request carries a
    # custom ``X-User-Id`` header plus multipart bodies, which trigger a
    # CORS preflight. Without the middleware the preflight returns 405 and
    # the browser silently aborts the real request.
    cors_allow_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_cors_csv(cls, v):
        # Pydantic-settings defaults to JSON-parsing list fields, which is
        # awful in a .env file ("[...]" quoting pain). Accept a plain
        # comma-separated string instead, e.g.
        #   CORS_ALLOW_ORIGINS=https://stilist24.com,https://www.stilist24.com
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # --- Feature flags ----------------------------------------------------
    # Use OutfitGenerator (new explainable pipeline) instead of legacy OutfitEngine.
    # Set USE_NEW_OUTFIT_ENGINE=false in .env to revert to the old engine.
    use_new_outfit_engine: bool = True

    # Включает ML-путь (FASHN recolor) для «примерки цвета» (color try-on).
    # По умолчанию выключен — платные вызовы делаются только по явному желанию.
    # CV-путь (rembg + HSV) работает всегда, без флага.
    enable_ml_color_tryon: bool = False

    # --- CV category classifier ------------------------------------------
    # Включает автоопределение категории вещи при загрузке через OpenAI
    # vision (gpt-5-nano). Off — поведение как раньше: либо category из
    # формы, либо None (фронт попросит уточнить).
    use_cv_category_classifier: bool = False
    # "openai" (gpt-5-nano vision) | "heuristic" (rule-based на Phase-0
    # атрибутах) | "disabled". При "heuristic" платные вызовы не
    # делаются даже если флаг включён.
    category_classifier_provider: str = "heuristic"
    # Минимальный confidence от классификатора, ниже которого category
    # сохраняется как None — фронт показывает «уточни категорию».
    category_confidence_threshold: float = 0.6
    # OpenAI endpoint config. Default — api.openai.com напрямую.
    # Bearer-auth с sk-ключом, vision через image_url+detail=low (фикс
    # 85 input-токенов на изображение, t-shirt vs coat читаются с запасом).
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com"
    openai_model: str = "gpt-5-nano"

    # --- FASHN / Auth (unchanged) -----------------------------------------
    fashn_api_key: str = ""
    fashn_base_url: str = "https://api.fashn.ai"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_minutes: int = 60
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
