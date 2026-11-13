"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: _env("MCW_DATABASE_URL", "postgresql+psycopg://mcw:mcw@localhost:18482/mcw")
    )
    minio_endpoint: str = field(default_factory=lambda: _env("MCW_MINIO_ENDPOINT", "localhost:18483"))
    minio_access_key: str = field(default_factory=lambda: _env("MCW_MINIO_ACCESS_KEY", "mcwminio"))
    minio_secret_key: str = field(default_factory=lambda: _env("MCW_MINIO_SECRET_KEY", "mcwminio-secret"))
    minio_bucket: str = field(default_factory=lambda: _env("MCW_MINIO_BUCKET", "mcw-documents"))
    opensearch_url: str = field(default_factory=lambda: _env("MCW_OPENSEARCH_URL", "http://localhost:18485"))
    opensearch_index: str = field(default_factory=lambda: _env("MCW_OPENSEARCH_INDEX", "mcw-documents"))
    fuseki_url: str = field(default_factory=lambda: _env("MCW_FUSEKI_URL", "http://localhost:18486"))
    fuseki_dataset: str = field(default_factory=lambda: _env("MCW_FUSEKI_DATASET", "mcw"))
    fuseki_user: str = field(default_factory=lambda: _env("MCW_FUSEKI_USER", "admin"))
    fuseki_password: str = field(default_factory=lambda: _env("MCW_FUSEKI_PASSWORD", "mcw-fuseki"))
    ontology_path: Path = field(
        default_factory=lambda: Path(_env("MCW_ONTOLOGY_PATH", str(REPO_ROOT / "ontology" / "mcw.ttl")))
    )
    fixtures_dir: Path = field(
        default_factory=lambda: Path(_env("MCW_FIXTURES_DIR", str(REPO_ROOT / "fixtures")))
    )
    max_upload_bytes: int = field(default_factory=lambda: int(_env("MCW_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))))
