from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class PackageProvenance:
    generated_at_utc: str
    git_commit: str
    git_dirty: bool
    platform: str
    python: str

    def to_dict(self) -> dict:
        return asdict(self)


def package_provenance() -> PackageProvenance:
    return PackageProvenance(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        git_commit=_git_value(["rev-parse", "--short", "HEAD"]),
        git_dirty=_git_value(["status", "--short"]) != "",
        platform=platform.platform(),
        python=platform.python_version(),
    )


def _git_value(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip()
