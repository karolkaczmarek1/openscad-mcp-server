# OpenSCAD MCP Server
## OpenSCAD Agent for LLMs

A Model Context Protocol (MCP) server that provides tools for interacting with OpenSCAD. This allows LLMs (like Gemini) to write SCAD code, render previews, export 3D models, and securely inspect installed libraries.

## Features

- **Write SCAD Files**: `write_scad_script` allows creating/editing scripts in the current directory.
- **Multimodal Previews**:
    - `render_preview`: Returns a rendered PNG image of the model. Supports optional `rotation_x`, `rotation_y`, `rotation_z` and `distance` parameters.
    - **Auto-Centering & Auto-Zoom**: The tool automatically analyzes the model geometry (via temporary STL export) to center the camera and calculate an optimal distance, ensuring the object is always visible.
    - `render_views_matrix`: Generates a composite image containing **14 standard views** (6 orthogonal: Top, Bottom, Front, Back, Left, Right; and 8 isometric from every corner), clearly labeled and framed. This provides a comprehensive visual summary of the object.
- **Export STL**: `export_stl` for geometry validation (manifold checks) and export.
- **Library Inspection**: 
    - `list_libraries`: Lists all available library roots.
    - `list_scad_library_directory` and `read_scad_library_file` allow the LLM to learn from installed libraries (e.g. `BOSL2/threading.scad`).
    - **Smart Path Resolution**: Supports searching by relative paths (e.g., just `BOSL2`).
    - Access is strictly limited to configured library paths.
- **Configuration**: Customizable via `.env` file.

## Prerequisites

- **Python 3.10+**
- **OpenSCAD**: Must be installed.
    - **Windows**: Checks `C:\Program Files\OpenSCAD\openscad.exe` by default.
    - **Linux**: Checks `PATH`. Requires `xvfb` (e.g., `apt install xvfb`) for headless rendering support, which is automatically handled.
- **Python Dependencies**:
    - `mcp`
    - `python-dotenv`
    - `Pillow` (for image processing)
    - `numpy` & `numpy-stl` (for geometry analysis and auto-centering)

## Installation

1. Clone this repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. (Optional) Configure paths in `.env`:
   - Copy `.env.example` to `.env`.
   - Edit `.env` to set your `OPENSCAD_PATH` or `OPENSCAD_LIBRARIES_PATH` if they differ from defaults.

## Usage

### Running the Server

Run the server using Python:

```bash
python src/server.py
```

### Integration with Gemini CLI

To use this with the Gemini CLI (or any MCP client), configure the client to launch this server.

Example configuration:

```json
{
  "mcpServers": {
    "openscad": {
      "command": "python",
      "args": ["<path_to_repo>/src/server.py"]
    }
  }
}
```

### Windows Notes

- If OpenSCAD is not detected, set `OPENSCAD_PATH` in `.env`.
- To allow the LLM to read your installed libraries (e.g., in `Documents/OpenSCAD/libraries`), ensure that path is either standard or added to `OPENSCAD_LIBRARIES_PATH` in `.env`.

### Troubleshooting for LLMs

If the model tries to use generic tools like `write_file` or `edit_file`:
- The server is designed with aggressive prompts in tool descriptions to force the use of `write_scad_script`.
- Ensure your client is actually using the tools provided by this server.

## Acknowledgements

- **LLMto3D**: This work is inspired by the research paper *[LLMto3D - Generation of parametric 3D printable objects using large language models](https://www.researchgate.net/publication/392939330_LLMto3D_-_Generation_of_parametric_3D_printable_objects_using_large_language_models)* by Bat El Hizmi et al.
- **[OpenSCAD](https://openscad.org/)**: The programmers' solid 3D CAD modeller.
- **[BOSL2](https://github.com/BelfrySCAD/BOSL2)**: The Belfry OpenScad Library v2, an essential library for parametric design.
- **[Gemini CLI](https://github.com/google-gemini/gemini-cli)**: An open-source AI agent that brings the power of Gemini directly into your terminal.
