"""
Low-level drawing primitives and keyboard/text-input handling.

Part of the Word Finder application (split from the original single-file
WordFinder.py for maintainability). Behavior is unchanged from the original --
this is a pure refactor.
"""

import unicodedata
import pygame

import wf_constants as C
import wf_state as S
from wf_constants import FONT_DEFAULT, FONT_SM, FONT_MD, PAD, special_chars
from wf_search import exist_key_for_input
# NOTE: _make_pattern_slot lives in wf_state.py (it's a plain data-shape factory
# for AppState's pattern slots, not a drawing primitive) to avoid a circular
# import between wf_ui_helpers and wf_state.
from wf_state import (
    add_exist_letter, delete_exist_item_at, toggle_letter,
    backspace_letter_slot, clear_letter_slot,
    ph_add_letter, ph_backspace, ph_clear_slot,
    _results_keyboard_rects,
)
from wf_state import clamp


def add_absent_letter(letter: str):
    key = exist_key_for_input(letter, S.state.language)
    if key is None:
        return
    if key in S.state.absent_letters:
        S.state.absent_letters.remove(key)
        S.state.selected_absent_idx = clamp(
            S.state.selected_absent_idx, 0, max(len(S.state.absent_letters) - 1, 0)
        )
    else:
        S.state.absent_letters.append(key)

def delete_absent_item_at(idx):
    if 0 <= idx < len(S.state.absent_letters):
        del S.state.absent_letters[idx]
        S.state.selected_absent_idx = clamp(
            S.state.selected_absent_idx, 0, max(len(S.state.absent_letters) - 1, 0)
        )

def handle_text_input(ch: str):
    if not ch or not ch.isalpha():
        return
    if S.state.finder_mode == "letter_match":
        if S.state.input_mode in ("valid", "invalid"):
            toggle_letter(ch)
        elif S.state.input_mode == "exist":
            add_exist_letter(ch)
        elif S.state.input_mode == "absent":
            add_absent_letter(ch)
    else:
        ph_add_letter(ch)

def handle_backspace_input():
    """Backspace: removes one letter/character at a time (does not clear
    a whole slot). Exist/Absent already operate on discrete list items, so
    Backspace there deletes just the selected item, same as before."""
    if S.state.finder_mode == "letter_match":
        if S.state.input_mode == "exist":
            delete_exist_item_at(S.state.selected_exist_idx)
        elif S.state.input_mode == "absent":
            delete_absent_item_at(S.state.selected_absent_idx)
        else:
            backspace_letter_slot()
    else:
        ph_backspace()

def handle_delete_input():
    """Delete: fully clears the targeted slot(s) in one action, for both
    finder modes."""
    if S.state.finder_mode == "letter_match":
        if S.state.input_mode == "exist":
            delete_exist_item_at(S.state.selected_exist_idx)
        elif S.state.input_mode == "absent":
            delete_absent_item_at(S.state.selected_absent_idx)
        else:
            clear_letter_slot()
    else:
        ph_clear_slot()

def greek_tone_variant(ch: str, tone_state: int):
    """
    tone_state:
        0 = plain
        1 = tonos
        2 = diaeresis
        3 = tonos + diaeresis
    """
    if not ch or tone_state == 0:
        return ch

    # Decompose and keep only the base character
    base = unicodedata.normalize("NFD", ch)[0]
    low = base.lower()

    # Only Greek vowels can take tonos in your use case.
    vowels = {"α", "ε", "η", "ι", "ο", "υ", "ω"}
    if low not in vowels:
        return ch

    # Special handling for iota/upsilon diaeresis forms:
    # ι -> ϊ,  υ -> ϋ,  ι + tonos + diaeresis -> ΐ,  υ + tonos + diaeresis -> ΰ
    if low in {"ι", "υ"}:
        if tone_state == 2:
            return unicodedata.normalize("NFC", base + "\u0308")
        if tone_state == 3:
            return unicodedata.normalize("NFC", base + "\u0308\u0301")

    # Tonos on any Greek vowel
    if tone_state == 1:
        return unicodedata.normalize("NFC", base + "\u0301")

    # If tone_state == 2 or 3 for non-ι/υ vowels, diaeresis is not meaningful here.
    # Fall back to tonos for 3, plain for 2.
    if tone_state == 3:
        return unicodedata.normalize("NFC", base + "\u0301")

    return ch

def keyboard_char_for(base: str):
    if S.state.language == "english":
        return base.upper() if S.state.keyboard_caps else base.lower()

    ch = base.upper() if S.state.keyboard_caps else base.lower()
    return greek_tone_variant(ch, S.state.keyboard_tone)

def _keyboard_rows():
    if S.state.language == "english":
        return [
            list("qwertyuiop"),
            list("asdfghjkl"),
            list("zxcvbnm"),
        ]
    return [
        ["ς", "ε", "ρ", "τ", "υ", "θ", "ι", "ο", "π"],
        ["α", "σ", "δ", "φ", "γ", "η", "ξ", "κ", "λ"],
        ["ζ", "χ", "ψ", "ω", "β", "ν", "μ"],
    ]

def draw_virtual_keyboard(surface, panel, mouse_pos):
    kb_h = 120
    kb_rect = pygame.Rect(
        panel.x + PAD,
        panel.bottom - kb_h - 28,
        panel.width - 2 * PAD,
        kb_h,
    )
    draw_panel(surface, kb_rect, C.PANEL2, C.BORDER, radius=14)

    blit_text(
        surface,
        f"Virtual Keyboard {special_chars['kb']}",
        FONT_SM,
        C.MUTED,
        kb_rect.centerx,
        kb_rect.y + 6,
        anchor="midtop",
    )

    controls = {}
    key_rects = []

    rows = _keyboard_rows()

    row1 = rows[0]
    row2 = rows[1]
    row3 = rows[2]

    # Layout constants
    row_top_1 = kb_rect.y + 28
    row_h = 25
    row_gap = 5
    key_gap = 20

    # Widths of the non-letter controls
    backspace_w = 90
    caps_w = 80
    lang_btn_w = 220
    tone_w = 80

    # Row 1 available width for letters
    row1_available = (
        kb_rect.width
        - 16
        - backspace_w
        - key_gap
    )

    row1_letter_w = (
        row1_available - (len(row1) - 1) * key_gap
    ) // len(row1)

    # Row 2 available width for letters
    row2_available = (
        kb_rect.width
        - 16
        - caps_w
        - tone_w
        - 2 * key_gap
    )

    row2_letter_w = (
        row2_available - (len(row2) - 1) * key_gap
    ) // len(row2)

    # Row 3 is split around the language button
    lang_left = kb_rect.centerx - lang_btn_w // 2
    lang_right = kb_rect.centerx + lang_btn_w // 2

    row3_left_available = (
        lang_left
        - (kb_rect.x + 8)
        - key_gap
    )

    row3_right_available = (
        (kb_rect.right - 8)
        - lang_right
        - key_gap
    )

    left_keys = row3[:len(row3) // 2 + 1]
    right_keys = row3[len(row3) // 2 + 1:]

    if left_keys:
        row3_left_letter_w = (
            row3_left_available
            - (len(left_keys) - 1) * key_gap
        ) // len(left_keys)
    else:
        row3_left_letter_w = row1_letter_w

    if right_keys:
        row3_right_letter_w = (
            row3_right_available
            - (len(right_keys) - 1) * key_gap
        ) // len(right_keys)
    else:
        row3_right_letter_w = row1_letter_w

    # The smallest calculated width is the width that fits
    # in every row.
    letter_w = max(
        24,
        min(
            row1_letter_w,
            row2_letter_w,
            row3_left_letter_w,
            row3_right_letter_w,
        ),
    )

    # Row 1
    start_x1 = kb_rect.x + 8

    for i, base in enumerate(row1):
        r = pygame.Rect(
            start_x1 + i * (letter_w + key_gap),
            row_top_1,
            letter_w,
            row_h,
        )

        key_rects.append((base, r))

        draw_button(
            surface,
            r,
            keyboard_char_for(base),
            bg=C.BLUE_BG,
            fg=C.TEXT,
            radius=7,
            hovered=r.collidepoint(mouse_pos),
            font=FONT_SM,
        )

    # Backspace
    back_rect = pygame.Rect(
        kb_rect.right - backspace_w - 8,
        row_top_1,
        backspace_w,
        row_h,
    )

    controls["backspace"] = back_rect

    draw_button(
        surface,
        back_rect,
        "Backspace",
        bg=C.RED,
        fg=C.WHITE,
        radius=7,
        hovered=back_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )

    # Row 2
    row2_y = row_top_1 + row_h + row_gap

    # Caps
    caps_rect = pygame.Rect(
        kb_rect.x + 8,
        row2_y,
        caps_w,
        row_h,
    )

    controls["caps"] = caps_rect

    draw_button(
        surface,
        caps_rect,
        "Caps on" if S.state.keyboard_caps else "Caps off",
        bg=C.ORANGE if S.state.keyboard_caps else C.BROWN,
        fg=C.WHITE,
        radius=7,
        hovered=caps_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )

    # Row 2 letters
    row2_start_x = caps_rect.right + key_gap

    for i, base in enumerate(row2):
        r = pygame.Rect(
            row2_start_x + i * (letter_w + key_gap),
            row2_y,
            letter_w,
            row_h,
        )

        key_rects.append((base, r))

        draw_button(
            surface,
            r,
            keyboard_char_for(base),
            bg=C.BLUE_BG,
            fg=C.TEXT,
            radius=7,
            hovered=r.collidepoint(mouse_pos),
            font=FONT_SM,
        )

    # Tone button
    tone_labels = [
        "Tone off",
        "Tonos",
        "Diaeresis",
        "Both",
    ]

    tone_rect = pygame.Rect(
        kb_rect.right - tone_w - 8,
        row2_y,
        tone_w,
        row_h,
    )

    controls["tone"] = tone_rect

    draw_button(
        surface,
        tone_rect,
        tone_labels[S.state.keyboard_tone],
        bg=C.PURPLE if S.state.keyboard_tone else C.DARK,
        fg=C.WHITE,
        radius=7,
        hovered=tone_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )

    # Row 3
    row3_y = row2_y + row_h + row_gap

    # Language button
    lang_rect = pygame.Rect(
        kb_rect.centerx - lang_btn_w // 2,
        row3_y,
        lang_btn_w,
        row_h,
    )

    controls["lang"] = lang_rect

    draw_button(
        surface,
        lang_rect,
        "Greek" if S.state.language == "greek" else "English",
        bg=C.CYAN,
        fg=C.WHITE,
        radius=10,
        hovered=lang_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )

    # Row 3 left letters
    if left_keys:
        lx = kb_rect.x + 8

        for i, base in enumerate(left_keys):
            r = pygame.Rect(
                lx + i * (letter_w + key_gap),
                row3_y,
                letter_w,
                row_h,
            )

            key_rects.append((base, r))

            draw_button(
                surface,
                r,
                keyboard_char_for(base),
                bg=C.BLUE_BG,
                fg=C.TEXT,
                radius=7,
                hovered=r.collidepoint(mouse_pos),
                font=FONT_SM,
            )

    # Row 3 right letters
    if right_keys:
        rx = lang_rect.right + 5.0 * key_gap

        for i, base in enumerate(right_keys):
            r = pygame.Rect(
                rx + i * (letter_w + key_gap),
                row3_y,
                letter_w,
                row_h,
            )

            key_rects.append((base, r))

            draw_button(
                surface,
                r,
                keyboard_char_for(base),
                bg=C.BLUE_BG,
                fg=C.TEXT,
                radius=7,
                hovered=r.collidepoint(mouse_pos),
                font=FONT_SM,
            )

    # Store rectangles for mouse handling
    _results_keyboard_rects["panel"] = kb_rect
    _results_keyboard_rects["keys"] = key_rects
    _results_keyboard_rects["controls"] = controls

    return kb_rect.top

def fit_text_with_ellipsis(text, font, max_width):
    if font.size(text)[0] <= max_width:
        return text
    ell = "..."
    if font.size(ell)[0] > max_width:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid] + ell
        if font.size(candidate)[0] <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell

def blit_text(surface, text, font, color, x, y, anchor="topleft"):
    img = font.render(text, True, color)
    r = img.get_rect()
    setattr(r, anchor, (int(x), int(y)))
    surface.blit(img, r)
    return r

def draw_panel(surface, rect, color=None, border_color=None, radius=12):
    c = color if color is not None else C.PANEL
    b = border_color if border_color is not None else C.BORDER
    pygame.draw.rect(surface, c, rect, border_radius=radius)
    pygame.draw.rect(surface, b, rect, 1, border_radius=radius)

def lighten(color, amount=35):
    return tuple(min(255, c + amount) for c in color[:3])

def _dim_color(color, toward=None, factor=0.45):
    """Blends `color` toward a muted/background tone, used to de-emphasize
    non-hovered chart bars relative to the hovered one."""
    target = toward if toward is not None else C.PANEL2
    return tuple(
        int(c + (t - c) * factor) for c, t in zip(color[:3], target[:3])
    )

def draw_button(
    surface, rect, label, bg=None, fg=None, radius=8, hovered=False, font=None
):
    bg = bg if bg is not None else C.DARK
    fg = fg if fg is not None else C.WHITE
    font = font or FONT_DEFAULT
    draw_rect = (
        rect.inflate(int(rect.width * 0.1), int(rect.height * 0.1)) if hovered else rect
    )
    fill = lighten(bg) if hovered else bg
    pygame.draw.rect(surface, fill, draw_rect, border_radius=radius)
    img = font.render(label, True, fg)
    surface.blit(img, img.get_rect(center=draw_rect.center))

def draw_nav_button(
    surface, rect, direction="left", color=None, hovered=False, enabled=True
):
    """Small triangular prev/next navigation button."""
    base = color if color is not None else C.ACCENT
    bg = lighten(C.PANEL2, 14) if (hovered and enabled) else C.PANEL2
    fg = lighten(base) if (hovered and enabled) else (base if enabled else C.BORDER)

    pygame.draw.rect(surface, bg, rect, border_radius=6)
    pygame.draw.rect(surface, fg, rect, 2, border_radius=6)

    cx, cy = rect.center
    s = min(rect.width, rect.height) * 0.28
    if direction == "left":
        points = [(cx + s * 0.6, cy - s), (cx + s * 0.6, cy + s), (cx - s * 0.7, cy)]
    else:
        points = [(cx - s * 0.6, cy - s), (cx - s * 0.6, cy + s), (cx + s * 0.7, cy)]
    pygame.draw.polygon(surface, fg, points)

def draw_pill_toggle(
    surface, rect, labels, active_idx, colors=None, hovered=False, mouse_pos=None
):
    if colors is None:
        colors = [C.ACCENT] * len(labels)
    draw_rect = (
        rect.inflate(int(rect.width * 0.1), int(rect.height * 0.1)) if hovered else rect
    )
    draw_panel(surface, draw_rect, C.PANEL2, C.BORDER, radius=draw_rect.height // 2)
    n = len(labels)
    iw = draw_rect.width - 4
    sw = iw // n
    rects = []
    for i, lbl in enumerate(labels):
        w = (iw - i * sw) if i == n - 1 else sw
        sr = pygame.Rect(
            draw_rect.x + 2 + i * sw, draw_rect.y + 2, w, draw_rect.height - 4
        )
        if i == active_idx:
            pygame.draw.rect(
                surface, colors[i], sr, border_radius=max(4, sr.height // 2)
            )
            fg = C.WHITE
        else:
            fg = C.MUTED
        img = FONT_MD.render(lbl, True, fg)
        surface.blit(img, img.get_rect(center=sr.center))
        rects.append(sr)
    return rects

def draw_slider(
    surface, x, y, w, min_v, max_v, value, label, show_all_marker=False, is_all=False
):
    """Horizontal slider. Returns (track_rect, knob_rect)."""
    disp_val = "All" if is_all else str(value)
    blit_text(surface, f"{label}  {disp_val}", FONT_SM, C.MUTED, x, y)
    ty = y + 20
    track = pygame.Rect(x, ty + 5, w, 4)
    pygame.draw.rect(surface, C.BORDER, track, border_radius=2)

    if not is_all:
        t = (value - min_v) / max(max_v - min_v, 1)
        fw = int(t * w)
        if fw > 0:
            pygame.draw.rect(
                surface, C.ACCENT, pygame.Rect(x, ty + 5, fw, 4), border_radius=2
            )
        kx = x + int(t * w)
    else:
        kx = x

    knob = pygame.Rect(kx - 5, ty, 18, 14)
    knob_color = C.RED if is_all else C.WHITE
    pygame.draw.rect(surface, knob_color, knob, border_radius=7)
    pygame.draw.rect(surface, C.ACCENT, knob, 2, border_radius=7)

    if show_all_marker:
        # Draw a small marker at the far left indicating "All" zone
        all_mark = pygame.Rect(x - 5, ty + 2, 5, 5)
        pygame.draw.rect(surface, C.RED, all_mark, border_radius=3)
        blit_text(surface, "All", FONT_SM, C.RED, x - 20, ty)

    return track, knob
