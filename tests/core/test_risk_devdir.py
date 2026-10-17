import pytest

from wimm.core.risk_table import devdir_consequence

GENERIC = "Serve reinstallare le dipendenze (npm install o uv sync) prima di usare il progetto."


@pytest.mark.parametrize(
    ("folder_name", "marker", "command"),
    [
        ("node_modules", "", "npm install"),
        (".venv", "", "uv sync"),
        ("venv", "", "uv sync"),
        (".tox", "tox.ini", "uv sync"),
        ("target", "Cargo.toml", "cargo build"),
        ("target", "pom.xml", "mvn package"),
        (".gradle", "build.gradle", "gradle build"),
        ("build", "settings.gradle.kts", "gradle build"),
        (".next", "package.json", "npm run build"),
        (".nuxt", "package.json", "npm run build"),
        ("vendor", "composer.json", "composer install"),
    ],
)
def test_devdir_consequence_names_the_rebuild_command_for_its_kind(
    folder_name: str, marker: str, command: str
) -> None:
    text = devdir_consequence(folder_name=folder_name, marker=marker)

    assert text == f"Per usare di nuovo il progetto serve ricostruire la cartella con {command}."


def test_target_with_cargo_and_with_maven_get_different_commands() -> None:
    cargo = devdir_consequence(folder_name="target", marker="Cargo.toml")
    maven = devdir_consequence(folder_name="target", marker="pom.xml")

    assert cargo != maven
    assert "cargo build" in cargo
    assert "mvn package" not in cargo


@pytest.mark.parametrize(
    ("folder_name", "marker"),
    [("", ""), ("target", ""), ("target", "Makefile"), ("dist", "package.json")],
)
def test_devdir_without_a_known_kind_keeps_the_generic_text(folder_name: str, marker: str) -> None:
    assert devdir_consequence(folder_name=folder_name, marker=marker) == GENERIC
