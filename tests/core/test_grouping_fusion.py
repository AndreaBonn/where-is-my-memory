from collections.abc import Mapping
from dataclasses import replace
from typing import Unpack

import pytest

from wimm.core.categorize import CategoryDecision
from wimm.core.grouping import GroupDraft, GroupingInput, build_groups
from wimm.core.grouping_keys import Pair, stable_group_id
from wimm.model.enums import Category, MetricsSource
from wimm.model.raw import Mount, RawContainer, RawProcess

from .helpers import ProcessChanges, process

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


def dev(
    pid: int, /, *, category: Category = Category.DEV_PROCESS, **changes: Unpack[ProcessChanges]
) -> Pair:
    proc = replace(process(**changes), pid=pid)
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


def test_build_groups_compose_plus_uvicorn_under_working_dir_fuses_into_project() -> None:
    uvicorn = dev(
        30,
        cwd=WHITEBOX_DIR + "/app",
        name="uvicorn",
        category=Category.DEV_SERVER,
    )
    containers = (
        container(name="w-1", project="whitebox", workdir=WHITEBOX_DIR),
        container(name="w-2", project="whitebox", workdir=WHITEBOX_DIR),
    )

    groups = build(
        pairs=(uvicorn,),
        containers=containers,
        roots={WHITEBOX_DIR + "/app": WHITEBOX_DIR},
        ports={30: frozenset({8000})},
    )

    assert len(groups) == 1
    fused = groups[0]
    assert fused.category is Category.PROJECT
    assert fused.name == "whitebox"
    assert fused.process_pids == (30,)
    assert fused.container_ids == ("id-w-1", "id-w-2")
    assert fused.working_dir == WHITEBOX_DIR
    assert fused.explanation == (
        f"progetto compose 'whitebox' con 2 container in {WHITEBOX_DIR}, "
        "più un processo uvicorn nella stessa cartella, in ascolto sulla porta 8000"
    )


def test_build_groups_root_ancestor_of_working_dir_fuses() -> None:
    groups = build(
        pairs=(dev(30, cwd="/home/bonn/dev", name="make"),),
        containers=(container(name="w", project="whitebox", workdir=WHITEBOX_DIR),),
        roots={"/home/bonn/dev": "/home/bonn/dev"},
    )

    assert len(groups) == 1
    assert groups[0].category is Category.PROJECT


def test_build_groups_sibling_with_shared_prefix_does_not_fuse() -> None:
    groups = build(
        pairs=(dev(30, cwd="/a/bc", name="node"),),
        containers=(container(name="w", project="p", workdir="/a/b"),),
        roots={"/a/bc": "/a/bc"},
    )

    assert sorted(g.category.value for g in groups) == ["CONTAINER", "DEV_PROCESS"]


def test_build_groups_two_process_groups_fuse_into_the_same_compose() -> None:
    groups = build(
        pairs=(
            dev(30, cwd=WHITEBOX_DIR, name="uvicorn"),
            dev(31, cwd=WHITEBOX_DIR + "/web", name="vite"),
        ),
        containers=(container(name="w", project="whitebox", workdir=WHITEBOX_DIR),),
        roots={WHITEBOX_DIR: WHITEBOX_DIR, WHITEBOX_DIR + "/web": WHITEBOX_DIR + "/web"},
        ports={30: frozenset({8000}), 31: frozenset({5173})},
    )

    assert len(groups) == 1
    assert groups[0].process_pids == (30, 31)
    assert groups[0].explanation.endswith(
        "più 2 processi nella stessa cartella, in ascolto sulle porte 5173 e 8000"
    )


def test_build_groups_container_only_compose_stays_container() -> None:
    groups = build(containers=(container(name="w", project="whitebox", workdir=WHITEBOX_DIR),))

    assert groups[0].category is Category.CONTAINER


def test_build_groups_process_without_root_never_fuses_with_compose() -> None:
    groups = build(
        pairs=(dev(30, cwd=None, name="node"),),
        containers=(container(name="w", project="p", workdir="/srv/p"),),
    )

    assert len(groups) == 2


def test_build_groups_excluded_process_is_rejected() -> None:
    excluded = (process(pid=40), CategoryDecision(category=None, reason_code="excluded"))

    with pytest.raises(ValueError, match="excluded"):
        build(pairs=(excluded,))


def test_stable_group_id_is_identical_across_samples_with_different_pids() -> None:
    first = build(
        pairs=(dev(10, cwd="/work/api", name="uvicorn"),), roots={"/work/api": "/work/api"}
    )
    second = build(
        pairs=(dev(9999, cwd="/work/api", name="uvicorn"),), roots={"/work/api": "/work/api"}
    )

    assert first[0].id == second[0].id
    assert first[0].process_pids != second[0].process_pids
    assert first[0].id.startswith("g_")
    assert len(first[0].id) == len("g_") + 12


def test_stable_group_id_unrooted_group_ignores_pid() -> None:
    first = build(pairs=(dev(10, name="npm", cwd=None),))
    second = build(pairs=(dev(77, name="npm", cwd=None),))

    assert first[0].id == second[0].id


def test_stable_group_id_differs_for_different_key_classes_with_same_key() -> None:
    assert stable_group_id(key_class="compose", key="demo") != stable_group_id(
        key_class="container", key="demo"
    )
    assert stable_group_id(key_class="compose", key="demo") == stable_group_id(
        key_class="compose", key="demo"
    )


def test_stable_group_id_differs_for_different_keys() -> None:
    assert stable_group_id(key_class="app", key="a") != stable_group_id(key_class="app", key="b")


def test_folder_group_keeps_its_id_when_category_changes() -> None:
    roots = {"/work/api": "/work/api"}
    process_only = build(
        pairs=(dev(10, cwd="/work/api", category=Category.DEV_PROCESS),), roots=roots
    )
    serving = build(pairs=(dev(10, cwd="/work/api", category=Category.DEV_SERVER),), roots=roots)

    assert process_only[0].category is Category.DEV_PROCESS
    assert serving[0].category is Category.DEV_SERVER
    assert process_only[0].id == serving[0].id


def test_compose_group_keeps_its_id_after_fusing_into_project() -> None:
    compose = container(name="w", project="whitebox", workdir=WHITEBOX_DIR)
    alone = build(containers=(compose,))
    fused = build(
        pairs=(dev(30, cwd=WHITEBOX_DIR, category=Category.DEV_SERVER),),
        containers=(compose,),
        roots={WHITEBOX_DIR: WHITEBOX_DIR},
    )

    assert alone[0].category is Category.CONTAINER
    assert fused[0].category is Category.PROJECT
    assert alone[0].id == fused[0].id


def test_group_ids_differ_across_key_classes_with_same_key_text() -> None:
    folder = build(pairs=(dev(10, cwd="/work/x"),))
    unrooted = build(pairs=(dev(11, name="x", cwd=None),))
    compose = build(containers=(container(name="a", project="/work/x"),))

    assert len({folder[0].id, unrooted[0].id, compose[0].id}) == 3


def test_build_groups_compose_in_home_or_root_never_fuses() -> None:
    groups = build(
        pairs=(
            dev(10, cwd="/work/a", name="uvicorn", category=Category.DEV_SERVER),
            dev(11, cwd="/work/b", name="vite", category=Category.DEV_SERVER),
        ),
        containers=(
            container(name="h", project="home", workdir=HOME),
            container(name="r", project="rootdir", workdir="/"),
        ),
        roots={"/work/a": "/work/a", "/work/b": "/work/b"},
    )

    assert sorted(g.name for g in groups) == ["a", "b", "home", "rootdir"]


def test_build_groups_most_specific_compose_wins_on_nested_working_dirs() -> None:
    groups = build(
        pairs=(dev(10, cwd="/h/a/b/s", name="node"),),
        containers=(
            container(name="outer", project="outer", workdir="/h/a"),
            container(name="inner", project="inner", workdir="/h/a/b"),
        ),
        roots={"/h/a/b/s": "/h/a/b/s"},
    )

    by_name = {g.name: g for g in groups}
    assert by_name["inner"].category is Category.PROJECT
    assert by_name["inner"].process_pids == (10,)
    assert by_name["outer"].category is Category.CONTAINER


def test_build_groups_equally_specific_composes_resolve_by_key() -> None:
    containers = (
        container(name="y", project="beta", workdir="/h/a/y"),
        container(name="x", project="alpha", workdir="/h/a/x"),
    )
    forward = build(
        pairs=(dev(10, cwd="/h/a", name="make"),), containers=containers, roots={"/h/a": "/h/a"}
    )
    backward = build(
        pairs=(dev(10, cwd="/h/a", name="make"),),
        containers=tuple(reversed(containers)),
        roots={"/h/a": "/h/a"},
    )

    assert forward == backward
    assert {g.name: g.category for g in forward} == {
        "alpha": Category.PROJECT,
        "beta": Category.CONTAINER,
    }


def test_build_groups_fused_explanation_keeps_the_lead_process_name() -> None:
    groups = build(
        pairs=(dev(30, cwd=WHITEBOX_DIR, name="uvicorn"),),
        containers=(container(name="w", project="whitebox", workdir=WHITEBOX_DIR),),
        roots={WHITEBOX_DIR: WHITEBOX_DIR},
    )

    assert "un processo uvicorn" in groups[0].explanation
