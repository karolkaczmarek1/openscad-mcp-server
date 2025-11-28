from mcp.server.fastmcp import FastMCP, Image
import os
import logging
from openscad_runner import OpenSCADRunner
from PIL import Image as PILImage, ImageDraw, ImageFont
from typing import Optional
import tempfile

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
def render_preview(scad_filename: str, output_filename: str = "preview.png",
                   rotation_x: Optional[float] = None, rotation_y: Optional[float] = None,
                   rotation_z: Optional[float] = None, distance: Optional[float] = None) -> list:
    """
    Renders a PNG preview of the OpenSCAD file and returns it visually.
    Optionally allows specifying rotation and distance.

    Args:
        scad_filename: The .scad file to render.
        output_filename: The output image filename (default: preview.png).
        rotation_x: Rotation around X axis (degrees).
        rotation_y: Rotation around Y axis (degrees).
        rotation_z: Rotation around Z axis (degrees).
        distance: Camera distance.

    Returns:
        A list containing the success message/logs and the Image resource.
    """
    if not runner.executable:
        return ["Error: OpenSCAD executable not found."]

    if not os.path.exists(scad_filename):
        return [f"Error: File {scad_filename} does not exist."]

    args = ["-o", output_filename]

    # Construct camera argument if parameters are provided
    if any(v is not None for v in [rotation_x, rotation_y, rotation_z, distance]):
        rx = rotation_x if rotation_x is not None else 60
        ry = rotation_y if rotation_y is not None else 0
        rz = rotation_z if rotation_z is not None else 135
        # Default distance 500 is a necessary evil if not provided, as we can't easily auto-zoom with manual rotation in CLI
        d = distance if distance is not None else 500

        args.append(f"--camera=0,0,0,{rx},{ry},{rz},{d}")

    args.append(scad_filename)

    success, stdout, stderr = runner.run(args)

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
def render_views_matrix(scad_filename: str, output_filename: str = "views_matrix.png", distance: float = 500) -> list:
    """
    Renders a set of views (Top, Bottom, Front, Back, Left, Right, Isometric)
    and combines them into a single matrix image with labels.

    Args:
        scad_filename: The .scad file to render.
        output_filename: The final combined image filename.
        distance: Camera distance for all views.

    Returns:
        A list containing the success message and the Image resource.
    """
    if not runner.executable:
        return ["Error: OpenSCAD executable not found."]

    if not os.path.exists(scad_filename):
        return [f"Error: File {scad_filename} does not exist."]

    # Define views: Name -> (rot_x, rot_y, rot_z)
    views = {
        "Top": (0, 0, 0),
        "Bottom": (180, 0, 0),
        "Front": (90, 0, 0),
        "Back": (270, 0, 0),
        "Left": (90, 0, 90),
        "Right": (90, 0, 270),
        "Isometric": (60, 0, 45)
    }

    generated_images = []
    temp_files = []

    try:
        # Create a temporary directory to store individual view images
        with tempfile.TemporaryDirectory() as temp_dir:
            for name, (rx, ry, rz) in views.items():
                temp_out = os.path.join(temp_dir, f"{name}.png")
                # temp_files is strictly not needed for cleanup since we use TemporaryDirectory,
                # but good to track if we were not using it. Here TemporaryDirectory handles it.

                # 0,0,0 translation
                camera_arg = f"--camera=0,0,0,{rx},{ry},{rz},{distance}"

                success, stdout, stderr = runner.run(["-o", temp_out, camera_arg, scad_filename])

                if not success:
                    logger.error(f"Failed to render view {name}: {stderr}")
                    return [f"Failed to render view {name}.\nError Output:\n{stderr}"]

                try:
                    # We need to copy or load the image into memory because temp_dir will be deleted
                    img = PILImage.open(temp_out)
                    img.load() # Force loading into memory
                    generated_images.append((name, img, rx, ry, rz))
                except Exception as e:
                    return [f"Error processing image for view {name}: {str(e)}"]

            # Create composite image
            cols = 3
            rows = 3

            if not generated_images:
                return ["No images generated."]

            # Assume all images are same size
            w, h = generated_images[0][1].size

            # Add space for labels
            label_height = 30
            cell_w = w
            cell_h = h + label_height

            matrix_w = cols * cell_w
            matrix_h = rows * cell_h

            matrix_img = PILImage.new('RGB', (matrix_w, matrix_h), color=(255, 255, 255))
            draw = ImageDraw.Draw(matrix_img)

            # Load font
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
            ]
            font = None
            for fp in font_paths:
                if os.path.exists(fp):
                    try:
                        font = ImageFont.truetype(fp, 14)
                        break
                    except IOError:
                        continue

            if font is None:
                font = ImageFont.load_default()

            for idx, (name, img, rx, ry, rz) in enumerate(generated_images):
                col = idx % cols
                row = idx // cols

                x = col * cell_w
                y = row * cell_h

                matrix_img.paste(img, (x, y + label_height))

                label = f"{name} (Rot: {rx},{ry},{rz} Dist: {distance})"
                draw.text((x + 5, y + 5), label, fill=(0, 0, 0), font=font)

            matrix_img.save(output_filename)

            result = []
            message = f"Successfully generated views matrix: {output_filename}"
            result.append(message)

            with open(output_filename, "rb") as f:
                img_data = f.read()
                result.append(Image(data=img_data, format="png"))

            return result

    except Exception as e:
        return [f"Error generating matrix: {str(e)}"]

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
