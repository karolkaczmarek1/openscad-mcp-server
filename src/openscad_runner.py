import shutil
import subprocess
import os
import platform
import logging
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv

# Load .env from the repository root, independent of the process working directory
# (MCP clients such as Claude Code or Antigravity start the server from the user's project).
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

logger = logging.getLogger("openscad_runner")

# Max time (seconds) for a single OpenSCAD invocation. Complex CGAL renders can be slow.
DEFAULT_TIMEOUT = int(os.getenv("OPENSCAD_TIMEOUT", "300"))


def _is_within(base: str, target: str) -> bool:
    """True if target is base or lies inside base (case-insensitive on Windows, drive-safe)."""
    base = os.path.normcase(os.path.abspath(base))
    target = os.path.normcase(os.path.abspath(target))
    try:
        return os.path.commonpath([base, target]) == base
    except ValueError:
        # Different drives on Windows
        return False


class OpenSCADRunner:
    def __init__(self, executable_path: Optional[str] = None):
        self.executable = executable_path or self.find_executable()
        if not self.executable:
            logger.warning("OpenSCAD executable not found. Make sure it is installed and in PATH or set in .env.")

        self.library_paths = self.get_library_paths()
        self.supports_summary = self._detect_summary_support()

    def _detect_summary_support(self) -> bool:
        """Newer OpenSCAD (2023+ snapshots) can write a JSON render summary (--summary-file)."""
        if not self.executable:
            return False
        success, stdout, stderr = self.run(["--help"], timeout=30)
        return "--summary-file" in (stdout + stderr)

    def find_executable(self) -> Optional[str]:
        """
        Attempts to locate the OpenSCAD executable.
        Checks env var, PATH and common installation directories.
        """
        # Check environment variable first
        env_path = os.getenv("OPENSCAD_PATH")
        if env_path and os.path.exists(env_path):
            return env_path

        # Check PATH
        path_executable = shutil.which("openscad")
        if path_executable:
            return path_executable

        # Check common Windows paths
        if platform.system() == "Windows":
            common_paths = [
                r"C:\Program Files\OpenSCAD (Nightly)\openscad.exe",
                r"C:\Program Files\OpenSCAD\openscad.exe",
                r"C:\Program Files (x86)\OpenSCAD\openscad.exe",
                os.path.expanduser(r"~\AppData\Local\Programs\OpenSCAD\openscad.exe")
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path

        # Check common Linux paths
        if platform.system() == "Linux":
            common_paths = [
                "/usr/bin/openscad",
                "/usr/local/bin/openscad",
                "/snap/bin/openscad"
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path

        # Check common macOS paths
        if platform.system() == "Darwin":
            path = "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"
            if os.path.exists(path):
                return path

        return None

    def run(self, args: list[str], cwd: Optional[str] = None,
            timeout: Optional[int] = None) -> Tuple[bool, str, str]:
        """
        Runs OpenSCAD with the given arguments.
        Returns (success, stdout, stderr).
        """
        if not self.executable:
            return False, "", "OpenSCAD executable not found."

        command = [self.executable] + args

        # On Linux, try to use xvfb-run if available to support headless rendering
        if platform.system() == "Linux" and not os.getenv("DISPLAY"):
            xvfb_path = shutil.which("xvfb-run")
            if xvfb_path:
                command = [xvfb_path, "-a"] + command

        kwargs = {}
        if platform.system() == "Windows":
            # Don't flash a console/GUI window for every render
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                cwd=cwd,
                timeout=timeout or DEFAULT_TIMEOUT,
                check=False,
                **kwargs
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", f"OpenSCAD timed out after {timeout or DEFAULT_TIMEOUT}s."
        except Exception as e:
            return False, "", str(e)

    def get_library_paths(self) -> list[str]:
        """
        Returns a list of allowed library paths, in priority order.
        Sources: OPENSCAD_LIBRARIES_PATH (.env), OPENSCADPATH, user library dir,
        and the libraries bundled with the OpenSCAD installation.
        """
        paths = []

        # Env vars may contain several paths separated by os.pathsep (';' on Windows, ':' on Linux)
        for var in ("OPENSCAD_LIBRARIES_PATH", "OPENSCADPATH"):
            value = os.getenv(var)
            if value:
                paths.extend(p for p in value.split(os.pathsep) if p.strip())

        # Standard user paths
        if platform.system() == "Windows":
            paths.append(os.path.expanduser(r"~\Documents\OpenSCAD\libraries"))
        elif platform.system() == "Linux":
            paths.append(os.path.expanduser("~/.local/share/OpenSCAD/libraries"))
            paths.append("/usr/share/openscad/libraries")
        elif platform.system() == "Darwin":  # macOS
            paths.append(os.path.expanduser("~/Documents/OpenSCAD/libraries"))

        # Libraries shipped with the installation (e.g. MCAD)
        if self.executable:
            exe_dir = os.path.dirname(os.path.abspath(self.executable))
            paths.append(os.path.join(exe_dir, "libraries"))
            paths.append(os.path.join(exe_dir, "..", "Resources", "libraries"))  # macOS bundle

        # Keep existing paths, remove duplicates, preserve order
        result = []
        seen = set()
        for p in paths:
            abs_p = os.path.abspath(p)
            key = os.path.normcase(abs_p)
            if os.path.isdir(abs_p) and key not in seen:
                seen.add(key)
                result.append(abs_p)
        return result

    def resolve_library_path(self, path: str) -> Optional[str]:
        """
        Resolves a relative path to an absolute path within one of the allowed library directories.
        Returns the absolute path if found and safe, otherwise None.
        """
        # If absolute, check safety directly
        if os.path.isabs(path):
            return os.path.abspath(path) if self.is_path_safe(path) else None

        # Try to find the file/dir in known library paths
        for lib_path in self.library_paths:
            candidate_path = os.path.join(lib_path, path)
            # Verify safety to prevent traversal (e.g., "BOSL2/../../windows")
            if os.path.exists(candidate_path) and _is_within(lib_path, candidate_path):
                return os.path.abspath(candidate_path)

        return None

    def is_path_safe(self, target_path: str) -> bool:
        """
        Checks if the target_path is within one of the allowed library directories.
        """
        return any(_is_within(lib_path, target_path) for lib_path in self.library_paths)


if __name__ == "__main__":
    runner = OpenSCADRunner()
    print(f"Executable: {runner.executable}")
    print(f"Library Paths: {runner.library_paths}")
