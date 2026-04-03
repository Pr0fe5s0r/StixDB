from __future__ import annotations

from pathlib import Path
from typing import Any
from .base import _BaseResource, _AsyncBaseResource


class MemoryAPI(_BaseResource):
    def store(
        self,
        collection: str,
        *,
        content: str,
        node_type: str = "fact",
        tier: str = "episodic",
        importance: float = 0.5,
        source: str | None = None,
        source_agent_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        pinned: bool = True,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        return self._client._request(
            "POST",
            f"/collections/{collection}/nodes",
            json={
                "id": node_id,
                "content": content,
                "node_type": node_type,
                "tier": tier,
                "importance": importance,
                "source": source,
                "source_agent_id": source_agent_id,
                "tags": tags or [],
                "metadata": metadata or {},
                "pinned": pinned,
            },
        )

    def bulk_store(self, collection: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return self._client._request(
            "POST",
            f"/collections/{collection}/nodes/bulk",
            json=items,
        )

    def list(
        self,
        collection: str,
        *,
        tier: str | None = None,
        node_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        params = {
            "tier": tier,
            "node_type": node_type,
            "limit": limit,
            "offset": offset,
        }
        return self._client._request("GET", f"/collections/{collection}/nodes", params=params)

    def get(self, collection: str, node_id: str) -> dict[str, Any]:
        return self._client._request("GET", f"/collections/{collection}/nodes/{node_id}")

    def delete(self, collection: str, node_id: str) -> dict[str, Any]:
        return self._client._request("DELETE", f"/collections/{collection}/nodes/{node_id}")

    def delete_collection(self, collection: str) -> dict[str, Any]:
        return self._client._request("DELETE", f"/collections/{collection}")

    def upload(
        self,
        collection: str,
        file_path: str | Path,
        *,
        tags: list[str] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        parser: str = "auto",
    ) -> dict[str, Any]:
        path = Path(file_path)
        with path.open("rb") as handle:
            files = {"file": (path.name, handle)}
            data = {
                "tags": ",".join(tags or []),
                "chunk_size": str(chunk_size),
                "chunk_overlap": str(chunk_overlap),
                "parser": parser,
            }
            return self._client._request(
                "POST",
                f"/collections/{collection}/upload",
                files=files,
                data=data,
            )

    def ingest_folder(
        self,
        collection: str,
        folder_path: str | Path,
        *,
        tags: list[str] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        parser: str = "auto",
        recursive: bool = True,
    ) -> dict[str, Any]:
        root = Path(folder_path)
        if not root.exists():
            raise FileNotFoundError(f"Folder not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        allowed_suffixes = {
            ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl",
            ".yaml", ".yml", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx",
            ".java", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".sh", ".sql",
            ".toml", ".ini", ".cfg", ".conf", ".pdf",
        }

        iterator = root.rglob("*") if recursive else root.glob("*")
        ingested: list[dict[str, Any]] = []
        skipped: list[str] = []

        for path in iterator:
            if not path.is_file():
                continue
            if path.suffix.lower() not in allowed_suffixes:
                skipped.append(str(path))
                continue
            result = self.upload(
                collection,
                path,
                tags=tags,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                parser=parser,
            )
            ingested.append(
                {
                    "filepath": str(path),
                    "relative_path": str(path.relative_to(root)),
                    "result": result,
                }
            )

        return {
            "collection": collection,
            "folder": str(root),
            "files_processed": len(ingested),
            "files_skipped": len(skipped),
            "ingested": ingested,
            "skipped": skipped,
        }


class AsyncMemoryAPI(_AsyncBaseResource):
    async def store(
        self,
        collection: str,
        *,
        content: str,
        node_type: str = "fact",
        tier: str = "episodic",
        importance: float = 0.5,
        source: str | None = None,
        source_agent_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        pinned: bool = True,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._client._request(
            "POST",
            f"/collections/{collection}/nodes",
            json={
                "id": node_id,
                "content": content,
                "node_type": node_type,
                "tier": tier,
                "importance": importance,
                "source": source,
                "source_agent_id": source_agent_id,
                "tags": tags or [],
                "metadata": metadata or {},
                "pinned": pinned,
            },
        )

    async def bulk_store(self, collection: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._client._request(
            "POST",
            f"/collections/{collection}/nodes/bulk",
            json=items,
        )

    async def list(
        self,
        collection: str,
        *,
        tier: str | None = None,
        node_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        params = {
            "tier": tier,
            "node_type": node_type,
            "limit": limit,
            "offset": offset,
        }
        return await self._client._request("GET", f"/collections/{collection}/nodes", params=params)

    async def get(self, collection: str, node_id: str) -> dict[str, Any]:
        return await self._client._request("GET", f"/collections/{collection}/nodes/{node_id}")

    async def delete(self, collection: str, node_id: str) -> dict[str, Any]:
        return await self._client._request("DELETE", f"/collections/{collection}/nodes/{node_id}")

    async def delete_collection(self, collection: str) -> dict[str, Any]:
        return await self._client._request("DELETE", f"/collections/{collection}")

    async def upload(
        self,
        collection: str,
        file_path: str | Path,
        *,
        tags: list[str] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        parser: str = "auto",
    ) -> dict[str, Any]:
        path = Path(file_path)
        with path.open("rb") as handle:
            files = {"file": (path.name, handle)}
            data = {
                "tags": ",".join(tags or []),
                "chunk_size": str(chunk_size),
                "chunk_overlap": str(chunk_overlap),
                "parser": parser,
            }
            return await self._client._request(
                "POST",
                f"/collections/{collection}/upload",
                files=files,
                data=data,
            )

    async def ingest_folder(
        self,
        collection: str,
        folder_path: str | Path,
        *,
        tags: list[str] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        parser: str = "auto",
        recursive: bool = True,
    ) -> dict[str, Any]:
        root = Path(folder_path)
        if not root.exists():
            raise FileNotFoundError(f"Folder not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        allowed_suffixes = {
            ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl",
            ".yaml", ".yml", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx",
            ".java", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".sh", ".sql",
            ".toml", ".ini", ".cfg", ".conf", ".pdf",
        }

        iterator = root.rglob("*") if recursive else root.glob("*")
        ingested: list[dict[str, Any]] = []
        skipped: list[str] = []

        for path in iterator:
            if not path.is_file():
                continue
            if path.suffix.lower() not in allowed_suffixes:
                skipped.append(str(path))
                continue
            result = await self.upload(
                collection,
                path,
                tags=tags,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                parser=parser,
            )
            ingested.append(
                {
                    "filepath": str(path),
                    "relative_path": str(path.relative_to(root)),
                    "result": result,
                }
            )

        return {
            "collection": collection,
            "folder": str(root),
            "files_processed": len(ingested),
            "files_skipped": len(skipped),
            "ingested": ingested,
            "skipped": skipped,
        }
