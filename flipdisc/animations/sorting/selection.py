"""Selection sort."""

from collections.abc import Iterator

from .base import Highlight, sort_algorithm


@sort_algorithm("selection")
def selection_sort(values: list[int]) -> Iterator[Highlight]:
    """Scan the unsorted part for its smallest value, keeping the smallest
    found so far highlighted, then swap it to the front of that part."""
    for start in range(len(values) - 1):
        smallest = start
        for i in range(start + 1, len(values)):
            if values[i] < values[smallest]:
                smallest = i
            yield (smallest, i)
        if smallest != start:
            values[start], values[smallest] = values[smallest], values[start]
            yield (start, smallest)
