from collections.abc import Mapping

import pytest

from wimm.core.categorize import CategoryDecision
from wimm.core.grouping import GroupDraft, GroupingInput, build_groups
from wimm.core.grouping_keys import Pair, paths_related
from wimm.model.enums import Category, MetricsSource
from wimm.model.raw import Mount, RawContainer, RawProcess

from .helpers import process

HOME = "/home/bonn"
WHITEBOX_DIR = "/home/bonn/dev/ai-whitebox-core"
COMPOSE_PROJECT = "com.docker.compose.project"
COMPOSE_WORKDIR = "com.docker.compose.project.working_dir"


def container(*, name: str, project: str | None = None, workdir: str | None = None) -> RawContainer:
    labels: list[tuple[str, str]] = []
    if project is not None:
        labels.append((COMPOSE_PROJECT, project))
    if workdir is not None:
        labels.append((COMPOSE_WORKDIR, workdir))
    return RawContainer(
        id=f"id-{name}",
        name=name,
        image="img",
        state="running",
        labels=tuple(labels),
        mounts=(Mount(type="volume", source="v", destination="/v"),),
        ports=(),
        pid=900,
        memory_bytes=1,
        cpu_usage_usec=0,
        net_bytes=None,
        metrics_source=MetricsSource.CGROUP,
    )


def dev(pid: int, *, category: Category = Category.DEV_PROCESS, **changes: object) -> Pair:
    proc = process(pid=pid, **changes)  # type: ignore[arg-type]
    return proc, CategoryDecision(category=category, reason_code="x")


def build(
    *,
    pairs: tuple[tuple[RawProcess, CategoryDecision], ...] = (),
    containers: tuple[RawContainer, ...] = (),
    roots: Mapping[str, str] | None = None,
    ports: Mapping[int, frozenset[int]] | None = None,
) -> tuple[GroupDraft, ...]:
    return build_groups(
        grouping=GroupingInput(
            pairs=pairs,
            containers=containers,
            project_root_by_cwd=roots or {},
            desktop_name_by_appid={},
            own_home=HOME,
            own_uid=1000,
            listen_ports_by_pid=ports or {},
        )
    )


def test_build_groups_six_compose_containers_and_one_standalone_make_two_groups() -> None:
    whitebox = tuple(
        container(name=f"whitebox-{i}", project="whitebox", workdir=WHITEBOX_DIR) for i in range(6)
    )

    groups = build(containers=(*whitebox, container(name="redis-solo")))

    assert [(g.category, g.name, len(g.container_ids)) for g in groups] == [
        (Category.CONTAINER, "redis-solo", 1),
        (Category.CONTAINER, "whitebox", 6),
    ]
    compose = groups[1]
    assert compose.compose_project == "whitebox"
    assert compose.working_dir == WHITEBOX_DIR
    assert groups[0].compose_project is None
    assert groups[0].working_dir is None
    assert compose.container_ids == tuple(f"id-whitebox-{i}" for i in range(6))
    assert compose.explanation == (f"progetto compose 'whitebox' con 6 container in {WHITEBOX_DIR}")
    assert groups[0].explanation == "container 'redis-solo' senza progetto compose"


def test_build_groups_compose_without_working_dir_takes_dir_from_any_container() -> None:
    groups = build(
        containers=(
            container(name="a", project="p"),
            container(name="b", project="p", workdir="/srv/p"),
        )
    )

    assert len(groups) == 1
    assert groups[0].working_dir == "/srv/p"
    assert groups[0].explanation == "progetto compose 'p' con 2 container in /srv/p"


def test_build_groups_compose_without_any_working_dir_has_none() -> None:
    groups = build(containers=(container(name="a", project="p"),))

    assert groups[0].working_dir is None
    assert groups[0].explanation == "progetto compose 'p' con 1 container"


def test_build_groups_processes_with_same_project_root_make_one_group() -> None:
    root = "/home/bonn/dev/api"
    pairs = (
        dev(10, cwd=root, name="node", category=Category.DEV_PROCESS),
        dev(11, cwd=root + "/src", name="vite", category=Category.DEV_SERVER),
    )

    groups = build(pairs=pairs, roots={root: root, root + "/src": root})

    assert len(groups) == 1
    assert groups[0].process_pids == (10, 11)
    assert groups[0].name == "api"
    assert groups[0].category is Category.DEV_SERVER
    assert groups[0].key == root


def test_build_groups_ai_cli_beats_dev_process_but_not_dev_server() -> None:
    cwd = "/work/x"
    mixed = build(
        pairs=(
            dev(10, cwd=cwd, category=Category.DEV_PROCESS),
            dev(11, cwd=cwd, category=Category.AI_CLI),
        )
    )

    assert mixed[0].category is Category.AI_CLI


def test_build_groups_different_roots_make_different_groups() -> None:
    groups = build(pairs=(dev(10, cwd="/work/a"), dev(11, cwd="/work/b")))

    assert [g.name for g in groups] == ["a", "b"]


def test_build_groups_cwd_without_marker_root_is_its_own_root() -> None:
    groups = build(pairs=(dev(10, cwd="/srv/scratch"),))

    assert groups[0].key == "/srv/scratch"
    assert groups[0].name == "scratch"


@pytest.mark.parametrize("cwd", [HOME, "/"])
def test_build_groups_home_and_filesystem_root_are_never_project_roots(cwd: str) -> None:
    groups = build(
        pairs=(dev(10, cwd=cwd, name="tool"),),
        roots={cwd: cwd},
    )

    assert groups[0].key == f"tool|{cwd}"
    assert groups[0].name == "tool"


def test_build_groups_process_without_cwd_groups_by_root_process() -> None:
    parent = dev(10, ppid=1, name="npm", cwd=None)
    child = dev(11, ppid=10, name="node", cwd=None)
    other = dev(20, ppid=1, name="npm", cwd=None)

    groups = build(pairs=(child, parent, other))

    assert len(groups) == 1
    assert groups[0].key == "npm|"
    assert groups[0].name == "npm"
    assert groups[0].process_pids == (10, 11, 20)


def test_build_groups_unrelated_processes_without_cwd_stay_apart_by_root_name() -> None:
    groups = build(pairs=(dev(10, name="aaa"), dev(11, name="bbb")))

    assert [g.name for g in groups] == ["aaa", "bbb"]


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("/a/b", "/a/b", True),
        ("/a/b", "/a/b/c", True),
        ("/a/b/c", "/a/b", True),
        ("/a/b", "/a/bc", False),
        ("/a/bc", "/a/b", False),
        ("/x", "/y", False),
    ],
)
def test_paths_related_compares_whole_components(left: str, right: str, expected: bool) -> None:
    assert paths_related(left=left, right=right) is expected
