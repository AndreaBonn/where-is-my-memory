class WimmError(Exception):
    """Service failure with an internal message and a separate Italian UI message."""

    code = "WIMM_ERROR"
    message = "Application operation failed"
    user_message = "L'operazione non è riuscita"

    def __init__(self, message: str | None = None) -> None:
        self.message = self.message if message is None else message
        super().__init__(self.message)


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


class ProtectedTarget(WimmError):
    code = "PROTECTED_TARGET"
    message = "Action target is protected"
    user_message = "L'elemento è protetto e non può essere modificato"


class DockerUnavailable(WimmError):
    code = "DOCKER_UNAVAILABLE"
    message = "Docker is unavailable"
    user_message = "Docker non è disponibile"


class InvalidRequest(WimmError):
    code = "INVALID_REQUEST"
    message = "Action request is invalid"
    user_message = "La richiesta non è valida"
