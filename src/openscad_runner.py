import shutil
import subprocess
import os
import platform
import logging
from typing import Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("openscad_runner")

class OpenSCADRunner:
    def __init__(self, executable_path: Optional[str] = None):
        self.executable = executable_path or self.find_executable()
        if not self.executable:
            logger.warning("OpenSCAD executable not found. Make sure it is installed and in PATH or set in .env.")

        self.library_paths = self.get_library_paths()

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

        return None

    def run(self, args: list[str]) -> Tuple[bool, str, str]:
        """
        Runs OpenSCAD with the given arguments.
        Returns (success, stdout, stderr).
        """
        if not self.executable:
            return False, "", "OpenSCAD executable not found."

        command = [self.executable] + args
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False
            )
            return result.returncode == 0, result.stdout, result.stderr
        except Exception as e:
            return False, "", str(e)

    def get_library_paths(self) -> list[str]:
        """
        Returns a list of allowed library paths.
        Prioritizes .env, then standard system paths.
        """
        paths = []

        # Check env var
        env_lib_path = os.getenv("OPENSCAD_LIBRARIES_PATH")
        if env_lib_path:
            # Handle multiple paths if separated by os.pathsep (e.g. ';' on Windows, ':' on Linux)
            # though usually it's just one directory for libraries.
            if os.path.exists(env_lib_path):
                paths.append(os.path.abspath(env_lib_path))

        # Standard system paths
        if platform.system() == "Windows":
             paths.append(os.path.abspath(os.path.expanduser(r"~\Documents\OpenSCAD\libraries")))
        elif platform.system() == "Linux":
             paths.append(os.path.abspath(os.path.expanduser("~/.local/share/OpenSCAD/libraries")))
             paths.append(os.path.abspath("/usr/share/openscad/libraries"))
        elif platform.system() == "Darwin": # macOS
             paths.append(os.path.abspath(os.path.expanduser("~/Documents/OpenSCAD/libraries")))

        # Filter existing paths and remove duplicates
        return list(set([p for p in paths if os.path.exists(p)]))

    def resolve_library_path(self, path: str) -> Optional[str]:
        """
        Resolves a relative path to an absolute path within one of the allowed library directories.
        Returns the absolute path if found and safe, otherwise None.
        """
        # If absolute, check safety directly
        if os.path.isabs(path):
            return path if self.is_path_safe(path) else None

        # Try to find the file/dir in known library paths
        for lib_path in self.library_paths:
            candidate_path = os.path.join(lib_path, path)
            if os.path.exists(candidate_path):
                # Verify safety to prevent traversal (e.g., "BOSL2/../../windows")
                # os.path.abspath inside is_path_safe handles the traversal check
                if self.is_path_safe(candidate_path):
                    return os.path.abspath(candidate_path)

        return None

    def is_path_safe(self, target_path: str) -> bool:
        """
        Checks if the target_path is within one of the allowed library directories.
        """
        try:
            target_path = os.path.abspath(target_path)
            for lib_path in self.library_paths:
                # We use os.path.commonpath to safely check if target_path is inside lib_path
                # This prevents directory traversal attacks like ../../../
                if os.path.commonpath([lib_path, target_path]) == lib_path:
                    return True
        except Exception as e:
            logger.error(f"Path safety check error: {e}")
            return False

        return False

if __name__ == "__main__":
    runner = OpenSCADRunner()
    print(f"Executable: {runner.executable}")
    print(f"Library Paths: {runner.library_paths}")
