import pytest

from wimm.core.devdir_rules import DevdirContext, classify_devdir, gitignore_names


def ctx(*entries: str, **kwargs: object) -> DevdirContext:
    return DevdirContext(parent_entries=frozenset(entries), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "context"),
    [
        ("node_modules", ctx()),
        (".venv", ctx(has_pyvenv_cfg=True)),
        ("venv", ctx(has_pyvenv_cfg=True)),
        (".tox", ctx("tox.ini")),
        (".tox", ctx("pyproject.toml")),
        (".tox", ctx("setup.cfg")),
        ("target", ctx("Cargo.toml", has_cachedir_tag=True)),
        ("target", ctx("pom.xml", gitignore_text="target/\n")),
        (".gradle", ctx("settings.gradle.kts", gitignore_text=".gradle\n")),
        ("build", ctx("build.gradle", gitignore_text="/build\n")),
        ("build", ctx("build.gradle.kts", has_cachedir_tag=True)),
        ("build", ctx("settings.gradle", has_cachedir_tag=True)),
        (".next", ctx("package.json", gitignore_text=".next\n")),
        (".nuxt", ctx("package.json", has_cachedir_tag=True)),
        ("vendor", ctx("composer.json", gitignore_text="vendor\n")),
    ],
)
def test_classify_devdir_accepts_listed_folder_with_its_signals(
    name: str, context: DevdirContext
) -> None:
    assert classify_devdir(name=name, context=context) is True


@pytest.mark.parametrize(
    ("name", "context"),
    [
        ("target", ctx(has_cachedir_tag=True, gitignore_text="target\n")),
        ("target", ctx("Cargo.toml")),
        ("target", ctx("pom.xml", gitignore_text="# target\n!target\n")),
        ("vendor", ctx("go.mod", has_cachedir_tag=True, gitignore_text="vendor\n")),
        ("vendor", ctx("composer.json")),
        ("venv", ctx("pyproject.toml")),
        (".venv", ctx(gitignore_text=".venv\n")),
        ("build", ctx(has_cachedir_tag=True)),
        ("build", ctx("build.gradle")),
        (".next", ctx(has_cachedir_tag=True)),
        (".nuxt", ctx("package.json")),
        (".gradle", ctx("build.gradle")),
        (".tox", ctx("README.md")),
        ("dist", ctx("package.json", has_cachedir_tag=True, gitignore_text="dist\n")),
        ("src", ctx("package.json")),
        ("node_modules", ctx(parent_is_home=True)),
        (".venv", ctx(has_pyvenv_cfg=True, parent_is_home=True)),
        ("target", ctx("Cargo.toml", has_cachedir_tag=True, parent_is_home=True)),
    ],
)
def test_classify_devdir_refuses_false_positives(name: str, context: DevdirContext) -> None:
    assert classify_devdir(name=name, context=context) is False


def test_gitignore_names_strips_slashes_and_skips_comments_and_negations() -> None:
    text = "# comment\n\n  /target/  \n!keep\nbuild\n"
    assert gitignore_names(text=text) == frozenset({"target", "build"})


def test_gitignore_names_drops_a_name_negated_later() -> None:
    assert "target" not in gitignore_names(text="target/\n!target\n")
    assert "target" in gitignore_names(text="!target\ntarget/\n")
