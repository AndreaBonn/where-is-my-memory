from tests.test_cli import RecordingWindow
from wimm.app import WindowHost


def make_host() -> tuple[WindowHost, list[RecordingWindow]]:
    built: list[RecordingWindow] = []

    def factory() -> RecordingWindow:
        built.append(RecordingWindow())
        return built[-1]

    return WindowHost(factory=factory), built


def test_a_missing_tray_does_not_create_the_window() -> None:
    host, built = make_host()
    host.set_tray_missing(missing=True)
    host.set_tray_missing(missing=False)
    assert built == []
    host.present(group_id=None)  # positive pair: only a request builds it
    assert len(built) == 1


def test_a_window_built_while_the_tray_is_missing_starts_with_the_banner() -> None:
    host, built = make_host()
    host.set_tray_missing(missing=True)
    host.present(group_id=None)
    assert built[0].tray_missing == [True]


def test_a_window_built_with_the_tray_present_is_left_alone() -> None:
    host, built = make_host()
    host.present(group_id=None)
    assert built[0].tray_missing == []


def test_the_banner_follows_the_tray_on_an_existing_window() -> None:
    host, built = make_host()
    host.present(group_id=None)
    host.set_tray_missing(missing=True)
    host.set_tray_missing(missing=False)
    assert built[0].tray_missing == [True, False]
