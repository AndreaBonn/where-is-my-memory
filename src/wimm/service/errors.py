from wimm.model.errors import InvalidRequest as InvalidRequest
from wimm.model.errors import ProtectedTarget as ProtectedTarget
from wimm.model.errors import WimmError as WimmError


class PlanExpired(WimmError):
    code = "PLAN_EXPIRED"
    message = "Action plan has expired"
    user_message = "Il piano è scaduto. Richiedi una nuova anteprima"


class PlanNotFound(WimmError):
    code = "PLAN_NOT_FOUND"
    message = "Action plan was not found"
    user_message = "Il piano richiesto non è disponibile"


class TargetChanged(WimmError):
    code = "TARGET_CHANGED"
    message = "Action target has changed"
    user_message = "L'elemento è cambiato. Richiedi una nuova anteprima"


class ConfirmationMismatch(WimmError):
    code = "CONFIRMATION_MISMATCH"
    message = "Typed confirmation does not match"
    user_message = "Il testo di conferma non corrisponde"


class DockerUnavailable(WimmError):
    code = "DOCKER_UNAVAILABLE"
    message = "Docker is unavailable"
    user_message = "Docker non è disponibile"


class ControlFailed(WimmError):
    code = "CONTROL_FAILED"
    message = "System control call failed"
    user_message = "L'operazione non è riuscita"


class TargetGone(WimmError):
    code = "TARGET_GONE"
    message = "Action target no longer exists"
    user_message = "L'elemento non esiste più"
