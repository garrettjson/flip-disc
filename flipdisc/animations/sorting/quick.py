"""Quicksort."""

from collections.abc import Iterator

from .base import Highlight, sort_algorithm


@sort_algorithm("quick")
def quick_sort(values: list[int]) -> Iterator[Highlight]:
    """Partition around the last value (the pivot): move every smaller value
    in front of it and the pivot between the two parts, then sort each part.

    Each comparison highlights the pivot, the value compared with it, and
    the boundary where the next smaller value will go (Lomuto's scheme).
    """
    yield from _sort(values, 0, len(values) - 1)


def _sort(values: list[int], lo: int, hi: int) -> Iterator[Highlight]:
    if lo >= hi:
        return
    pivot = values[hi]
    boundary = lo
    for i in range(lo, hi):
        smaller = values[i] < pivot
        if smaller:
            values[boundary], values[i] = values[i], values[boundary]
        yield (boundary, i, hi)
        if smaller:
            boundary += 1
    values[boundary], values[hi] = values[hi], values[boundary]
    yield (boundary, hi)
    yield from _sort(values, lo, boundary - 1)
    yield from _sort(values, boundary + 1, hi)
