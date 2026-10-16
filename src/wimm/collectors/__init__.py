from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CollectorResult[T]:
    data: T
    error: str | None = None
