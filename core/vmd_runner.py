import subprocess
import threading

# Lines that mean psfgen/solvate quietly did something wrong. They are worth
# collecting rather than skimming, because a build "succeeds" (VMD exits 0) even
# when a residue was skipped or a coordinate was invented.
PROBLEM_PATTERNS = (
    "unknown residue", "failed to set coordinate", "poorly guessed",
    "failed to guess", "bad bond", "duplicate", "ERROR", "error:",
    "couldn't find", "warning: missing",
)


def vmd_command(vmd_path: str, tcl_script: str) -> list[str]:
    """The one place that decides how VMD is invoked."""
    return [vmd_path, "-dispdev", "none", "-e", tcl_script]


# Noise from reading CHARMM stream files: they contain scripting directives
# psfgen does not implement (set/if/WRNLEV/BOMLEV) and routinely redefine
# residues already loaded from another file. psfgen complains loudly and then
# skips them, so these lines say nothing about the structure being built.
# Reporting them would bury the handful of lines that do matter.
HARMLESS_PATTERNS = (
    "failed to recognize",
    "duplicate residue key",
    "duplicate type key",
    "duplicate resname",
    "failed to parse bond statement",
)


def scan_problems(lines) -> list[str]:
    """Pick out the log lines that indicate a silent build problem."""
    found = []
    for line in lines:
        lowered = line.lower()
        if any(pattern in lowered for pattern in HARMLESS_PATTERNS):
            continue
        if any(pattern.lower() in lowered for pattern in PROBLEM_PATTERNS):
            found.append(line.strip())
    return found


def run_vmd(vmd_path: str, tcl_script: str, on_output, on_done, cwd=None):
    """Run VMD headlessly with a Tcl script. Calls on_output(line) for each
    line of output, then calls on_done(success: bool). `cwd` sets the working
    directory (solvate/autoionize write scratch files there)."""

    def _run():
        try:
            process = subprocess.Popen(
                vmd_command(vmd_path, tcl_script),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=cwd,
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


def run_vmd_sync(vmd_path: str, tcl_script: str, cwd=None, timeout=None):
    """Blocking variant for scripts and the CLI: returns (returncode, lines)."""
    try:
        proc = subprocess.run(
            vmd_command(vmd_path, tcl_script),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=cwd, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 1, [f"ERROR: VMD did not finish within {timeout}s"]
    except OSError as exc:
        return 1, [f"ERROR: could not run VMD: {exc}"]
    return proc.returncode, proc.stdout.splitlines()
