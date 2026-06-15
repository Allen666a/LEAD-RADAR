from abc import ABC, abstractmethod

from app.schemas import RawItem


class Collector(ABC):
    @abstractmethod
    async def collect(self) -> list[RawItem]:
        raise NotImplementedError

