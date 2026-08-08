"""Smoke tests for the easynamd CLI.

These cover the two things that break most easily and silently: the argparse
wiring (a subcommand that no longer builds is only noticed when someone runs it)
and the shape of the `inspect` report, which agents and scripts parse.
"""

import contextlib
import io
import os
import tempfile
import unittest

from cli.__main__ import build_parser
from cli.doctor import check_environment
from cli.inspect import inspect_structure


def atom(serial, name, resname, chain, resid, x, y, z, *, record="ATOM", element=None):
    element = element or name.strip()[0]
    return (
        f"{record:<6}{serial:5d} {name:<4} {resname:>3} {chain:1}{resid:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2}\n"
    )


@contextlib.contextmanager
def quiet():
    """argparse writes usage to stdout/stderr; keep it out of the test report."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


class ParserTests(unittest.TestCase):
    def test_every_subcommand_builds_and_has_help(self):
        parser = build_parser()
        for command in ("doctor", "inspect", "status"):
            with self.subTest(command=command):
                # parse_args on --help raises SystemExit(0); anything else is a bug
                with self.assertRaises(SystemExit) as ctx, quiet():
                    parser.parse_args([command, "--help"])
                self.assertEqual(ctx.exception.code, 0)

    def test_missing_argument_fails_instead_of_prompting(self):
        # An agent shell has nobody to answer a prompt, so this must exit, not block.
        with self.assertRaises(SystemExit), quiet():
            build_parser().parse_args(["inspect"])


class InspectTests(unittest.TestCase):
    def _write(self, text: str) -> str:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".pdb", delete=False)
        tmp.write(text)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return tmp.name

    def test_reports_chains_ligands_and_warnings(self):
        pdb = self._write(
            atom(1, "N", "ALA", "A", 1, 0.0, 0.0, 0.0)
            + atom(2, "CA", "ALA", "A", 1, 1.5, 0.0, 0.0)
            + atom(3, "CA", "GLY", "A", 2, 5.3, 0.0, 0.0)
            + atom(4, "O", "HOH", "A", 90, 20.0, 0.0, 0.0, record="HETATM")
            + atom(5, "C1", "LIG", "B", 300, 30.0, 0.0, 0.0, record="HETATM")
            + "END\n"
        )
        report = inspect_structure(pdb)

        self.assertEqual([c["chain"] for c in report["protein_chains"]], ["A"])
        # waters and ligands share chain ids with protein; they must not inflate it
        self.assertEqual(report["protein_chains"][0]["residues"], 2)

        labels = {g["label"] for g in report["groups"] if g["type"] != "protein"}
        self.assertTrue(any("LIG" in label for label in labels), labels)
        self.assertTrue(any("HOH" in label or "Water" in label for label in labels), labels)

    def test_finds_disulfide_by_distance_without_ssbond_record(self):
        # MD-frame PDBs carry no SSBOND header; the bridge must still be found.
        pdb = self._write(
            atom(1, "SG", "CYS", "A", 10, 0.0, 0.0, 0.0, element="S")
            + atom(2, "SG", "CYS", "A", 50, 2.05, 0.0, 0.0, element="S")
            + "END\n"
        )
        bonds = inspect_structure(pdb)["disulfides"]
        self.assertEqual(len(bonds), 1)
        self.assertEqual(bonds[0]["source"], "SG–SG distance")
        self.assertEqual({bonds[0]["resid1"], bonds[0]["resid2"]}, {"10", "50"})

    def test_metal_coordination_reports_distance(self):
        # The distance is what makes a wrong cutoff visible, so it must be present.
        pdb = self._write(
            atom(1, "SG", "CYS", "A", 10, 0.0, 0.0, 0.0, element="S")
            + atom(2, "ZN", "ZN", "A", 100, 2.30, 0.0, 0.0, record="HETATM", element="ZN")
            + "END\n"
        )
        cys = inspect_structure(pdb)["metal_coordination"]["cysteines"]
        self.assertEqual(len(cys), 1)
        self.assertEqual(cys[0]["metal"], "ZN")
        self.assertAlmostEqual(cys[0]["distance"], 2.30, places=2)

    def test_multiple_models_are_reported_and_warned_about(self):
        pdb = self._write(
            "MODEL        1\n" + atom(1, "CA", "ALA", "A", 1, 0.0, 0.0, 0.0) + "ENDMDL\n"
            "MODEL        2\n" + atom(2, "C1", "LIG", "B", 9, 9.0, 0.0, 0.0, record="HETATM") + "ENDMDL\n"
            "END\n"
        )
        report = inspect_structure(pdb)
        self.assertEqual(report["models"], [1, 2])
        self.assertTrue(any("model" in w for w in report["warnings"]), report["warnings"])


class DoctorTests(unittest.TestCase):
    def test_reports_required_and_optional_dependencies(self):
        report = check_environment()
        names = {c["name"] for c in report["checks"]}
        self.assertLessEqual({"vmd", "topologies", "parameters", "namd"}, names)

        required = {c["name"] for c in report["checks"] if c["required"]}
        self.assertEqual(required, {"vmd", "topologies", "parameters"})
        # NAMD only generates input here; the simulation runs on a cluster.
        namd = next(c for c in report["checks"] if c["name"] == "namd")
        self.assertFalse(namd["required"])


if __name__ == "__main__":
    unittest.main()


class BuildDecisionTests(unittest.TestCase):
    """The rules that turn coordinates into protonation and patches."""

    def _write(self, text: str) -> str:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".pdb", delete=False)
        tmp.write(text)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return tmp.name

    def test_metal_bound_residues_get_rule_derived_choices_with_evidence(self):
        from cli.build import decide
        from core.run_dir import DETERMINISTIC_RULE, DOMAIN_DEFAULT

        pdb = self._write(
            atom(1, "CA", "ALA", "A", 1, 10.0, 10.0, 10.0)
            + atom(2, "ND1", "HIS", "A", 5, 0.0, 0.0, 0.0, element="N")
            + atom(3, "NE2", "HIS", "A", 5, 4.0, 0.0, 0.0, element="N")
            + atom(4, "SG", "CYS", "A", 8, 2.0, 2.3, 0.0, element="S")
            + atom(5, "ZN", "ZN", "A", 99, 2.0, 0.0, 0.0, record="HETATM", element="ZN")
            + "END\n"
        )
        _segments, histidines, patches, decisions = decide(pdb)

        # ND1 is 2.0 A from the zinc and NE2 is 2.0 A too, but ND1 comes first;
        # whichever coordinates, the proton must go on the *other* nitrogen.
        his = next(d for d in decisions if d[0] == "histidine")
        self.assertEqual(his[3], DETERMINISTIC_RULE)
        self.assertIn("ZN", his[4])
        self.assertIn(histidines[0].protonation, ("HSD", "HSE"))

        cysd = [d for d in decisions if d[2] == "CYSD"]
        self.assertEqual(len(cysd), 1, decisions)
        self.assertEqual(cysd[0][3], DETERMINISTIC_RULE)
        self.assertTrue(any(p.name == "CYSD" for p in patches))

    def test_plain_histidine_takes_a_documented_default(self):
        from cli.build import decide
        from core.run_dir import DOMAIN_DEFAULT

        pdb = self._write(
            atom(1, "ND1", "HIS", "A", 5, 0.0, 0.0, 0.0, element="N")
            + atom(2, "NE2", "HIS", "A", 5, 2.0, 0.0, 0.0, element="N")
            + "END\n"
        )
        _s, histidines, _p, decisions = decide(pdb)
        entry = next(d for d in decisions if d[0] == "histidine")
        self.assertEqual(entry[2], "HSD")
        self.assertEqual(entry[3], DOMAIN_DEFAULT)
        self.assertEqual(histidines[0].protonation, "HSD")

    def test_an_explicit_override_beats_the_rule(self):
        from cli.build import decide
        from core.run_dir import USER_DECISION

        pdb = self._write(
            atom(1, "ND1", "HIS", "A", 5, 0.0, 0.0, 0.0, element="N")
            + atom(2, "NE2", "HIS", "A", 5, 4.0, 0.0, 0.0, element="N")
            + atom(3, "ZN", "ZN", "A", 99, 2.0, 0.0, 0.0, record="HETATM", element="ZN")
            + "END\n"
        )
        _s, histidines, _p, decisions = decide(pdb, his_overrides={"A:5": "HSP"})
        entry = next(d for d in decisions if d[0] == "histidine")
        self.assertEqual((entry[2], entry[3]), ("HSP", USER_DECISION))
        self.assertEqual(histidines[0].protonation, "HSP")

    def test_disulfides_are_found_without_a_header_record(self):
        from cli.build import decide

        pdb = self._write(
            atom(1, "SG", "CYS", "A", 10, 0.0, 0.0, 0.0, element="S")
            + atom(2, "SG", "CYS", "A", 50, 2.05, 0.0, 0.0, element="S")
            + "END\n"
        )
        _s, _h, patches, decisions = decide(pdb)
        self.assertTrue(any(p.name == "DISU" for p in patches))
        self.assertTrue(any(d[0] == "disulfide" for d in decisions))

    def test_disulfides_can_be_switched_off(self):
        from cli.build import decide

        pdb = self._write(
            atom(1, "SG", "CYS", "A", 10, 0.0, 0.0, 0.0, element="S")
            + atom(2, "SG", "CYS", "A", 50, 2.05, 0.0, 0.0, element="S")
            + "END\n"
        )
        _s, _h, patches, _d = decide(pdb, use_disulfides=False)
        self.assertFalse(any(p.name == "DISU" for p in patches))


class LogScanTests(unittest.TestCase):
    def test_charmm_stream_noise_is_not_reported_as_a_problem(self):
        # These appear in every build that loads .str files; treating them as
        # problems would bury the lines that matter.
        from core.vmd_runner import scan_problems

        noise = [
            'psfgen) ERROR!  FAILED TO RECOGNIZE SET.  Line 18: set nat ?NATC',
            'psfgen) duplicate residue key TM3P will be ignored',
            'psfgen) duplicate type key SOD',
            'Info) Duplicate resname "4YS" for glycanReader.',
            'psfgen) ERROR!  Failed to parse bond statement.  Line 2727: BOND PA',
        ]
        self.assertEqual(scan_problems(noise), [])

    def test_structure_problems_are_reported(self):
        from core.vmd_runner import scan_problems

        real = [
            "psfgen) Warning: failed to set coordinate for atom O ARG:270 A",
            "psfgen) ERROR: unknown residue type XYZ",
        ]
        self.assertEqual(len(scan_problems(real)), 2)
