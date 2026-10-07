from mcp.server.mcpserver import MCPServer, Image
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
import os
import sys
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from openscad_runner import OpenSCADRunner, _is_within
from PIL import Image as PILImage, ImageChops, ImageDraw, ImageFont
from typing import Optional, Tuple
import tempfile
import math
from stl import mesh

# Initialize Logging (stderr only - stdout is reserved for the MCP stdio protocol)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("mcp_server")

INSTRUCTIONS = """OpenSCAD engineering tools for designing parametric 3D-printable models.

Workflow (iterate until correct):
1. Write parametric OpenSCAD code (variables for all dimensions) with `write_scad_script`.
   It returns the absolute path of the file; small edits may also be done on that path with
   your own file-editing tools, if you have them.
2. Verify visually with `render_views_matrix` (14 labeled views) - inspect it carefully.
   Use `render_preview` with custom rotation_x/y/z for close-ups of specific details.
3. Fix problems and re-render.
4. Finish with `export_stl`: it reports dimensions, volume and manifold status - check them
   against the requirements.

Need complex features (threads, gears, rounding)? Discover installed libraries with
`list_libraries`, then `list_scad_library_directory` / `read_scad_library_file`.
All file names are relative to the server workspace directory."""

# Initialize MCP Server
mcp = MCPServer("OpenSCAD Server", instructions=INSTRUCTIONS)

# Initialize OpenSCAD Runner
runner = OpenSCADRunner()

# Directory where scripts and renders live. MCP clients (Claude Code, Antigravity)
# start the server in the user's project directory, so cwd is the natural default.
WORKSPACE = os.path.abspath(os.getenv("OPENSCAD_WORKSPACE") or os.getcwd())
os.makedirs(WORKSPACE, exist_ok=True)
logger.info(f"Workspace: {WORKSPACE}; OpenSCAD: {runner.executable}; summary: {runner.supports_summary}")

# Size of each single view in render_views_matrix (keeps the composite readable for LLM vision).
# Views are rendered at 2x, cropped to the object and scaled down to fit the cell.
MATRIX_VIEW_SIZE = (400, 300)
MATRIX_RENDER_SCALE = 2
MAX_PARALLEL_RENDERS = min(8, os.cpu_count() or 4)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES_OUTPUT = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                idempotent_hint=True, open_world_hint=False)


def resolve_workspace_path(filename: str, extension: Optional[str] = None) -> Optional[str]:
    """
    Resolves a filename to an absolute path inside the workspace.
    Appends the extension if missing. Returns None if the path escapes the workspace.
    """
    if extension and not filename.lower().endswith(extension):
        filename += extension
    path = os.path.abspath(os.path.join(WORKSPACE, filename))
    return path if _is_within(WORKSPACE, path) else None


def load_font(size: int):
    """Loads a bold TrueType font if available on this OS, otherwise Pillow's default."""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    font_paths = [
        os.path.join(windir, "Fonts", "arialbd.ttf"),
        os.path.join(windir, "Fonts", "segoeuib.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except IOError:
                continue
    return ImageFont.load_default(size=size)


def resolve_io_paths(scad_filename: str, output_filename: str, output_extension: str) -> Tuple[str, str]:
    """
    Validates the input .scad and output file of a render/export tool.
    Returns (scad_path, output_path) or raises ToolError.
    """
    if not runner.executable:
        raise ToolError("OpenSCAD executable not found. Set OPENSCAD_PATH in .env.")

    scad_path = resolve_workspace_path(scad_filename, ".scad")
    output_path = resolve_workspace_path(output_filename, output_extension)
    if not scad_path or not output_path:
        raise ToolError(f"Files must be inside the workspace ({WORKSPACE}).")

    if not os.path.exists(scad_path):
        raise ToolError(f"File {scad_filename} does not exist in workspace ({WORKSPACE}).")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    return scad_path, output_path


def summarize_log(stderr: str, max_lines: int = 30) -> str:
    """
    Extracts the lines relevant for the model author (ECHO/WARNING/ERROR/TRACE/DEPRECATED)
    from OpenSCAD's verbose log. Duplicates are removed, order is kept.
    """
    keys = ("ECHO:", "WARNING:", "ERROR:", "TRACE:", "DEPRECATED", "Can't", "Current top level object is empty")
    lines = []
    for line in stderr.splitlines():
        line = line.strip()
        if any(k in line for k in keys) and line not in lines:
            lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines)"]
    return "\n".join(lines) if lines else "(no echo output or warnings)"


def error_report(message: str, stderr: str) -> str:
    """Error text for a failed OpenSCAD call: relevant lines, plus the raw log tail if they don't explain it."""
    summary = summarize_log(stderr)
    if "ERROR:" in summary or "Can't" in summary:
        return f"{message}\n{summary}"
    return f"{message}\n{summary}\n\nFull output:\n{stderr[-3000:]}"


def calculate_camera_parameters(scad_filename: str) -> Tuple[float, float, float, float]:
    """
    Calculates the center of the model and an optimal camera distance
    by exporting to STL and analyzing the bounding box.
    Only needed when the caller requests an explicit camera distance
    (otherwise OpenSCAD's --autocenter --viewall does this natively).
    Returns (center_x, center_y, center_z, distance).
    """
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        temp_stl = tmp.name

    try:
        # Export to STL to get geometry bounds
        success, stdout, stderr = runner.run(cwd=WORKSPACE, args=["-o", temp_stl, scad_filename])
        if not success:
            logger.error(f"Failed to export STL for calculation: {stderr}")
            # Fallback to defaults
            return 0, 0, 0, 500

        try:
            your_mesh = mesh.Mesh.from_file(temp_stl)
            if your_mesh.points.size == 0:
                return 0, 0, 0, 500

            mins = your_mesh.min_
            maxs = your_mesh.max_
            cx, cy, cz = (mins + maxs) / 2
            # Diagonal approximates the bounding sphere diameter; add padding.
            diagonal = math.sqrt(sum((maxs - mins) ** 2))
            dist = diagonal * 2.5 if diagonal > 0 else 100

            return float(cx), float(cy), float(cz), float(dist)

        except Exception as e:
            logger.error(f"Error analyzing STL: {e}")
            return 0, 0, 0, 500

    finally:
        if os.path.exists(temp_stl):
            os.remove(temp_stl)


def camera_args(scad_filename: str, rx: float, ry: float, rz: float,
                distance: Optional[float]) -> list[str]:
    """
    Camera arguments for a given rotation. Without explicit distance OpenSCAD centers
    and fits the object itself; with distance we have to compute the center.
    """
    if distance is None:
        return [f"--camera=0,0,0,{rx},{ry},{rz},1", "--autocenter", "--viewall"]
    cx, cy, cz, _ = calculate_camera_parameters(scad_filename)
    return [f"--camera={cx},{cy},{cz},{rx},{ry},{rz},{distance}"]


def crop_to_object(img: PILImage.Image, target: Tuple[int, int], margin: float = 0.06) -> PILImage.Image:
    """
    Crops the render to the object (removing the empty background around it)
    and scales it to fit `target`, keeping the aspect ratio.
    """
    img = img.convert("RGB")
    background = PILImage.new("RGB", img.size, img.getpixel((0, 0)))
    diff = ImageChops.difference(img, background).convert("L").point(lambda p: 255 if p > 12 else 0)
    bbox = diff.getbbox()

    out = PILImage.new("RGB", target, img.getpixel((0, 0)))
    if not bbox:
        return out

    left, top, right, bottom = bbox
    pad_x = int((right - left) * margin) + 2
    pad_y = int((bottom - top) * margin) + 2
    obj = img.crop((max(0, left - pad_x), max(0, top - pad_y),
                    min(img.width, right + pad_x), min(img.height, bottom + pad_y)))

    scale = min(target[0] / obj.width, target[1] / obj.height)
    obj = obj.resize((max(1, int(obj.width * scale)), max(1, int(obj.height * scale))), PILImage.LANCZOS)
    out.paste(obj, ((target[0] - obj.width) // 2, (target[1] - obj.height) // 2))
    return out


def read_stl_stats(stl_path: str) -> dict:
    """Bounding box, triangle count and volume of an STL file (numpy-stl)."""
    m = mesh.Mesh.from_file(stl_path)
    stats = {"triangles": len(m.vectors)}
    if len(m.vectors):
        stats["min"] = [float(v) for v in m.min_]
        stats["max"] = [float(v) for v in m.max_]
        stats["size"] = [float(a - b) for a, b in zip(m.max_, m.min_)]
        volume, _, _ = m.get_mass_properties()
        stats["volume"] = abs(float(volume))
    return stats


def fmt_vec(v) -> str:
    return " x ".join(f"{x:.2f}" for x in v)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                      idempotent_hint=True, open_world_hint=False))
def write_scad_script(filename: str, content: str) -> str:
    """
    Creates or overwrites an OpenSCAD script in the workspace (replaces the entire file).
    Use this to save OpenSCAD code so the render/export tools can find it.

    Args:
        filename: The name of the file to save (.scad is appended if missing).
        content: The OpenSCAD code to write to the file.

    Returns:
        The absolute path of the saved file and a hint to render it.
    """
    path = resolve_workspace_path(filename, ".scad")
    if not path:
        raise ToolError(f"Cannot save files outside the workspace ({WORKSPACE}).")

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        raise ToolError(f"Error saving file: {e}")
    return f"Successfully saved {path}. NOW call `render_views_matrix` or `render_preview` to check your work."


@mcp.tool(annotations=READ_ONLY)
def read_scad_script(filename: str) -> str:
    """
    Reads an OpenSCAD script from the workspace.
    Use this to read the code back before making edits.

    Args:
        filename: The name of the file to read (.scad is appended if missing).

    Returns:
        The content of the file.
    """
    path = resolve_workspace_path(filename, ".scad")
    if not path:
        raise ToolError(f"Cannot read files outside the workspace ({WORKSPACE}).")

    if not os.path.exists(path):
        raise ToolError(f"File {filename} does not exist in workspace ({WORKSPACE}).")

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise ToolError(f"Error reading file: {e}")


@mcp.tool(annotations=READ_ONLY)
def read_scad_library_file(filepath: str) -> str:
    """
    Reads the content of a file from the OpenSCAD library directories.
    Use this ONLY for inspecting external libraries (e.g. BOSL2).

    Args:
        filepath: The path to the library file to read. Can be relative (e.g., 'BOSL2/std.scad').

    Returns:
        The content of the file.
    """
    resolved_path = runner.resolve_library_path(filepath)
    if not resolved_path or not os.path.isfile(resolved_path):
        raise ToolError(f"File '{filepath}' not found in any allowed library path or access denied.")

    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise ToolError(f"Error reading file: {e}")


@mcp.tool(annotations=READ_ONLY)
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
    if not resolved_path or not os.path.isdir(resolved_path):
        raise ToolError(f"Directory '{dirpath}' not found in any allowed library path or access denied.")

    try:
        result = f"Contents of {dirpath} ({resolved_path}):\n"
        for item in sorted(os.listdir(resolved_path)):
            item_path = os.path.join(resolved_path, item)
            if os.path.isdir(item_path):
                result += f"  [DIR]  {item}\n"
            elif item.endswith(".scad") or item.endswith(".inc"):
                result += f"  [FILE] {item}\n"
            else:
                result += f"  [OTHER] {item}\n"
        return result
    except Exception as e:
        raise ToolError(f"Error reading directory: {e}")


@mcp.tool(annotations=WRITES_OUTPUT)
def render_preview(scad_filename: str, output_filename: str = "preview.png",
                   rotation_x: Optional[float] = None, rotation_y: Optional[float] = None,
                   rotation_z: Optional[float] = None, distance: Optional[float] = None) -> list:
    """
    Renders a PNG preview of the OpenSCAD file and returns it visually.
    The object is always centered and fitted in the frame automatically.
    Optionally allows specifying camera rotation and an explicit distance (zoom).

    Args:
        scad_filename: The .scad file to render.
        output_filename: The output image filename (default: preview.png).
        rotation_x: Rotation around X axis (degrees). 0 = top view, 90 = front view.
        rotation_y: Rotation around Y axis (degrees).
        rotation_z: Rotation around Z axis (degrees).
        distance: Camera distance. If None, the object is fitted to the frame.

    Returns:
        A list containing the render log (echo/warnings) and the Image.
    """
    scad_filename, output_filename = resolve_io_paths(scad_filename, output_filename, ".png")

    args = ["-o", output_filename]

    has_rotation = any(v is not None for v in [rotation_x, rotation_y, rotation_z])
    if has_rotation or distance is not None:
        rx = rotation_x if rotation_x is not None else 60
        ry = rotation_y if rotation_y is not None else 0
        rz = rotation_z if rotation_z is not None else 135
        args += camera_args(scad_filename, rx, ry, rz, distance)
    else:
        # OpenSCAD's default view angle, centered and fitted
        args += ["--autocenter", "--viewall"]

    args.append(scad_filename)

    success, stdout, stderr = runner.run(cwd=WORKSPACE, args=args)
    if not success:
        raise ToolError(error_report("Failed to render preview.", stderr))

    try:
        with open(output_filename, "rb") as f:
            img_data = f.read()
    except Exception as e:
        raise ToolError(f"Rendered, but could not read generated image file: {e}")

    return [f"Successfully rendered {output_filename}.\nLog:\n{summarize_log(stderr)}",
            Image(data=img_data, format="png")]


@mcp.tool(annotations=WRITES_OUTPUT)
def render_views_matrix(scad_filename: str, output_filename: str = "views_matrix.png", distance: Optional[float] = None) -> list:
    """
    Renders 14 views (Top, Bottom, Front, Back, Left, Right and 8 isometric corners)
    and combines them into a single labeled matrix image.
    Each view is automatically centered and zoomed so the object fills its frame
    (scale differs between views; use export_stl for real dimensions).

    Args:
        scad_filename: The .scad file to render.
        output_filename: The final combined image filename.
        distance: Fixed camera distance for all views (same scale everywhere).
            If None, each view is fitted automatically.

    Returns:
        A list containing the render log (echo/warnings) and the Image.
    """
    scad_filename, output_filename = resolve_io_paths(scad_filename, output_filename, ".png")

    # Define views: Name -> (rot_x, rot_y, rot_z)
    views = {
        # Orthogonal views
        "Top": (0, 0, 0),
        "Bottom": (180, 0, 0),
        "Front": (90, 0, 0),
        "Back": (90, 0, 180),  # 90 around X (Front), then 180 around Z to look from back upright
        "Left": (90, 0, 270),  # 90 around X (Front), then 270 around Z (or -90) to look from Left
        "Right": (90, 0, 90),  # 90 around X (Front), then 90 around Z to look from Right

        # Top Isometrics
        "Iso TFR": (60, 0, 45),   # Top-Front-Right
        "Iso TFL": (60, 0, 315),  # Top-Front-Left
        "Iso TBR": (60, 0, 135),  # Top-Back-Right
        "Iso TBL": (60, 0, 225),  # Top-Back-Left

        # Bottom Isometrics
        "Iso BFR": (120, 0, 45),   # Bottom-Front-Right
        "Iso BFL": (120, 0, 315),  # Bottom-Front-Left
        "Iso BBR": (120, 0, 135),  # Bottom-Back-Right
        "Iso BBL": (120, 0, 225)   # Bottom-Back-Left
    }

    # Map short names to long descriptions for labels
    labels_map = {
        "Iso TFR": "Isometric - Top-Front-Right",
        "Iso TFL": "Isometric - Top-Front-Left",
        "Iso TBR": "Isometric - Top-Back-Right",
        "Iso TBL": "Isometric - Top-Back-Left",
        "Iso BFR": "Isometric - Bottom-Front-Right",
        "Iso BFL": "Isometric - Bottom-Front-Left",
        "Iso BBR": "Isometric - Bottom-Back-Right",
        "Iso BBL": "Isometric - Bottom-Back-Left"
    }

    # The center only has to be computed once when a fixed distance is requested
    fixed_center = calculate_camera_parameters(scad_filename) if distance is not None else None
    render_w, render_h = (MATRIX_VIEW_SIZE[0] * MATRIX_RENDER_SCALE, MATRIX_VIEW_SIZE[1] * MATRIX_RENDER_SCALE)

    with tempfile.TemporaryDirectory() as temp_dir:

        def render_view(item):
            name, (rx, ry, rz) = item
            temp_out = os.path.join(temp_dir, f"{name.replace(' ', '_')}.png")
            if fixed_center:
                cx, cy, cz, _ = fixed_center
                cam = [f"--camera={cx},{cy},{cz},{rx},{ry},{rz},{distance}"]
            else:
                cam = [f"--camera=0,0,0,{rx},{ry},{rz},1", "--autocenter", "--viewall"]
            args = ["-o", temp_out, f"--imgsize={render_w},{render_h}"] + cam + [scad_filename]
            return name, temp_out, runner.run(cwd=WORKSPACE, args=args)

        # Each view is a separate OpenSCAD process, so they can run in parallel
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_RENDERS) as pool:
            results = list(pool.map(render_view, views.items()))

        generated_images = []
        for name, temp_out, (success, stdout, stderr) in results:
            if not success:
                logger.error(f"Failed to render view {name}: {stderr}")
                raise ToolError(error_report(f"Failed to render view {name}.", stderr))
            try:
                with PILImage.open(temp_out) as raw:
                    if fixed_center:
                        img = raw.convert("RGB").resize(MATRIX_VIEW_SIZE, PILImage.LANCZOS)
                    else:
                        img = crop_to_object(raw, MATRIX_VIEW_SIZE)
                rx, ry, rz = views[name]
                generated_images.append((name, img, rx, ry, rz))
            except Exception as e:
                raise ToolError(f"Error processing image for view {name}: {e}")

        log = summarize_log(results[0][2][2])

    # Create composite image: 14 views, 4 columns -> 4 rows (16 slots)
    cols = 4
    rows = math.ceil(len(generated_images) / cols)

    img_w, img_h = MATRIX_VIEW_SIZE

    # Layout constants
    label_height = 30
    padding = 3      # Space between content (image+text) and frame
    margin = 3       # Space between frame and next cell/edge

    # Content size (Text + Image)
    content_w = img_w
    content_h = label_height + img_h

    # Frame size (Content + Padding)
    frame_w = content_w + 2 * padding
    frame_h = content_h + 2 * padding

    # Total cell size (Frame + Margin)
    cell_w = frame_w + margin
    cell_h = frame_h + margin

    # Matrix image size (add one margin for the left/top edge)
    matrix_w = cols * cell_w + margin
    matrix_h = rows * cell_h + margin

    matrix_img = PILImage.new('RGB', (matrix_w, matrix_h), color=(255, 255, 255))
    draw = ImageDraw.Draw(matrix_img)
    font = load_font(13)

    for idx, (name, img, rx, ry, rz) in enumerate(generated_images):
        col = idx % cols
        row = idx // cols

        # Top-left coordinate of the cell (including outer margin)
        cell_x = margin + col * cell_w
        cell_y = margin + row * cell_h

        # Draw Frame (PIL rectangle coordinates are inclusive)
        draw.rectangle(
            [cell_x, cell_y, cell_x + frame_w - 1, cell_y + frame_h - 1],
            outline=(0, 0, 0),
            width=1
        )

        # Paste Image
        # Inside frame: padding -> Text (label_height) -> Image
        img_x = cell_x + padding
        img_y = cell_y + padding + label_height
        matrix_img.paste(img, (img_x, img_y))

        # Draw Label
        text_x = cell_x + padding + 5
        text_y = cell_y + padding + 2

        # Use long label if available, otherwise just name
        display_name = labels_map.get(name, name)
        label = f"{display_name}  (rot {rx},{ry},{rz})"
        draw.text((text_x, text_y), label, fill=(0, 0, 0), font=font)

    matrix_img.save(output_filename)

    with open(output_filename, "rb") as f:
        img_data = f.read()

    return [f"Successfully generated views matrix: {output_filename}\nLog:\n{log}",
            Image(data=img_data, format="png")]


@mcp.tool(annotations=WRITES_OUTPUT)
def export_stl(scad_filename: str, output_filename: str = "model.stl") -> str:
    """
    Exports the OpenSCAD model to an STL file and VALIDATES the geometry.
    Reports bounding box (dimensions in mm), volume, triangle count, manifold status
    and any warnings - compare these with the design requirements.

    Args:
        scad_filename: The .scad file to export.
        output_filename: The output STL filename (default: model.stl).

    Returns:
        A geometry report, or raises an error with the OpenSCAD log.
    """
    scad_filename, output_filename = resolve_io_paths(scad_filename, output_filename, ".stl")

    with tempfile.TemporaryDirectory() as temp_dir:
        summary_file = os.path.join(temp_dir, "summary.json")
        args = ["-o", output_filename]
        if runner.supports_summary:
            args += ["--summary", "all", "--summary-file", summary_file]
        args.append(scad_filename)

        success, stdout, stderr = runner.run(cwd=WORKSPACE, args=args)
        if not success:
            raise ToolError(error_report("Failed to export STL.", stderr))

        summary = {}
        if os.path.exists(summary_file):
            try:
                with open(summary_file, encoding="utf-8") as f:
                    summary = json.load(f)
            except Exception as e:
                logger.warning(f"Could not read render summary: {e}")

    report = [f"Successfully exported {output_filename}"]

    try:
        stats = read_stl_stats(output_filename)
    except Exception as e:
        stats = {}
        report.append(f"Warning: could not analyze STL: {e}")

    geometry = summary.get("geometry", {})
    bbox = geometry.get("bounding_box", {})
    size = bbox.get("size") or stats.get("size")
    if size:
        report.append(f"Dimensions (X x Y x Z): {fmt_vec(size)} mm")
        report.append(f"Bounding box: min ({fmt_vec(bbox.get('min') or stats['min'])}) "
                      f"max ({fmt_vec(bbox.get('max') or stats['max'])})")
    else:
        report.append("WARNING: the exported geometry is empty.")
    if "volume" in stats:
        report.append(f"Volume: {stats['volume']:.2f} mm^3 ({stats['volume'] / 1000:.2f} cm^3)")
    if "triangles" in stats:
        report.append(f"Triangles: {stats['triangles']}")

    if "simple" in geometry:
        report.append("Manifold: yes" if geometry["simple"] else
                      "Manifold: NO - the mesh is not a valid closed solid; fix overlapping/zero-thickness geometry.")
    elif "2-manifold" in stderr:
        report.append("Manifold: NO - OpenSCAD reports the object may not be a valid 2-manifold.")
    else:
        report.append("Manifold: no problems reported by OpenSCAD.")

    render_time = summary.get("time", {}).get("time")
    if render_time:
        report.append(f"Render time: {render_time}")

    report.append(f"Log:\n{summarize_log(stderr)}")
    return "\n".join(report)


@mcp.tool(annotations=READ_ONLY)
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
            for item in sorted(os.listdir(path)):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    result += f"  [DIR]  {item}\n"
                elif item.endswith(".scad"):
                    result += f"  [FILE] {item}\n"
        except Exception as e:
            result += f"  Error reading directory: {e}\n"

    return result


def main():
    mcp.run()


if __name__ == "__main__":
    main()
