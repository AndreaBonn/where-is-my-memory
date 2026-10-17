from wimm.core.dev_roots import DEV_ROOT_CANDIDATES, select_dev_roots


def test_detect_dev_roots_keeps_only_candidates_with_a_repo() -> None:
    candidates = ("/h/code", "/h/src", "/h/Documenti")
    has_repo = {"/h/code": True, "/h/src": False, "/h/Documenti": True}
    assert select_dev_roots(candidates=candidates, has_repo=lambda p: has_repo[p]) == (
        "/h/code",
        "/h/Documenti",
    )


def test_select_dev_roots_drops_duplicates_keeping_first_order() -> None:
    result = select_dev_roots(candidates=("/b", "/a", "/b", "/a"), has_repo=lambda p: True)
    assert result == ("/b", "/a")


def test_select_dev_roots_empty_candidates_returns_empty_tuple() -> None:
    assert select_dev_roots(candidates=(), has_repo=lambda p: True) == ()


def test_select_dev_roots_no_repo_anywhere_returns_empty_tuple() -> None:
    assert select_dev_roots(candidates=("/a", "/b"), has_repo=lambda p: False) == ()


def test_select_dev_roots_does_not_probe_duplicates_twice() -> None:
    probed: list[str] = []

    def has_repo(path: str) -> bool:
        probed.append(path)
        return True

    select_dev_roots(candidates=("/a", "/a"), has_repo=has_repo)
    assert probed == ["/a"]


def test_dev_root_candidates_lists_the_conventional_directories() -> None:
    assert DEV_ROOT_CANDIDATES == (
        "~/code",
        "~/projects",
        "~/src",
        "~/dev",
        "~/git",
        "~/workspace",
        "~/Documents",
        "~/Documenti",
    )
