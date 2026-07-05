import os
import tempfile
import unittest

from core.coverage import uncovered_built_residues
from core.molecule_groups import build_focus_scene_pdb, find_altlocs
from core.namd.conf_writer import stage_conf_text
from core.namd.models import Stage, SystemConfig
from core.namd.package import _copy_unique
from core.pdb_parser import HeteroSegment, SegmentConfig
from core.tcl_writer import _tcl_aliases, write_build_script


def atom(serial, name, resname, chain, resid, x, y, z, *, alt=" ", record="ATOM", element=None):
    element = element or name.strip()[0]
    return (
        f"{record:<6}{serial:5d} {name:<4}{alt}{resname:>3} {chain:1}{resid:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2}\n"
    )


class CoreSmokeTests(unittest.TestCase):
    def test_metal_aliases_are_shared_by_coverage_and_tcl(self):
        with tempfile.TemporaryDirectory() as tmp:
            topology = os.path.join(tmp, "ions.str")
            with open(topology, "w") as f:
                f.write("RESI Co2p 2.00\nRESI Ni2p 2.00\nRESI CD2 2.00\nRESI ZN2 2.00\n")
            self.assertEqual(uncovered_built_residues(["CO", "NI", "CD", "ZN"], [topology]), [])

        aliases = _tcl_aliases()
        self.assertIn("pdbalias residue CO Co2p", aliases)
        self.assertIn("pdbalias residue NI Ni2p", aliases)
        self.assertIn("pdbalias atom CO CO Co2p", aliases)
        self.assertIn("pdbalias atom NI NI Ni2p", aliases)

    def test_build_script_uses_python_written_segment_pdbs(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdb = os.path.join(tmp, "input.pdb")
            with open(pdb, "w") as f:
                f.write(atom(1, "N", "ALA", "A", 1, 0, 0, 0, element="N"))
                f.write(atom(2, "CA", "ALA", "A", 1, 1, 0, 0, element="C"))
                f.write(atom(3, "N", "GLY", "A", 2, 2, 0, 0, element="N"))
                f.write(atom(4, "CA", "GLY", "A", 2, 3, 0, 0, element="C"))
                f.write(atom(5, "C1", "LIG", "B", 1, 5, 0, 0, record="HETATM", element="C"))
                f.write("END\n")

            script = write_build_script(
                pdb_file=pdb,
                topology_files=[],
                parameter_files=[],
                segments=[SegmentConfig(chain="A")],
                patches=[],
                histidines=[],
                output_dir=tmp,
                padding=8.0,
                ionize=False,
                hetero_segments=[HeteroSegment(segname="LIGB", resname="LIG", chain="B")],
                base_stem="demo",
            )

            with open(script) as f:
                script_text = f.read()
            self.assertNotIn("protein and chain", script_text)

            with open(os.path.join(tmp, "chain_A.pdb")) as f:
                chain_text = f.read()
            self.assertIn("ALA", chain_text)
            self.assertIn("GLY", chain_text)
            self.assertNotIn("LIG", chain_text)

            with open(os.path.join(tmp, "het_LIGB.pdb")) as f:
                hetero_text = f.read()
            self.assertIn("LIG", hetero_text)

    def test_altloc_focus_pdb_has_context_and_unique_serials(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdb = os.path.join(tmp, "alt.pdb")
            with open(pdb, "w") as f:
                f.write(atom(1, "N", "SER", "A", 1, 0, 0, 0, element="N"))
                f.write(atom(2, "CA", "SER", "A", 1, 1, 0, 0, element="C"))
                f.write(atom(3, "CB", "SER", "A", 1, 2, 0, 0, alt="A", element="C"))
                f.write(atom(4, "CB", "SER", "A", 1, 2, 1, 0, alt="B", element="C"))
                f.write(atom(5, "N", "GLY", "A", 2, 3, 0, 0, element="N"))
                f.write(atom(6, "CA", "GLY", "A", 2, 4, 0, 0, element="C"))
                f.write("END\n")

            residues = find_altlocs(pdb)
            self.assertEqual(len(residues), 1)
            focus, conf_map = build_focus_scene_pdb(pdb, residues[0], radius=5.0)
            self.assertEqual(conf_map, [("A", "1"), ("B", "2")])
            self.assertIn("GLY", focus)
            serials = [
                int(line[6:11])
                for line in focus.splitlines()
                if line[:6].strip() in ("ATOM", "HETATM")
            ]
            self.assertEqual(serials, list(range(1, len(serials) + 1)))
            self.assertTrue(focus.endswith("END\n"))

    def test_cuda_soa_auto_is_off_for_minimize_and_on_for_md(self):
        system = SystemConfig(psf="x.psf", pdb="x.pdb", parameter_files=[])
        system.forcefield.cuda_soa_integrate = "auto"
        minimize = Stage(name="min", stage_type="minimize", minimize_steps=10)
        md = Stage(name="md", stage_type="md", steps=10)

        self.assertIn("CUDASOAintegrate    off", stage_conf_text(system, minimize, 1, None))
        self.assertIn("CUDASOAintegrate    on", stage_conf_text(system, md, 2, None))

    def test_package_copy_rejects_input_basename_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_dir = os.path.join(tmp, "a")
            b_dir = os.path.join(tmp, "b")
            out = os.path.join(tmp, "out")
            os.makedirs(a_dir)
            os.makedirs(b_dir)
            os.makedirs(out)
            first = os.path.join(a_dir, "same.prm")
            second = os.path.join(b_dir, "same.prm")
            with open(first, "w") as f:
                f.write("first\n")
            with open(second, "w") as f:
                f.write("second\n")

            with self.assertRaisesRegex(ValueError, "filename collision"):
                _copy_unique([first, second], out)


if __name__ == "__main__":
    unittest.main()
