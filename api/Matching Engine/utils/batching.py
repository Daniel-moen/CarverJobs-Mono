from typing import Any

from interfaces import BatchStrategy


class FixedSizeBatchStrategy(BatchStrategy):
    def __init__(self, batch_size: int = 5) -> None:
        if not 5 <= batch_size <= 10:
            raise ValueError("batch_size must be between 5 and 10")
        self._batch_size = batch_size

    def split(self, items: list[Any]) -> list[list[Any]]:
        if not items:
            return []
        return [items[i : i + self._batch_size] for i in range(0, len(items), self._batch_size)]

