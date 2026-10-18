"""User-facing names and reasons of the recognised developer tools (resolved at use time)."""

from types import MappingProxyType

from wimm.i18n import N_, _

from .tool_labels import ToolLabel, ToolReason

TOOL_NAMES = MappingProxyType(
    {
        ToolLabel.VIRTUAL_MACHINE: N_("Macchina virtuale"),
        ToolLabel.ANDROID_EMULATOR: N_("Emulatore Android"),
        ToolLabel.GRADLE_DAEMON: N_("Gradle daemon"),
        ToolLabel.KOTLIN_DAEMON: N_("Kotlin daemon"),
        ToolLabel.LANGUAGE_SERVER: N_("Language server"),
        ToolLabel.KIND_CLUSTER: N_("Cluster kind"),
        ToolLabel.MINIKUBE_CLUSTER: N_("Cluster minikube"),
    }
)
TOOL_REASONS = MappingProxyType(
    {
        ToolReason.GUEST_MEMORY: N_("memoria riservata al sistema ospite"),
        ToolReason.BACKGROUND_BUILD_DAEMON: N_("demone di build in background"),
        ToolReason.EDITOR_BACKGROUND_SERVICE: N_("servizio in background dell'editor"),
        ToolReason.LOCAL_CLUSTER: N_("cluster Kubernetes locale"),
    }
)


def tool_name(*, label: ToolLabel) -> str:
    """Name of a recognised tool in the active language."""
    return _(TOOL_NAMES[label])


def tool_reason(*, reason: ToolReason) -> str:
    """Why a recognised tool holds memory, in the active language."""
    return _(TOOL_REASONS[reason])
