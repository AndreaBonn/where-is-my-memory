from wimm.i18n import N_
from wimm.model.errors import InvalidRequest as InvalidRequest
from wimm.model.errors import ProtectedTarget as ProtectedTarget
from wimm.model.errors import WimmError as WimmError


class PlanExpired(WimmError):
    code = "PLAN_EXPIRED"
    message = "Action plan has expired"
    user_message = N_("Il piano è scaduto. Richiedi una nuova anteprima")


class PlanNotFound(WimmError):
    code = "PLAN_NOT_FOUND"
    message = "Action plan was not found"
    user_message = N_("Il piano richiesto non è disponibile")


class TargetChanged(WimmError):
    code = "TARGET_CHANGED"
    message = "Action target has changed"
    user_message = N_("L'elemento è cambiato. Richiedi una nuova anteprima")


class ConfirmationMismatch(WimmError):
    code = "CONFIRMATION_MISMATCH"
    message = "Typed confirmation does not match"
    user_message = N_("Il testo di conferma non corrisponde")


class DockerUnavailable(WimmError):
    code = "DOCKER_UNAVAILABLE"
    message = "Docker is unavailable"
    user_message = N_("Docker non è disponibile")


class ControlFailed(WimmError):
    code = "CONTROL_FAILED"
    message = "System control call failed"
    user_message = N_("L'operazione non è riuscita")


class TargetGone(WimmError):
    code = "TARGET_GONE"
    message = "Action target no longer exists"
    user_message = N_("L'elemento non esiste più")


class CacheIsLink(TargetChanged):
    code = "CACHE_IS_LINK"
    message = "Cache folder is a symlink"
    user_message = N_("La cache è un collegamento: puliscila con il comando dello strumento")
