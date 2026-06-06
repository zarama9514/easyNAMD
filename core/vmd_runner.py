import subprocess
import threading


def run_vmd(vmd_path: str, tcl_script: str, on_output, on_done):
    """Run VMD headlessly with a Tcl script. Calls on_output(line) for each
    line of output, then calls on_done(success: bool)."""

    def _run():
        try:
            process = subprocess.Popen(
                [vmd_path, "-dispdev", "none", "-e", tcl_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in process.stdout:
                on_output(line.rstrip())
            process.wait()
            on_done(process.returncode == 0)
        except Exception as e:
            on_output(f"ERROR: {e}")
            on_done(False)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
