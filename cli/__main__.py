"""Entry point: `python -m cli <command>`."""

import argparse
import sys

from cli import build, doctor, inspect, prepare, status, validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="easynamd",
        description="Prepare biomolecular systems for NAMD (VMD/psfgen + CHARMM36).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor.add_parser(subparsers)
    inspect.add_parser(subparsers)
    prepare.add_parser(subparsers)
    build.add_parser(subparsers)
    status.add_parser(subparsers)
    validate.add_parser(subparsers)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
