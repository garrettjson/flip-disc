"""Insertion sort."""

from collections.abc import Iterator

from .base import Highlight, sort_algorithm


@sort_algorithm("insertion")
def insertion_sort(values: list[int]) -> Iterator[Highlight]:
    """Take each value in turn and swap it leftwards past every larger value,
    growing a sorted part at the front."""
    for start in range(1, len(values)):
        for i in range(start, 0, -1):
            out_of_order = values[i - 1] > values[i]
            if out_of_order:
                values[i - 1], values[i] = values[i], values[i - 1]
            yield (i - 1, i)
            if not out_of_order:
                break
