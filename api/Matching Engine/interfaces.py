from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    @abstractmethod
    def generate(self, user_prompt: str, system_prompt: str | None = None) -> str:
        raise NotImplementedError


class BatchStrategy(ABC):
    @abstractmethod
    def split(self, items: list[Any]) -> list[list[Any]]:
        raise NotImplementedError

