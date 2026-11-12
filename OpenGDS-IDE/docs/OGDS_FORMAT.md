# OpenGDS workspace descriptor (`.ogds`)

## Purpose

A `.ogds` file is a JSON workspace descriptor owned by **OpenGDS - IDE**. It stores IDE settings that belong to a folder: its display name, root folder, optional Godot project path, OpenGDS core path, Godot executable, compile output/settings and debugger/editor preferences.

It lets OpenGDS open a plain directory even if the directory is not a Godot project. It is not a Godot engine project file and does not replace `project.godot`. The Godot engine still requires `project.godot` for normal project/editor/run/import/export workflows.

The default filename created by the IDE is `file.ogds`, but any filename ending in `.ogds` is accepted.

## Minimal valid example

```json
{
  "format": "opengds-project",
  "version": 2,
  "name": "My GDScript Workspace",
  "root": ".",
  "godot_project": "",
  "backend": "",
  "godot_executable": "",
  "compile": {
    "compressed": true,
    "tab_size": 4,
    "overwrite": false,
    "continue_on_error": true,
    "output_directory": ".opengds/compiled",
    "validate_with_godot": true
  },
  "debug": {
    "headless": false,
    "interrupt": false,
    "include_frame_callbacks": false,
    "scene": "",
    "source_path": "",
    "extra_args": [],
    "dry_run": false,
    "context": 4,
    "max_tokens": 200,
    "show_tokens": false
  },
  "editor": {
    "tab_width": 4,
    "encoding": "utf-8",
    "autosave": true
  }
}
```

## Fields

| Field | Type | Meaning |
|---|---|---|
| `format` | string | Must be `opengds-project`. |
| `version` | integer | Descriptor schema version. Current version is `2`. |
| `name` | string | Display name in the explorer/project UI. |
| `root` | string | Workspace folder. Relative paths resolve from the `.ogds` file's directory; `.` means the descriptor's own directory. |
| `godot_project` | string | Optional path relative to `root`, usually `project.godot`; empty for a plain workspace. |
| `backend` | string | Optional path to `OpenGDS.py`; empty means use the copy shipped with the IDE. |
| `godot_executable` | string | Optional Godot executable path; empty means auto-detect or ask. |
| `compile` | object | GDSC compression, tab-size, overwrite/error policy, output directory and optional validation preference. |
| `debug` | object | OpenGDS runtime-debug, Godot scene/source mapping and static debugger settings. |
| `editor` | object | Workspace/editor defaults reserved for IDE use. |

Unknown extra JSON fields are retained when loaded/saved. Missing known fields are supplied from current defaults. A descriptor with a version newer than the installed IDE is rejected rather than silently rewritten.

## Paths

- Prefer relative paths for portable workspaces.
- `root` is resolved relative to the descriptor location.
- `compile.output_directory` is resolved relative to the workspace root unless it is an absolute path. An absolute output path is useful when compiled artifacts are stored outside the project.
- `backend` and `godot_executable` can be absolute executable/file paths.
- `debug.scene` is a Godot resource path such as `res://scenes/main.tscn`.
- `debug.source_path` is normally blank. Set it to `res://path/to/script.gd` only when a compiled `.gdc` lives outside the project or needs an explicit source mapping.

## How to create/open it

1. Open any folder in **File → Open Project / Folder**. No descriptor is required.
2. Use **File → Create / Save OpenGDS Workspace (.ogds)** to save a descriptor, normally as `file.ogds` inside the folder.
3. Open the `.ogds` file later, or open its containing directory. The IDE will find `file.ogds` automatically in a directory.
4. A Godot project can be opened by selecting its `project.godot` file or its containing directory. If desired, create a `.ogds` beside it to persist OpenGDS-specific preferences.

## Relationship to `project.godot`

These files have different owners and purposes:

- `project.godot` is read by Godot Engine. It identifies the engine project and holds engine project configuration.
- `.ogds` is read by OpenGDS - IDE. It identifies an IDE workspace and stores OpenGDS-specific settings.

For a folder without `project.godot`, `.ogds` is enough to save its OpenGDS workspace and use OpenGDS `comp`, `dcmp`, `info`, `dbg` static mode, `audit`, `disasm`, `consts`, `hexdump` and `diff`. It is not enough to launch the Godot Editor, run/import/export a Godot project, use project-bound Godot LSP/DAP, or launch OpenGDS `dbg --godot/--interrupt`; those require a real Godot project.

The IDE does not convert an `.ogds` descriptor into a valid `project.godot` automatically, because that would fabricate engine configuration (main scene, feature tags, autoloads, input map, render settings and other project state). Create/import the engine project in Godot when engine execution is required.
