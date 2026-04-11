"""
Pass 1 — Deterministic AST extractor for Python source files.

Zero LLM. Zero embeddings. Walks a .py file with the stdlib ast module
and produces typed MemoryNodes + EXTRACTED RelationEdges.

Nodes produced:
    CODE_FILE   — one per file
    MODULE      — one per file (logical unit)
    FUNCTION    — one per function/method definition
    CLASS       — one per class definition

Edges produced (all EXTRACTED):
    DEFINES     — module -> function, module -> class, class -> method
    CALLS       — function -> function (best-effort static analysis)
    IMPORTS     — module -> imported module name
    INHERITS    — class -> base class name
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stixdb.graph.node import MemoryNode, NodeType
from stixdb.graph.edge import RelationEdge, RelationType, EdgeProvenance

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────── #
# Result container                                                              #
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class CodeExtractionResult:
    nodes: list[MemoryNode] = field(default_factory=list)
    edges: list[RelationEdge] = field(default_factory=list)
    file_path: str = ""
    parse_errors: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────── #
# Internal helpers                                                              #
# ──────────────────────────────────────────────────────────────────────────── #

def _make_node(
    collection: str,
    node_type: NodeType,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> MemoryNode:
    return MemoryNode(
        collection=collection,
        node_type=node_type,
        content=content,
        metadata=metadata or {},
        importance=0.7,
    )


def _make_edge(
    collection: str,
    source_id: str,
    target_id: str,
    relation_type: RelationType,
    weight: float = 1.0,
    metadata: dict[str, Any] | None = None,
) -> RelationEdge:
    return RelationEdge(
        collection=collection,
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        weight=weight,
        confidence=1.0,
        provenance=EdgeProvenance.EXTRACTED,
        created_by="ast_extractor",
        metadata=metadata or {},
    )


def _get_docstring(node: ast.AST) -> str:
    """Extract docstring from a function, class, or module AST node."""
    try:
        return ast.get_docstring(node) or ""
    except Exception:
        return ""


def _collect_calls(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Collect all function/method names called inside a function body."""
    called: list[str] = []
    for child in ast.walk(func_node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                called.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                called.append(child.func.attr)
    return list(set(called))


# ──────────────────────────────────────────────────────────────────────────── #
# Main extractor                                                                #
# ──────────────────────────────────────────────────────────────────────────── #

def extract_code_graph(
    filepath: str | Path,
    collection: str,
    source_name: str = "",
) -> CodeExtractionResult:
    """
    Walk a Python source file and return all nodes + EXTRACTED edges.

    Args:
        filepath:    Path to the .py file (may be a temp path).
        collection:  StixDB collection name to assign to all produced nodes/edges.
        source_name: Display name for the file (e.g. original filename when
                     filepath is a temp file). Falls back to path.name.

    Returns:
        CodeExtractionResult with nodes, edges, and any parse errors.
    """
    path = Path(filepath)
    display_name = source_name or path.name
    display_stem = Path(display_name).stem
    result = CodeExtractionResult(file_path=str(path))

    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        result.parse_errors.append(f"SyntaxError: {exc}")
        logger.warning("AST parse failed for %s: %s", path, exc)
        return result
    except Exception as exc:
        result.parse_errors.append(str(exc))
        logger.warning("Failed to read %s: %s", path, exc)
        return result

    # ── CODE_FILE node ────────────────────────────────────────────────────
    # Low importance (0.3): structural hub for DEFINES edges, not a search target.
    file_node = _make_node(
        collection=collection,
        node_type=NodeType.CODE_FILE,
        content=f"Code file: {display_name}",
        metadata={"path": str(path), "filename": display_name, "suffix": path.suffix},
    )
    file_node.importance = 0.3
    result.nodes.append(file_node)

    # ── MODULE node ───────────────────────────────────────────────────────
    # Content is a structural label, NOT the docstring. The docstring already
    # lands in text chunk 0 via the normal ingestion pipeline — using it here
    # would create a near-duplicate embedding that pollutes search results.
    # Low importance (0.3): structural hub, not a search target.
    module_docstring = _get_docstring(tree)
    module_node = _make_node(
        collection=collection,
        node_type=NodeType.MODULE,
        content=f"Module: {display_stem}",
        metadata={"path": str(path), "module_name": display_stem, "docstring": module_docstring},
    )
    module_node.importance = 0.3
    result.nodes.append(module_node)

    # CODE_FILE -> MODULE (DEFINES)
    result.edges.append(_make_edge(
        collection=collection,
        source_id=file_node.id,
        target_id=module_node.id,
        relation_type=RelationType.DEFINES,
    ))

    # ── Import edges ──────────────────────────────────────────────────────
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_node = _make_node(
                    collection=collection,
                    node_type=NodeType.MODULE,
                    content=f"Module: {alias.name}",
                    metadata={"module_name": alias.name, "external": True},
                )
                result.nodes.append(import_node)
                result.edges.append(_make_edge(
                    collection=collection,
                    source_id=module_node.id,
                    target_id=import_node.id,
                    relation_type=RelationType.IMPORTS,
                    metadata={"alias": alias.asname},
                ))

        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            import_node = _make_node(
                collection=collection,
                node_type=NodeType.MODULE,
                content=f"Module: {module_name}",
                metadata={"module_name": module_name, "external": True},
            )
            result.nodes.append(import_node)
            result.edges.append(_make_edge(
                collection=collection,
                source_id=module_node.id,
                target_id=import_node.id,
                relation_type=RelationType.IMPORTS,
                metadata={"names": [a.name for a in node.names]},
            ))

    # ── Class and function nodes ──────────────────────────────────────────
    # Map function/class name -> node ID for CALLS resolution
    name_to_id: dict[str, str] = {}

    # Top-level classes
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            docstring = _get_docstring(node)
            bases = [
                (b.id if isinstance(b, ast.Name) else ast.unparse(b))
                for b in node.bases
            ]
            class_node = _make_node(
                collection=collection,
                node_type=NodeType.CLASS,
                content=docstring or f"Class: {node.name}",
                metadata={
                    "name": node.name,
                    "path": str(path),
                    "lineno": node.lineno,
                    "end_lineno": getattr(node, "end_lineno", None),
                    "bases": bases,
                    "docstring": docstring,
                },
            )
            result.nodes.append(class_node)
            name_to_id[node.name] = class_node.id

            # MODULE -> CLASS (DEFINES)
            result.edges.append(_make_edge(
                collection=collection,
                source_id=module_node.id,
                target_id=class_node.id,
                relation_type=RelationType.DEFINES,
            ))

            # INHERITS edges
            for base_name in bases:
                base_node = _make_node(
                    collection=collection,
                    node_type=NodeType.CLASS,
                    content=f"Class: {base_name}",
                    metadata={"name": base_name, "external": True},
                )
                result.nodes.append(base_node)
                result.edges.append(_make_edge(
                    collection=collection,
                    source_id=class_node.id,
                    target_id=base_node.id,
                    relation_type=RelationType.INHERITS,
                ))

            # Methods inside the class
            for item in ast.iter_child_nodes(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_doc = _get_docstring(item)
                    method_node = _make_node(
                        collection=collection,
                        node_type=NodeType.FUNCTION,
                        content=method_doc or f"Method: {node.name}.{item.name}",
                        metadata={
                            "name": item.name,
                            "qualified_name": f"{node.name}.{item.name}",
                            "path": str(path),
                            "lineno": item.lineno,
                            "end_lineno": getattr(item, "end_lineno", None),
                            "is_async": isinstance(item, ast.AsyncFunctionDef),
                            "docstring": method_doc,
                            "parent_class": node.name,
                        },
                    )
                    result.nodes.append(method_node)
                    name_to_id[f"{node.name}.{item.name}"] = method_node.id
                    name_to_id[item.name] = method_node.id  # also reachable by short name

                    # CLASS -> METHOD (DEFINES)
                    result.edges.append(_make_edge(
                        collection=collection,
                        source_id=class_node.id,
                        target_id=method_node.id,
                        relation_type=RelationType.DEFINES,
                    ))

        # Top-level functions
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = _get_docstring(node)
            func_node = _make_node(
                collection=collection,
                node_type=NodeType.FUNCTION,
                content=docstring or f"Function: {node.name}",
                metadata={
                    "name": node.name,
                    "path": str(path),
                    "lineno": node.lineno,
                    "end_lineno": getattr(node, "end_lineno", None),
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "docstring": docstring,
                },
            )
            result.nodes.append(func_node)
            name_to_id[node.name] = func_node.id

            # MODULE -> FUNCTION (DEFINES)
            result.edges.append(_make_edge(
                collection=collection,
                source_id=module_node.id,
                target_id=func_node.id,
                relation_type=RelationType.DEFINES,
            ))

    # ── CALLS edges (second pass — all names now registered) ─────────────
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            caller_id = name_to_id.get(node.name)
            if caller_id is None:
                continue
            for called_name in _collect_calls(node):
                callee_id = name_to_id.get(called_name)
                if callee_id and callee_id != caller_id:
                    result.edges.append(_make_edge(
                        collection=collection,
                        source_id=caller_id,
                        target_id=callee_id,
                        relation_type=RelationType.CALLS,
                        weight=0.9,
                    ))

    logger.debug(
        "AST extraction: %s -> %d nodes, %d edges",
        path.name, len(result.nodes), len(result.edges),
    )
    return result
