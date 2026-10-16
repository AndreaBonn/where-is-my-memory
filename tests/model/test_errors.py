import importlib
import sys

import pytest

from wimm.model import errors as model_errors
from wimm.service import errors as service_errors


def test_service_errors_reexports_the_model_error_classes() -> None:
    for name in ("WimmError", "InvalidRequest", "ProtectedTarget"):
        assert getattr(service_errors, name) is getattr(model_errors, name)
    assert issubclass(service_errors.TargetChanged, model_errors.WimmError)


def test_planning_import_does_not_load_the_service_package(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in sys.modules if n == "wimm" or n.startswith("wimm.")]:
        monkeypatch.delitem(sys.modules, name)

    importlib.import_module("wimm.core.planning")

    assert "wimm.core.planning" in sys.modules
    assert not [n for n in sys.modules if n.startswith("wimm.service")]
