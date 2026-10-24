"""Merge sort."""

from collections.abc import Iterator

from .base import Highlight, sort_algorithm


@sort_algorithm("merge")
def merge_sort(values: list[int]) -> Iterator[Highlight]:
    """Sort each half, then merge the two halves back into place.

    The merge copies both halves aside and writes the merged values over them
    one at a time, as in the usual sorting videos, so while it runs some values
    show twice and others not at all.
    """
    yield from _sort(values, 0, len(values))


def _sort(values: list[int], lo: int, hi: int) -> Iterator[Highlight]:
    if hi - lo < 2:
        return
    mid = (lo + hi) // 2
    yield from _sort(values, lo, mid)
    yield from _sort(values, mid, hi)
    yield from _merge(values, lo, mid, hi)


def _merge(values: list[int], lo: int, mid: int, hi: int) -> Iterator[Highlight]:
    left, right = values[lo:mid], values[mid:hi]
    i = j = 0
    for k in range(lo, hi):
        if j == len(right) or (i < len(left) and left[i] <= right[j]):
            values[k] = left[i]
            i += 1
        else:
            values[k] = right[j]
            j += 1
        yield (k,)
