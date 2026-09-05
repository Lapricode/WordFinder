"""
Top-level frame rendering functions for each UI section.

Part of the Word Finder application (split from the original single-file
WordFinder.py for maintainability). Behavior is unchanged from the original --
this is a pure refactor.
"""

import pygame

import wf_constants as C
import wf_state as S
from wf_constants import (
    FONT_SM, FONT_MD, FONT_LG, LINK_FONT_SM, PAD, GAP,
    H_HEADER, H_CTRL, H_FILES, LEFT_LABEL_W, REVIEW_BTN_W, REVIEW_BTN_H,
    RESULTS_TOP_Y, WORKSPACE_Y, MAX_WORD_LENGTH, MAX_MAX_PREVIEW,
    MIN_RESULTS_PER_ROW, MAX_RESULTS_PER_ROW, PH_ROWS, PH_COLS,
    ENGLISH_GROUP_BY_FIRST, GREEK_GROUP_BY_FIRST, special_chars,
    clamp, short_path,
)
from wf_search import expand_sequence
from wf_ui_helpers import (
    blit_text, draw_panel, draw_button, draw_nav_button, draw_pill_toggle,
    draw_slider, draw_virtual_keyboard, fit_text_with_ellipsis, lighten,
)
from wf_state import (
    ph_cell_slots, ph_cell_count, ph_cell_selected_idx,
    lookup_word_entry, format_meaning_lines, rebuild_results_cache,
    draw_search_progress_bar,
    _results_action_rects, _results_legend_rects, _results_scroll_rects,
)


_result_word_rects = []  # list of (word, rect)

_hover_word_rect = None  # (word, rect) that is hovered

_info_btn_rect = pygame.Rect(0, 0, 0, 0)

def render_header(mouse_pos):
    global _info_btn_rect
    pygame.draw.rect(C.screen, C.PANEL, (0, 0, C.WIDTH, H_HEADER))
    pygame.draw.line(C.screen, C.BORDER, (0, H_HEADER), (C.WIDTH, H_HEADER))

    mode_label = (
        "Letter Match" if S.state.finder_mode == "letter_match" else "Pattern Hunt"
    )
    title_x = PAD + 4
    lg_h = FONT_LG.get_linesize()
    sm_h = FONT_SM.get_linesize()
    total_title_h = lg_h + sm_h
    title_top = H_HEADER // 2 - total_title_h // 2
    blit_text(
        C.screen, "Word Finder", FONT_LG, C.TEXT, title_x, title_top, anchor="topleft"
    )
    blit_text(
        C.screen,
        f"[{mode_label}]",
        FONT_SM,
        C.MUTED,
        title_x,
        title_top + lg_h + 1,
        anchor="topleft",
    )

    hints1 = (
        f"Backspace = Erase last  {special_chars["*"]}  Delete = Clear slot  {special_chars["*"]}  (Shift +) {special_chars["<"]} {special_chars[">"]} = Navigate  {special_chars["*"]}  {special_chars["^"]} {special_chars["v"]} = Mode"
        f"  {special_chars["*"]}  Tab = Letter Match/Pattern Hunt  {special_chars["*"]}  Shift+Space = Slot/All  {special_chars["*"]}  Ctrl+Space = Expand (PH)"
    )
    hints2 = (
        f"/ = Greek/English  {special_chars["*"]}  Ctrl+S = Save  {special_chars["*"]}  Page Up/Down = Scroll  {special_chars["*"]}  Shift+/- = Word length  {special_chars["*"]}  Ctrl+/- = Max preview"
        f"  {special_chars["*"]}  +/- = Add/remove PH slot  {special_chars["*"]}  Ctrl+I = Info  {special_chars["*"]}  Enter = Search"
    )
    blit_text(
        C.screen, hints1, FONT_SM, C.MUTED, PAD + 200, H_HEADER * 0.28, anchor="midleft"
    )
    blit_text(
        C.screen, hints2, FONT_SM, C.MUTED, PAD + 200, H_HEADER * 0.70, anchor="midleft"
    )

    r = 0.25 * H_HEADER
    cx = C.WIDTH - PAD - r
    cy = H_HEADER // 2
    _info_btn_rect = pygame.Rect(cx - r, cy - r, 2 * r, 2 * r)
    # pygame.draw.circle(screen, ACCENT, (cx, cy), r)
    # img = FONT_MD.render("i", True, WHITE)
    # screen.blit(img, img.get_rect(center=(cx, cy - 1)))
    draw_button(
        C.screen,
        _info_btn_rect,
        "i",
        C.ACCENT,
        C.WHITE,
        radius=12,
        hovered=_info_btn_rect.collidepoint(mouse_pos),
        font=FONT_LG,
    )

def distribute_columns(total_width, left_pad, right_pad, widths):
    """Given a list of fixed column widths, return their x-positions so that
    the gap between every consecutive pair of columns is equal.
    The first column starts at left_pad; the last column ends at
    total_width - right_pad."""
    n = len(widths)
    if n == 0:
        return []
    if n == 1:
        return [left_pad]
    available = total_width - left_pad - right_pad
    fixed_sum = sum(widths)
    gap = max(8, (available - fixed_sum) / (n - 1))
    xs = []
    x = left_pad
    for w in widths:
        xs.append(x)
        x += w + gap
    return xs

def render_controls(mouse_pos):
    """Returns t1, k1, t2, k2, mode_rects, scope_rects, lang_rects, search_rect,
    finder_btn_rect, ph_col_rects (None in Letter Match mode).
    """
    y0 = H_HEADER
    pygame.draw.rect(C.screen, C.PANEL2, (0, y0, C.WIDTH, H_CTRL))
    pygame.draw.line(C.screen, C.BORDER, (0, y0 + H_CTRL), (C.WIDTH, y0 + H_CTRL))

    btn_h = 0.6 * H_CTRL

    # ── Column widths (fixed) ──────────────────────────────────────
    finder_btn_w = 150
    slider_col_w = 300
    mode_w = 300
    scope_w = 200
    lang_w = 200
    search_w = 180
    col_widths = [finder_btn_w, slider_col_w, mode_w, scope_w, lang_w, search_w]

    if sum(col_widths) > C.WIDTH:
        width_surplus = sum(col_widths) - C.WIDTH
        width_remove = (width_surplus + 100) / len(col_widths)
        finder_btn_w -= width_remove
        slider_col_w -= width_remove
        mode_w -= width_remove
        scope_w -= width_remove
        lang_w -= width_remove
        search_w -= width_remove
        col_widths = [finder_btn_w, slider_col_w, mode_w, scope_w, lang_w, search_w]

    xs = distribute_columns(C.WIDTH, PAD, PAD, col_widths)
    finder_x, slider_x, mode_x, scope_x, lang_x, search_x = xs

    # Two stacked rows inside the same 80px header
    pill_h = 0.4 * H_CTRL
    pill_y_default = y0 + (H_CTRL - pill_h) / 2
    if S.state.finder_mode == "letter_match":
        pill_y_top = y0 + (H_CTRL - pill_h) / 2
    elif S.state.finder_mode == "pattern_hunt":
        pill_y_top = y0 + (H_CTRL / 2 - pill_h) / 2
        pill_y_bottom = y0 + H_CTRL / 2 + (H_CTRL / 2 - pill_h) / 2

    # ── Finder Mode Button ──────────────────────────────────────────
    finder_btn_rect = pygame.Rect(
        finder_x, y0 + (H_CTRL - btn_h) / 2, finder_btn_w, btn_h
    )
    finder_lbl = (
        "Letter Match" if S.state.finder_mode == "letter_match" else "Pattern Hunt"
    )
    draw_button(
        C.screen,
        finder_btn_rect,
        finder_lbl,
        C.RED,
        C.WHITE,
        radius=8,
        hovered=finder_btn_rect.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    # ── Sliders (stacked within the slider column) ───────────────────
    sl_w = slider_col_w
    cy1 = y0 + 0.05 * H_FILES
    cy2 = y0 + H_CTRL / 2

    is_all = S.state.finder_mode == "pattern_hunt" and S.state.ph_word_length_all
    active_word_length = (
        S.state.ph_word_length
        if S.state.finder_mode == "pattern_hunt"
        else S.state.lm_word_length
    )
    t1, k1 = draw_slider(
        C.screen,
        slider_x,
        cy1,
        sl_w,
        1,
        MAX_WORD_LENGTH,
        active_word_length,
        "Word length",
        show_all_marker=(S.state.finder_mode == "pattern_hunt"),
        is_all=is_all,
    )
    t2, k2 = draw_slider(
        C.screen,
        slider_x,
        cy2,
        sl_w,
        1,
        MAX_MAX_PREVIEW,
        S.state.max_preview,
        "Max preview",
    )

    # ── Main mode pill toggle ───────────────────────────────────────
    if S.state.finder_mode == "letter_match":
        mode_labels = ["Valid", "Invalid", "Exist", "Absent"]
        mode_colors = [C.GREEN, C.RED, C.BROWN, C.ORANGE]
        mode_idx = {
            "valid": 0,
            "invalid": 1,
            "exist": 2,
            "absent": 3,
        }[S.state.input_mode]
    else:
        mode_labels = ["Start", "Inner", "Middle", "End"]
        mode_colors = [C.TEAL, C.CYAN, C.PURPLE, C.PINK]
        mode_idx = {
            "start": 0,
            "inner": 1,
            "middle": 2,
            "end": 3,
        }[S.state.ph_mode]

    m_rect = pygame.Rect(mode_x, pill_y_top, mode_w, pill_h)
    m_rects = draw_pill_toggle(
        C.screen,
        m_rect,
        mode_labels,
        mode_idx,
        mode_colors,
        hovered=m_rect.collidepoint(mouse_pos),
    )

    # ── Pattern Hunt secondary column toggle, stacked directly below ──
    ph_col_rects = None
    if S.state.finder_mode == "pattern_hunt":
        ph_col_rect = pygame.Rect(mode_x, pill_y_bottom, mode_w, pill_h)
        ph_col_labels = ["Valid", "Invalid", "Exist", "Absent"]
        ph_col_colors = [C.GREEN, C.RED, C.BROWN, C.ORANGE]
        ph_col_idx = {
            "valid": 0,
            "invalid": 1,
            "exist": 2,
            "absent": 3,
        }[S.state.ph_col]
        ph_col_rects = draw_pill_toggle(
            C.screen,
            ph_col_rect,
            ph_col_labels,
            ph_col_idx,
            ph_col_colors,
            hovered=ph_col_rect.collidepoint(mouse_pos),
        )

    # ── Scope pill toggle (Slot / All) ────────────────────────────
    scope_rect = pygame.Rect(scope_x, pill_y_default, scope_w, pill_h)
    active_scope = (
        S.state.input_scope if S.state.finder_mode == "letter_match" else S.state.ph_scope
    )
    scope_rects = draw_pill_toggle(
        C.screen,
        scope_rect,
        ["Slot", "All"],
        0 if active_scope == "single" else 1,
        [C.ORANGE, C.ORANGE],
        hovered=scope_rect.collidepoint(mouse_pos),
    )

    # ── Language pill toggle ──────────────────────────────────────
    lang_rect = pygame.Rect(lang_x, pill_y_default, lang_w, pill_h)
    lang_rects = draw_pill_toggle(
        C.screen,
        lang_rect,
        ["Greek", "English"],
        0 if S.state.language == "greek" else 1,
        [C.CYAN, C.CYAN],
        hovered=lang_rect.collidepoint(mouse_pos),
    )

    # ── Search button ─────────────────────────────────────────────
    search_rect = pygame.Rect(search_x, y0 + (H_CTRL - btn_h) / 2, search_w, btn_h)
    draw_button(
        C.screen,
        search_rect,
        f"Search",
        C.GREEN,
        C.WHITE,
        hovered=search_rect.collidepoint(mouse_pos),
        font=FONT_LG,
    )

    return (
        t1,
        k1,
        t2,
        k2,
        m_rects,
        scope_rects,
        lang_rects,
        search_rect,
        finder_btn_rect,
        ph_col_rects,
    )

def render_file_row(mouse_pos):
    y0 = H_HEADER + H_CTRL
    pygame.draw.rect(C.screen, C.BG, (0, y0, C.WIDTH, H_FILES))
    pygame.draw.line(C.screen, C.BORDER, (0, y0 + H_FILES), (C.WIDTH, y0 + H_FILES))

    by = y0 + (H_FILES - 40) / 2
    bh = 0.5 * H_FILES  # file unit button height
    BW = 90
    unit_w = BW + 6 + 126  # button + gap + label/path area, used only for spacing math

    def file_unit(x, label, path, count):
        br = pygame.Rect(x, by, BW, bh)
        tx = x + BW + 6
        path_img = LINK_FONT_SM.render(short_path(path), True, C.ACCENT)
        path_rect = path_img.get_rect(topleft=(tx, by + 2))
        C.screen.blit(path_img, path_rect)
        # plus/minus buttons under the path, left of the count (Pattern Hunt style)
        btn_size = 14
        plus_rect = pygame.Rect(tx, by + 22, btn_size, btn_size)
        minus_rect = pygame.Rect(tx + btn_size + 6, by + 22, btn_size, btn_size)

        plus_hover = plus_rect.collidepoint(mouse_pos)
        minus_hover = minus_rect.collidepoint(mouse_pos)

        pygame.draw.rect(
            C.screen,
            lighten(C.GREEN_BG, 18) if plus_hover else C.GREEN_BG,
            plus_rect,
            border_radius=4,
        )
        pygame.draw.rect(C.screen, C.GREEN_BDR, plus_rect, 1, border_radius=4)
        blit_text(C.screen, "+", FONT_SM, C.GREEN, plus_rect.centerx, plus_rect.centery, anchor="center")

        pygame.draw.rect(
            C.screen,
            lighten(C.RED_BG, 18) if minus_hover else C.RED_BG,
            minus_rect,
            border_radius=4,
        )
        pygame.draw.rect(C.screen, C.RED_BDR, minus_rect, 1, border_radius=4)
        blit_text(C.screen, "-", FONT_SM, C.RED, minus_rect.centerx, minus_rect.centery, anchor="center")

        blit_text(
            C.screen, f"{count} words", FONT_SM, C.MUTED, tx + btn_size * 2 + 12, by + 20, anchor="topleft"
        )
        hover_rect = pygame.Rect(tx, by, 126, 36)

        draw_button(
            C.screen,
            br,
            label,
            C.DARK,
            C.WHITE,
            radius=7,
            hovered=br.collidepoint(mouse_pos),
            font=FONT_MD,
        )

        if hover_rect.collidepoint(mouse_pos) and path:
            tip_img = FONT_SM.render(path, True, C.WHITE)
            tip_pad = 6
            tip_rect = tip_img.get_rect(topleft=(mouse_pos[0] + 14, mouse_pos[1] + 14))
            tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
            if tip_rect.right > C.WIDTH - PAD:
                tip_rect.right = mouse_pos[0] - 14
            pygame.draw.rect(C.screen, C.DARK, tip_rect, border_radius=6)
            pygame.draw.rect(C.screen, C.BORDER, tip_rect, 1, border_radius=6)
            C.screen.blit(tip_img, tip_img.get_rect(center=tip_rect.center))

        return br, path_rect, plus_rect, minus_rect

    # ── Column widths for equal spacing across the whole row ──
    action_col_w = 150
    theme_w = 100
    save_w = 130
    col_widths = [unit_w, unit_w, unit_w, action_col_w, action_col_w, save_w, theme_w]

    if sum(col_widths) > C.WIDTH:
        width_surplus = sum(col_widths) - C.WIDTH
        width_remove = (width_surplus + 100) / len(col_widths)
        unit_w -= width_remove
        action_col_w -= width_remove
        save_w -= width_remove
        theme_w -= width_remove
        col_widths = [
            unit_w,
            unit_w,
            unit_w,
            action_col_w,
            action_col_w,
            save_w,
            theme_w,
        ]

    xs = distribute_columns(C.WIDTH, PAD, PAD, col_widths)
    greek_x, english_x, saveto_x, translate_x, meaning_x, save_x, theme_x = xs

    # ── Show translation / Show meaning stacked sections ─────────────
    chk_size = 0.3 * H_FILES
    action_btn_h = 0.4 * H_FILES
    chk_y = y0 + 0.1 * H_FILES
    btn_y = y0 + H_FILES / 2

    def draw_checkbox(x, y, checked, label):
        box = pygame.Rect(x, y, chk_size, chk_size)
        pygame.draw.rect(
            C.screen, (C.GREEN_BG if checked else C.PANEL2), box, border_radius=4
        )
        pygame.draw.rect(
            C.screen, (C.GREEN if checked else C.BORDER), box, 2, border_radius=4
        )
        if checked:
            img = FONT_LG.render(special_chars["[OK]"], True, C.GREEN)
            C.screen.blit(img, img.get_rect(center=box.center))
        lbl_img = FONT_SM.render(label, True, C.TEXT)
        C.screen.blit(lbl_img, lbl_img.get_rect(midleft=(box.right + 8, box.centery)))
        return box

    translate_chk_rect = draw_checkbox(
        translate_x, chk_y, S.state.show_translation, "Show Translation"
    )
    meaning_chk_rect = draw_checkbox(
        meaning_x, chk_y, S.state.show_meaning, "Show Meaning"
    )

    translate_btn = pygame.Rect(translate_x, btn_y, action_col_w + 10, action_btn_h)
    meaning_btn = pygame.Rect(meaning_x, btn_y, action_col_w - 10, action_btn_h)

    draw_button(
        C.screen,
        translate_btn,
        f"Translation {special_chars['<>']}",
        C.PURPLE,
        C.WHITE,
        radius=7,
        hovered=translate_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )
    draw_button(
        C.screen,
        meaning_btn,
        f"Meaning {special_chars['?']}",
        C.PURPLE,
        C.WHITE,
        radius=7,
        hovered=meaning_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    # ── Theme + Save (right side) ───────────────────────────────────
    btn_h2 = 0.6 * H_FILES
    btn_y2 = by + (40 - btn_h2) / 2

    sv_btn = pygame.Rect(save_x, btn_y2, save_w, btn_h2)
    draw_button(
        C.screen,
        sv_btn,
        "Save",
        C.PURPLE,
        C.WHITE,
        hovered=sv_btn.collidepoint(mouse_pos),
        font=FONT_LG,
    )

    theme_btn = pygame.Rect(theme_x, btn_y2, theme_w, btn_h2)
    theme_label = "Light" if S.state.theme == "light" else "Dark"
    draw_button(
        C.screen,
        theme_btn,
        theme_label,
        C.ACCENT,
        C.WHITE,
        radius=7,
        hovered=theme_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    # ── Show Files buttons and paths ─────────────

    sp_btn, sp_link, sp_plus, sp_minus = file_unit(
        saveto_x, "Save to", S.state.results_file, S.state.results_count
    )
    ef_btn, ef_link, ef_plus, ef_minus = file_unit(
        english_x, "English", S.state.english_file, S.state.english_count
    )
    gf_btn, gf_link, gf_plus, gf_minus = file_unit(greek_x, "Greek", S.state.greek_file, S.state.greek_count)

    return (
        gf_btn,
        gf_link,
        ef_btn,
        ef_link,
        sp_btn,
        sp_link,
        gf_plus,
        gf_minus,
        ef_plus,
        ef_minus,
        sp_plus,
        sp_minus,
        theme_btn,
        sv_btn,
        translate_chk_rect,
        meaning_chk_rect,
        translate_btn,
        meaning_btn,
    )

def _slot_layout():
    gap = 8
    left_edge = PAD + LEFT_LABEL_W
    right_edge = C.WIDTH - PAD
    available = max(1, right_edge - left_edge)
    n = max(S.state.word_length, 1)
    slots_num = 5
    slots_perc = 0.75
    if S.state.word_length <= slots_num:
        total_w = available * slots_perc
    else:
        t = (S.state.word_length - slots_num) / max(MAX_WORD_LENGTH - slots_num, 1)
        total_w = available * (slots_perc + (1 - slots_perc) * t)
    slot_w = max(16, int((total_w - (n - 1) * gap) // n))
    tw = n * slot_w + (n - 1) * gap
    sx = left_edge + max(0, (available - tw) // 2)
    ty = WORKSPACE_Y + PAD
    slot_h = 32
    return slot_w, slot_h, sx, ty, gap

def format_exist_letters(counter):
    parts = []
    for key, count in counter.items():
        if S.state.language == "greek":
            group = GREEK_GROUP_BY_FIRST.get(key, (key,))
        elif S.state.language == "english":
            group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
        else:
            group = (key,)
        label = "".join(group)
        parts.append(f"{label} (x{count})" if count > 1 else label)
    return f"  {special_chars["*"]}  ".join(parts) if parts else f"{special_chars["-"]}"

def render_workspace_lm(mouse_pos):
    """Letter Match workspace. Returns (slot_w, slot_h, sx, ty, gap, table_bottom_y, summary_btn, lm_ui)."""
    slot_w, slot_h, sx, ty, gap = _slot_layout()

    # ── Position squares ──────────────────────────────────────────
    for i in range(S.state.word_length):
        x = sx + i * (slot_w + gap)
        r = pygame.Rect(x, ty, slot_w, slot_h)
        sel = i == S.state.selected_pos
        hv = bool(S.state.valid_sets[i])
        hi = bool(S.state.invalid_sets[i])

        if hv and hi:
            fill = C.BLUE_BG
        elif hv:
            fill = C.GREEN_BG
        elif hi:
            fill = C.RED_BG
        else:
            fill = C.SLOT

        # Highlight border when this slot is selected AND mode matches
        if sel and S.state.input_mode in ("valid", "invalid"):
            if S.state.input_mode == "valid":
                bdr_col = C.GREEN
            else:
                bdr_col = C.RED
            bdr_w = 3
        elif sel:
            bdr_col = C.ACCENT
            bdr_w = 3
        else:
            bdr_col = C.BORDER
            bdr_w = 1

        pygame.draw.rect(C.screen, fill, r, border_radius=10)
        pygame.draw.rect(C.screen, bdr_col, r, bdr_w, border_radius=10)

        ni = FONT_SM.render(str(i + 1), True, C.ACCENT if sel else C.MUTED)
        C.screen.blit(ni, ni.get_rect(center=(x + slot_w // 2, ty - 13)))

    # ── Hint line ─────────────────────────────────────────────────
    hint_y = ty + slot_h - 10
    if S.state.input_mode == "valid":
        mc = C.GREEN
    if S.state.input_mode == "invalid":
        mc = C.RED
    if S.state.input_mode == "exist":
        mc = C.BROWN
    if S.state.input_mode == "absent":
        mc = C.ORANGE
    blit_text(
        C.screen,
        f"Position {S.state.selected_pos + 1}  |  Mode:",
        FONT_SM,
        C.MUTED,
        PAD,
        hint_y,
    )
    mode_w = FONT_SM.size(f"Position {S.state.selected_pos + 1}  |  Mode:")[0]
    blit_text(
        C.screen, f"  {S.state.input_mode.upper()}", FONT_SM, mc, PAD + mode_w, hint_y
    )

    # ── Condition tables ──────────────────────────────────────────
    table_y = hint_y + 25
    row_h = 36

    summary_btn = pygame.Rect(PAD, WORKSPACE_Y, REVIEW_BTN_W, REVIEW_BTN_H)
    draw_button(
        C.screen,
        summary_btn,
        "Slots Review",
        C.DARK,
        C.WHITE,
        radius=7,
        hovered=summary_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    hover_text = None
    hover_pos = None
    hover_text = None
    hover_pos = None

    lm_ui = {
        "valid_cells": [],  # list of (position_index, rect)
        "invalid_cells": [],  # list of (position_index, rect)
        "exist_chips": [],  # list of (exist_index, rect)
        "exist_row": None,  # whole-row rect, clickable even with no chips
    }

    for label, sets, bg_c, bdr_c, lbl_c, mode_str in [
        ("VALID", S.state.valid_sets, C.GREEN_BG, C.GREEN_BDR, C.GREEN, "valid"),
        ("INVALID", S.state.invalid_sets, C.RED_BG, C.RED_BDR, C.RED, "invalid"),
    ]:
        blit_text(C.screen, label, FONT_MD, lbl_c, PAD, table_y + row_h // 2 - 10)
        for i in range(S.state.word_length):
            x = sx + i * (slot_w + gap)
            cell = pygame.Rect(x, table_y, slot_w, row_h)
            # Highlight border if this cell matches selected pos + mode
            if i == S.state.selected_pos and S.state.input_mode == mode_str:
                cell_bdr = lbl_c
                cell_bdr_w = 2
            else:
                cell_bdr = bdr_c
                cell_bdr_w = 1
            pygame.draw.rect(C.screen, bg_c, cell, border_radius=8)
            pygame.draw.rect(C.screen, cell_bdr, cell, cell_bdr_w, border_radius=8)
            letters = "".join(sorted(sets[i]))
            max_text_w = cell.width - 8
            display_letters = fit_text_with_ellipsis(letters, FONT_SM, max_text_w)
            img = FONT_SM.render(
                display_letters or f"{special_chars["-"]}",
                True,
                C.TEXT if letters else C.MUTED,
            )
            C.screen.blit(img, img.get_rect(center=cell.center))

            lm_ui[f"{mode_str}_cells"].append((i, cell))

            if cell.collidepoint(mouse_pos):
                letters_full = "".join(sorted(sets[i])) or f"{special_chars["-"]}"
                hover_text = f"{label} slot {i + 1}: {letters_full}"
                hover_pos = mouse_pos
        table_y += row_h + 6

    # ── Exist + Absent rows ─────────────────────────────────────────
    exist_items = S.state.get_exist_items()
    absent_items = S.state.get_absent_letters()

    exist_row_h = row_h
    half_w = (C.WIDTH - 3 * PAD) // 2
    exist_rect = pygame.Rect(PAD, table_y, half_w, exist_row_h)
    absent_rect = pygame.Rect(exist_rect.right + PAD, table_y, half_w, exist_row_h)

    lm_ui["exist_row"] = exist_rect
    lm_ui["absent_row"] = absent_rect
    lm_ui["exist_chips"] = []
    lm_ui["absent_chips"] = []

    # Highlighted border for exist row when mode is "exist"
    if S.state.input_mode == "exist":
        exist_bdr_col = C.BROWN
        exist_bdr_w = 3
    else:
        exist_bdr_col = C.BROWN_BDR
        exist_bdr_w = 1

    pygame.draw.rect(C.screen, C.BROWN_BG, exist_rect, border_radius=8)
    pygame.draw.rect(C.screen, exist_bdr_col, exist_rect, exist_bdr_w, border_radius=8)
    blit_text(C.screen, "EXIST", FONT_MD, C.BROWN, PAD + 6, table_y + exist_row_h // 2 - 10)

    # Highlight Absent row when mode is "absent"
    if S.state.input_mode == "absent":
        absent_bdr_col = C.ORANGE
        absent_bdr_w = 3
    else:
        # NOTE: original used `"ORANGE_BDR" in globals()` as a defensive check; ORANGE_BDR
        # is always defined by the time this runs (set in wf_constants at import time and
        # refreshed by set_theme()), so this always evaluated True in the original too.
        absent_bdr_col = C.ORANGE_BDR
        absent_bdr_w = 1

    pygame.draw.rect(C.screen, C.ORANGE_BG, absent_rect, border_radius=8)
    pygame.draw.rect(C.screen, absent_bdr_col, absent_rect, absent_bdr_w, border_radius=8)
    blit_text(C.screen, "ABSENT", FONT_MD, C.ORANGE, absent_rect.x + 6, table_y + exist_row_h // 2 - 10)

    if exist_items:
        # Draw each exist item as a small chip, navigatable
        chip_x = PAD + 90
        chip_gap = 8
        chip_y = table_y + 4
        chip_h = exist_row_h - 8
        exist_rects_local = []
        for ei, (key, count) in enumerate(exist_items):
            if S.state.language == "greek":
                group = GREEK_GROUP_BY_FIRST.get(key, (key,))
            else:
                group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
            label = "".join(group)
            disp = f"{label}x{count}" if count > 1 else label
            tw_chip = FONT_SM.size(disp)[0] + 16
            chip_rect = pygame.Rect(chip_x, chip_y, tw_chip, chip_h)

            lm_ui["exist_chips"].append((ei, chip_rect))

            is_sel = S.state.input_mode == "exist" and ei == S.state.selected_exist_idx
            chip_bg = C.BROWN_BDR if is_sel else C.BROWN_BG
            chip_bdr = C.BROWN if is_sel else C.BROWN_BDR
            chip_bdr_w = 2 if is_sel else 1
            pygame.draw.rect(C.screen, chip_bg, chip_rect, border_radius=6)
            pygame.draw.rect(C.screen, chip_bdr, chip_rect, chip_bdr_w, border_radius=6)
            img = FONT_SM.render(disp, True, C.BROWN if is_sel else C.TEXT)
            C.screen.blit(img, img.get_rect(midleft=(chip_x + 8, chip_y + chip_h // 2)))
            if chip_rect.collidepoint(mouse_pos):
                hover_text = f"Exist: {disp}"
                hover_pos = mouse_pos
            exist_rects_local.append(chip_rect)
            chip_x += tw_chip + chip_gap
            if chip_x > exist_rect.right - 100:
                break
    else:
        img = FONT_SM.render(f"{special_chars["-"]}", True, C.MUTED)
        C.screen.blit(img, img.get_rect(midleft=(PAD + 90, table_y + exist_row_h // 2)))

    if absent_items:
        chip_x = absent_rect.x + 90
        chip_gap = 8
        chip_y = table_y + 4
        chip_h = exist_row_h - 8
        absent_rects_local = []

        for ai, key in absent_items:
            if S.state.language == "greek":
                group = GREEK_GROUP_BY_FIRST.get(key, (key,))
            else:
                group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
            label = "".join(group)
            disp = label

            tw_chip = FONT_SM.size(disp)[0] + 16
            chip_rect = pygame.Rect(chip_x, chip_y, tw_chip, chip_h)
            lm_ui["absent_chips"].append((ai, chip_rect))

            is_sel = S.state.input_mode == "absent" and ai == S.state.selected_absent_idx
            chip_bg = C.ORANGE_BDR if is_sel else C.ORANGE_BG
            chip_bdr = C.ORANGE if is_sel else C.ORANGE_BDR
            chip_bdr_w = 2 if is_sel else 1

            pygame.draw.rect(C.screen, chip_bg, chip_rect, border_radius=6)
            pygame.draw.rect(C.screen, chip_bdr, chip_rect, chip_bdr_w, border_radius=6)
            img = FONT_SM.render(disp, True, C.ORANGE if is_sel else C.TEXT)
            C.screen.blit(img, img.get_rect(midleft=(chip_x + 8, chip_y + chip_h // 2)))

            if chip_rect.collidepoint(mouse_pos):
                hover_text = f"Absent: {disp}"
                hover_pos = mouse_pos

            absent_rects_local.append(chip_rect)
            chip_x += tw_chip + chip_gap
            if chip_x > absent_rect.right - 100:
                break
    else:
        img = FONT_SM.render(f"{special_chars['-']}", True, C.MUTED)
        C.screen.blit(img, img.get_rect(midleft=(absent_rect.x + 90, table_y + exist_row_h // 2)))

    table_y += exist_row_h + 6

    if hover_text:
        tip_font = FONT_SM
        tip_img = tip_font.render(hover_text, True, C.WHITE)
        tip_pad = 8
        tip_rect = tip_img.get_rect(topleft=(hover_pos[0] + 16, hover_pos[1] + 16))
        tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
        if tip_rect.right > C.WIDTH - PAD:
            tip_rect.right = C.WIDTH - PAD
        if tip_rect.bottom > C.HEIGHT - PAD:
            tip_rect.bottom = C.HEIGHT - PAD
        if tip_rect.left < PAD:
            tip_rect.left = PAD
        if tip_rect.top < PAD:
            tip_rect.top = PAD
        pygame.draw.rect(C.screen, C.DARK, tip_rect, border_radius=8)
        pygame.draw.rect(C.screen, C.BORDER, tip_rect, 1, border_radius=8)
        C.screen.blit(tip_img, tip_img.get_rect(center=tip_rect.center))

    return slot_w, slot_h, sx, ty, gap, RESULTS_TOP_Y, summary_btn, lm_ui

def _ph_cell_layout(cell_rect, slot_count):
    btn_w = 16
    inner_pad = 4
    gap = 6
    usable = max(1, cell_rect.width - btn_w - inner_pad * 2 - 6)
    n = max(slot_count, 1)
    slot_w = max(20, min(110, (usable - (n - 1) * gap) // n))
    total_w = n * slot_w + (n - 1) * gap
    sx = cell_rect.x + btn_w + inner_pad + max(0, (usable - total_w) // 2)
    return slot_w, sx, gap, btn_w

def render_workspace_ph(mouse_pos):
    top_y = WORKSPACE_Y + PAD
    summary_btn = pygame.Rect(PAD, WORKSPACE_Y, REVIEW_BTN_W, REVIEW_BTN_H)
    draw_button(
        C.screen,
        summary_btn,
        "Patterns Review",
        C.DARK,
        C.WHITE,
        radius=7,
        hovered=summary_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    col_labels = ["Valid", "Invalid", "Exist", "Absent"]
    col_colors = [C.GREEN, C.RED, C.BROWN, C.ORANGE]
    col_bg = [C.GREEN_BG, C.RED_BG, C.BROWN_BG, C.BROWN_BG]
    row_labels = ["Start", "Inner", "Middle", "End"]
    row_colors = [C.TEAL, C.CYAN, C.PURPLE, C.PINK]

    grid_left = PAD + LEFT_LABEL_W
    grid_right = C.WIDTH - PAD
    col_gap = 10
    cols = 4
    cell_w = max(130, (grid_right - grid_left - (cols - 1) * col_gap) // cols)
    cell_h = 34
    row_gap = 10
    header_y = top_y - 10
    row_start_y = header_y + 28

    col_hdr_rects = {}
    for ci, (clbl, ccol) in enumerate(zip(col_labels, col_colors)):
        x = grid_left + ci * (cell_w + col_gap)
        r = pygame.Rect(x, header_y, cell_w, 22)
        pygame.draw.rect(C.screen, ccol, r, border_radius=6)
        img = FONT_MD.render(clbl.upper(), True, C.WHITE)
        C.screen.blit(img, img.get_rect(center=r.center))
        col_hdr_rects[PH_COLS[ci]] = r

    ph_ui = {"summary_btn": summary_btn, "cells": {}, "col_hdrs": col_hdr_rects}
    hover_text = None
    hover_pos = None

    for ri, row in enumerate(PH_ROWS):
        y = row_start_y + ri * (cell_h + row_gap)
        row_lbl = row_labels[ri]
        row_col = row_colors[ri]
        blit_text(C.screen, row_lbl.upper(), FONT_MD, row_col, PAD, y + cell_h // 2 - 10)

        for ci, col in enumerate(PH_COLS):
            x = grid_left + ci * (cell_w + col_gap)
            cell = pygame.Rect(x, y, cell_w, cell_h)
            is_active_cell = (
                S.state.finder_mode == "pattern_hunt"
                and S.state.ph_mode == row
                and S.state.ph_col == col
            )
            cell_border = row_col if is_active_cell else col_colors[ci]
            cell_border_w = 3 if is_active_cell else 1
            pygame.draw.rect(C.screen, col_bg[ci], cell, border_radius=8)
            pygame.draw.rect(C.screen, cell_border, cell, cell_border_w, border_radius=8)

            count = ph_cell_count(row, col)
            selected_idx = ph_cell_selected_idx(row, col)
            slots = ph_cell_slots(row, col)
            slot_w, sx, gap, btn_w = _ph_cell_layout(cell, count)

            plus_r = pygame.Rect(cell.x + 2, cell.y + 3, 14, 14)
            minus_r = pygame.Rect(cell.x + 2, cell.y + cell.height - 17, 14, 14)

            plus_hover = plus_r.collidepoint(mouse_pos)
            minus_hover = minus_r.collidepoint(mouse_pos)

            pygame.draw.rect(
                C.screen,
                lighten(C.GREEN_BG, 18) if plus_hover else C.GREEN_BG,
                plus_r,
                border_radius=4,
            )
            pygame.draw.rect(C.screen, C.GREEN_BDR, plus_r, 1, border_radius=4)

            pygame.draw.rect(
                C.screen,
                lighten(C.RED_BG, 18) if minus_hover else C.RED_BG,
                minus_r,
                border_radius=4,
            )
            pygame.draw.rect(C.screen, C.RED_BDR, minus_r, 1, border_radius=4)

            blit_text(
                C.screen,
                "+",
                FONT_SM,
                C.GREEN,
                plus_r.centerx,
                plus_r.centery,
                anchor="center",
            )
            blit_text(
                C.screen,
                "-",
                FONT_SM,
                C.RED,
                minus_r.centerx,
                minus_r.centery,
                anchor="center",
            )

            slot_rects = []
            for si in range(count):
                sx_i = sx + si * (slot_w + gap)
                sr = pygame.Rect(sx_i, cell.y + 4, slot_w, cell.height - 8)
                slot = slots[si]
                seq = slot["seq"]
                expanded = slot["expanded"]
                is_sel_slot = is_active_cell and si == selected_idx
                slot_fill = C.BLUE_BG if expanded and seq else C.PANEL2
                slot_bdr = row_col if is_sel_slot else C.BORDER
                slot_bdr_w = 2 if is_sel_slot else 1
                pygame.draw.rect(C.screen, slot_fill, sr, border_radius=6)
                pygame.draw.rect(C.screen, slot_bdr, sr, slot_bdr_w, border_radius=6)

                disp_seq = (
                    expand_sequence(seq, S.state.language) if (seq and expanded) else seq
                )
                disp = (
                    fit_text_with_ellipsis(disp_seq, FONT_SM, slot_w - 10)
                    if seq
                    else f"{special_chars["-"]}"
                )
                img = FONT_SM.render(
                    disp, True, C.PURPLE if expanded and seq else (C.TEXT if seq else C.MUTED)
                )
                C.screen.blit(img, img.get_rect(center=sr.center))

                exp_btn = pygame.Rect(sr.right - 15, sr.top + 2, 12, 12)
                exp_hover = exp_btn.collidepoint(mouse_pos)

                base_exp_bg = C.PURPLE if expanded else C.BORDER
                pygame.draw.rect(
                    C.screen,
                    lighten(base_exp_bg, 18) if exp_hover else base_exp_bg,
                    exp_btn,
                    border_radius=3,
                )

                e_img = FONT_SM.render(
                    f"{special_chars["~"]}", True, C.WHITE if expanded else C.MUTED
                )
                C.screen.blit(e_img, e_img.get_rect(center=exp_btn.center))

                if sr.collidepoint(mouse_pos):
                    hover_text = f"{row_lbl} / {col_labels[ci]}: {disp_seq or f'{special_chars["-"]}'}" + (
                        " [expanded]" if expanded else ""
                    )
                    hover_pos = mouse_pos

                slot_rects.append({"rect": sr, "expand_btn": exp_btn})

            ph_ui["cells"][(row, col)] = {
                "cell": cell,
                "plus": plus_r,
                "minus": minus_r,
                "slots": slot_rects,
            }

    if hover_text:
        tip_img = FONT_SM.render(hover_text, True, C.WHITE)
        tip_pad = 8
        tip_rect = tip_img.get_rect(topleft=(hover_pos[0] + 16, hover_pos[1] + 16))
        tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
        if tip_rect.right > C.WIDTH - PAD:
            tip_rect.right = C.WIDTH - PAD
        if tip_rect.bottom > C.HEIGHT - PAD:
            tip_rect.bottom = C.HEIGHT - PAD
        if tip_rect.left < PAD:
            tip_rect.left = PAD
        if tip_rect.top < PAD:
            tip_rect.top = PAD
        pygame.draw.rect(C.screen, C.DARK, tip_rect, border_radius=8)
        pygame.draw.rect(C.screen, C.BORDER, tip_rect, 1, border_radius=8)
        C.screen.blit(tip_img, tip_img.get_rect(center=tip_rect.center))

    return RESULTS_TOP_Y, summary_btn, ph_ui

def render_results(table_bottom_y, mouse_pos=(0, 0)):
    global _result_word_rects, _hover_word_rect
    _result_word_rects = []

    y0 = table_bottom_y + PAD
    h = C.HEIGHT - y0 - PAD / 2
    if h < 80:
        return None, None

    panel = pygame.Rect(PAD, y0, C.WIDTH - 2 * PAD, h)
    draw_panel(C.screen, panel, C.PANEL, C.BORDER, radius=12)
    _results_scroll_rects["panel"] = panel

    progress_h = draw_search_progress_bar(C.screen, panel)

    if S.state.results_cache_dirty:
        rebuild_results_cache()

    panel_words = S.state.results_visible_words
    n = len(panel_words)

    if n:
        S.state.preview_start = clamp(S.state.preview_start, 0, n - 1)
        start_index = S.state.preview_start + 1
        end_index = min(S.state.preview_start + S.state.max_preview, n)
    else:
        S.state.preview_start = 0
        start_index = 0
        end_index = 0

    n_save = sum(1 for v in S.state.word_selections.values() if v == "save")
    n_excl = sum(1 for v in S.state.word_selections.values() if v == "exclude")
    sel_parts = []
    if n_save:
        sel_parts.append(f"{n_save} word(s) selected {special_chars['[OK]']}")
    if n_excl:
        sel_parts.append(f"{n_excl} word(s) excluded {special_chars['X']}")
    sel_str = "  |  " + f"  {special_chars['*']}  ".join(sel_parts) if sel_parts else ""

    top_y = panel.y + 10 + progress_h
    blit_text(C.screen, S.state.status, FONT_SM, C.MUTED, panel.x + PAD, top_y)

    cnt = f"{n} total  {special_chars['*']}  showing {start_index} - {end_index}"
    cnt_w = FONT_SM.size(cnt)[0]
    nav_w, nav_h, nav_gap = 22, 20, 6
    group_w = nav_w * 2 + nav_gap * 2 + cnt_w
    group_x = panel.right - PAD - group_w
    nav_y = panel.y + 8 + progress_h

    prev_rect = pygame.Rect(group_x, nav_y, nav_w, nav_h)
    cnt_x = prev_rect.right + nav_gap
    blit_text(C.screen, cnt, FONT_SM, C.ACCENT, cnt_x, top_y, anchor="topleft")
    next_rect = pygame.Rect(cnt_x + cnt_w + nav_gap, nav_y, nav_w, nav_h)

    can_prev = S.state.preview_start > 0
    can_next = n > 0 and (S.state.preview_start + S.state.max_preview) < n
    draw_nav_button(
        C.screen,
        prev_rect,
        "left",
        hovered=prev_rect.collidepoint(mouse_pos),
        enabled=can_prev,
    )
    draw_nav_button(
        C.screen,
        next_rect,
        "right",
        hovered=next_rect.collidepoint(mouse_pos),
        enabled=can_next,
    )

    if sel_str:
        blit_text(
            C.screen,
            sel_str,
            FONT_SM,
            C.PURPLE,
            panel.centerx,
            top_y,
            anchor="midtop",
        )

    counts = S.state.results_status_counts

    legend_items = [
        ("ok", "ok"),
        ("no_translation", f"no {special_chars['<>']}"),
        ("no_meaning", f"no {special_chars['?']}"),
        ("no_translation_no_meaning", "none"),
    ]

    legend_y = panel.bottom - 14

    toggle_rect = pygame.Rect(panel.right - PAD - 80, legend_y - 11, 80, 22)
    hovered_toggle = toggle_rect.collidepoint(mouse_pos)
    draw_button(
        C.screen,
        toggle_rect,
        "color on" if S.state.colorize_status else "color off",
        bg=C.ORANGE if S.state.colorize_status else C.BROWN,
        fg=C.WHITE,
        radius=8,
        hovered=hovered_toggle,
        font=FONT_SM,
    )

    x = toggle_rect.left - 10
    legend_rects = {}

    for key, short_label in reversed(legend_items):
        selected = key in S.state.status_filters
        mark = special_chars["[OK]"] if selected else special_chars["X"]

        label = f"{short_label} {counts.get(key, 0)}"
        label_w = FONT_SM.size(label)[0]
        chip_w = label_w + 42
        chip_rect = pygame.Rect(x - chip_w, legend_y - 11, chip_w, 22)

        hovered = chip_rect.collidepoint(mouse_pos)

        if S.state.colorize_status:
            fill = C.STATUS_BG.get(key, C.PANEL2)
            border = C.STATUS_BDR.get(key, C.BORDER)
        else:
            fill = C.PANEL2
            border = C.BORDER

        if hovered:
            fill = lighten(fill, 14)
            border = lighten(border, 14)

        pygame.draw.rect(C.screen, fill, chip_rect, border_radius=10)
        pygame.draw.rect(C.screen, border, chip_rect, 1, border_radius=10)

        mark_rect = pygame.Rect(chip_rect.x + 5, chip_rect.y + 5, 12, 12)
        mark_fill = C.GREEN_BG if selected else C.RED_BG
        mark_border = C.GREEN_BDR if selected else C.RED_BDR
        pygame.draw.rect(C.screen, mark_fill, mark_rect, border_radius=4)
        pygame.draw.rect(C.screen, mark_border, mark_rect, 1, border_radius=4)

        mark_img = FONT_SM.render(mark, True, C.TEXT)
        C.screen.blit(mark_img, mark_img.get_rect(center=mark_rect.center))

        blit_text(
            C.screen,
            label,
            FONT_SM,
            C.TEXT,
            mark_rect.right + 6,
            chip_rect.centery,
            anchor="midleft",
        )

        legend_rects[key] = chip_rect
        x = chip_rect.left - 8

    _results_legend_rects["toggle"] = toggle_rect
    _results_legend_rects["items"] = legend_rects

    show_words_rect = pygame.Rect(panel.x + PAD, legend_y - 11, 118, 22)
    show_stats_rect = pygame.Rect(show_words_rect.right + 8, legend_y - 11, 138, 22)

    keyboard_rect = pygame.Rect(panel.centerx - 40, legend_y - 11, 80, 22)
    _results_action_rects["keyboard"] = keyboard_rect
    _results_action_rects["show_words"] = show_words_rect
    _results_action_rects["show_stats"] = show_stats_rect

    draw_button(
        C.screen,
        keyboard_rect,
        f"{special_chars['kb']} on" if S.state.keyboard_on else f"{special_chars['kb']} off",
        bg=C.ORANGE if S.state.keyboard_on else C.BROWN,
        fg=C.WHITE,
        radius=8,
        hovered=keyboard_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )

    draw_button(
        C.screen,
        show_words_rect,
        "Show Words",
        bg=C.TEAL,
        fg=C.WHITE,
        radius=8,
        hovered=show_words_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )
    draw_button(
        C.screen,
        show_stats_rect,
        "Show Statistics",
        bg=C.PURPLE,
        fg=C.WHITE,
        radius=8,
        hovered=show_stats_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )

    keyboard_top = panel.bottom - 8
    if S.state.keyboard_on:
        keyboard_top = draw_virtual_keyboard(C.screen, panel, mouse_pos)

    preview = panel_words[S.state.preview_start : S.state.preview_start + S.state.max_preview]
    if not preview:
        msg = (
            "No categories selected — click a legend chip to show results."
            if not S.state.status_filters
            else f"No results yet {special_chars['-']} press Enter or click Search."
        )
        blit_text(
            C.screen,
            msg,
            FONT_MD,
            C.MUTED,
            panel.x + PAD,
            panel.y + 36 + progress_h,
        )
        return prev_rect, next_rect

    grid_y = panel.y + 34 + progress_h
    per_row = clamp(S.state.results_per_row, MIN_RESULTS_PER_ROW, MAX_RESULTS_PER_ROW)
    cols = per_row
    cw = max(30, (panel.width - 2 * PAD - (cols - 1) * GAP) // cols)
    ch_h = 26
    row_h = ch_h + 4

    grid_bottom = (keyboard_top - 8) if S.state.keyboard_on else (panel.bottom - 8)
    grid_h = max(0, grid_bottom - grid_y)

    grid_rect = pygame.Rect(panel.x + PAD, grid_y, panel.width - 2 * PAD, grid_h)

    _hover_word_rect = None

    for idx, word in enumerate(preview):
        col = idx % cols
        row = idx // cols
        wx = panel.x + PAD + col * (cw + GAP)
        wy = grid_y + row * row_h
        if wy + ch_h > grid_bottom:
            break

        wr = pygame.Rect(wx, wy, cw, ch_h)
        is_hovered = wr.collidepoint(mouse_pos)
        sel_state = S.state.word_selections.get(word)
        status = S.state.results_status_map.get(word, "no_translation_no_meaning")

        if sel_state == "save":
            bg_color = C.GREEN_BG
            bdr_color = C.GREEN_BDR
            marker = special_chars["[OK]"]
        elif sel_state == "exclude":
            bg_color = C.RED_BG
            bdr_color = C.RED_BDR
            marker = special_chars["X"]
        else:
            if S.state.colorize_status:
                bg_color = C.STATUS_BG.get(status, C.PANEL2)
                bdr_color = C.STATUS_BDR.get(status, C.BORDER)
            else:
                bg_color = C.PANEL2
                bdr_color = C.BORDER
            marker = None

        if is_hovered:
            draw_r = wr.inflate(int(wr.w * 0.1), int(wr.h * 0.1))
            _hover_word_rect = (word, wr)
        else:
            draw_r = wr

        pygame.draw.rect(C.screen, bg_color, draw_r, border_radius=6)
        pygame.draw.rect(C.screen, bdr_color, draw_r, 1, border_radius=6)

        wimg = FONT_SM.render(word, True, C.TEXT)
        C.screen.blit(wimg, wimg.get_rect(midleft=(draw_r.x + 8, draw_r.centery)))

        if marker is not None:
            m_img = FONT_SM.render(marker, True, C.TEXT)
            C.screen.blit(
                m_img, m_img.get_rect(midright=(draw_r.right - 8, draw_r.centery))
            )

        _result_word_rects.append((word, wr))

    # ── Words-per-row control (− / count / +) ───────────────────────────
    # Placed left of the total/showing + prev/next nav group so they don't overlap.
    rpr_h = nav_h
    rpr_y = nav_y
    rpr_minus_rect = pygame.Rect(group_x - 120, rpr_y, 20, rpr_h)
    rpr_plus_rect = pygame.Rect(group_x - 35, rpr_y, 20, rpr_h)
    rpr_label_rect = pygame.Rect(
        rpr_minus_rect.right + 2,
        rpr_y,
        rpr_plus_rect.x - rpr_minus_rect.right - 4,
        rpr_h,
    )

    draw_button(
        C.screen,
        rpr_minus_rect,
        "-",
        bg=C.PANEL2,
        fg=C.TEXT,
        radius=6,
        hovered=rpr_minus_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )
    draw_button(
        C.screen,
        rpr_plus_rect,
        "+",
        bg=C.PANEL2,
        fg=C.TEXT,
        radius=6,
        hovered=rpr_plus_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )
    pygame.draw.rect(C.screen, C.PANEL2, rpr_label_rect, border_radius=6)
    pygame.draw.rect(C.screen, C.BORDER, rpr_label_rect, 1, border_radius=6)
    blit_text(
        C.screen,
        f"{per_row}/row",
        FONT_SM,
        C.MUTED,
        rpr_label_rect.centerx,
        rpr_label_rect.centery,
        anchor="center",
    )

    _results_action_rects["per_row_minus"] = rpr_minus_rect
    _results_action_rects["per_row_plus"] = rpr_plus_rect
    _results_scroll_rects["grid"] = grid_rect

    # Draw zoom tooltip near mouse for hovered word
    if _hover_word_rect is not None:
        hword, _ = _hover_word_rect

        lines = []  # list of (text, font, color)
        lines.append((hword, FONT_LG, C.TEXT))

        entry = lookup_word_entry(hword, S.state.language)

        if S.state.show_translation:
            tr = None
            if entry is not None:
                tr = (
                    entry.get("greek_translation")
                    if S.state.language == "english"
                    else entry.get("english_translation")
                )
            tr_text = (
                f"{hword} {special_chars['>']} {tr}"
                if tr
                else f"{hword} {special_chars['>']} (no translation yet)"
            )
            lines.append((tr_text, FONT_MD, C.ACCENT))

        if S.state.show_meaning:
            for ml in format_meaning_lines(entry, S.state.language):
                lines.append((ml, FONT_SM, C.MUTED))

        max_w = 0
        total_h = 0
        line_gap = 3
        for text, font, color in lines:
            w, h = font.size(text)
            max_w = max(max_w, w)
            total_h += h + line_gap

        tip_pad = 10
        tip_w = min(max_w + tip_pad * 2, C.WIDTH - 2 * PAD)
        tip_h = total_h + tip_pad * 2

        tip_rect = pygame.Rect(mouse_pos[0] + 20, mouse_pos[1] + 10, tip_w, tip_h)
        if tip_rect.right > C.WIDTH - PAD:
            tip_rect.right = C.WIDTH - PAD
        if tip_rect.bottom > C.HEIGHT - PAD:
            tip_rect.bottom = C.HEIGHT - PAD
        if tip_rect.left < PAD:
            tip_rect.left = PAD
        if tip_rect.top < PAD:
            tip_rect.top = PAD

        pygame.draw.rect(C.screen, C.PANEL, tip_rect, border_radius=10)
        pygame.draw.rect(C.screen, C.ACCENT, tip_rect, 2, border_radius=10)

        ly = tip_rect.y + tip_pad
        max_text_w = tip_rect.width - tip_pad * 2
        for text, font, color in lines:
            display_text = fit_text_with_ellipsis(text, font, max_text_w)
            img = font.render(display_text, True, color)
            C.screen.blit(img, (tip_rect.x + tip_pad, ly))
            ly += font.size(text)[1] + line_gap

    return prev_rect, next_rect
