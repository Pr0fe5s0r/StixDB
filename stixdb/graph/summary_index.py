"""
Structured connection metadata for summary nodes.

Summary nodes are the fast-path retrieval index for the agent. This module
normalises the connection metadata that gets written onto those nodes and
provides helpers for reading legacy summary fields back out again.
"""
from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable, Mapping
from typing import Any

SUMMARY_CONNECTION_INDEX_KEY = "connection_index"
SUMMARY_CONNECTION_INDEX_VERSION = 1


def _coerce_node_id(value: Any) -> str | None:
    if value is None:
        return None
    node_id = str(value).strip()
    return node_id or None


def _coerce_relation_type(value: Any) -> str:
    if value is None:
        return "relates_to"
    return str(getattr(value, "value", value))


def build_connection_entry(
    node_id: str,
    *,
    relation_type: Any,
    role: str,
    rank: int,
    weight: float = 1.0,
    direction: str = "out",
    source: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "node_id": node_id,
        "relation_type": _coerce_relation_type(relation_type),
        "role": role,
        "rank": max(1, int(rank)),
        "weight": max(0.0, float(weight)),
        "direction": direction,
    }
    if source:
        entry["source"] = source
    if extra:
        entry.update(extra)
    return entry


def build_connection_entries(
    node_ids: Iterable[Any],
    *,
    relation_type: Any,
    role: str,
    weight: float = 1.0,
    direction: str = "out",
    source: str | None = None,
    rank_start: int = 1,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for rank, node_id in enumerate(node_ids, start=rank_start):
        coerced = _coerce_node_id(node_id)
        if not coerced:
            continue
        entries.append(
            build_connection_entry(
                coerced,
                relation_type=relation_type,
                role=role,
                rank=rank,
                weight=weight,
                direction=direction,
                source=source,
            )
        )
    return entries


def _normalise_entry(
    entry: Mapping[str, Any],
    *,
    default_rank: int,
    default_weight: float,
    default_relation_type: Any,
    default_role: str,
    default_direction: str,
    default_source: str | None,
) -> dict[str, Any] | None:
    payload = dict(entry)
    node_id = _coerce_node_id(payload.get("node_id"))
    if not node_id:
        return None

    payload["node_id"] = node_id
    payload["relation_type"] = _coerce_relation_type(
        payload.get("relation_type", default_relation_type)
    )
    payload["role"] = str(payload.get("role", default_role) or default_role)
    try:
        payload["rank"] = max(1, int(payload.get("rank", default_rank)))
    except (TypeError, ValueError):
        payload["rank"] = default_rank
    try:
        payload["weight"] = max(0.0, float(payload.get("weight", default_weight)))
    except (TypeError, ValueError):
        payload["weight"] = default_weight
    payload["direction"] = str(payload.get("direction", default_direction) or default_direction)
    if payload.get("source") in (None, "") and default_source:
        payload["source"] = default_source
    return payload


def _dedupe_entries(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (
            str(entry.get("node_id", "")),
            str(entry.get("relation_type", "")),
            str(entry.get("role", "")),
            str(entry.get("direction", "")),
        )
        existing = best.get(key)
        if existing is None:
            best[key] = entry
            continue
        existing_rank = int(existing.get("rank", 1) or 1)
        incoming_rank = int(entry.get("rank", 1) or 1)
        existing_weight = float(existing.get("weight", 0.0) or 0.0)
        incoming_weight = float(entry.get("weight", 0.0) or 0.0)
        if (incoming_rank, -incoming_weight, key[0]) < (existing_rank, -existing_weight, key[0]):
            best[key] = entry

    return sorted(
        best.values(),
        key=lambda item: (
            int(item.get("rank", 1) or 1),
            -float(item.get("weight", 0.0) or 0.0),
            str(item.get("node_id", "")),
        ),
    )


def _legacy_connection_entries(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    legacy: list[dict[str, Any]] = []

    def extend_from_ids(
        values: Any,
        *,
        relation_type: Any,
        role: str,
        weight: float,
        direction: str = "out",
        source: str | None = None,
    ) -> None:
        if values is None:
            return
        if isinstance(values, (str, bytes)):
            iterable = [values]
        elif isinstance(values, Iterable):
            iterable = values
        else:
            return

        for rank, value in enumerate(iterable, start=1):
            node_id = _coerce_node_id(value)
            if not node_id:
                continue
            legacy.append(
                build_connection_entry(
                    node_id,
                    relation_type=relation_type,
                    role=role,
                    rank=rank,
                    weight=weight,
                    direction=direction,
                    source=source,
                )
            )

    extend_from_ids(
        metadata.get("supporting_node_ids"),
        relation_type="summarizes",
        role="support",
        weight=1.0,
        source=str(metadata.get("source") or ""),
    )
    extend_from_ids(
        metadata.get("synthesized_from"),
        relation_type="summarizes",
        role="support",
        weight=1.0,
        source=str(metadata.get("source") or ""),
    )
    extend_from_ids(
        metadata.get("source_node_ids"),
        relation_type="summarizes",
        role="source",
        weight=1.0,
        source=str(metadata.get("source") or ""),
    )
    extend_from_ids(
        metadata.get("focus_node_ids"),
        relation_type="references",
        role="focus",
        weight=0.8,
        source=str(metadata.get("source") or ""),
    )
    extend_from_ids(
        metadata.get("merged_from"),
        relation_type="derived_from",
        role="source",
        weight=1.0,
        source=str(metadata.get("source") or ""),
    )
    extend_from_ids(
        metadata.get("parent_node_ids"),
        relation_type="derived_from",
        role="parent",
        weight=1.0,
        source=str(metadata.get("source") or ""),
    )

    source_lineage = metadata.get("source_lineage")
    if isinstance(source_lineage, list):
        for rank, item in enumerate(source_lineage, start=1):
            if not isinstance(item, Mapping):
                continue
            node_id = _coerce_node_id(item.get("node_id") or item.get("id"))
            if not node_id:
                continue
            legacy.append(
                build_connection_entry(
                    node_id,
                    relation_type=item.get("relation_type", "derived_from"),
                    role=str(item.get("role") or "lineage"),
                    rank=rank,
                    weight=float(item.get("weight", item.get("similarity", 1.0)) or 1.0),
                    direction=str(item.get("direction") or "out"),
                    source=str(item.get("source") or metadata.get("source") or ""),
                )
            )

    return legacy


def extract_summary_connection_entries(
    metadata: Mapping[str, Any] | None,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if not metadata:
        return []

    entries: list[dict[str, Any]] = []
    connection_index = metadata.get(SUMMARY_CONNECTION_INDEX_KEY)
    if isinstance(connection_index, Mapping):
        entries.extend(
            _normalise_entry(
                entry,
                default_rank=index + 1,
                default_weight=1.0,
                default_relation_type=connection_index.get("relation_type", "summarizes"),
                default_role=str(connection_index.get("role", "support") or "support"),
                default_direction=str(connection_index.get("direction", "out") or "out"),
                default_source=str(connection_index.get("source") or metadata.get("source") or ""),
            )
            for index, entry in enumerate(connection_index.get("entries", []) or [])
            if isinstance(entry, Mapping)
        )

    entries.extend(_legacy_connection_entries(metadata))
    normalised = [entry for entry in entries if entry is not None]
    deduped = _dedupe_entries(normalised)
    if limit is not None:
        return deduped[: max(0, int(limit))]
    return deduped


def extract_summary_related_node_ids(
    metadata: Mapping[str, Any] | None,
    *,
    limit: int | None = None,
) -> list[str]:
    entries = extract_summary_connection_entries(metadata, limit=limit)
    node_ids: list[str] = []
    seen: set[str] = set()
    summary_id = None
    if metadata and isinstance(metadata.get(SUMMARY_CONNECTION_INDEX_KEY), Mapping):
        summary_id = _coerce_node_id(
            metadata[SUMMARY_CONNECTION_INDEX_KEY].get("summary_id")
        )

    for entry in entries:
        node_id = _coerce_node_id(entry.get("node_id"))
        if not node_id or node_id in seen:
            continue
        if summary_id and node_id == summary_id:
            continue
        seen.add(node_id)
        node_ids.append(node_id)
    return node_ids


def _build_snapshot(
    *,
    summary_id: str | None,
    summary_kind: str | None,
    source: str | None,
    content_hash: str | None,
    node_ids: Iterable[str],
) -> str:
    pieces = [
        f"summary:{summary_id or ''}",
        f"kind:{summary_kind or ''}",
        f"source:{source or ''}",
        f"content:{content_hash or ''}",
    ]
    pieces.extend(f"node:{node_id}" for node_id in sorted(set(node_ids)))
    return hashlib.sha1("|".join(pieces).encode("utf-8")).hexdigest()


def build_summary_connection_index(
    *,
    summary_id: str | None = None,
    summary_kind: str | None = None,
    source: str | None = None,
    content_hash: str | None = None,
    entries: Iterable[Mapping[str, Any]] = (),
    created_at: float | None = None,
    updated_at: float | None = None,
) -> dict[str, Any]:
    normalised = [
        entry
        for entry in (
            _normalise_entry(
                item,
                default_rank=index + 1,
                default_weight=1.0,
                default_relation_type="summarizes",
                default_role="support",
                default_direction="out",
                default_source=source,
            )
            for index, item in enumerate(entries)
            if isinstance(item, Mapping)
        )
        if entry is not None
    ]
    deduped = _dedupe_entries(normalised)
    node_ids = [entry["node_id"] for entry in deduped]
    created = created_at or time.time()
    updated = updated_at or created
    return {
        "version": SUMMARY_CONNECTION_INDEX_VERSION,
        "summary_id": summary_id,
        "summary_kind": summary_kind,
        "source": source,
        "content_hash": content_hash,
        "created_at": created,
        "updated_at": updated,
        "snapshot": _build_snapshot(
            summary_id=summary_id,
            summary_kind=summary_kind,
            source=source,
            content_hash=content_hash,
            node_ids=node_ids,
        ),
        "node_ids": node_ids,
        "entries": deduped,
    }


def merge_summary_connection_index(
    metadata: Mapping[str, Any] | None,
    *,
    summary_id: str | None = None,
    summary_kind: str | None = None,
    source: str | None = None,
    content_hash: str | None = None,
    entries: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    base_metadata = dict(metadata or {})
    existing = base_metadata.get(SUMMARY_CONNECTION_INDEX_KEY)
    existing_entries: list[dict[str, Any]] = []
    created_at: float | None = None

    if isinstance(existing, Mapping):
        existing_entries = extract_summary_connection_entries(base_metadata)
        try:
            created_at = float(existing.get("created_at")) if existing.get("created_at") is not None else None
        except (TypeError, ValueError):
            created_at = None
        summary_id = summary_id or _coerce_node_id(existing.get("summary_id"))
        summary_kind = summary_kind or str(existing.get("summary_kind") or "") or None
        source = source or str(existing.get("source") or "") or None
        content_hash = content_hash or str(existing.get("content_hash") or "") or None

    additions = [
        entry
        for entry in (
            _normalise_entry(
                item,
                default_rank=index + 1,
                default_weight=1.0,
                default_relation_type="summarizes",
                default_role="support",
                default_direction="out",
                default_source=source,
            )
            for index, item in enumerate(entries)
            if isinstance(item, Mapping)
        )
        if entry is not None
    ]
    combined = _dedupe_entries([*existing_entries, *additions])
    built = build_summary_connection_index(
        summary_id=summary_id,
        summary_kind=summary_kind,
        source=source,
        content_hash=content_hash,
        entries=combined,
        created_at=created_at,
        updated_at=time.time(),
    )
    return built
