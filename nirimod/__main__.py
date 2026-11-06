"""NiriMod application entry point."""

from __future__ import annotations

import sys

try:
    import gi
except ModuleNotFoundError:
    print(
        "\033[31mError: Could not find Python GObject bindings (PyGObject).\033[0m",
        file=sys.stderr,
    )
    print(
        "This application requires system-level libraries to interface with GTK4.",
        file=sys.stderr,
    )
    print(
        "\nPlease install the required packages for your distribution:", file=sys.stderr
    )
    print(
        "  \033[1mArch:\033[0m   sudo pacman -S python-gobject gtk4 libadwaita",
        file=sys.stderr,
    )
    print(
        "  \033[1mFedora:\033[0m sudo dnf install python3-gobject gtk4 libadwaita",
        file=sys.stderr,
    )
    print(
        "  \033[1mUbuntu:\033[0m sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1",
        file=sys.stderr,
    )
    print(
        "\nAfter installing, re-run the installer or re-create your virtual environment.",
        file=sys.stderr,
    )
    sys.exit(1)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib

from nirimod.window import SIDEBAR_PAGES, NiriModWindow

# Valid values for --page: the sidebar page IDs, in sidebar order.
PAGE_IDS = tuple(page_id for page_id, _icon, _label in SIDEBAR_PAGES)


class NiriModApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.nirimod",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        if not GLib.get_application_name():
            GLib.set_application_name("NiriMod")
        GLib.set_prgname("nirimod")

        # Prefer dark theme globally via libadwaita
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        self._cli_config_path: str | None = None
        self._cli_page: str | None = None
        self.add_main_option(
            "config",
            ord("c"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            "Path to Niri configuration file",
            "PATH",
        )
        self.add_main_option(
            "version",
            ord("v"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Show application version",
            None,
        )
        self.add_main_option(
            "page",
            ord("p"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            "Open on this page (" + ", ".join(PAGE_IDS) + ")",
            "PAGE",
        )

    def do_handle_local_options(self, options: GLib.VariantDict) -> int:
        if options.contains("version"):
            print("NiriMod 0.5.0")
            return 0
        if options.contains("page"):
            page = options.lookup_value("page").get_string()
            if page not in PAGE_IDS:
                # Reject before the config is read or any window is created.
                print(
                    f"nirimod: unknown page {page!r}; valid pages: "
                    + ", ".join(PAGE_IDS),
                    file=sys.stderr,
                )
                return 2
            self._cli_page = page
        if options.contains("config"):
            self._cli_config_path = options.lookup_value("config").get_string()
        return -1

    def do_activate(self):
        win = self.get_active_window()
        if win is None:
            from nirimod import app_settings
            from nirimod.kdl_parser import set_paths

            cfg_path = self._cli_config_path or app_settings.get("config_path", "")
            set_paths(
                config_path=cfg_path,
                backup_path=app_settings.get("backup_path", ""),
            )
            win = NiriModWindow(application=self, initial_page=self._cli_page)
        elif self._cli_page is not None:
            win.select_page(self._cli_page)
        win.present()


def main():
    app = NiriModApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
