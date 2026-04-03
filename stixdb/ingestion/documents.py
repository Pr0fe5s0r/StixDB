from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
}


@dataclass
class IngestionExtractionResult:
    segments: list[dict[str, Any]]
    parser_used: str
    filetype: str


def is_supported_text_file(filepath: str | Path) -> bool:
    return (
        Path(filepath).suffix.lower() in SUPPORTED_TEXT_EXTENSIONS
        or Path(filepath).suffix.lower() == ".pdf"
    )


def _extract_text_segments(filepath: str | Path) -> IngestionExtractionResult:
    path = Path(filepath)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        content = handle.read()
    return IngestionExtractionResult(
        segments=[{"text": content, "metadata": {}}],
        parser_used="text",
        filetype="text",
    )


def _extract_pdf_segments(filepath: str | Path) -> IngestionExtractionResult:
    try:
        import pypdf
    except ImportError as exc:
        raise ImportError(
            "Please install pypdf to read PDF files (pip install pypdf)."
        ) from exc

    reader = pypdf.PdfReader(str(filepath))
    segments: list[dict[str, Any]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        segments.append(
            {
                "text": page_text,
                "metadata": {
                    "page_number": page_number,
                    "page_start": page_number,
                    "page_end": page_number,
                },
            }
        )
    return IngestionExtractionResult(
        segments=segments,
        parser_used="pypdf",
        filetype="pdf",
    )


def extract_document_segments(
    source: str | Path | list,
    parser: str = "auto",
) -> IngestionExtractionResult:
    # LangChain Document objects or plain dicts — convert directly to segments.
    # Accepts any object with a .page_content attribute (LangChain Document)
    # or a dict with "page_content" / "text" keys.
    if isinstance(source, list):
        segments: list[dict[str, Any]] = []
        for doc in source:
            if hasattr(doc, "page_content"):
                text = doc.page_content
                meta = dict(getattr(doc, "metadata", {}) or {})
            elif isinstance(doc, dict):
                text = doc.get("page_content", doc.get("text", ""))
                meta = dict(doc.get("metadata", {}) or {})
            else:
                text = str(doc)
                meta = {}
            if text.strip():
                segments.append({"text": text, "metadata": meta})
        return IngestionExtractionResult(
            segments=segments,
            parser_used="langchain",
            filetype="documents",
        )

    path = Path(source)

    if path.suffix.lower() == ".pdf":
        return _extract_pdf_segments(path)

    return _extract_text_segments(path)
