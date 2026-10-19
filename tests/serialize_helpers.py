from pathlib import Path
from typing import Any, cast

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_whitebox.json"


def set_path(document: dict[str, Any], path: tuple[str | int, ...], value: object) -> None:
    target: Any = document
    for key in path[:-1]:
        target = (
            cast(dict[str, Any], target)[key]
            if isinstance(key, str)
            else cast(list[Any], target)[key]
        )
    key = path[-1]
    if isinstance(key, str):
        cast(dict[str, Any], target)[key] = value
    else:
        cast(list[Any], target)[key] = value
