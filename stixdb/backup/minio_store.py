from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

from stixdb.config import BackupConfig


class BackupStore:
    async def upload_file(self, collection: str, filepath: str, source_name: Optional[str] = None) -> dict | None:
        return None


class MinioBackupStore(BackupStore):
    def __init__(self, config: BackupConfig) -> None:
        self.config = config
        from minio import Minio

        self._client = Minio(
            config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
        )
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        if not self._client.bucket_exists(self.config.bucket):
            self._client.make_bucket(self.config.bucket)
        self._bucket_ready = True

    async def upload_file(self, collection: str, filepath: str, source_name: Optional[str] = None) -> dict | None:
        path = Path(filepath)
        self._ensure_bucket()
        object_name = "/".join(
            part.strip("/")
            for part in [self.config.prefix, collection, source_name or path.name]
            if part and part.strip("/")
        )
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._client.fput_object(
            self.config.bucket,
            object_name,
            str(path),
            content_type=content_type,
        )
        return {
            "provider": "minio",
            "bucket": self.config.bucket,
            "object_name": object_name,
            "endpoint": self.config.endpoint,
        }


def build_backup_store(config: BackupConfig) -> BackupStore:
    if not config.enabled:
        return BackupStore()
    return MinioBackupStore(config)
