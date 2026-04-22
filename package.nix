{
  lib,
  python3Packages,
  wrapGAppsHook4,
  gtk4,
  libadwaita,
  gdk-pixbuf,
  gobject-introspection,
  hicolor-icon-theme,
  desktop-file-utils,
}:

python3Packages.buildPythonApplication (finalAttrs: {
  pname = "nirimod";
  version = "0.1.0";

  pyproject = true;

  src = lib.cleanSource ./.;
  # For nixpkgs: replace with fetchFromGitHub pointing to a release tag:
  # src = fetchFromGitHub {
  #   owner = "srinivasr";
  #   repo = "nirimod";
  #   tag = "v${finalAttrs.version}";
  #   hash = "sha256-...";
  # };

  nativeBuildInputs = [
    wrapGAppsHook4
    gobject-introspection
    desktop-file-utils
  ];

  build-system = with python3Packages; [
    hatchling
  ];

  buildInputs = [
    gtk4
    libadwaita
    gdk-pixbuf
    hicolor-icon-theme
  ];

  dependencies = with python3Packages; [
    pygobject3
  ];

  postInstall = ''
    install -Dm644 data/nirimod.svg $out/share/icons/hicolor/scalable/apps/nirimod.svg

    mkdir -p $out/share/applications
    cat > $out/share/applications/io.github.nirimod.desktop << EOF
    [Desktop Entry]
    Version=1.0
    Name=NiriMod
    GenericName=Compositor Settings
    Comment=GUI Configuration Manager for the Niri Wayland Compositor
    Exec=nirimod
    Icon=nirimod
    Terminal=false
    Type=Application
    Categories=Utility;Settings;DesktopSettings;
    Keywords=compositor;windowmanager;wayland;niri;settings;config;
    StartupNotify=true
    StartupWMClass=nirimod
    EOF
  '';

  meta = {
    description = "A polished GTK4/libadwaita GUI configurator for the niri Wayland compositor";
    homepage = "https://github.com/srinivasr/nirimod";
    license = lib.licenses.mit;
    maintainers = [ ];
    mainProgram = "nirimod";
    platforms = lib.platforms.linux;
  };
})
