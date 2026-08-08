"""Tests for the run directory records.

The property worth protecting here is staleness: a recorded validation must stop
counting as soon as the files it covered change. Without that, a run keeps
looking validated while the artifacts underneath it have moved on — and the
mistake only shows up after the system reaches a cluster.
"""

import json
import os
import shutil
import tempfile
import unittest

from cli.status import resolve_run_dir, status_report
from core.run_dir import (
    DETERMINISTIC_RULE, USER_DECISION, MANIFEST_NAME, RunDir,
)


class RunDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pdb = os.path.join(self.tmp, "1ABC.pdb")
        with open(self.pdb, "w") as f:
            f.write("ATOM      1  CA  ALA A   1       0.000   0.000   0.000\nEND\n")

    def _run_with_output(self):
        run = RunDir.for_input(self.pdb)
        produced = os.path.join(run.path, "1ABC_clean.pdb")
        shutil.copy(self.pdb, produced)
        run.record_step("prepare", outputs=[produced])
        return run, produced

    def test_creates_directory_named_after_the_structure(self):
        run = RunDir.for_input(self.pdb)
        self.assertEqual(run.manifest["run_id"], "1ABC")
        self.assertEqual(os.path.basename(run.path), "1ABC")
        self.assertTrue(os.path.isdir(run.path))

    def test_paths_inside_the_run_are_stored_relative(self):
        # The folder gets copied to a cluster; records must not point back here.
        run, produced = self._run_with_output()
        stored = run.manifest["steps"][0]["outputs"][0]["path"]
        self.assertEqual(stored, "1ABC_clean.pdb")

    def test_validation_expires_when_a_covered_file_changes(self):
        run, produced = self._run_with_output()
        run.record_validation(True, files=[produced])
        self.assertEqual(run.validation_state(), ("ok", []))

        with open(produced, "a") as f:
            f.write("ATOM      2  CB  ALA A   1       1.000   0.000   0.000\n")
        state, changed = run.validation_state()
        self.assertEqual(state, "stale")
        self.assertEqual(changed, ["1ABC_clean.pdb"])

    def test_validation_expires_when_a_covered_file_disappears(self):
        run, produced = self._run_with_output()
        run.record_validation(True, files=[produced])
        os.unlink(produced)
        self.assertEqual(run.validation_state()[0], "stale")

    def test_failed_validation_is_reported_as_failed_not_missing(self):
        run, produced = self._run_with_output()
        run.record_validation(False, files=[produced], problems=["atom count mismatch"])
        self.assertEqual(run.validation_state(), ("failed", []))

    def test_unvalidated_run_reports_missing(self):
        run = RunDir.for_input(self.pdb)
        self.assertEqual(run.validation_state(), ("missing", []))

    def test_a_decision_records_where_it_came_from(self):
        run = RunDir.for_input(self.pdb)
        run.record_decision("histidine", "A:120", "HSD",
                            DETERMINISTIC_RULE, "NE2 2.15 A from ZN 273")
        entry = run.decisions["decisions"][0]
        self.assertEqual(entry["source"], DETERMINISTIC_RULE)
        self.assertIn("2.15", entry["evidence"])

    def test_unknown_decision_source_is_rejected(self):
        run = RunDir.for_input(self.pdb)
        with self.assertRaises(ValueError):
            run.record_decision("histidine", "A:120", "HSD", "vibes")

    def test_re_deciding_the_same_target_replaces_it(self):
        run = RunDir.for_input(self.pdb)
        run.record_decision("histidine", "A:120", "HSD", DETERMINISTIC_RULE)
        run.record_decision("histidine", "A:120", "HSE", USER_DECISION, "user overrode")
        entries = [d for d in run.decisions["decisions"] if d["target"] == "A:120"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["value"], "HSE")
        self.assertEqual(entries[0]["source"], USER_DECISION)

    def test_records_survive_a_reopen(self):
        run, produced = self._run_with_output()
        run.record_decision("altloc", "A:83", "A", DETERMINISTIC_RULE)
        run.save()

        reopened = RunDir.open(run.path)
        self.assertEqual(reopened.steps_done(), ["prepare"])
        self.assertEqual(reopened.outputs_of("prepare"), [produced])
        self.assertEqual(len(reopened.decisions["decisions"]), 1)

    def test_opening_a_plain_directory_fails_clearly(self):
        plain = os.path.join(self.tmp, "not-a-run")
        os.makedirs(plain)
        with self.assertRaises(FileNotFoundError) as ctx:
            RunDir.open(plain)
        self.assertIn(MANIFEST_NAME, str(ctx.exception))


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pdb = os.path.join(self.tmp, "2XYZ.pdb")
        with open(self.pdb, "w") as f:
            f.write("ATOM      1  CA  ALA A   1       0.000   0.000   0.000\nEND\n")

    def test_resolves_from_a_structure_file_as_well_as_a_directory(self):
        run = RunDir.for_input(self.pdb)
        run.save()
        inside = os.path.join(run.path, "2XYZ_clean.pdb")
        shutil.copy(self.pdb, inside)

        self.assertEqual(resolve_run_dir(run.path), run.path)
        self.assertEqual(resolve_run_dir(inside), run.path)

    def test_report_carries_steps_decisions_and_validation_state(self):
        run = RunDir.for_input(self.pdb)
        produced = os.path.join(run.path, "2XYZ_clean.pdb")
        shutil.copy(self.pdb, produced)
        run.record_step("prepare", outputs=[produced])
        run.record_decision("model", "file", "1", USER_DECISION)
        run.record_validation(True, files=[produced])
        run.save()

        report = status_report(run.path)
        self.assertEqual(report["run_id"], "2XYZ")
        self.assertEqual([s["step"] for s in report["steps"]], ["prepare"])
        self.assertEqual(report["validation"]["state"], "ok")
        self.assertEqual(len(report["decisions"]), 1)
        # the report must be serialisable — agents consume it as JSON
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
