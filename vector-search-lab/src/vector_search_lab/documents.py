"""Load and chunk markdown documents from a corpus directory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    id: str
    source_path: str
    heading_path: str
    text: str
    char_start: int
    char_end: int


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """Return (heading_path, section_body) pairs."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text.strip())]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(("", preamble))

    heading_stack: list[tuple[int, str]] = []
    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, title))
        path = " > ".join(h for _, h in heading_stack)

        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            sections.append((path, body))

    return sections


def _window_chunks(text: str, chunk_size: int, overlap: int) -> list[tuple[int, int, str]]:
    """Sliding window over text; returns (start, end, chunk_text)."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [(0, len(text), text)]

    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append((start, end, chunk))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def load_markdown_files(root: Path, *, skip_readmes: bool = True) -> list[Path]:
    """Collect .md files, skipping hidden dirs and optionally README stubs."""
    files: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.parts):
            continue
        if skip_readmes and path.name.upper() == "README.MD":
            continue
        if path.name in {"AGENTS.md", "DOC_TEMPLATE.md", "BACKLOG.md"}:
            continue
        files.append(path)
    return files


def chunk_file(
    path: Path,
    root: Path,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Chunk one markdown file by heading sections, then sliding window."""
    rel = str(path.relative_to(root))
    raw = path.read_text(encoding="utf-8")
    out: list[Chunk] = []
    chunk_idx = 0

    for heading_path, section in _split_by_headings(raw):
        for start, end, text in _window_chunks(section, chunk_size, chunk_overlap):
            chunk_id = f"{rel}::{chunk_idx}"
            out.append(
                Chunk(
                    id=chunk_id,
                    source_path=rel,
                    heading_path=heading_path,
                    text=text,
                    char_start=start,
                    char_end=end,
                )
            )
            chunk_idx += 1
    return out


def load_corpus(
    root: Path,
    *,
    chunk_size: int,
    chunk_overlap: int,
    skip_readmes: bool = True,
) -> list[Chunk]:
    """Load all markdown files and return flat chunk list."""
    chunks: list[Chunk] = []
    for path in load_markdown_files(root, skip_readmes=skip_readmes):
        chunks.extend(
            chunk_file(path, root, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        )
    return chunks
