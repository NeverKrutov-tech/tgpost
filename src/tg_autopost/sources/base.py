from abc import ABC, abstractmethod
from typing import Iterable

from ..models import Joke


class JokeSource(ABC):
    name: str

    @abstractmethod
    def fetch(self, limit: int) -> Iterable[Joke]:
        raise NotImplementedError
