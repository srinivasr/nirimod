"""CSS theme definitions for NiriMod."""

CSS = """
/* --- Nirimod -- Purple Theme --- */

/* --- Accent --- */
@define-color nm_accent         #9b6dff;
@define-color nm_accent_mid     #7c3aed;
@define-color nm_accent_dim     rgba(155, 109, 255, 0.13);
@define-color nm_accent_hover   rgba(155, 109, 255, 0.20);
@define-color nm_accent_border  rgba(155, 109, 255, 0.28);

/* --- Surfaces --- */
@define-color window_bg_color    #111114;
@define-color window_fg_color    #e8e8ed;
@define-color view_bg_color      #18181c;
@define-color view_fg_color      #e8e8ed;
@define-color headerbar_bg_color #111114;
@define-color card_bg_color      #1e1e24;
@define-color card_fg_color      #e8e8ed;
@define-color popover_bg_color   #1e1e24;
@define-color popover_fg_color   #e8e8ed;
@define-color dialog_bg_color    #18181c;
@define-color dialog_fg_color    #e8e8ed;

/* --- Borders --- */
@define-color nm_border         rgba(255, 255, 255, 0.07);
@define-color nm_border_strong  rgba(255, 255, 255, 0.12);

/* --- Window --- */
window {
    background-color: @window_bg_color;
    color: @window_fg_color;
}

/* --- Header Bars --- */
headerbar,
.nm-sidebar-bg {
    background-color: @window_bg_color;
    background-image: none;
    box-shadow: none;
    border-bottom: 1px solid @nm_border;
    color: @window_fg_color;
}

/* --- Sidebar --- */
.navigation-sidebar {
    background-color: transparent;
    border-right: 1px solid @nm_border;
}

.nm-sidebar-listbox {
    background: transparent;
    border: none;
}

.nm-sidebar-listbox row {
    border-radius: 7px;
    margin: 1px 4px;
    padding: 5px 8px;
    transition: background 130ms ease;
    color: @window_fg_color;
}

.nm-sidebar-listbox row:hover {
    background: rgba(255, 255, 255, 0.045);
}

.nm-sidebar-listbox row:selected {
    background: @nm_accent_dim;
    color: @nm_accent;
}

.nm-sidebar-listbox row:selected image,
.nm-sidebar-listbox row:selected label {
    color: @nm_accent;
}

/* --- Section Labels --- */
.nm-sidebar-section-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: rgba(255, 255, 255, 0.30);
}

/* --- Search --- */
.nm-search-entry {
    color: @window_fg_color;
    background-color: @card_bg_color;
    border: 1px solid @nm_border;
    border-radius: 8px;
}

.nm-search-entry > box { color: @window_fg_color; }
.nm-search-entry text  { color: @window_fg_color; }

.nm-search-results {
    background: transparent;
    border: none;
}

.nm-search-results row {
    padding: 8px 12px;
    border-radius: 7px;
    margin: 2px 4px;
    transition: background 110ms ease;
}

.nm-search-results row:hover {
    background: @nm_accent_dim;
}

/* --- Content Cards --- */
.nm-card,
preferencesgroup > box {
    background-color: @card_bg_color;
    border: 1px solid @nm_border;
    border-radius: 12px;
    padding: 4px;
}

row {
    border-radius: 7px;
    transition: background 110ms ease;
}

row:hover {
    background: rgba(255, 255, 255, 0.025);
}

/* --- Unsaved Changes Bar --- */
.nm-dirty-bar {
    background: rgba(155, 109, 255, 0.07);
    border-top: 1px solid rgba(155, 109, 255, 0.18);
    padding: 8px 20px;
}

/* --- Niri Banner --- */
.nm-niri-banner {
    background: rgba(180, 110, 0, 0.10);
    color: rgba(240, 180, 50, 0.90);
    padding: 6px 16px;
    font-size: 13px;
    border-bottom: 1px solid rgba(180, 110, 0, 0.18);
}

/* --- Badges & Status --- */
.nm-badge {
    background: @nm_accent;
    color: #111114;
    border-radius: 12px;
    font-size: 10px;
    font-weight: 700;
    padding: 1px 7px;
    min-width: 16px;
}

/* --- Inline Tag Chips --- */
.tag {
    background: rgba(255, 255, 255, 0.06);
    color: @window_fg_color;
    border: 1px solid @nm_border_strong;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 600;
    padding: 1px 7px;
}

.tag.accent {
    background: @nm_accent_dim;
    color: @nm_accent;
    border-color: @nm_accent_border;
}

/* --- Buttons --- */
button.suggested-action {
    border-radius: 9px;
    font-weight: 600;
    background: @nm_accent_mid;
}

/* --- Toasts --- */
toast {
    background-color: @card_bg_color;
    color: @card_fg_color;
    border: 1px solid @nm_accent_border;
    border-radius: 20px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45);
    margin-bottom: 20px;
}

toast label { font-weight: 500; }

/* --- Code Editor --- */
.code-editor {
    background-color: #0d0d10;
    color: #e8e8ed;
    border: 1px solid @nm_border;
    border-radius: 10px;
}

/* --- Keyboard Visualizer --- */
.nm-kb-action-panel {
    background-color: @card_bg_color;
    border: 1px solid @nm_border;
    border-radius: 12px;
    padding: 4px;
}

.nm-kb-key-id-label {
    font-size: 20px;
    font-weight: 700;
    color: @window_fg_color;
}

.nm-kb-swatch {
    min-width: 12px;
    min-height: 12px;
    border-radius: 3px;
}

/* --- Keycaps --- */
.nm-keycap-main, .nm-keycap-mod {
    background-color: @nm_accent_dim;
    border: 1px solid @nm_accent_border;
    border-radius: 5px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 600;
    color: @nm_accent;
    box-shadow: 0 1px 0 rgba(0, 0, 0, 0.3);
}

.nm-keycap-main {
    background-color: rgba(155, 109, 255, 0.22);
    border-color: rgba(155, 109, 255, 0.45);
    color: rgba(210, 190, 255, 1.0);
    font-weight: 700;
}

.nm-keycap-mod { opacity: 0.80; }

.nm-keycap-purple {
    background: @nm_accent_dim;
    color: @nm_accent;
    border: 1px solid @nm_accent_border;
    border-radius: 5px;
    padding: 2px 8px;
    font-weight: 600;
    font-size: 12px;
}

/* --- Pulse Highlight (search) --- */
@keyframes pulse-highlight {
    0%   { background-color: transparent; }
    18%  { background-color: rgba(155, 109, 255, 0.28); }
    100% { background-color: transparent; }
}

.nm-pulse-highlight {
    animation-name: pulse-highlight;
    animation-duration: 1.4s;
    animation-timing-function: ease-out;
}

/* --- Animations Page --- */
.nm-anim-banner {
    background: @nm_accent_dim;
    border: 1px solid @nm_accent_border;
    border-radius: 10px;
    padding: 10px 16px;
    color: @nm_accent;
}

.nm-anim-banner button {
    background: rgba(155, 109, 255, 0.15);
    border: 1px solid @nm_accent_border;
    color: @nm_accent;
    font-weight: 600;
    border-radius: 8px;
    padding: 4px 14px;
}

.nm-anim-banner button:hover {
    background: @nm_accent_hover;
}

.nm-preset-icon {
    font-size: 18px;
    min-width: 28px;
}

/* --- Bindings Page --- */
.nm-binding-card {
    background: rgba(30, 30, 35, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 16px;
    transition: all 200ms ease;
}
.nm-binding-card:hover {
    background: rgba(45, 45, 50, 0.8);
    border-color: rgba(147, 51, 234, 0.4);
}
.nm-binding-actions-label {
    color: rgba(255, 255, 255, 0.4);
    font-weight: 800;
    letter-spacing: 0.05em;
    font-size: 0.7rem;
}
.nm-binding-action-name {
    color: white;
    font-weight: 600;
    font-size: 1.0rem;
}
.nm-keycap-purple {
    background: #581c87;
    color: white;
    border-radius: 6px;
    padding: 2px 8px;
    font-weight: bold;
    font-size: 0.8rem;
}
""".encode("utf-8")
