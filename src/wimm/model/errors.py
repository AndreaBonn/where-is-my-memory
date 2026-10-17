from wimm.i18n import N_


class WimmError(Exception):
    """Service failure with an internal message and a separate Italian UI message.

    ``user_message`` is only marked with ``N_``: the UI translates it with ``_`` where it is shown.
    """

    code = "WIMM_ERROR"
    message = "Application operation failed"
    user_message = N_("L'operazione non è riuscita")

    def __init__(self, message: str | None = None) -> None:
        self.message = self.message if message is None else message
        super().__init__(self.message)


class ProtectedTarget(WimmError):
    code = "PROTECTED_TARGET"
    message = "Action target is protected"
    user_message = N_("L'elemento è protetto e non può essere modificato")


class InvalidRequest(WimmError):
    code = "INVALID_REQUEST"
    message = "Action request is invalid"
    user_message = N_("La richiesta non è valida")
