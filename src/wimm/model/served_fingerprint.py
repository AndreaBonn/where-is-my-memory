"""Identity of a model served by the system ollama install (T-6.38a, design note section 2)."""

from dataclasses import dataclass

from .cache_items import MODEL_ID_PATTERN
from .ollama_names import is_valid_model_name
from .validation import ImmutableModel


@dataclass(frozen=True, slots=True)
class ServedModelFingerprint(ImmutableModel):
    """The name `ollama rm` takes and the 12-hex id of `ollama list`, checked again at run time.

    Not a file: there is no inode to compare. The id tells a model re-pulled with other
    content between the report and the confirmation from the one the user saw.
    """

    name: str
    model_id: str

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        if not is_valid_model_name(name=self.name):
            raise ValueError("name is not a valid ollama model name")
        if type(self.model_id) is not str or not MODEL_ID_PATTERN.fullmatch(self.model_id):
            raise ValueError("model_id must be 12 lowercase hex digits")
