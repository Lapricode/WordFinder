"""
Word Finder -- entry point.

This is the original WordFinder.py, refactored into separate modules for
maintainability (wf_constants, wf_search, wf_translate, wf_ui_helpers,
wf_modals, wf_state, wf_render). This file wires everything together and
contains only the main event loop, exactly as before. Behavior is unchanged
from the original single-file version -- this is a pure refactor.

Run this file to start the application, the same way as the original
WordFinder.py:

    python WordFinder.py
"""

import os

import pygame

import wf_constants as C
import wf_state as S
import wf_modals
from wf_constants import clock
from wf_state import (
    state,
    do_search, do_save,
    open_file_dialog, open_text_file, save_file_dialog,
    ph_adjust_cell_count, ph_cell_selected_idx, ph_set_cell_selected_idx, ph_toggle_expand,
    poll_search_job,
    refresh_summary_window, refresh_visible_results, refresh_words_counts,
    toggle_finder_mode,
)
from wf_constants import (
    clamp, set_theme,
    MAX_WORD_LENGTH, MAX_MAX_PREVIEW, MIN_RESULTS_PER_ROW, MAX_RESULTS_PER_ROW,
    PH_ROWS, PH_COLS,
)
from wf_ui_helpers import (
    handle_text_input, handle_backspace_input, handle_delete_input,
    keyboard_char_for,
)
from wf_modals import (
    InfoModal, ProgressModal, EnrichmentModal, ShowWordsModal, AddWordsModal,
    DeleteWordsModal, ShowStatisticsModal, SummaryModal,
)
import wf_render as R
from wf_render import (
    render_header, render_controls, render_file_row,
    render_workspace_lm, render_workspace_ph, render_results,
)


if __name__ == "__main__":
    refresh_words_counts()
    info_modal = InfoModal()
    progress_modal = ProgressModal()
    enrichment_modal = EnrichmentModal()
    words_modal = ShowWordsModal()
    add_modal = AddWordsModal()
    delete_modal = DeleteWordsModal()
    stats_modal = ShowStatisticsModal()
    summary_modal = SummaryModal()

    # wf_modals.py and wf_state.py reference progress_modal / words_modal by name
    # (e.g. EnrichmentModal.open_choice() calls progress_modal.close(), and
    # do_translate_action() calls progress_modal.start()). In the original
    # single-file program these were plain forward references resolved at call
    # time, since everything shared one module namespace. Splitting into modules
    # means those references now live in wf_modals / wf_state, so we publish the
    # two shared instances onto those modules here, before the main loop starts
    # and before any code path could try to use them.
    wf_modals.progress_modal = progress_modal
    wf_modals.words_modal = words_modal
    S.progress_modal = progress_modal
    S.words_modal = words_modal
    dragging = None  # None | 'wl' | 'mp'
    running = True

    # Store layout rects across frames for hit-testing
    _lm_slot_sx = 0
    _lm_slot_ty = 0
    _lm_slot_w = 30
    _lm_slot_h = 32
    _lm_slot_gap = 8
    lm_ui = {}
    _ph_slot_rects = {}

    while running:
        C.screen.fill(C.BG)
        mouse_pos = pygame.mouse.get_pos()

        render_header(mouse_pos)
        (
            t1,
            k1,
            t2,
            k2,
            mode_rects,
            scope_rects,
            lang_rects,
            search_rect,
            finder_btn_rect,
            ph_col_rects,
        ) = render_controls(mouse_pos)
        (
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
        ) = render_file_row(mouse_pos)

        if state.finder_mode == "letter_match":
            slot_w, slot_h, sx, ty, gap, tby, summary_btn, lm_ui = render_workspace_lm(
                mouse_pos
            )
            _lm_slot_sx = sx
            _lm_slot_ty = ty
            _lm_slot_w = slot_w
            _lm_slot_h = slot_h
            _lm_slot_gap = gap
        else:
            tby, summary_btn, _ph_slot_rects = render_workspace_ph(mouse_pos)

        poll_search_job()
        page_prev_rect, page_next_rect = render_results(tby, mouse_pos)
        info_modal.draw(C.screen, C.WIDTH, C.HEIGHT)
        progress_modal.draw(C.screen, C.WIDTH, C.HEIGHT, mouse_pos)
        enrichment_modal.draw(C.screen, C.WIDTH, C.HEIGHT, mouse_pos)
        stats_modal.draw(C.screen, C.WIDTH, C.HEIGHT, mouse_pos)
        words_modal.draw(C.screen, C.WIDTH, C.HEIGHT, mouse_pos)
        add_modal.draw(C.screen, C.WIDTH, C.HEIGHT, mouse_pos)
        delete_modal.draw(C.screen, C.WIDTH, C.HEIGHT, mouse_pos)
        summary_modal.draw(C.screen, C.WIDTH, C.HEIGHT, mouse_pos)

        pygame.display.flip()
        clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.VIDEORESIZE:
                C.WIDTH, C.HEIGHT = event.w, event.h
                C.screen = pygame.display.set_mode((C.WIDTH, C.HEIGHT), pygame.RESIZABLE)

            # Let the enrichment modal get first crack at clicks/keys.
            if enrichment_modal.visible and enrichment_modal.handle_event(
                event, C.WIDTH, C.HEIGHT
            ):
                continue

            progress_modal_was_open = progress_modal.visible
            progress_modal.handle_event(event, C.WIDTH, C.HEIGHT)
            if progress_modal_was_open:
                continue

            modal_was_open = info_modal.visible
            info_modal.handle_event(event, C.WIDTH, C.HEIGHT)
            if modal_was_open:
                continue

            if words_modal.visible and words_modal.handle_event(event, C.WIDTH, C.HEIGHT):
                continue

            if add_modal.visible and add_modal.handle_event(event, C.WIDTH, C.HEIGHT):
                continue

            if delete_modal.visible and delete_modal.handle_event(event, C.WIDTH, C.HEIGHT):
                continue

            if stats_modal.visible and stats_modal.handle_event(event, C.WIDTH, C.HEIGHT):
                continue

            if summary_modal.visible and summary_modal.handle_event(event, C.WIDTH, C.HEIGHT):
                continue

            if event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                btn = event.button

                if btn == 1:
                    # Sliders
                    if t1.collidepoint(mx, my) or k1.collidepoint(mx, my):
                        dragging = "wl"
                    elif t2.collidepoint(mx, my) or k2.collidepoint(mx, my):
                        dragging = "mp"

                    # Results words-per-row controls
                    elif R._results_action_rects.get(
                        "per_row_minus"
                    ) is not None and R._results_action_rects["per_row_minus"].collidepoint(
                        mx, my
                    ):
                        state.results_per_row = clamp(
                            state.results_per_row - 1,
                            MIN_RESULTS_PER_ROW,
                            MAX_RESULTS_PER_ROW,
                        )
                    elif R._results_action_rects.get(
                        "per_row_plus"
                    ) is not None and R._results_action_rects["per_row_plus"].collidepoint(
                        mx, my
                    ):
                        state.results_per_row = clamp(
                            state.results_per_row + 1,
                            MIN_RESULTS_PER_ROW,
                            MAX_RESULTS_PER_ROW,
                        )

                    # Finder mode button
                    elif finder_btn_rect.collidepoint(mx, my):
                        toggle_finder_mode()

                    # Input Mode pill toggle
                    elif mode_rects[0].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_mode = "valid"
                        else:
                            state.ph_mode = "start"
                    elif mode_rects[1].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_mode = "invalid"
                        else:
                            state.ph_mode = "inner"
                    elif mode_rects[2].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_mode = "exist"
                        else:
                            state.ph_mode = "middle"
                    elif mode_rects[3].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_mode = "absent"
                        else:
                            state.ph_mode = "end"

                    # Summary btn
                    elif summary_btn.collidepoint(mx, my):
                        if summary_modal.visible:
                            summary_modal.hide()
                        else:
                            summary_modal.show(state.finder_mode)

                    # PH column toggle (Valid/Invalid/Exist row under Start/Middle/End)
                    elif ph_col_rects is not None and ph_col_rects[0].collidepoint(mx, my):
                        state.ph_col = "valid"
                    elif ph_col_rects is not None and ph_col_rects[1].collidepoint(mx, my):
                        state.ph_col = "invalid"
                    elif ph_col_rects is not None and ph_col_rects[2].collidepoint(mx, my):
                        state.ph_col = "exist"
                    elif ph_col_rects is not None and ph_col_rects[3].collidepoint(mx, my):
                        state.ph_col = "absent"

                    # Translate / Meaning checkboxes
                    elif translate_chk_rect.collidepoint(mx, my):
                        state.show_translation = not state.show_translation
                    elif meaning_chk_rect.collidepoint(mx, my):
                        state.show_meaning = not state.show_meaning

                    # Translation / Meaning buttons
                    elif translate_btn.collidepoint(mx, my):
                        enrichment_modal.open_choice("translation")
                    elif meaning_btn.collidepoint(mx, my):
                        enrichment_modal.open_choice("meaning")

                    # Info btn
                    elif R._info_btn_rect.collidepoint(mx, my):
                        info_modal.show()

                    # Scope pill toggle
                    elif scope_rects[0].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_scope = "single"
                        else:
                            state.ph_scope = "single"
                    elif scope_rects[1].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_scope = "all"
                        else:
                            state.ph_scope = "all"

                    # Language pill toggle
                    elif lang_rects[0].collidepoint(mx, my):
                        state.language = "greek"
                        state.status = "Language: Greek"
                        state.results_cache_dirty = True
                    elif lang_rects[1].collidepoint(mx, my):
                        state.language = "english"
                        state.status = "Language: English"
                        state.results_cache_dirty = True

                    # Search
                    elif search_rect.collidepoint(mx, my):
                        do_search()

                    # File buttons
                    elif gf_btn.collidepoint(mx, my):
                        p = open_file_dialog()
                        if p:
                            state.greek_file = p
                            refresh_words_counts()
                            state.status = f"Greek file: {os.path.basename(p)}"
                    elif ef_btn.collidepoint(mx, my):
                        p = open_file_dialog()
                        if p:
                            state.english_file = p
                            refresh_words_counts()
                            state.status = f"English file: {os.path.basename(p)}"
                    elif sp_btn.collidepoint(mx, my):
                        p = save_file_dialog(state.results_file)
                        if p:
                            state.results_file = p
                            refresh_words_counts()
                            state.status = f"Save path: {os.path.basename(p)}"

                    # Plus / Minus buttons for each file (add / delete words)
                    elif gf_plus.collidepoint(mx, my):
                        add_modal.show(state.greek_file, "greek")
                    elif gf_minus.collidepoint(mx, my):
                        delete_modal.show(state.greek_file, "greek")
                    elif ef_plus.collidepoint(mx, my):
                        add_modal.show(state.english_file, "english")
                    elif ef_minus.collidepoint(mx, my):
                        delete_modal.show(state.english_file, "english")
                    elif sp_plus.collidepoint(mx, my):
                        add_modal.show(state.results_file, "both")
                    elif sp_minus.collidepoint(mx, my):
                        delete_modal.show(state.results_file, "both")
                    elif sv_btn.collidepoint(mx, my):
                        do_save()

                    # Toggle theme
                    elif theme_btn.collidepoint(mx, my):
                        state.theme = "dark" if state.theme == "light" else "light"
                        set_theme(state.theme)
                        state.status = f"Theme: {state.theme.title()}"

                    # File path links
                    elif gf_link.collidepoint(mx, my):
                        open_text_file(state.greek_file)
                    elif ef_link.collidepoint(mx, my):
                        open_text_file(state.english_file)
                    elif sp_link.collidepoint(mx, my):
                        open_text_file(state.results_file)

                    # Results page navigation buttons
                    elif page_prev_rect and page_prev_rect.collidepoint(mx, my):
                        if state.search_results:
                            state.preview_start = max(
                                0, state.preview_start - state.max_preview
                            )
                    elif page_next_rect and page_next_rect.collidepoint(mx, my):
                        if state.search_results:
                            state.preview_start = min(
                                len(state.search_results) - 1,
                                state.preview_start + state.max_preview,
                            )

                    else:
                        if state.finder_mode == "letter_match":
                            clicked = False
                            # Slot selection
                            for i in range(state.word_length):
                                r = pygame.Rect(
                                    _lm_slot_sx + i * (_lm_slot_w + _lm_slot_gap),
                                    _lm_slot_ty,
                                    _lm_slot_w,
                                    _lm_slot_h,
                                )
                                if r.collidepoint(mx, my):
                                    state.selected_pos = i
                                    clicked = True
                                    break
                                    # VALID cells
                            if not clicked:
                                for i, cell in lm_ui.get("valid_cells", []):
                                    if cell.collidepoint(mx, my):
                                        state.selected_pos = i
                                        state.input_mode = "valid"
                                        clicked = True
                                        break

                            # INVALID cells
                            if not clicked:
                                for i, cell in lm_ui.get("invalid_cells", []):
                                    if cell.collidepoint(mx, my):
                                        state.selected_pos = i
                                        state.input_mode = "invalid"
                                        clicked = True
                                        break

                            # EXIST chips (specific item)
                            if not clicked:
                                for ei, chip in lm_ui.get("exist_chips", []):
                                    if chip.collidepoint(mx, my):
                                        state.input_mode = "exist"
                                        state.selected_exist_idx = ei
                                        clicked = True
                                        break

                            # EXIST row (anywhere else in the bar, e.g. empty space or no chips yet)
                            if not clicked:
                                exist_row = lm_ui.get("exist_row")
                                if exist_row is not None and exist_row.collidepoint(
                                    mx, my
                                ):
                                    state.input_mode = "exist"
                                    clicked = True

                            # ABSENT chips (specific item)
                            if not clicked:
                                for ai, chip in lm_ui.get("absent_chips", []):
                                    if chip.collidepoint(mx, my):
                                        state.input_mode = "absent"
                                        state.selected_absent_idx = ai
                                        clicked = True
                                        break

                            # ABSENT row
                            if not clicked:
                                absent_row = lm_ui.get("absent_row")
                                if absent_row is not None and absent_row.collidepoint(mx, my):
                                    state.input_mode = "absent"
                                    clicked = True

                        else:
                            # PH grid clicks
                            clicked_ph = False
                            cells = (
                                _ph_slot_rects.get("cells", {})
                                if isinstance(_ph_slot_rects, dict)
                                else _ph_slot_rects
                            )
                            for (row, col), rdata in cells.items():
                                if rdata["plus"].collidepoint(mx, my):
                                    ph_adjust_cell_count(1, row, col)
                                    clicked_ph = True
                                    break
                                if rdata["minus"].collidepoint(mx, my):
                                    ph_adjust_cell_count(-1, row, col)
                                    clicked_ph = True
                                    break
                                for si, sdata in enumerate(rdata["slots"]):
                                    if sdata["rect"].collidepoint(mx, my):
                                        state.ph_mode = row
                                        state.ph_col = col
                                        ph_set_cell_selected_idx(si, row, col)
                                        if sdata["expand_btn"].collidepoint(mx, my):
                                            ph_toggle_expand()
                                        clicked_ph = True
                                        break
                                if clicked_ph:
                                    break

                        if state.keyboard_on and S._results_keyboard_rects.get("panel") is not None:
                            kp = S._results_keyboard_rects["panel"]
                            if kp.collidepoint(mx, my):
                                controls = S._results_keyboard_rects.get("controls", {})
                                if controls.get("lang") and controls["lang"].collidepoint(mx, my):
                                    state.language = "english" if state.language == "greek" else "greek"
                                    state.status = f"Language: {state.language.title()}"
                                    state.results_cache_dirty = True
                                    break
                                if controls.get("caps") and controls["caps"].collidepoint(mx, my):
                                    state.keyboard_caps = not state.keyboard_caps
                                    break
                                if controls.get("tone") and controls["tone"].collidepoint(mx, my):
                                    state.keyboard_tone = (state.keyboard_tone + 1) % 4
                                    break
                                if controls.get("backspace") and controls["backspace"].collidepoint(mx, my):
                                    handle_backspace_input()
                                    break
                                for base, r in S._results_keyboard_rects.get("keys", []):
                                    if r.collidepoint(mx, my):
                                        handle_text_input(keyboard_char_for(base))
                                        break
                                break

                        # Results panel word selection (left click = save)
                        for word, wr in R._result_word_rects:
                            if wr.collidepoint(mx, my):
                                if state.word_selections.get(word) == "save":
                                    del state.word_selections[word]
                                else:
                                    state.word_selections[word] = "save"
                                break

                        # Results action buttons
                        if R._results_action_rects.get("keyboard") is not None and R._results_action_rects["keyboard"].collidepoint(mx, my):
                            state.keyboard_on = not state.keyboard_on
                            break

                        if R._results_action_rects.get("show_words") is not None and R._results_action_rects["show_words"].collidepoint(mx, my):
                            words_modal.show(state.results_visible_words, state.language)
                            break

                        if R._results_action_rects.get("show_stats") is not None and R._results_action_rects["show_stats"].collidepoint(mx, my):
                            stats_modal.show(state.results_visible_words, state.language)
                            break

                        # Results legend toggles
                        if R._results_legend_rects.get(
                            "toggle"
                        ) is not None and R._results_legend_rects["toggle"].collidepoint(
                            mx, my
                        ):
                            state.colorize_status = not state.colorize_status
                            break

                        clicked_legend = False
                        for status_key, rect in R._results_legend_rects.get(
                            "items", {}
                        ).items():
                            if rect.collidepoint(mx, my):
                                if status_key in state.status_filters:
                                    state.status_filters.remove(status_key)
                                else:
                                    state.status_filters.add(status_key)
                                refresh_visible_results()
                                state.preview_start = 0
                                clicked_legend = True
                                break
                        if clicked_legend:
                            break

                elif btn == 3:
                    # Right click: exclude/deselect in results
                    for word, wr in R._result_word_rects:
                        if wr.collidepoint(mx, my):
                            if state.word_selections.get(word) == "exclude":
                                del state.word_selections[word]
                            else:
                                state.word_selections[word] = "exclude"
                            break

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                dragging = None

            elif event.type == pygame.MOUSEMOTION:
                if dragging == "wl":
                    rel = clamp(event.pos[0] - t1.left, 0, t1.width)
                    if state.finder_mode == "pattern_hunt":
                        all_zone = int(t1.width * 0.04)
                        if rel <= all_zone:
                            state.ph_word_length_all = True
                        else:
                            state.ph_word_length_all = False
                            nw = int(
                                round(
                                    1
                                    + ((rel - all_zone) / max(t1.width - all_zone, 1))
                                    * (MAX_WORD_LENGTH - 1)
                                )
                            )
                            nw = clamp(nw, 1, MAX_WORD_LENGTH)
                            if nw != state.word_length:
                                state.word_length = nw
                                state.rebuild_sets()
                                refresh_summary_window()
                    else:
                        state.ph_word_length_all = False
                        nw = int(round(1 + (rel / t1.width) * (MAX_WORD_LENGTH - 1)))
                        if nw != state.word_length:
                            state.word_length = nw
                            state.rebuild_sets()
                            refresh_summary_window()
                elif dragging == "mp":
                    rel = clamp(event.pos[0] - t2.left, 0, t2.width)
                    state.max_preview = int(
                        round(1 + (rel / t2.width) * (MAX_MAX_PREVIEW - 1))
                    )
                    state.preview_start = clamp(
                        state.preview_start, 0, max(len(state.search_results) - 1, 0)
                    )

            elif event.type == pygame.MOUSEWHEEL:
                wheel_pos = pygame.mouse.get_pos()
                results_panel_rect = R._results_scroll_rects.get("panel")
                if results_panel_rect and results_panel_rect.collidepoint(wheel_pos):
                    # Scroll up (event.y > 0) = fewer words per row (bigger buttons)
                    # Scroll down (event.y < 0) = more words per row (smaller buttons)
                    step = 1 if event.y < 0 else (-1 if event.y > 0 else 0)
                    if step:
                        state.results_per_row = clamp(
                            state.results_per_row + step,
                            MIN_RESULTS_PER_ROW,
                            MAX_RESULTS_PER_ROW,
                        )

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                elif event.key == pygame.K_RETURN:
                    do_search()

                elif event.key == pygame.K_BACKSPACE:
                    handle_backspace_input()
                    refresh_summary_window()

                elif event.key == pygame.K_DELETE:
                    handle_delete_input()
                    refresh_summary_window()

                elif event.key == pygame.K_LEFT:
                    if state.finder_mode == "letter_match":
                        if state.input_mode == "exist":
                            items = state.get_exist_items()
                            if items:
                                state.selected_exist_idx = (
                                    state.selected_exist_idx - 1
                                ) % len(items)
                        elif state.input_mode == "absent":
                            letters = state.get_absent_letters()
                            if letters:
                                state.selected_absent_idx = (
                                    state.selected_absent_idx - 1
                                ) % len(letters)                        
                        else:
                            if state.word_length > 0:
                                state.selected_pos = (
                                    state.selected_pos - 1
                                ) % state.word_length
                    else:
                        if event.mod & pygame.KMOD_SHIFT:
                            cols = PH_COLS
                            cidx = cols.index(state.ph_col)
                            state.ph_col = cols[(cidx - 1) % len(cols)]
                        else:
                            ph_set_cell_selected_idx(
                                ph_cell_selected_idx() - 1, state.ph_mode, state.ph_col
                            )

                elif event.key == pygame.K_RIGHT:
                    if state.finder_mode == "letter_match":
                        if state.input_mode == "exist":
                            items = state.get_exist_items()
                            if items:
                                state.selected_exist_idx = (
                                    state.selected_exist_idx + 1
                                ) % len(items)
                        elif state.input_mode == "absent":
                            letters = state.get_absent_letters()
                            if letters:
                                state.selected_absent_idx = (
                                    state.selected_absent_idx + 1
                                ) % len(letters)                        
                        else:
                            if state.word_length > 0:
                                state.selected_pos = (
                                    state.selected_pos + 1
                                ) % state.word_length
                    else:
                        if event.mod & pygame.KMOD_SHIFT:
                            cols = PH_COLS
                            cidx = cols.index(state.ph_col)
                            state.ph_col = cols[(cidx + 1) % len(cols)]
                        else:
                            ph_set_cell_selected_idx(
                                ph_cell_selected_idx() + 1, state.ph_mode, state.ph_col
                            )

                elif event.key == pygame.K_UP:
                    if state.finder_mode == "letter_match":
                        state.cycle_input_mode_lm(-1)
                    else:
                        rows = PH_ROWS
                        ridx = rows.index(state.ph_mode)
                        state.ph_mode = rows[(ridx - 1) % len(rows)]
                        ph_set_cell_selected_idx(
                            ph_cell_selected_idx(), state.ph_mode, state.ph_col
                        )

                elif event.key == pygame.K_DOWN:
                    if state.finder_mode == "letter_match":
                        state.cycle_input_mode_lm(1)
                    else:
                        rows = PH_ROWS
                        ridx = rows.index(state.ph_mode)
                        state.ph_mode = rows[(ridx + 1) % len(rows)]
                        ph_set_cell_selected_idx(
                            ph_cell_selected_idx(), state.ph_mode, state.ph_col
                        )

                # Tab = toggle finder mode
                elif event.key == pygame.K_TAB:
                    toggle_finder_mode()

                # Space / Shift+Space / Ctrl+Space bindings
                elif event.key == pygame.K_SPACE:
                    if state.finder_mode == "pattern_hunt" and (
                        event.mod & pygame.KMOD_CTRL
                    ):
                        ph_toggle_expand()
                        refresh_summary_window()
                    elif event.mod & pygame.KMOD_SHIFT:
                        if state.finder_mode == "letter_match":
                            state.input_scope = (
                                "all" if state.input_scope == "single" else "single"
                            )
                            state.status = f'Input scope: {"All" if state.input_scope == "all" else "Slot"}'
                        else:
                            state.ph_scope = (
                                "all" if state.ph_scope == "single" else "single"
                            )
                            state.status = f'Pattern scope: {"All" if state.ph_scope == "all" else "Slot"}'
                    else:
                        pass

                # / key = toggle language
                elif event.key in (pygame.K_SLASH, pygame.K_QUESTION):
                    state.language = "english" if state.language == "greek" else "greek"
                    state.status = f"Language: {state.language.title()}"
                    refresh_summary_window()

                elif event.key == pygame.K_s and (event.mod & pygame.KMOD_CTRL):
                    do_save()

                elif event.key == pygame.K_PAGEUP:
                    if state.search_results:
                        state.preview_start = max(
                            0, state.preview_start - state.max_preview
                        )

                elif event.key == pygame.K_PAGEDOWN:
                    if state.search_results:
                        state.preview_start = min(
                            len(state.search_results) - 1,
                            state.preview_start + state.max_preview,
                        )

                elif event.key == pygame.K_LEFTBRACKET:
                    state.results_per_row = clamp(
                        state.results_per_row - 1,
                        MIN_RESULTS_PER_ROW,
                        MAX_RESULTS_PER_ROW,
                    )
                    state.status = f"Words per row: {state.results_per_row}"

                elif event.key == pygame.K_RIGHTBRACKET:
                    state.results_per_row = clamp(
                        state.results_per_row + 1,
                        MIN_RESULTS_PER_ROW,
                        MAX_RESULTS_PER_ROW,
                    )
                    state.status = f"Words per row: {state.results_per_row}"

                elif event.key == pygame.K_i and (event.mod & pygame.KMOD_CTRL):
                    info_modal.show()

                elif (
                    event.key in (pygame.K_EQUALS, pygame.K_PLUS)
                    and (event.mod & pygame.KMOD_SHIFT)
                    and not (event.mod & pygame.KMOD_CTRL)
                ):
                    if state.finder_mode == "pattern_hunt" and state.ph_word_length_all:
                        state.ph_word_length_all = False
                        state.word_length = 1
                    else:
                        state.ph_word_length_all = False
                        if state.word_length < MAX_WORD_LENGTH:
                            state.word_length += 1
                            state.rebuild_sets()
                    refresh_summary_window()

                elif (
                    event.key == pygame.K_MINUS
                    and (event.mod & pygame.KMOD_SHIFT)
                    and not (event.mod & pygame.KMOD_CTRL)
                ):
                    if (
                        state.finder_mode == "pattern_hunt"
                        and state.word_length <= 1
                        and not state.ph_word_length_all
                    ):
                        state.ph_word_length_all = True
                    elif not (
                        state.finder_mode == "pattern_hunt" and state.ph_word_length_all
                    ):
                        if state.word_length > 1:
                            state.word_length -= 1
                            state.rebuild_sets()
                    refresh_summary_window()

                elif (
                    event.key == pygame.K_EQUALS
                    and (event.mod & pygame.KMOD_CTRL)
                    and not (event.mod & pygame.KMOD_SHIFT)
                ):
                    state.max_preview = clamp(state.max_preview + 1, 1, MAX_MAX_PREVIEW)
                    state.preview_start = clamp(
                        state.preview_start, 0, max(len(state.search_results) - 1, 0)
                    )

                elif (
                    event.key == pygame.K_MINUS
                    and (event.mod & pygame.KMOD_CTRL)
                    and not (event.mod & pygame.KMOD_SHIFT)
                ):
                    state.max_preview = clamp(state.max_preview - 1, 1, MAX_MAX_PREVIEW)
                    state.preview_start = clamp(
                        state.preview_start, 0, max(len(state.search_results) - 1, 0)
                    )

                elif event.key == pygame.K_EQUALS and not (
                    event.mod & (pygame.KMOD_CTRL | pygame.KMOD_SHIFT)
                ):
                    if state.finder_mode == "pattern_hunt":
                        ph_adjust_cell_count(1)
                        refresh_summary_window()

                elif event.key == pygame.K_MINUS and not (
                    event.mod & (pygame.KMOD_CTRL | pygame.KMOD_SHIFT)
                ):
                    if state.finder_mode == "pattern_hunt":
                        ph_adjust_cell_count(-1)
                        refresh_summary_window()

                else:
                    ch = event.unicode
                    if len(ch) == 1 and ch.isalpha():
                        handle_text_input(ch)
                        refresh_summary_window()

    if S.tk_root is not None and S.tk_root.winfo_exists():
        S.tk_root.destroy()

    pygame.quit()
