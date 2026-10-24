"""Bogosort."""

from collections.abc import Iterator

import numpy as np

from .base import Highlight, sort_algorithm


@sort_algorithm("bogo")
def bogo_sort(values: list[int]) -> Iterator[Highlight]:
    """Check whether the values are in order, one neighbouring pair at a
    time; at the first pair out of order, shuffle them all and start again.

    Shuffling is one operation. A shuffle comes out sorted once in n! tries
    on average, so with more than about 8 bars it effectively never finishes.
    """
    while True:
        for i in range(len(values) - 1):
            yield (i, i + 1)
            if values[i] > values[i + 1]:
                break
        else:
            return
        values[:] = np.random.permutation(values).tolist()
        yield ()
