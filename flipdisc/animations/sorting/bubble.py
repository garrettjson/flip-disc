"""Bubble sort."""

from collections.abc import Iterator

from .base import Highlight, sort_algorithm


@sort_algorithm("bubble")
def bubble_sort(values: list[int]) -> Iterator[Highlight]:
    """Pass left to right swapping neighbours that are out of order, so the
    largest unsorted value bubbles up to the end of the unsorted part. Stops
    after a pass with no swaps."""
    for end in range(len(values) - 1, 0, -1):
        swapped = False
        for i in range(end):
            if values[i] > values[i + 1]:
                values[i], values[i + 1] = values[i + 1], values[i]
                swapped = True
            yield (i, i + 1)
        if not swapped:
            return
