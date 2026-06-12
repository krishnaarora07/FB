from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar


T = TypeVar("T")


def chunked(items: Iterable[T], size: int) -> list[list[T]]:
    chunk: list[T] = []
    chunks: list[list[T]] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            chunks.append(chunk)
            chunk = []
    if chunk:
        chunks.append(chunk)
    return chunks

