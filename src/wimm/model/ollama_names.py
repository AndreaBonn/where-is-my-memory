"""Which ollama model names may reach a command line (T-6.37b, moved here by T-6.38a).

The model layer owns the rule because `ServedModelFingerprint` must refuse a bad name at
construction; the core, the planner and the executor all apply this same function.
"""

import re
import string

MAX_MODEL_NAME_LENGTH = 255
_ALNUM = string.ascii_letters + string.digits
_SEGMENT = f"[{_ALNUM}][{_ALNUM}._-]*"
_TAG = f"[{_ALNUM}_][{_ALNUM}._-]{{0,127}}"
MODEL_NAME_PATTERN = re.compile(f"{_SEGMENT}(/{_SEGMENT}){{0,2}}:{_TAG}")


def is_valid_model_name(*, name: str) -> bool:
    """True for `[<host>/][<namespace>/]<name>:<tag>` with no leading dash or control byte.

    A name that fails never reaches an argv: it could read as an option, climb a path or
    carry a terminal escape. A host with a port (`localhost:5000/...`) is refused too.
    """
    return (
        type(name) is str
        and len(name) <= MAX_MODEL_NAME_LENGTH
        and MODEL_NAME_PATTERN.fullmatch(name) is not None
    )
