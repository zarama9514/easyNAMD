"""The run directory: what was done to a structure, and on what evidence.

A run directory is the per-structure folder from `core.naming.structure_dir`
(``3ZR9/``). Alongside the generated files it holds two records:

  manifest.json    identity, tool versions, the steps performed, hashes of what
                   they produced, and the latest validation result
  decisions.json   the scientific choices — histidine tautomers, alternate
                   conformers, which models to keep — each with its evidence and
                   whether it came from a rule, a default, or the user

They exist so a later session can resume from the files instead of from a
conversation: nothing about a run should be knowable only from chat.

The hashes are what let a validation expire. A recorded "validation passed"
says nothing about the file on disk if that file has changed since, and this is
the failure worth guarding against: everything still *looks* fine, and the
mistake only surfaces after the system has been copied to a cluster and queued.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

from core.naming import root_name, structure_dir
from core.namd.provenance import package_provenance

SCHEMA = 1

MANIFEST_NAME = "manifest.json"
DECISIONS_NAME = "decisions.json"

# Where a decision came from. Worth distinguishing: "a rule inferred it from the
# coordinates", "we applied the usual default" and "the user chose it" carry very
# different weight when someone revisits the run months later.
DETERMINISTIC_RULE = "deterministic-rule"
DOMAIN_DEFAULT = "domain-default"
USER_DECISION = "user-decision"
DECISION_SOURCES = (DETERMINISTIC_RULE, DOMAIN_DEFAULT, USER_DECISION)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunDir:
    """Read/write access to one structure's run directory."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.manifest = self._load(MANIFEST_NAME) or {}
        self.decisions = self._load(DECISIONS_NAME) or {"schema": SCHEMA, "decisions": []}

    # -- construction ------------------------------------------------- #

    @classmethod
    def for_input(cls, pdb_path: str) -> "RunDir":
        """Open (creating if needed) the run directory for an input structure."""
        run = cls(structure_dir(pdb_path))
        os.makedirs(run.path, exist_ok=True)
        if not run.manifest:
            run.manifest = {
                "schema": SCHEMA,
                "run_id": root_name(pdb_path),
                "created": _now(),
                "input": run.file_record(pdb_path),
                "steps": [],
                "validation": None,
            }
        return run

    @classmethod
    def open(cls, path: str) -> "RunDir":
        """Open an existing run directory. Raises if it has no manifest."""
        run = cls(path)
        if not run.manifest:
            raise FileNotFoundError(
                f"{os.path.join(run.path, MANIFEST_NAME)} not found — "
                "this directory was not produced by easynamd"
            )
        return run

    # -- recording ------------------------------------------------------ #

    def file_record(self, path: str) -> dict:
        """Identify a file by location, size and content hash."""
        return {
            "path": self.relative(path),
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
        }

    def record_step(self, name: str, outputs=(), params=None) -> None:
        """Append a completed step and hash what it produced."""
        self.manifest.setdefault("steps", []).append({
            "step": name,
            "at": _now(),
            "tools": package_provenance().to_dict(),
            "params": params or {},
            "outputs": [self.file_record(p) for p in outputs],
        })

    def record_decision(self, kind: str, target: str, value: str,
                        source: str, evidence: str = "") -> None:
        """Record one scientific choice, replacing any earlier one for the same
        target so re-running a step stays idempotent."""
        if source not in DECISION_SOURCES:
            raise ValueError(f"unknown decision source {source!r}; "
                             f"expected one of {', '.join(DECISION_SOURCES)}")
        entry = {"kind": kind, "target": target, "value": value,
                 "source": source, "evidence": evidence, "at": _now()}
        kept = [d for d in self.decisions["decisions"]
                if not (d["kind"] == kind and d["target"] == target)]
        self.decisions["decisions"] = kept + [entry]

    def record_validation(self, ok: bool, files=(), problems=()) -> None:
        """Record a validation result against the exact files it inspected."""
        self.manifest["validation"] = {
            "at": _now(),
            "ok": bool(ok),
            "problems": list(problems),
            "files": [self.file_record(p) for p in files],
        }

    # -- reading -------------------------------------------------------- #

    def validation_state(self) -> tuple[str, list[str]]:
        """Return ("missing" | "failed" | "stale" | "ok", changed_files).

        "stale" means the recorded result was real but the files it covered have
        changed since — the only honest answer is that we no longer know.
        """
        record = self.manifest.get("validation")
        if not record:
            return "missing", []
        changed = [f["path"] for f in record.get("files", ())
                   if not self._matches(f)]
        if changed:
            return "stale", changed
        return ("ok" if record["ok"] else "failed"), []

    def steps_done(self) -> list[str]:
        return [s["step"] for s in self.manifest.get("steps", ())]

    def outputs_of(self, step: str) -> list[str]:
        """Absolute paths produced by the most recent run of a step."""
        for entry in reversed(self.manifest.get("steps", ())):
            if entry["step"] == step:
                return [self.absolute(o["path"]) for o in entry["outputs"]]
        return []

    # -- paths and persistence ------------------------------------------ #

    def relative(self, path: str) -> str:
        """Store paths inside the run directory relative, so the folder can be
        copied to a cluster without the records pointing back at this laptop."""
        absolute = os.path.abspath(path)
        if os.path.commonpath([absolute, self.path]) == self.path:
            return os.path.relpath(absolute, self.path)
        return absolute

    def absolute(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(self.path, path)

    def save(self) -> None:
        os.makedirs(self.path, exist_ok=True)
        self.manifest["updated"] = _now()
        self._write(MANIFEST_NAME, self.manifest)
        self._write(DECISIONS_NAME, self.decisions)

    # -- internals ------------------------------------------------------- #

    def _matches(self, record: dict) -> bool:
        path = self.absolute(record["path"])
        if not os.path.isfile(path):
            return False
        return sha256_file(path) == record["sha256"]

    def _load(self, name: str):
        try:
            with open(os.path.join(self.path, name)) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _write(self, name: str, payload) -> None:
        with open(os.path.join(self.path, name), "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
