import sys

from wimm import __version__

SUCCESS = 0
GUI_NOT_IMPLEMENTED = 2


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--version"]:
        print(f"wimm {__version__}")
        return SUCCESS
    sys.stderr.write("GUI not implemented yet\n")
    return GUI_NOT_IMPLEMENTED
