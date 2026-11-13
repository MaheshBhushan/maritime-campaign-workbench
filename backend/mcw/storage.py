"""MinIO document storage."""

from __future__ import annotations

import io

from minio import Minio
from minio.deleteobjects import DeleteObject
from minio.error import S3Error


class DocumentStore:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
        self.bucket = bucket

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put(self, key: str, data: bytes, content_type: str, metadata: dict[str, str]) -> None:
        self.client.put_object(
            self.bucket, key, io.BytesIO(data), length=len(data), content_type=content_type, metadata=metadata
        )

    def get(self, key: str) -> bytes:
        resp = self.client.get_object(self.bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def stat(self, key: str) -> dict | None:
        """Return size and user metadata of an object, or None when it does not exist."""
        try:
            st = self.client.stat_object(self.bucket, key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                return None
            raise
        meta = {k.lower().removeprefix("x-amz-meta-"): v for k, v in (st.metadata or {}).items()
                if k.lower().startswith("x-amz-meta-")}
        return {"size": st.size, "content_type": st.content_type, "metadata": meta}

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(o.object_name for o in self.client.list_objects(self.bucket, prefix=prefix, recursive=True))

    def delete_prefix(self, prefix: str) -> None:
        objs = [DeleteObject(k) for k in self.list_keys(prefix)]
        for err in self.client.remove_objects(self.bucket, objs):
            raise RuntimeError(f"failed to delete {err.object_name}: {err.message}")

    def ping(self) -> bool:
        return self.client.bucket_exists(self.bucket)
