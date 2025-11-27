from mcp.server.fastmcp import FastMCP, Image
import os
import logging
from openscad_runner import OpenSCADRunner

# Initialize Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_server")

# Initialize MCP Server
mcp = FastMCP("OpenSCAD Server")

# Initialize OpenSCAD Runner
runner = OpenSCADRunner()

@mcp.tool()
def write_scad_script(filename: str, content: str) -> str:
    """
    EXCLUSIVE tool for creating/overwriting OpenSCAD scripts.
    ALWAYS use this tool to save your code. DO NOT use generic file writing tools.
    Replaces the entire content of the file.

    Args:
        filename: The name of the file to save (must end with .scad).
        content: The OpenSCAD code to write to the file.

    Returns:
        A message confirming the file was saved and a hint to render it.
    """
    if not filename.endswith(".scad"):
        filename += ".scad"

    # We allow saving in the current working directory.
    # Basic security check to prevent escaping the current directory with ../
    if ".." in filename or os.path.isabs(filename):
        # Allow absolute paths ONLY if they are inside the CWD
        try:
            cwd = os.getcwd()
            abs_path = os.path.abspath(filename)
            if os.path.commonpath([cwd, abs_path]) != cwd:
                 return "Error: Cannot save files outside the current working directory."
        except:
             return "Error: Invalid filename."

    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully saved {filename}. NOW call `render_preview` to check your work."
    except Exception as e:
        return f"Error saving file: {str(e)}"

@mcp.tool()
def read_scad_script(filename: str) -> str:
    """
    Reads an OpenSCAD script from the current working directory.
    Use this to read the code back before making edits.

    Args:
        filename: The name of the file to read (must end with .scad).

    Returns:
        The content of the file or an error message.
    """
    if not filename.endswith(".scad"):
        filename += ".scad"

    if not os.path.exists(filename):
        return f"Error: File {filename} does not exist in working directory."

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
def read_scad_library_file(filepath: str) -> str:
    """
    Reads the content of a file from the OpenSCAD library directories.
    Use this ONLY for inspecting external libraries (e.g. BOSL2).

    Args:
        filepath: The path to the library file to read. Can be relative (e.g., 'BOSL2/std.scad').

    Returns:
        The content of the file or an error message.
    """
    resolved_path = runner.resolve_library_path(filepath)
    if not resolved_path:
         return f"Error: File '{filepath}' not found in any allowed library path or access denied."

    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
def list_scad_library_directory(dirpath: str) -> str:
    """
    Lists the contents of a directory within the OpenSCAD library paths.
    Use this to explore external libraries.

    Args:
        dirpath: The path of the directory to list. Can be relative (e.g., 'BOSL2').

    Returns:
        A formatted list of files and directories.
    """
    resolved_path = runner.resolve_library_path(dirpath)
    if not resolved_path:
         return f"Error: Directory '{dirpath}' not found in any allowed library path or access denied."

    if not os.path.exists(resolved_path):
        return f"Error: Directory '{resolved_path}' does not exist."

    try:
        result = f"Contents of {dirpath} ({resolved_path}):\n"
        for item in os.listdir(resolved_path):
            item_path = os.path.join(resolved_path, item)
            if os.path.isdir(item_path):
                result += f"  [DIR]  {item}\n"
            elif item.endswith(".scad") or item.endswith(".inc"):
                result += f"  [FILE] {item}\n"
            else:
                result += f"  [OTHER] {item}\n"
        return result
    except Exception as e:
        return f"Error reading directory: {str(e)}"

@mcp.tool()
def render_preview(scad_filename: str, output_filename: str = "preview.png") -> list:
    """
    Renders a PNG preview of the OpenSCAD file and returns it visually.

    Args:
        scad_filename: The .scad file to render.
        output_filename: The output image filename (default: preview.png).

    Returns:
        A list containing the success message/logs and the Image resource.
    """
    if not runner.executable:
        return ["Error: OpenSCAD executable not found."]

    if not os.path.exists(scad_filename):
        return [f"Error: File {scad_filename} does not exist."]

    success, stdout, stderr = runner.run(["-o", output_filename, scad_filename])

    result = []
    if success:
        message = f"Successfully rendered {output_filename}.\nLogs:\n{stderr}"
        result.append(message)

        # Add the image resource
        try:
            with open(output_filename, "rb") as f:
                img_data = f.read()
                result.append(Image(data=img_data, format="png"))
        except Exception as e:
            result.append(f"Warning: Could not read generated image file: {e}")

        return result
    else:
        return [f"Failed to render preview.\nError Output:\n{stderr}"]

@mcp.tool()
def export_stl(scad_filename: str, output_filename: str = "model.stl") -> str:
    """
    Exports the OpenSCAD model to an STL file.
    Use this to VALIDATE geometry. If export fails, the model is likely non-manifold.

    Args:
        scad_filename: The .scad file to export.
        output_filename: The output STL filename (default: model.stl).

    Returns:
        Success message or error logs from OpenSCAD.
    """
    if not runner.executable:
        return "Error: OpenSCAD executable not found."

    if not os.path.exists(scad_filename):
        return f"Error: File {scad_filename} does not exist."

    success, stdout, stderr = runner.run(["-o", output_filename, scad_filename])

    if success:
        return f"Successfully exported {output_filename}.\nLogs:\n{stderr}"
    else:
        return f"Failed to export STL.\nError Output:\n{stderr}"

@mcp.tool()
def list_libraries() -> str:
    """
    Lists available OpenSCAD libraries in standard directories (and those configured in .env).

    Returns:
        A formatted list of library directories and files.
    """
    paths = runner.get_library_paths()
    if not paths:
        return "No standard library paths found."

    result = "Found libraries in:\n"

    for path in paths:
        result += f"\nPath: {path}\n"
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    result += f"  [DIR]  {item}\n"
                elif item.endswith(".scad"):
                    result += f"  [FILE] {item}\n"
        except Exception as e:
            result += f"  Error reading directory: {e}\n"

    return result

if __name__ == "__main__":
    mcp.run()
