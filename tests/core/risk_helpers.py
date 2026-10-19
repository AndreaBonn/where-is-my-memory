from wimm.core.risk import RiskTarget as Target
from wimm.model.enums import ActivityState, Category

PROCESS = Target(kind="process", category=Category.DEV_PROCESS, activity=ActivityState.IDLE)


CONTAINER_TEXT = "Il container si ferma; dati e configurazione restano."
CONTAINER_TIMEOUT_TEXT = "Se il container non si ferma da solo, Docker lo termina dopo 10 secondi."
