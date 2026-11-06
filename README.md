<div align="center">
  <h1>NiriMod</h1>
  
  **GTK4/libadwaita configuration editor for the [niri](https://github.com/niri-wm/niri) Wayland compositor.**

  [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
  [![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python&logoColor=white)](https://python.org)
  [![GTK4](https://img.shields.io/badge/GTK-4%20%2B%20libadwaita-4A90D9?logo=gnome&logoColor=white)](https://gtk.org)
  [![Wayland](https://img.shields.io/badge/Wayland-native-orange)](https://wayland.freedesktop.org)
</div>

<br>

![NiriMod Interface](media/1.png)

Niri uses KDL for configuration. Hand-editing works well for basic keys, but managing multi-monitor layouts, easing curves, and complex window rules directly in text is error-prone. NiriMod provides a native graphical interface for these subsystems while preserving existing comments, file structures, and manual edits.

## Features

- Drag-and-drop monitor layout arrangement, resolution, refresh rate, variable refresh rate (VRR), and fractional scaling.
- Interactive keyboard heat map and searchable shortcut table with duplicate conflict detection.
- Column widths, gaps, struts, and per-window matching criteria.
- Mouse, touchpad, and trackpoint settings (acceleration profiles, scroll methods, button bindings, left-handed mode).
- Cubic-bezier and spring curve editor with live previews across all compositor transitions.
- Built-in KDL editor with syntax validation and undo/redo history.

![Keybinding Management](media/2.png)

## Configuration Safety

- Writes run through `niri validate` before committing to disk. Invalid configurations are blocked and surfaced with compiler diagnostics.
- Config updates are staged in temporary files before replacing targets, preventing half-written files.
- Custom comments, whitespace, and formatting are preserved across round-trips.
- Snapshot and restore alternate configurations on demand.

### Multi-File and Desktop Shell Setups

![Multi-File Configurations](media/multiple_configs.png)

Niri configurations frequently use `include` directives to separate concerns across files (such as inputs, outputs, or third-party shells like Dank Material Shell and Noctalia).

NiriMod resolves `include` paths recursively up to five levels deep. When modifying a setting from the interface, NiriMod maps the node back to its originating file and writes only to that file. Unrecognized directives and custom shell blocks remain untouched.

## NixOS and Home Manager

When managing Niri via Home Manager, point NiriMod directly to your source files by using out-of-store symlinks:

```nix
xdg.configFile."niri/config.kdl".source = config.lib.file.mkOutOfStoreSymlink "${config.home.homeDirectory}/path/to/your/dotfiles/niri/config.kdl";
```

NiriMod resolves symlinks to their underlying target before writing, allowing GUI adjustments to commit directly into your dotfiles repository.

## Usage

```bash
nirimod                          # open on the first page
nirimod --page outputs           # open directly on a sidebar page
nirimod -p bindings -c ~/dotfiles/niri/config.kdl
nirimod --help                   # list options and valid page IDs
```

Valid `--page` / `-p` IDs, matching the sidebar order: `input`, `bindings`, `outputs`, `appearance`, `animations`, `layout`, `workspaces`, `window_rules`, `startup`, `environment`, `gestures`, `raw_config`. An unknown ID exits with status 2 before the config is read or a window is opened.

## Installation

### Arch Linux (AUR)

```bash
yay -S nirimod-git
```

### Installation Script

```bash
curl -sSL https://raw.githubusercontent.com/srinivasr/nirimod/main/install.sh | bash
```

Use `--install` for non-interactive installs, `--uninstall` to remove, or `--skip-deps` to bypass package manager checks.

## Dependencies

- Python 3.12+ and `uv`
- GTK4, libadwaita, PyGObject, and Pycairo
- `niri` compositor binary

**Gentoo** (with [GURU overlay](https://wiki.gentoo.org/wiki/Project:GURU)):

```bash
emerge dev-vcs/git net-misc/curl dev-lang/python gui-libs/gtk gui-libs/libadwaita dev-python/pygobject dev-python/pycairo x11-libs/libxkbcommon x11-misc/xkeyboard-config
curl -sSL https://raw.githubusercontent.com/srinivasr/nirimod/main/install.sh | bash -s -- --install --skip-deps
```

## Contributing

Review [CONTRIBUTING.md](CONTRIBUTING.md) for local development setup and style expectations.

<a href="https://www.star-history.com/?repos=srinivasr%2Fnirimod&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=srinivasr/nirimod&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=srinivasr/nirimod&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=srinivasr/nirimod&type=date&legend=top-left" />
 </picture>
</a>

*NiriMod is an independent project and is not affiliated with the official niri team.*
