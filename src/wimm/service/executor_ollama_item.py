"""Removal of one model of the system ollama install with `ollama rm` (T-6.38b, design note L5).

The command talks to whichever server answers on `OLLAMA_HOST`, so it is run only while the
situation is S2 (one server of another user) and only for the row of `ollama list` that has
the planned name and the planned id. No file of the system store is ever touched.
"""

import logging
import os

from wimm.collectors.ollama_command import CommandOutput, OllamaCommandError
from wimm.collectors.ollama_processes import collect_ollama_processes
from wimm.core.constants import (
    CACHE_COMMAND_TIMEOUT_S,
    OLLAMA_COMMAND_ENV_KEYS,
    OLLAMA_LIST_COMMAND,
    OLLAMA_LIST_TIMEOUT_S,
    OLLAMA_NAME,
)
from wimm.core.ollama_list import ListedModel, parse_ollama_list
from wimm.core.ollama_served import (
    ServedFacts,
    ServedStore,
    default_models_path,
    home_store_path,
    served_store,
)
from wimm.core.terminal_text import printable
from wimm.i18n import N_
from wimm.model.actions import PlanStep
from wimm.model.served_fingerprint import ServedModelFingerprint

from .control_protocols import StepOutcome, StepStatus
from .errors import ControlFailed, InvalidRequest, ProtectedTarget, TargetChanged
from .fs_controls import DiskFsControl

LOGGER = logging.getLogger(__name__)
REMOVE_COMMAND = "rm"
END_OF_OPTIONS = "--"


class NotSystemServed(ProtectedTarget):
    """The server that would answer is not the system one: `ollama rm` could hit another store."""

    message = "The ollama server that answers is not the system one, nothing was removed"
    user_message = N_("Il server ollama attivo non è quello di sistema: non è stato rimosso nulla")


def _fingerprint(*, step: PlanStep) -> ServedModelFingerprint:
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, ServedModelFingerprint):
        raise InvalidRequest(f"Step {step.order} has no served model fingerprint")
    return fingerprint


def ollama_tool(*, control: DiskFsControl) -> str:
    found = control.which(OLLAMA_NAME)
    if found is None or not os.path.isabs(found):
        raise ProtectedTarget("The ollama tool is not available by an absolute path")
    return found


def served_situation(*, control: DiskFsControl) -> ServedStore:
    """The situation is read now, from the processes and the environment, never from the plan."""
    found = collect_ollama_processes(reader=control.serve_reader, current_uid=control.uid)
    facts = ServedFacts(
        processes=found.serves,
        current_uid=control.uid,
        ollama_host=control.environ.get("OLLAMA_HOST"),
        home_store=home_store_path(table=control.caches, home=control.home),
        default_models=default_models_path(home=control.home),
        unreadable_ollama=found.unreadable,
    )
    return served_store(facts=facts, realpath=os.path.realpath)


def _require_system_server(*, control: DiskFsControl) -> None:
    situation = served_situation(control=control)
    if situation is not ServedStore.SYSTEM:
        raise NotSystemServed(f"{NotSystemServed.message} (situation: {situation.value})")


def command_env(*, control: DiskFsControl) -> dict[str, str]:
    """The same dictionary for `list` and `rm`, so both talk to the same server."""
    return {key: control.environ[key] for key in OLLAMA_COMMAND_ENV_KEYS if key in control.environ}


def run_ollama(*, control: DiskFsControl, argv: list[str], timeout_s: float) -> CommandOutput:
    try:
        return control.ollama_runner(
            argv=argv, timeout_s=timeout_s, env=command_env(control=control)
        )
    except OllamaCommandError as error:
        raise ControlFailed(f"ollama {argv[1]} failed: {printable(text=str(error))}") from error


def command_detail(*, result: CommandOutput) -> str:
    """Both streams, cleaned: `ollama rm` writes its spinner and its error to the terminal."""
    return printable(text=f"{result.stdout}\n{result.stderr}")


def list_models(*, tool: str, control: DiskFsControl) -> tuple[ListedModel, ...]:
    result = run_ollama(
        control=control, argv=[tool, OLLAMA_LIST_COMMAND], timeout_s=OLLAMA_LIST_TIMEOUT_S
    )
    if result.returncode:
        detail = command_detail(result=result)
        raise ControlFailed(f"ollama list exited with code {result.returncode}: {detail}")
    models = parse_ollama_list(text=result.stdout)
    if models is None:
        raise ControlFailed("ollama list has an unknown format")
    return models


def _planned_row(
    *, tool: str, fingerprint: ServedModelFingerprint, control: DiskFsControl
) -> ListedModel | None:
    """The listed row of the planned model; None if it is gone; raise if it is another model."""
    _require_system_server(control=control)
    for model in list_models(tool=tool, control=control):
        if model.name != fingerprint.name:
            continue
        if model.model_id != fingerprint.model_id:
            raise TargetChanged(f"{model.name} is not the model the plan showed (id changed)")
        return model
    return None


def check_ollama_item(*, step: PlanStep, control: DiskFsControl) -> bool:
    """Raise if the model must not be removed now; True if it is listed, False if gone."""
    fingerprint = _fingerprint(step=step)
    tool = ollama_tool(control=control)
    return _planned_row(tool=tool, fingerprint=fingerprint, control=control) is not None


def run_ollama_item(*, step: PlanStep, control: DiskFsControl) -> StepOutcome:
    """Check again, `ollama rm`, then list again: DONE only if the name is no longer there."""
    fingerprint = _fingerprint(step=step)
    tool = ollama_tool(control=control)
    row = _planned_row(tool=tool, fingerprint=fingerprint, control=control)
    if row is None:
        return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
    argv = [tool, REMOVE_COMMAND, END_OF_OPTIONS, fingerprint.name]
    result = run_ollama(control=control, argv=argv, timeout_s=CACHE_COMMAND_TIMEOUT_S)
    if result.returncode:
        detail = command_detail(result=result)
        raise ControlFailed(f"ollama rm exited with code {result.returncode}: {detail}")
    try:
        listed = list_models(tool=tool, control=control)
    except ControlFailed as err:
        # rm said it worked; only the confirmation is missing, so the outcome stays unknown.
        raise ControlFailed(f"ollama rm exited 0 but the check after it failed: {err}") from err
    if any(model.name == fingerprint.name for model in listed):
        raise ControlFailed(f"{fingerprint.name} is still listed after ollama rm")
    LOGGER.info("Removed the system ollama model %s", fingerprint.name)
    return StepOutcome(order=step.order, status=StepStatus.DONE, freed_bytes=row.size)
