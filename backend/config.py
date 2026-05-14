from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent
_HOST_RUNTIME = _BASE_DIR / "runtime"
_DEFAULT_DATA_DIR = _HOST_RUNTIME if _HOST_RUNTIME.exists() else Path("/app/runtime")


class Settings(BaseSettings):
    app_name: str = "PDF Diff Checker API"
    debug: bool = False

    base_dir: Path = _BASE_DIR
    data_dir: Path = _DEFAULT_DATA_DIR

    jwt_secret: str = ""
    jwt_expiry_seconds: int = 86400 * 7

    # Derived paths — defaults are placeholders; model_validator resolves them.
    uploads_dir: Path = Path(".")
    old_upload_dir: Path = Path(".")
    new_upload_dir: Path = Path(".")
    export_dir: Path = Path(".")
    markdown_export_dir: Path = Path(".")
    snapshots_dir: Path = Path(".")
    crops_dir: Path = Path(".")
    archive_dir: Path = Path(".")
    db_path: Path = Path(".")

    allowed_origins: list[str] = ["http://localhost:8001"]
    max_upload_size_mb: int = 100

    # MinerU REST API endpoint (empty = disabled, falls back to Docling)
    # Example: "http://mineru-api:18080" (docker-compose internal) or "http://localhost:18080"
    mineru_api_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _resolve_derived_paths(self):
        """Cascade derived paths from data_dir so env-var overrides propagate."""
        self.uploads_dir = self.data_dir / "uploads"
        self.old_upload_dir = self.uploads_dir / "old"
        self.new_upload_dir = self.uploads_dir / "new"
        self.export_dir = self.data_dir / "exports"
        self.markdown_export_dir = self.export_dir / "markdown"
        self.snapshots_dir = self.data_dir / "snapshots"
        self.crops_dir = self.data_dir / "crops"
        self.archive_dir = self.data_dir / "archive"
        self.db_path = self.data_dir / "app.db"

        # Auto-generate JWT secret if not provided (writes to data_dir for persistence)
        if not self.jwt_secret:
            import secrets
            secret_file = self.data_dir / ".jwt_secret"
            try:
                if secret_file.exists():
                    self.jwt_secret = secret_file.read_text().strip()
                else:
                    self.data_dir.mkdir(parents=True, exist_ok=True)
                    self.jwt_secret = secrets.token_urlsafe(48)
                    secret_file.write_text(self.jwt_secret)
                    secret_file.chmod(0o600)
            except OSError:
                # Fallback to in-memory random secret if filesystem write fails
                self.jwt_secret = secrets.token_urlsafe(48)
        return self

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on", "dev", "debug"}:
                return True
            if lowered in {"0", "false", "no", "off", "prod", "production", "release"}:
                return False
        return bool(value)


settings = Settings()
