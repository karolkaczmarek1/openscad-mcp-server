# OpenSCAD MCP Server
## OpenSCAD Agent for LLMs

A Model Context Protocol (MCP) server that provides tools for interacting with OpenSCAD. This allows LLM agents (Claude Code, Antigravity, Gemini CLI, ...) to write SCAD code, render previews, export 3D models, and securely inspect installed libraries.

## Features

- **Write SCAD Files**: `write_scad_script` allows creating/editing scripts in the current directory.
- **Multimodal Previews**:
    - `render_preview`: Returns a rendered PNG image of the model. Supports optional `rotation_x`, `rotation_y`, `rotation_z` and `distance` parameters.
    - **Auto-Centering & Auto-Zoom**: Uses OpenSCAD's `--autocenter --viewall`, so the object is always visible. With an explicit `distance`, the center is computed from the geometry.
    - `render_views_matrix`: Generates a composite image containing **14 standard views** (6 orthogonal: Top, Bottom, Front, Back, Left, Right; and 8 isometric from every corner), clearly labeled and framed. This provides a comprehensive visual summary of the object.
    - Each view is auto-centered and cropped so the object fills its frame; views render in parallel.
- **Export STL**: `export_stl` exports and validates the model, reporting dimensions (bounding box in mm), volume, triangle count, manifold status, and warnings.
- **Concise logs**: only `ECHO`/`WARNING`/`ERROR` lines from OpenSCAD are returned; failures are reported as MCP errors (`isError`).
- **Library Inspection**: 
    - `list_libraries`: Lists all available library roots.
    - `list_scad_library_directory` and `read_scad_library_file` allow the LLM to learn from installed libraries (e.g. `BOSL2/threading.scad`).
    - **Smart Path Resolution**: Supports searching by relative paths (e.g., just `BOSL2`).
    - Access is strictly limited to configured library paths.
- **Configuration**: Customizable via `.env` file.

## Prerequisites

- **Python 3.10+** and [uv](https://docs.astral.sh/uv/) (recommended) or pip
- **OpenSCAD**: Must be installed. A recent [development snapshot](https://openscad.org/downloads.html#snapshots) is strongly recommended
  (Manifold backend: much faster renders, and `export_stl` gets manifold status from OpenSCAD's render summary). 2021.01 works too.
- **Libraries (optional)**: e.g. [BOSL2](https://github.com/BelfrySCAD/BOSL2) cloned into `Documents/OpenSCAD/libraries`.
    - **Windows**: Checks `C:\Program Files\OpenSCAD (Nightly)\openscad.exe` and `C:\Program Files\OpenSCAD\openscad.exe` by default.
    - **Linux**: Checks `PATH`. Requires `xvfb` (e.g., `apt install xvfb`) for headless rendering support, which is automatically handled.
    - **macOS**: Checks `/Applications/OpenSCAD.app`.

## Installation

```bash
git clone https://github.com/karolkaczmarek1/openscad-mcp-server.git
cd openscad-mcp-server
uv sync            # or: pip install -r requirements.txt
```

(Optional) Copy `.env.example` to `.env` and adjust it:

| Variable | Purpose | Default |
|---|---|---|
| `OPENSCAD_PATH` | OpenSCAD executable | auto-detected |
| `OPENSCAD_LIBRARIES_PATH` | Extra library dirs (`;`-separated on Windows) | user + bundled library dirs |
| `OPENSCAD_WORKSPACE` | Where `.scad`, `.png`, `.stl` files are read/written | the client's working directory |
| `OPENSCAD_TIMEOUT` | Max seconds per OpenSCAD call | `300` |

`.env` is loaded from the repository root, regardless of where the client starts the server.

## Usage

The server speaks MCP over stdio. Files are created in the directory the MCP client is started in
(your project), unless `OPENSCAD_WORKSPACE` is set. All file access is confined to that workspace
and to the OpenSCAD library directories.

### Claude Code

```bash
claude mcp add -s user openscad -- uv run --project <path_to_repo> python <path_to_repo>/src/server.py
```

Then start `claude` in any project directory and ask it to design something, e.g.
*"Design a parametric PCB enclosure 50x30mm with screw posts and check it from all sides."*

### Antigravity CLI (agy)

```bash
agy mcp add openscad -- uv run --project <path_to_repo> python <path_to_repo>/src/server.py
```

### Other MCP clients (Gemini CLI, etc.)

```json
{
  "mcpServers": {
    "openscad": {
      "command": "uv",
      "args": ["run", "--project", "<path_to_repo>", "python", "<path_to_repo>/src/server.py"]
    }
  }
}
```

The server sends short workflow instructions to the client during initialization.

### Agent skill (recommended)

`skills/openscad-design/SKILL.md` is a detailed design workflow (LLMto3D method, OpenSCAD and BOSL2
best practices, 3D-printing rules). It uses the standard `SKILL.md` format, so it works in both
Claude Code and Antigravity. Copy it to the client's skills directory:

```bash
# Claude Code
cp -r skills/openscad-design ~/.claude/skills/
# Antigravity
cp -r skills/openscad-design ~/.gemini/config/skills/
```

### Windows Notes

- If OpenSCAD is not detected, set `OPENSCAD_PATH` in `.env`.
- To allow the LLM to read your installed libraries (e.g., in `Documents/OpenSCAD/libraries`), ensure that path is either standard or added to `OPENSCAD_LIBRARIES_PATH` in `.env`.

### Troubleshooting for LLMs

If the model tries to use generic tools like `write_file` or `edit_file`:
- Scripts must be in the server workspace (the client's working directory, or `OPENSCAD_WORKSPACE`). `write_scad_script` returns the absolute path, so the agent can also edit that file with its own tools.
- Ensure your client is actually using the tools provided by this server (e.g. `claude mcp list`, `agy mcp list`).

## Acknowledgements

- **LLMto3D**: This work is inspired by the research paper *[LLMto3D - Generation of parametric 3D printable objects using large language models](https://www.researchgate.net/publication/392939330_LLMto3D_-_Generation_of_parametric_3D_printable_objects_using_large_language_models)* by Bat El Hizmi et al.
- **[OpenSCAD](https://openscad.org/)**: The programmers' solid 3D CAD modeller.
- **[BOSL2](https://github.com/BelfrySCAD/BOSL2)**: The Belfry OpenScad Library v2, an essential library for parametric design.
- **[Claude Code](https://claude.com/claude-code)**, **[Antigravity](https://antigravity.google/)** and **[Gemini CLI](https://github.com/google-gemini/gemini-cli)**: AI agents this server was built and tested with.
