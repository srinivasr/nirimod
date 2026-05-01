"""Helpers for Niri global window effect rules."""

from __future__ import annotations

from nirimod.kdl_parser import KdlNode, remove_child, set_child_arg, set_node_flag

_RULE_CHILD_ORDER = [
    "match",
    "exclude",
    "geometry-corner-radius",
    "clip-to-geometry",
    "draw-border-with-background",
    "opacity",
    "background-effect",
]

_EFFECT_CHILD_ORDER = ["blur", "xray"]
_BLUR_CONFIG_CHILD_ORDER = ["off", "passes", "offset", "noise", "saturation"]


def _is_global_window_rule(node: KdlNode) -> bool:
    return (
        node.name == "window-rule"
        and not node.get_children("match")
        and not node.get_children("exclude")
    )


def _is_focused_window_rule(node: KdlNode) -> bool:
    if node.name != "window-rule" or node.get_children("exclude"):
        return False
    matches = node.get_children("match")
    if len(matches) != 1:
        return False
    match = matches[0]
    return match.args == [] and match.props == {"is-focused": True}


def _global_window_rule(nodes: list[KdlNode]) -> KdlNode | None:
    return next((n for n in reversed(nodes) if _is_global_window_rule(n)), None)


def _focused_window_rule(nodes: list[KdlNode]) -> KdlNode | None:
    return next((n for n in reversed(nodes) if _is_focused_window_rule(n)), None)


def _blur_config_node(nodes: list[KdlNode]) -> KdlNode | None:
    return next((n for n in reversed(nodes) if n.name == "blur"), None)


def _ensure_blur_config_node(nodes: list[KdlNode]) -> KdlNode:
    blur = _blur_config_node(nodes)
    if blur is None:
        blur = KdlNode("blur")
        blur.leading_trivia = "\n"
        nodes.append(blur)
    return blur


def _ensure_global_window_rule(nodes: list[KdlNode]) -> KdlNode:
    rule = _global_window_rule(nodes)
    if rule is None:
        rule = KdlNode("window-rule")
        rule.leading_trivia = "\n"
        nodes.append(rule)
    return rule


def _ensure_focused_window_rule(nodes: list[KdlNode]) -> KdlNode:
    rule = _focused_window_rule(nodes)
    if rule is None:
        rule = KdlNode("window-rule")
        rule.leading_trivia = "\n"
        rule.children.append(KdlNode("match", props={"is-focused": True}))
        nodes.append(rule)
    return rule


def _background_effect(rule: KdlNode) -> KdlNode | None:
    return rule.get_child("background-effect")


def _ensure_background_effect(rule: KdlNode) -> KdlNode:
    effect = _background_effect(rule)
    if effect is None:
        effect = KdlNode("background-effect")
        effect.leading_trivia = "\n"
        rule.children.append(effect)
    return effect


def _remove_rule_if_empty(nodes: list[KdlNode], rule: KdlNode) -> None:
    if not rule.args and not rule.props and not rule.children and rule in nodes:
        nodes.remove(rule)


def _remove_background_effect_if_empty(rule: KdlNode) -> None:
    effect = _background_effect(rule)
    if effect and not effect.args and not effect.props and not effect.children:
        remove_child(rule, "background-effect")


def _compact_generated_spacing(node: KdlNode) -> None:
    if not node.trailing_trivia or node.trailing_trivia.isspace():
        node.trailing_trivia = "\n"
    for child in node.children:
        if not child.leading_trivia or child.leading_trivia.isspace():
            child.leading_trivia = ""
        if not child.trailing_trivia or child.trailing_trivia.isspace():
            child.trailing_trivia = ""
        if child.name == "background-effect":
            _compact_generated_spacing(child)


def _sort_children_by_name(node: KdlNode, order: list[str]) -> None:
    order_index = {name: index for index, name in enumerate(order)}
    indexed_children = list(enumerate(node.children))
    indexed_children.sort(
        key=lambda item: (order_index.get(item[1].name, len(order)), item[0])
    )
    node.children = [child for _, child in indexed_children]


def _finalize_window_rule(rule: KdlNode) -> None:
    effect = _background_effect(rule)
    if effect is not None:
        _sort_children_by_name(effect, _EFFECT_CHILD_ORDER)
    _sort_children_by_name(rule, _RULE_CHILD_ORDER)
    _compact_generated_spacing(rule)


def _finalize_blur_config(blur: KdlNode) -> None:
    _sort_children_by_name(blur, _BLUR_CONFIG_CHILD_ORDER)
    _compact_generated_spacing(blur)


def _rule_opacity(rule: KdlNode | None) -> float:
    if rule is None:
        return 1.0
    value = rule.child_arg("opacity", 1.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def get_global_draw_border_with_background(nodes: list[KdlNode]) -> bool:
    rule = _global_window_rule(nodes)
    if rule is None:
        return True
    return rule.child_arg("draw-border-with-background", True) is not False


def set_global_draw_border_with_background(nodes: list[KdlNode], enabled: bool) -> None:
    rule = _ensure_global_window_rule(nodes)
    if enabled:
        remove_child(rule, "draw-border-with-background")
    else:
        set_child_arg(rule, "draw-border-with-background", False)
    _finalize_window_rule(rule)
    _remove_rule_if_empty(nodes, rule)


def blur_effects_enabled(nodes: list[KdlNode]) -> bool:
    blur = _blur_config_node(nodes)
    return blur is None or blur.get_child("off") is None


def set_blur_effects_enabled(nodes: list[KdlNode], enabled: bool) -> None:
    blur = _ensure_blur_config_node(nodes)
    set_node_flag(blur, "off", not enabled)
    _finalize_blur_config(blur)
    _remove_rule_if_empty(nodes, blur)
    if enabled:
        rule = _ensure_global_window_rule(nodes)
        if _rule_opacity(rule) >= 1.0:
            set_child_arg(rule, "opacity", 0.9)
        _finalize_window_rule(rule)
    else:
        set_global_window_blur(nodes, False)
        set_focused_window_blur(nodes, False)


def global_window_blur_enabled(nodes: list[KdlNode]) -> bool:
    rule = _global_window_rule(nodes)
    return _rule_blur_enabled(rule)


def focused_window_blur_enabled(nodes: list[KdlNode]) -> bool:
    rule = _focused_window_rule(nodes)
    return _rule_blur_enabled(rule)


def _rule_blur_enabled(rule: KdlNode | None) -> bool:
    if rule is None:
        return False
    effect = _background_effect(rule)
    if effect is None:
        return False
    blur = effect.get_child("blur")
    return blur is not None and (not blur.args or blur.args[0] is True)


def set_global_window_blur(nodes: list[KdlNode], enabled: bool) -> None:
    if enabled:
        rule = _ensure_global_window_rule(nodes)
        if _rule_opacity(rule) >= 1.0:
            set_child_arg(rule, "opacity", 0.9)
        effect = _ensure_background_effect(rule)
        set_child_arg(effect, "blur", True)
        _finalize_window_rule(rule)
        return

    existing_rule = _global_window_rule(nodes)
    if existing_rule is None:
        return
    existing_effect = _background_effect(existing_rule)
    if existing_effect is not None:
        remove_child(existing_effect, "blur")
        _remove_background_effect_if_empty(existing_rule)
    remove_child(existing_rule, "opacity")
    _finalize_window_rule(existing_rule)
    _remove_rule_if_empty(nodes, existing_rule)


def set_focused_window_blur(nodes: list[KdlNode], enabled: bool) -> None:
    if enabled:
        rule = _ensure_focused_window_rule(nodes)

        effect = _ensure_background_effect(rule)
        set_child_arg(effect, "blur", True)
        _finalize_window_rule(rule)
        return

    existing_rule = _focused_window_rule(nodes)
    if existing_rule is None:
        return
    existing_effect = _background_effect(existing_rule)
    if existing_effect is not None:
        remove_child(existing_effect, "blur")
        _remove_background_effect_if_empty(existing_rule)
    _finalize_window_rule(existing_rule)
    if len(existing_rule.children) == 1 and existing_rule.get_child("match"):
        nodes.remove(existing_rule)


def global_window_xray_enabled(nodes: list[KdlNode]) -> bool:
    rule = _global_window_rule(nodes)
    if rule is None:
        return True
    effect = _background_effect(rule)
    if effect is None:
        return True
    xray = effect.get_child("xray")
    return xray is None or not xray.args or xray.args[0] is True


def set_global_window_xray(nodes: list[KdlNode], enabled: bool) -> None:
    rule = _ensure_global_window_rule(nodes)
    effect = _ensure_background_effect(rule)
    set_child_arg(effect, "xray", enabled)
    _finalize_window_rule(rule)


def get_global_window_opacity(nodes: list[KdlNode]) -> float:
    return _rule_opacity(_global_window_rule(nodes))


def set_global_window_opacity(nodes: list[KdlNode], opacity: float) -> None:
    rule = _ensure_global_window_rule(nodes)
    if opacity < 1.0:
        set_child_arg(rule, "opacity", round(opacity, 2))
    else:
        remove_child(rule, "opacity")
    _finalize_window_rule(rule)
    _remove_rule_if_empty(nodes, rule)


def get_global_corner_radius(nodes: list[KdlNode]) -> int:
    rule = _global_window_rule(nodes)
    if rule is None:
        return 0
    value = rule.child_arg("geometry-corner-radius", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def set_global_corner_radius(nodes: list[KdlNode], radius: int) -> None:
    rule = _ensure_global_window_rule(nodes)
    if radius > 0:
        set_child_arg(rule, "geometry-corner-radius", radius)
        set_child_arg(rule, "clip-to-geometry", True)
    else:
        remove_child(rule, "geometry-corner-radius")
        remove_child(rule, "clip-to-geometry")
    _finalize_window_rule(rule)
    _remove_rule_if_empty(nodes, rule)
