from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent
_HOST_RUNTIME = _BASE_DIR / "runtime"
# Host/local default: <repo>/runtime (the README local-run layout; auto-created on
# startup). In the container, compose sets DATA_DIR=/app/runtime which overrides this.
# The previous `if exists() else /app/runtime` fallback wrongly pointed a fresh host
# checkout (no runtime/ yet) at the container path (\app\runtime on Windows).
_DEFAULT_DATA_DIR = _HOST_RUNTIME


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
    analysis_cache_dir: Path = Path(".")
    db_path: Path = Path(".")

    allowed_origins: list[str] = ["http://localhost:8001"]
    max_upload_size_mb: int = 100

    # The current job runner uses Python threads. Keep exactly one comparison
    # worker because PyMuPDF does not support multithreading; a process-wide
    # guard also serializes export/crop endpoints against this worker. Pending
    # work remains bounded in-process.
    compare_max_concurrency: int = 1
    compare_max_pending_tasks: int = 4

    # MinerU REST API endpoint (empty = disabled, falls back to Docling)
    # Example: "http://mineru-api:18080" (docker-compose internal) or "http://localhost:18080"
    mineru_api_url: str = ""
    # Legacy A/B controls retained for compatibility with older deployments.
    # Production routing is controlled by table_parser_strategy below.
    enable_docling_parallel: bool = True
    mineru_preferred_wait_seconds: float = 0.0
    # Deterministic table routing avoids starting MinerU and Docling together and
    # then discarding the slower result. ``parallel_race`` preserves the legacy
    # behavior for regression comparison; ``opendataloader_first`` is optional
    # and falls back cleanly when its Python package / Java runtime is absent.
    table_parser_strategy: str = "docling_first"
    heavy_parser_max_concurrency: int = 1
    mineru_timeout_seconds: float = 300.0
    enable_lightweight_table_probe: bool = True

    # In-process SHA-256 cache. Parsed documents are read-only downstream, so a
    # small bounded cache removes duplicate work without persisting pickle data.
    enable_parser_cache: bool = True
    parser_cache_max_entries: int = 8
    enable_pixel_diff_cache: bool = True
    pixel_diff_cache_max_entries: int = 8
    enable_persistent_analysis_cache: bool = True
    persistent_analysis_cache_max_entries: int = 128
    # Old/new OCR calls are independent. Run each pair concurrently so the
    # four-core OCI CPU host does not serialize hundreds of Tesseract processes.
    enable_parallel_ocr_pairs: bool = True

    # Image-only PDFs: also parse both sides via MinerU forced-OCR and diff text
    # by position, to recover large CJK block changes (e.g. an added clause) and
    # rate-table edits the pixel path classifies as IMAGE_DIFF and drops. OFF by
    # default — needs a fixed-sample regression before enabling (see
    # docs/pdf_diff_guardrails.md / docs/historical_issues.md §7).
    enable_image_text_recall: bool = False
    # When recall is enabled, prefer text-sequence alignment over bbox-IoU
    # heuristics. Set IMAGE_TEXT_RECALL_STRATEGY=heuristic for the older
    # position-matching path, or hybrid to score both paths together.
    image_text_recall_strategy: str = "alignment"

    # Experimental local PaddleOCR second engine. OFF by default. When enabled,
    # the diff report records PaddleOCR candidate diffs / numeric conflicts in
    # engine_stats for A/B evaluation, but does not promote candidates into final
    # reviewer-facing diff items yet.
    enable_paddle_ocr_experiment: bool = False
    paddle_ocr_lang: str = "ch"
    paddle_ocr_dpi: int = 200
    paddle_ocr_max_pages: int = 20
    paddle_ocr_min_confidence: float = 0.35

    # Snapshot PNGs are audit convenience artifacts. Rendering every page is CPU
    # expensive, so default to pages that actually contain diffs.
    generate_snapshots: bool = True
    snapshot_diff_pages_only: bool = True
    # Keep audit-artifact rendering in the compare worker. PyMuPDF does not
    # support multithreading, so a background artifact thread could overlap the
    # next comparison's parsing/rendering. ``True`` only changes whether the
    # task is marked done before artifacts are generated; it never spawns a
    # second thread.
    postprocess_artifacts_after_done: bool = False

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
        self.analysis_cache_dir = self.data_dir / "analysis_cache"
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

    @field_validator("image_text_recall_strategy", mode="before")
    @classmethod
    def normalize_image_text_recall_strategy(cls, value):
        strategy = str(value or "alignment").strip().lower()
        if strategy not in {"alignment", "heuristic", "hybrid"}:
            raise ValueError("image_text_recall_strategy must be 'alignment', 'heuristic', or 'hybrid'")
        return strategy

    @field_validator("table_parser_strategy", mode="before")
    @classmethod
    def normalize_table_parser_strategy(cls, value):
        strategy = str(value or "docling_first").strip().lower()
        allowed = {
            "docling_first",
            "mineru_first",
            "opendataloader_first",
            "parallel_race",
        }
        if strategy not in allowed:
            raise ValueError(f"table_parser_strategy must be one of {sorted(allowed)}")
        return strategy

    @field_validator(
        "heavy_parser_max_concurrency",
        "parser_cache_max_entries",
        "pixel_diff_cache_max_entries",
        "persistent_analysis_cache_max_entries",
        mode="before",
    )
    @classmethod
    def normalize_positive_integer(cls, value):
        return max(1, int(value))

    @field_validator("compare_max_concurrency", mode="before")
    @classmethod
    def force_single_threaded_compare_runner(cls, value):
        # Validate the supplied value, but never allow multiple thread workers.
        # Process-based parallelism may expose a larger value in a future runner.
        int(value)
        return 1

    @field_validator("compare_max_pending_tasks", mode="before")
    @classmethod
    def normalize_non_negative_integer(cls, value):
        return max(0, int(value))

    @field_validator("mineru_timeout_seconds", mode="before")
    @classmethod
    def normalize_positive_timeout(cls, value):
        return max(1.0, float(value))


settings = Settings()
