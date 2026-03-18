from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class BatchStrategy(ABC):
    @abstractmethod
    def split(self, items: list[Any]) -> list[list[Any]]:
        raise NotImplementedError

