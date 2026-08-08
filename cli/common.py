"""Output conventions shared by the easynamd CLI.

These commands are read by people and by agents, so the contract has to be
predictable:

    stdout   the result — human-readable text, or JSON with --json
    stderr   diagnostics, warnings, subprocess noise
    exit 0   the operation succeeded / the environment is usable
    exit 1   not safe to continue
    exit 2   usage error (argparse's own code)

Errors name what to do next, not just what broke. An agent that reads
"ERROR E_NO_VMD: ..." should be able to act on it without opening the source.
Nothing here ever prompts: a missing argument must fail with usage, because an
agent shell has no one to answer a question at a TTY.
"""

import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")
TOPOLOGIES_DIR = os.path.join(ROOT_DIR, "topologies")
PARAMETERS_DIR = os.path.join(ROOT_DIR, "parameters")

EXIT_OK = 0
EXIT_FAIL = 1


def load_config() -> dict:
    """Read the same config.json the desktop app writes (paths to VMD/NAMD)."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def collect_files(folder: str, extensions: tuple) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if name.endswith(extensions)
    )


def topology_files() -> list[str]:
    # .str streams carry RESI definitions too, so they count as topology.
    return collect_files(TOPOLOGIES_DIR, (".rtf", ".top", ".str"))


def parameter_files() -> list[str]:
    return collect_files(PARAMETERS_DIR, (".prm", ".str"))


def print_json(payload) -> None:
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def error(code: str, message: str, fix: str = "") -> int:
    """Report a blocking problem; returns EXIT_FAIL so callers can `return error(...)`."""
    print(f"ERROR {code}: {message}", file=sys.stderr)
    if fix:
        print(f"  fix: {fix}", file=sys.stderr)
    return EXIT_FAIL


def add_json_flag(parser) -> None:
    parser.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON on stdout instead of a text report",
    )
