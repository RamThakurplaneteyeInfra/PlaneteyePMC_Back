"""Helpers for memory-safe file upload processing."""

from __future__ import annotations

from typing import BinaryIO, Iterator


DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def iter_uploaded_chunks(file_obj, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
    """
    Yield file contents in chunks without loading the whole file into memory.

    Prefers Django UploadedFile.chunks(); falls back to read(chunk_size).
    """
    if file_obj is None:
        return

    chunks_fn = getattr(file_obj, "chunks", None)
    if callable(chunks_fn):
        yield from chunks_fn(chunk_size)
        return

    # SpooledTemporaryFile / plain file-like objects
    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        yield chunk


def copy_file_obj_chunked(
    source,
    target: BinaryIO,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> int:
    """Copy *source* → *target* in chunks. Returns bytes written."""
    written = 0
    if hasattr(source, "seek"):
        try:
            source.seek(0)
        except Exception:
            pass
    for chunk in iter_uploaded_chunks(source, chunk_size=chunk_size):
        target.write(chunk)
        written += len(chunk)
    if hasattr(target, "seek"):
        target.seek(0)
    if hasattr(source, "seek"):
        try:
            source.seek(0)
        except Exception:
            pass
    return written
