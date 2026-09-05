"""
All modal dialog classes (info, progress, enrichment, word lists, stats, etc).

Part of the Word Finder application (split from the original single-file
WordFinder.py for maintainability). Behavior is unchanged from the original --
this is a pure refactor.
"""

import os
import queue
import pygame
from collections import Counter

import wf_constants as C
import wf_state as S
from wf_constants import (
    FONT_SM, FONT_MD, FONT_LG, FONT_XL, PAD, MAX_WORD_LENGTH, special_chars,
    status_colors,
)
from wf_ui_helpers import (
    blit_text, draw_panel, draw_button, fit_text_with_ellipsis, lighten, _dim_color,
    clamp,
)
from wf_translate import (
    normalize_word, load_words, add_words_to_file, delete_words_from_file,
)
from wf_state import (
    build_summary_lines, copy_to_clipboard, get_tk_root,
    do_translate_action, do_get_meaning_action,
    get_target_words, get_word_status, get_word_translation, get_word_first_definition,
    format_meaning_lines, format_progress_result_lines,
    lookup_word_entry, _get_cached_json,
    rebuild_results_cache, refresh_visible_results, refresh_words_counts,
    save_manual_translation, save_manual_meaning, send_words_to_results,
    _base_letter, _word_letters, _is_vowel, _estimate_syllables,
    _stats_summary, _bucket_label, _top_ngrams, _display_alphabet,
)

# Modal instances created in the entrypoint but referenced by name inside other
# modals (e.g. EnrichmentModal opens progress_modal / words_modal). These are
# assigned by the entrypoint (WordFinder.py) onto this module before the main
# loop starts, matching the original single-file forward-reference behavior.
progress_modal = None
words_modal = None


class InfoModal:
    """Full-screen dimmed overlay showing the instructions. Click outside or press Escape to close."""

    CONTENT = [
        (f"Word Finder {special_chars["-"]} Instructions", "title"),
        ("", "gap"),
        ("Two Modes", "heading"),
        (
            "The program has two search modes, switchable via the red button at the left "
            "of the controls bar, or by pressing Tab:",
            "body",
        ),
        (
            f"Letter Match {special_chars["-"]} classic slot-based filtering",
            "bullet",
        ),
        (
            f"Pattern Hunt {special_chars["-"]} grid-based pattern filtering",
            "bullet",
        ),
        ("", "gap"),
        ("Letter Match", "heading"),
        ("Filters words by applying per-slot letter rules.", "body"),
        (
            f"Four input modes (cycle with {special_chars['^']} {special_chars['v']} or click the pill toggle):",
            "body",
        ),
        (f"Valid {special_chars['-']} the selected letter group must appear in that slot.", "bullet"),
        (f"Invalid {special_chars['-']} the selected letter group must not appear in that slot.", "bullet"),
        (f"Exist {special_chars['-']} the letter must appear somewhere in the word. Repeating a letter in Exist means it must occur multiple times.", "bullet"),
        (f"Absent {special_chars['-']} the letter must not appear anywhere in the word. Each letter can appear at most once in the Absent area.", "bullet"),
        ("", "gap"),
        ("Navigation:", "body"),
        (
            f"{special_chars["<"]} {special_chars[">"]} arrows: move between slots (Valid/Invalid) or between Exist items.",
            "bullet",
        ),
        (
            "Backspace: in Valid/Invalid, erases the most recently added letter/group "
            'from the selected slot (or from all slots if scope is "All"). In Exist/'
            "Absent, deletes the currently selected item.",
            "bullet",
        ),
        (
            "Delete: in Valid/Invalid, fully clears the selected slot (or all slots if "
            'scope is "All"). In Exist/Absent, deletes the currently selected item, same '
            "as Backspace.",
            "bullet",
        ),
        ("Type a letter: adds/removes constraint in current mode.", "bullet"),
        ("The active slot / exist area shows a highlighted border.", "bullet"),
        ("", "gap"),
        ("Slot / All scope (Shift+Space or pill toggle):", "body"),
        (
            f"Slot {special_chars["-"]} input affects only the selected slot.",
            "bullet",
        ),
        (f"All {special_chars["-"]} input affects all slots at once.", "bullet"),
        ("", "gap"),
        (
            "When word length increases, previously entered slot data is preserved. Data "
            "is only removed when the word length shrinks past its position.",
            "body",
        ),
        (
            'The "Slots Review" button opens a popup summarizing all current Letter '
            "Match constraints (Valid, Invalid, Exist, Absent), with Copy and Close "
            "buttons.",
            "body",
        ),
        ("", "gap"),
        ("Pattern Hunt", "heading"),
        (
            "Filters words by a 4x4 grid: rows are Start / Middle / Inner / End and columns are Valid / Invalid / Exist / Absent.",
            "body",
        ),
        ("Pattern matching rows:", "body"),
        (f"Start {special_chars['-']} sequence must match the beginning of the word.", "bullet"),
        (f"Inner {special_chars['-']} sequence may appear anywhere in the word.", "bullet"),
        (f"Middle {special_chars['-']} sequence must appear strictly inside the word.", "bullet"),
        (f"End {special_chars['-']} sequence must match the end of the word.", "bullet"),
        ("Cell behavior:", "body"),
        (f"Valid {special_chars['-']} at least one pattern in the cell must match.", "bullet"),
        (f"Invalid {special_chars['-']} no pattern in the cell may match.", "bullet"),
        (f"Exist {special_chars['-']} every pattern in the cell must appear in the word.", "bullet"),
        (f"Absent {special_chars['-']} every pattern in the cell must be absent from the word.", "bullet"),
        ("", "gap"),
        ("Navigation:", "body"),
        (
            f"{special_chars["^"]} {special_chars["v"]} arrows: move between Start / Middle / End rows.",
            "bullet",
        ),
        (
            f"{special_chars["<"]} {special_chars[">"]} arrows: move between the slots of a certain cell group.",
            "bullet",
        ),
        (
            f"Shift + {special_chars["<"]} {special_chars[">"]} arrows: move between Valid / Invalid / Exist columns.",
            "bullet",
        ),
        ("Click a slot to select it along with its cell group.", "bullet"),
        (
            "Backspace deletes the last character of the current slot's sequence, one "
            "letter at a time; if the slot becomes empty, its expand flag is also cleared.",
            "bullet",
        ),
        (
            "Delete fully clears the current slot's sequence in one action (and its "
            "expand flag).",
            "bullet",
        ),
        ("", "gap"),
        (
            "Expanded matching (Ctrl+Space or the small corner button): Normal mode keeps "
            "the typed sequence literal. Expanded mode shows and matches all accent/case "
            "variants.",
            "body",
        ),
        (
            "The left/right and up/down arrows move between the grid cells, while the "
            "selected cell keeps its own slot index.",
            "body",
        ),
        ("", "gap"),
        (
            'Word length in Pattern Hunt: Drag the slider all the way left to set "Word '
            "Length: All\", which disables length filtering. The slider's left edge is "
            "visually marked in red.",
            "body",
        ),
        ("", "gap"),
        (
            'The "Patterns Review" button opens a popup summarizing all current '
            "Pattern Hunt rules for every row/column, with Copy and Close buttons.",
            "body",
        ),
        ("", "gap"),
        ("Common Controls", "heading"),
        (f"Enter / Search button {special_chars["-"]} run the search.", "bullet"),
        (f"Ctrl+S {special_chars["-"]} save current results to file.", "bullet"),
        (
            f"Page Up / Page Down {special_chars["-"]} scroll through result pages.",
            "bullet",
        ),
        (
            f"Tab {special_chars["-"]} toggle between Letter Match and Pattern Hunt.",
            "bullet",
        ),
        (f"Shift+Space {special_chars["-"]} toggle Slot and All.", "bullet"),
        (
            f"/ (slash) {special_chars["-"]} switch between Greek and English word lists.",
            "bullet",
        ),
        (
            f"Ctrl+Space {special_chars["-"]} expand / collapse Pattern Hunt slot(s).",
            "bullet",
        ),
        (
            f"Ctrl+I or the circular i button {special_chars["-"]} open this instructions window.",
            "bullet",
        ),
        (
            f"Shift + / {special_chars['-']} increase/decrease word length. In Pattern Hunt, "
            'holding at 1 and pressing Shift+- switches to "All"; from "All", Shift++ returns to 1.',
            "bullet",
        ),
        (f"Ctrl + / {special_chars['-']} increase/decrease max preview.", "bullet"),
        (
            f"+ / {special_chars['-']} (Pattern Hunt only) add/remove a pattern slot in the current cell group.",
            "bullet",
        ),
        (
            f"Virtual keyboard button {special_chars['-']} shows or hides the keyboard in the results panel. Use Shift, Tone, Backspace, and Greek/English to switch input behavior.",
            "bullet",
        ),
        ("", "gap"),
        ("Results panel:", "heading"),
        (
            f'Left-click a word {special_chars["-"]} mark it as "to save" (green {special_chars["[OK]"]}).',
            "bullet",
        ),
        (
            f'Right-click a word {special_chars["-"]} mark it as "excluded" (red {special_chars["X"]}).',
            "bullet",
        ),
        (
            "Neutral words use status colors: blue = ok, orange = no_translation, pink = no_meaning, gray = no_translation_no_meaning.",
            "bullet",
        ),
        ("Click again to deselect.", "bullet"),
        (
            "The count of marked/excluded words is shown in the results header.",
            "bullet",
        ),
        ("Save writes all results (or only marked ones if any are marked).", "bullet"),
        ("", "gap"),
        ("Translations & Meanings", "heading"),
        (
            f"Show Translation {special_chars["-"]} hovering a word shows "
            f"[word] {special_chars[">"]} [translation] using the saved "
            "translation JSON files.",
            "bullet",
        ),
        (
            f"Show Meaning {special_chars["-"]} hovering a word shows its "
            "part of speech, definition, and an example, pulled from the saved "
            "meanings JSON file (English words only; Greek words show their "
            "saved English translation instead, since dictionary senses are "
            "English-only).",
            "bullet",
        ),
        ("", "gap"),
        (
            "The Translation and Meaning buttons (below the checkboxes) run "
            "on the current results selection: if any words are marked to save "
            "(green), only those are processed; otherwise every result except "
            "excluded (red) words is processed.",
            "body",
        ),
        (
            "The Translation and Meaning buttons first ask whether you want Set or Get. "
            "Get runs the automatic lookup. Set opens a manual editor with a word droplist.",
            "body",
        ),
        (
            "Both buttons show a progress window with a progress bar and a "
            "running log of completed words while they work in the background, "
            "and save results directly into the greek/english meanings JSON "
            "files as they go.",
            "body",
        ),
        ("", "gap"),
        ("Selection counts", "heading"),
        (
            "The top of the results panel shows how many words are currently "
            f'selected and excluded, e.g. "12 words selected {special_chars['[OK]']}" and "3 words '
            f'excluded {special_chars['X']}". This selection is shared by Save, Translation, and '
            "Meaning.",
            "body",
        ),
        ("", "gap"),
        ("Show Words / Show Statistics", "heading"),
        (
            "Both buttons (below the results panel) operate on the results panel's "
            "current word list.",
            "body",
        ),
        (
            f"Show Words {special_chars['-']} lists the words with Start-letter and "
            "Length filters (droplists scroll with the mouse wheel). Each row also "
            "shows the word's translation and first definition when available, and "
            "is hoverable with the same status colors as the results panel; hover "
            "for the full translation/definition if the row text is truncated.",
            "bullet",
        ),
        (
            f'The "{special_chars[">"]} Results" button in Show Words sends its '
            "currently filtered word list into the results panel (replacing the "
            "current results), ready to be reviewed and saved from there.",
            "bullet",
        ),
        (
            f"Show Statistics {special_chars['-']} bar charts (length, letters, "
            "position, vowel ratio, unique letters, first/last letter, bi-/"
            "tri-/tetra-/penta-/grams) with sorting and orientation controls; bar values "
            "are always visible, and hovering a bar highlights it while dimming the "
            "others.",
            "bullet",
        ),
        (
            "Click any bar in Show Statistics to open a Show Words-style popup "
            "listing exactly the words behind that bar (which also has its own "
            f'"{special_chars[">"]} Results" button).',
            "bullet",
        ),
        ("", "gap"),
        ("Word length per mode", "heading"),
        (
            "Letter Match and Pattern Hunt each remember their own word length "
            "independently, so switching between modes no longer changes the "
            "other mode's word length setting.",
            "body",
        ),
        ("", "gap"),
        ("File path tooltips", "heading"),
        (
            "Hover over any file path in the file row (Greek, English, Save to) "
            "to see its full, untruncated path.",
            "body",
        ),
        ("", "gap"),
        ("Theme", "heading"),
        (
            'The theme button shows "Light" when the light theme is active, and "Dark" '
            "when the dark theme is active. Click to toggle.",
            "body",
        ),
        ("", "gap"),
        ("Language behavior", "heading"),
        (
            "Greek mode understands accented forms and common letter variants. English "
            "mode groups uppercase and lowercase of the same letter.",
            "body",
        ),
        ("", "gap"),
        ("Press  Escape  or click anywhere to close.", "footer"),
    ]

    def __init__(self):
        self.visible = False
        self._scroll = 0
        self._dragging_sb = False
        self._drag_offset = 0

    def show(self):
        self.visible = True
        self._scroll = 0

    def hide(self):
        self.visible = False

    def handle_event(self, event, W, H):
        if not self.visible:
            return

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.hide()
                return
            if event.key == pygame.K_i and (event.mod & pygame.KMOD_CTRL):
                self.hide()
                return

        panel = self._panel_rect(W, H)
        track, thumb = self._scrollbar_rects(panel)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if thumb and thumb.collidepoint(event.pos):
                self._dragging_sb = True
                self._drag_offset = event.pos[1] - thumb.y
            elif not panel.collidepoint(event.pos):
                self.hide()

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging_sb = False

        if event.type == pygame.MOUSEMOTION and self._dragging_sb and track:
            max_scroll = self._max_scroll
            new_y = event.pos[1] - self._drag_offset
            max_thumb_y = track.y + track.height - thumb.height
            ratio = (new_y - track.y) / max(1, max_thumb_y - track.y)
            self._scroll = max(0, min(max_scroll, ratio * max_scroll))

        if event.type == pygame.MOUSEWHEEL:
            if panel.collidepoint(pygame.mouse.get_pos()):
                self._scroll = max(
                    0, min(self._max_scroll, self._scroll - event.y * 20)
                )

    def _panel_rect(self, W, H):
        pw = min(720, W - 80)
        ph = min(640, H - 60)
        return pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)

    def _content_height(self, panel):
        """Recompute the full wrapped content height for the current panel width."""
        PAD_ = 28
        max_w = panel.width - PAD_ * 2
        line_spacing = {
            "title": (FONT_XL, 14),
            "heading": (FONT_LG, 6),
            "body": (FONT_SM, 4),
            "bullet": (FONT_SM, 4),
            "footer": (FONT_SM, 4),
            "gap": (None, 10),
        }
        h = 0
        for text, kind in self.CONTENT:
            font, extra_gap = line_spacing.get(kind, line_spacing["body"])
            if font is None:
                h += extra_gap
                continue
            indent = 18 if kind == "bullet" else 0
            prefix = f"{special_chars["*"]}  " if kind == "bullet" else ""
            for _ in self._wrap(prefix + text, font, max_w - indent):
                h += font.get_height() + extra_gap
        return h

    @property
    def _max_scroll(self):
        # cached each frame in draw(); default 0 before first draw
        return getattr(self, "_max_scroll_cache", 0)

    def _scrollbar_rects(self, panel):
        PAD_ = 28
        visible_h = panel.height - PAD_ * 2
        total_h = self._content_height(panel)
        self._max_scroll_cache = max(0, total_h - visible_h)
        if total_h <= visible_h:
            return None, None
        track = pygame.Rect(panel.right - 16, panel.y + 12, 6, panel.height - 24)
        ratio = visible_h / total_h
        thumb_h = max(20, int(track.height * ratio))
        thumb_y = track.y + int(
            (track.height - thumb_h) * self._scroll / max(1, self._max_scroll_cache)
        )
        thumb = pygame.Rect(track.x, thumb_y, 6, thumb_h)
        return track, thumb

    def draw(self, surface, W, H):
        if not self.visible:
            return

        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        panel = self._panel_rect(W, H)
        pygame.draw.rect(surface, C.PANEL, panel, border_radius=16)
        pygame.draw.rect(surface, C.ACCENT, panel, 2, border_radius=16)

        PAD_ = 28
        content_x = panel.x + PAD_
        max_w = panel.width - PAD_ * 2
        y = panel.y + PAD_ - int(self._scroll)

        line_spacing = {
            "title": (FONT_XL, C.TEXT, 14),
            "heading": (FONT_LG, C.ACCENT, 6),
            "body": (FONT_SM, C.MUTED, 4),
            "bullet": (FONT_SM, C.TEXT, 4),
            "footer": (FONT_SM, C.MUTED, 4),
            "gap": (None, None, 10),
        }

        clip_rect = pygame.Rect(
            panel.x + 2, panel.y + 2, panel.width - 4, panel.height - 4
        )
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect)

        for text, kind in self.CONTENT:
            font, color, extra_gap = line_spacing.get(kind, line_spacing["body"])
            if font is None:
                y += extra_gap
                continue
            indent = 18 if kind == "bullet" else 0
            prefix = f"{special_chars["*"]}  " if kind == "bullet" else ""
            for line in self._wrap(prefix + text, font, max_w - indent):
                if panel.y <= y <= panel.y + panel.height:
                    surface.blit(
                        font.render(line, True, color), (content_x + indent, y)
                    )
                y += font.get_height() + extra_gap

        surface.set_clip(old_clip)

        # Clamp scroll now that we know the real max (also refreshes _max_scroll_cache)
        track, thumb = self._scrollbar_rects(panel)
        self._scroll = max(0, min(self._max_scroll_cache, self._scroll))
        if track:
            pygame.draw.rect(surface, C.PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, C.BORDER, thumb, border_radius=4)

    @staticmethod
    def _wrap(text, font, max_w):
        if not text:
            return [""]
        words = text.split()
        lines, current = [], ""
        for word in words:
            test = (current + " " + word).strip()
            if font.size(test)[0] <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

class ProgressModal:
    """Full-screen dimmed overlay showing progress of a running Translation /
    Meaning job: a progress bar plus a scrolling log of completed words,
    with the processed result shown next to each word."""

    def __init__(self):
        self.visible = False
        self.job = None
        self.title = ""
        self.log_lines = []
        self._scroll = 0
        self._max_scroll_cache = 0
        self._dragging_sb = False
        self._drag_offset = 0

    def start(self, job: "EnrichmentJob", title: str):
        self.job = job
        self.title = title
        self.log_lines = []
        self._scroll = 0
        self._dragging_sb = False
        self._drag_offset = 0
        self.visible = True
        job.start()

    def _panel_rect(self, W, H):
        pw = min(640, W - 80)
        ph = min(560, H - 60)
        return pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)

    def _log_rect(self, panel):
        PAD_ = 24
        x = panel.x + PAD_
        y = panel.y + PAD_
        y += FONT_LG.get_linesize() + 10
        y += 22 + 16
        return pygame.Rect(x, y, panel.width - PAD_ * 2, panel.bottom - y - 60)

    def _content_height(self, panel):
        log_rect = self._log_rect(panel)
        max_w = log_rect.width - 16
        line_h = FONT_SM.get_linesize() + 3
        total_h = 0

        for raw in self.log_lines:
            if raw == "":
                total_h += line_h
            else:
                total_h += max(1, len(self._wrap(raw, FONT_SM, max_w))) * line_h

        return total_h

    def _scrollbar_rects(self, panel):
        log_rect = self._log_rect(panel)
        visible_h = log_rect.height - 12
        total_h = self._content_height(panel)
        self._max_scroll_cache = max(0, total_h - visible_h)

        if total_h <= visible_h:
            return None, None

        track = pygame.Rect(panel.right - 16, panel.y + 12, 6, panel.height - 24)
        ratio = visible_h / total_h
        thumb_h = max(20, int(track.height * ratio))
        thumb_y = track.y + int(
            (track.height - thumb_h) * self._scroll / max(1, self._max_scroll_cache)
        )
        thumb = pygame.Rect(track.x, thumb_y, 6, thumb_h)
        return track, thumb

    def poll(self):
        """Drain the job's queue once per frame."""
        if not self.visible or self.job is None:
            return

        try:
            while True:
                kind, payload = self.job.progress_queue.get_nowait()

                if kind == "result":
                    word = payload["word"]
                    entry = payload["entry"]
                    job_kind = payload["job_kind"]
                    language = payload["language"]

                    self.log_lines.append(f"{special_chars['[OK]']} {word}")
                    for line in format_progress_result_lines(job_kind, entry, language):
                        self.log_lines.append(f"{special_chars['>']} {line}")
                    self.log_lines.append("")

                elif kind == "error":
                    self.log_lines.append(f"{special_chars['X']} {payload}")
                    self.log_lines.append("")

                elif kind == "done":
                    self.log_lines.append(f"{special_chars['[OK]']} Finished.")

        except queue.Empty:
            pass

    def handle_event(self, event, W, H):
        if not self.visible:
            return

        panel = self._panel_rect(W, H)
        btn_y = panel.bottom - 44
        action_btn_w = 85

        finished = self.job is None or (self.job.done_count >= self.job.total)
        paused = bool(self.job and self.job.paused and not finished)

        stop_btn = pygame.Rect(
            (panel.left + panel.right - action_btn_w) / 2, btn_y, action_btn_w, 30
        )
        resume_btn = pygame.Rect(
            (panel.left + panel.right - action_btn_w) / 2, btn_y, action_btn_w, 30
        )
        close_btn = pygame.Rect(panel.right - 96, btn_y, 72, 30)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if finished:
                self.close()
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Click outside closes only after the job is done
            if not panel.collidepoint(event.pos):
                if finished:
                    self.close()
                return

            track, thumb = self._scrollbar_rects(panel)
            if thumb and thumb.collidepoint(event.pos):
                self._dragging_sb = True
                self._drag_offset = event.pos[1] - thumb.y
                return

            if self.job is not None and close_btn.collidepoint(event.pos):
                self.job.cancel()
                self.close()
                return

            if paused and self.job is not None and resume_btn.collidepoint(event.pos):
                self.job.resume()
                return

            if (
                (not finished)
                and (not paused)
                and self.job is not None
                and stop_btn.collidepoint(event.pos)
            ):
                self.job.pause()
                return

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging_sb = False

        if event.type == pygame.MOUSEMOTION and self._dragging_sb:
            track, thumb = self._scrollbar_rects(panel)
            if track and thumb:
                new_y = event.pos[1] - self._drag_offset
                max_thumb_y = track.y + track.height - thumb.height
                ratio = (new_y - track.y) / max(1, max_thumb_y - track.y)
                self._scroll = max(
                    0, min(self._max_scroll_cache, ratio * self._max_scroll_cache)
                )

        if event.type == pygame.MOUSEWHEEL:
            if panel.collidepoint(pygame.mouse.get_pos()):
                self._scroll = max(
                    0, min(self._max_scroll_cache, self._scroll - event.y * 20)
                )

    def close(self):
        self.visible = False
        self.job = None
        self._dragging_sb = False
        self._drag_offset = 0

    def draw(self, surface, W, H, mouse_pos):
        if not self.visible:
            return

        self.poll()

        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        panel = self._panel_rect(W, H)
        pygame.draw.rect(surface, C.PANEL, panel, border_radius=16)
        pygame.draw.rect(surface, C.ACCENT, panel, 2, border_radius=16)

        PAD_ = 24
        x = panel.x + PAD_
        y = panel.y + PAD_

        blit_text(surface, self.title, FONT_LG, C.TEXT, x, y)
        y += FONT_LG.get_linesize() + 10

        total = max(1, self.job.total) if self.job else 1
        done = self.job.done_count if self.job else 0
        pct = clamp(done / total, 0, 1)

        bar_w = panel.width - PAD_ * 2
        bar_h = 22
        bar_rect = pygame.Rect(x, y, bar_w, bar_h)
        pygame.draw.rect(surface, C.PANEL2, bar_rect, border_radius=8)
        fill_w = int(bar_w * pct)
        if fill_w > 0:
            pygame.draw.rect(
                surface, C.GREEN, pygame.Rect(x, y, fill_w, bar_h), border_radius=8
            )
        pygame.draw.rect(surface, C.BORDER, bar_rect, 1, border_radius=8)
        pct_label = f"{done} / {total}  ({int(pct * 100)}%)"
        img = FONT_SM.render(pct_label, True, C.TEXT)
        surface.blit(img, img.get_rect(center=bar_rect.center))
        y += bar_h + 16

        # Log area
        log_rect = pygame.Rect(x, y, bar_w, panel.bottom - y - 60)
        pygame.draw.rect(surface, C.PANEL2, log_rect, border_radius=8)
        pygame.draw.rect(surface, C.BORDER, log_rect, 1, border_radius=8)

        line_h = FONT_SM.get_linesize() + 3
        visible_h = log_rect.height - 12
        total_h = self._content_height(panel)
        self._max_scroll_cache = max(0, total_h - visible_h)
        self._scroll = max(0, min(self._max_scroll_cache, self._scroll))

        old_clip = surface.get_clip()
        surface.set_clip(
            pygame.Rect(
                log_rect.x + 2, log_rect.y + 2, log_rect.width - 4, log_rect.height - 4
            )
        )

        ly = log_rect.y + 6 - int(self._scroll)
        for raw_line in self.log_lines:
            if raw_line == "":
                ly += line_h
                continue

            if raw_line.startswith(f"{special_chars['X']}"):
                color = C.RED
            elif raw_line.startswith(special_chars["[OK]"]):
                color = C.ACCENT
            else:
                color = C.MUTED

            for line in self._wrap(raw_line, FONT_SM, log_rect.width - 16):
                if log_rect.y <= ly <= log_rect.bottom:
                    surface.blit(
                        FONT_SM.render(line, True, color), (log_rect.x + 8, ly)
                    )
                ly += line_h

        surface.set_clip(old_clip)

        track, thumb = self._scrollbar_rects(panel)
        if track:
            pygame.draw.rect(surface, C.PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, C.BORDER, thumb, border_radius=4)

        finished = self.job is None or (self.job.done_count >= self.job.total)
        paused = bool(self.job and self.job.paused and not finished)

        btn_y = panel.bottom - 44
        action_btn_w = 85

        close_btn = pygame.Rect(panel.right - 96, btn_y, 72, 30)
        action_btn = pygame.Rect(
            (panel.left + panel.right - action_btn_w) / 2, btn_y, action_btn_w, 30
        )

        if finished:
            draw_button(
                surface,
                close_btn,
                "Close",
                C.RED,
                C.WHITE,
                radius=7,
                hovered=close_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
        elif paused:
            draw_button(
                surface,
                action_btn,
                "Resume",
                C.PURPLE,
                C.WHITE,
                radius=7,
                hovered=action_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
            draw_button(
                surface,
                close_btn,
                "Close",
                C.RED,
                C.WHITE,
                radius=7,
                hovered=close_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
        else:
            draw_button(
                surface,
                action_btn,
                "Stop",
                C.ORANGE,
                C.WHITE,
                radius=7,
                hovered=action_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
            draw_button(
                surface,
                close_btn,
                "Close",
                C.RED,
                C.WHITE,
                radius=7,
                hovered=close_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
            blit_text(surface, "Working…", FONT_SM, C.MUTED, panel.x + PAD_, btn_y)

    @staticmethod
    def _wrap(text, font, max_w):
        if not text:
            return [""]
        words = text.split()
        lines, current = [], ""
        for word in words:
            test = (current + " " + word).strip()
            if font.size(test)[0] <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

class EnrichmentModal:
    MAX_SENSES = 10

    def __init__(self):
        self.visible = False
        self.stage = None  # "choice" | "manual"
        self.job_kind = None  # "translation" | "meaning"
        self.words = []
        self.word_index = 0
        self.language = "greek"
        self.active_field = None
        self.fields = {}
        self.cursor_pos = 0
        self.cursor_blink_start = 0
        self.drafts = {}
        self._rects = {}
        self.word_scroll = 0
        self.source_data = {}
        self.picker_open = False
        self.picker_scroll = 0
        self.applying = False
        self.apply_items = []
        self.apply_done = 0
        self.apply_total = 0
        self.apply_label = ""
        self.get_action = None
        self.sense_index = 0  # which of the 1-10 definition slots is active
        self._hover_field_key = None  # field key currently hovered, for popup

    def open_choice(self, job_kind):
        pygame.key.stop_text_input()
        progress_modal.close()
        self.visible = True
        self.stage = "choice"
        self.job_kind = job_kind
        self.active_field = None
        self.fields = {}
        self.cursor_pos = 0
        self.cursor_blink_start = pygame.time.get_ticks()
        self.drafts = {}
        self._rects = {}
        self.word_scroll = 0
        self.sense_index = 0
        self.get_action = (
            do_translate_action if job_kind == "translation" else do_get_meaning_action
        )

    def open_manual(self, job_kind):
        progress_modal.close()
        words = get_target_words()
        if not words:
            S.state.status = (
                f"Nothing to edit {special_chars['-']} search results are empty."
            )
            return

        self.visible = True
        self.stage = "manual"
        self.job_kind = job_kind
        self.words = list(words)
        self.word_index = 0
        self.language = S.state.language
        self.source_data = _get_cached_json(self._path())
        self.picker_open = False
        self.picker_scroll = 0
        self.drafts = {}
        self.sense_index = 0
        pygame.key.start_text_input()
        self._load_current()
        self.word_scroll = 0

    def close(self):
        # Restore text input for the main screen. open_choice() and
        # open_manual() both turn text input off/on for their own needs;
        # closing the modal must leave it ON, otherwise Greek letters
        # can no longer be typed into the slots on the main screen.
        pygame.key.start_text_input()
        self.visible = False
        self.stage = None
        self.job_kind = None
        self.words = []
        self.word_index = 0
        self.active_field = None
        self.fields = {}
        self.cursor_pos = 0
        self.cursor_blink_start = pygame.time.get_ticks()
        self.drafts = {}
        self.source_data = {}
        self.picker_open = False
        self.picker_scroll = 0
        self.applying = False
        self.apply_items = []
        self.apply_done = 0
        self.apply_total = 0
        self.apply_label = ""
        self.get_action = None

    def _set_active_field(self, key, cursor_pos=None):
        """Select a manual text field and place the text cursor in it."""
        self.active_field = key
        value = self.fields.get(key, "")
        if cursor_pos is None:
            cursor_pos = len(value)
        self.cursor_pos = clamp(cursor_pos, 0, len(value))
        self.cursor_blink_start = pygame.time.get_ticks()

    def _manual_field_text(self):
        if not self.active_field:
            return ""
        return self.fields.get(self.active_field, "")

    def _reset_cursor_blink(self):
        self.cursor_blink_start = pygame.time.get_ticks()

    def _clipboard_text(self):
        """Read plain text from the system clipboard, best-effort."""
        try:
            # pygame.scrap works when the platform provides a clipboard target.
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            raw = pygame.scrap.get(pygame.SCRAP_TEXT)
            if raw:
                if isinstance(raw, bytes):
                    return raw.decode("utf-8", errors="replace").replace("\x00", "")
                return str(raw)
        except Exception:
            pass

        try:
            root = get_tk_root()
            root.update()
            value = root.clipboard_get()
            return str(value) if value is not None else ""
        except Exception:
            return ""

    def _insert_text_at_cursor(self, value):
        if not self.active_field or not value:
            return False
        value = "".join(ch for ch in value if ch.isprintable() and ch not in "\r\n\t")
        if not value:
            return False

        text = self.fields.get(self.active_field, "")
        pos = clamp(self.cursor_pos, 0, len(text))
        self.fields[self.active_field] = text[:pos] + value + text[pos:]
        self.cursor_pos = pos + len(value)
        self._reset_cursor_blink()
        return True

    def _path(self):
        return (
            S.state.english_meanings_file
            if self.language == "english"
            else S.state.greek_meanings_file
        )

    def _current_word(self):
        if not self.words:
            return ""
        return self.words[self.word_index]

    def _existing_entry(self, word):
        return self.source_data.get(normalize_word(word), {}) or {}

    @staticmethod
    def _sense_at(senses, idx):
        """Return the sense dict at idx from a raw JSON senses list, or {}."""
        if 0 <= idx < len(senses) and isinstance(senses[idx], dict):
            return senses[idx]
        return {}

    def _original_field_value(self, entry, key, sense_idx=None):
        if self.job_kind == "translation":
            if self.language == "english":
                return entry.get("greek_translation", "") or ""
            return entry.get("english_translation", "") or ""

        if sense_idx is None:
            sense_idx = self.sense_index

        senses = entry.get("senses") or []
        sense = self._sense_at(senses, sense_idx)
        examples = sense.get("examples") or []

        if key == "pos":
            return sense.get("part_of_speech", "") or ""
        if key == "def":
            return sense.get("definition", "") or ""
        if key == "ex1":
            return examples[0] if len(examples) > 0 else ""
        if key == "ex2":
            return examples[1] if len(examples) > 1 else ""
        if key == "ex3":
            return examples[2] if len(examples) > 2 else ""

        return ""

    def _slot_has_definition(self, word, sense_idx):
        """True if slot `sense_idx` (1-10 button) has a non-empty definition,
        checking the in-progress draft first and falling back to saved JSON."""
        draft = self.drafts.get(word)
        if draft is not None:
            slots = draft.get("senses") or []
            if 0 <= sense_idx < len(slots):
                return bool(str(slots[sense_idx].get("def", "")).strip())
            return False

        entry = self._existing_entry(word)
        sense = self._sense_at(entry.get("senses") or [], sense_idx)
        return bool(str(sense.get("definition", "")).strip())

    def _field_is_dirty(self, word, key):
        draft = self.drafts.get(word)
        if not draft:
            return False

        if key == "translation":
            current = draft.get("translation", "")
            original = self._original_field_value(self._existing_entry(word), key)
        else:
            slots = draft.get("senses") or []
            current = (
                slots[self.sense_index].get(key, "")
                if 0 <= self.sense_index < len(slots)
                else ""
            )
            original = self._original_field_value(
                self._existing_entry(word), key, self.sense_index
            )

        return (
            str(current).strip() != str(original).strip() and str(current).strip() != ""
        )

    def _picker_item_rects(self, picker_rect):
        if not self.words:
            return []

        row_h = 30
        gap = 5
        visible = max(1, (picker_rect.height - 16) // (row_h + gap))
        start = clamp(self.picker_scroll, 0, max(0, len(self.words) - visible))

        rects = []
        for i, word in enumerate(self.words[start : start + visible], start=start):
            r = pygame.Rect(
                picker_rect.x + 12,
                picker_rect.y + 8 + (i - start) * (row_h + gap),
                picker_rect.width - 24,
                row_h,
            )
            rects.append((i, word, r))
        return rects

    def _seed_meaning_draft(self, word):
        """Build a MAX_SENSES-slot draft list for `word` from saved JSON,
        without overwriting a draft that's already in progress."""
        if word in self.drafts:
            return
        entry = self._existing_entry(word)
        senses = entry.get("senses") or []
        slots = []
        for i in range(self.MAX_SENSES):
            sense = self._sense_at(senses, i)
            examples = sense.get("examples") or []
            slots.append(
                {
                    "pos": sense.get("part_of_speech", "") or "",
                    "def": sense.get("definition", "") or "",
                    "ex1": examples[0] if len(examples) > 0 else "",
                    "ex2": examples[1] if len(examples) > 1 else "",
                    "ex3": examples[2] if len(examples) > 2 else "",
                }
            )
        self.drafts[word] = {"senses": slots}

    def _load_current(self):
        word = self._current_word()
        if not word:
            return

        if self.job_kind == "translation":
            draft = self.drafts.get(word)
            if draft is not None:
                translation = draft.get("translation", "")
            else:
                entry = self._existing_entry(word)
                translation = (
                    entry.get("greek_translation")
                    if self.language == "english"
                    else entry.get("english_translation")
                ) or ""

            self.fields = {"translation": translation}
            self._set_active_field("translation")
            return

        self._seed_meaning_draft(word)
        self.sense_index = clamp(self.sense_index, 0, self.MAX_SENSES - 1)
        slot = self.drafts[word]["senses"][self.sense_index]
        self.fields = {
            "pos": slot.get("pos", ""),
            "def": slot.get("def", ""),
            "ex1": slot.get("ex1", ""),
            "ex2": slot.get("ex2", ""),
            "ex3": slot.get("ex3", ""),
        }
        self._set_active_field("pos")

    def _snapshot_current(self):
        word = self._current_word()
        if not word:
            return

        if self.job_kind == "translation":
            self.drafts[word] = {"translation": self.fields.get("translation", "")}
        else:
            self._seed_meaning_draft(word)
            slots = self.drafts[word]["senses"]
            slots[self.sense_index] = {
                "pos": self.fields.get("pos", ""),
                "def": self.fields.get("def", ""),
                "ex1": self.fields.get("ex1", ""),
                "ex2": self.fields.get("ex2", ""),
                "ex3": self.fields.get("ex3", ""),
            }

    def _apply_current(self):
        word = self._current_word()
        if not word:
            return

        self._snapshot_current()
        S.state.status = f"Staged {self.job_kind} for {word} (press Apply to save)"

    def _apply_all(self):
        self._snapshot_current()
        self.apply_items = list(self.drafts.items())
        self.apply_total = len(self.apply_items)
        self.apply_done = 0
        self.applying = bool(self.apply_items)

        if self.applying:
            S.state.status = f"Applying {self.apply_total} staged edit(s)…"
        else:
            S.state.status = "Nothing to save."

    def _apply_step(self, batch=1):
        if not self.applying:
            return

        for _ in range(batch):
            if not self.apply_items:
                break

            word, draft = self.apply_items.pop(0)
            if self.job_kind == "translation":
                save_manual_translation(
                    word, draft.get("translation", ""), self.language
                )
            else:
                slots = draft.get("senses") or []
                senses_payload = [
                    (
                        slot.get("pos", ""),
                        slot.get("def", ""),
                        [slot.get("ex1", ""), slot.get("ex2", ""), slot.get("ex3", "")],
                    )
                    for slot in slots
                ]
                save_manual_meaning(word, senses_payload, self.language)
            self.apply_done += 1

        if not self.apply_items:
            self.applying = False
            self.source_data = _get_cached_json(self._path())
            self.drafts.clear()
            self._load_current()
            S.state.results_cache_dirty = True
            rebuild_results_cache()
            refresh_visible_results()
            S.state.status = f"Saved {self.apply_done} staged edit(s)"

    def _panel_rect(self, W, H):
        if self.stage == "choice":
            pw = min(420, W - 120)
            ph = min(170, H - 120)
        elif self.job_kind == "translation":
            pw = min(820, W - 80)
            ph = min(400, H - 80)
        else:
            pw = min(820, W - 80)
            ph = min(560, H - 80)
        return pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)

    def _word_button_rects(self, panel):
        if not self.words:
            return []

        left = panel.x + 24
        top = panel.y + 75
        gap_x = 12
        gap_y = 10
        btn_h = 30
        btn_w = 140
        cols = max(2, (panel.width - 48 + gap_x) // (btn_w + gap_x))
        rows = 1
        per_page = cols * rows
        start = clamp(self.word_scroll, 0, max(0, len(self.words) - per_page))
        rects = []

        for i, word in enumerate(self.words[start : start + per_page], start=start):
            row = (i - start) // cols
            col = (i - start) % cols
            r = pygame.Rect(
                left + col * (btn_w + gap_x),
                top + row * (btn_h + gap_y),
                btn_w,
                btn_h,
            )
            rects.append((i, word, r))

        return rects

    def handle_event(self, event, W, H):
        if not self.visible:
            return False

        if self.applying:
            return True

        panel = self._panel_rect(W, H)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return True

            if self.stage == "manual":
                if event.key == pygame.K_TAB:
                    if self.job_kind == "translation":
                        self._set_active_field("translation")
                    else:
                        order = ["pos", "def", "ex1", "ex2", "ex3"]
                        idx = (
                            order.index(self.active_field)
                            if self.active_field in order
                            else 0
                        )
                        self._set_active_field(order[(idx + 1) % len(order)])
                    return True

                if event.key == pygame.K_RETURN:
                    self._apply_current()
                    return True

                if event.key == pygame.K_UP and self.picker_open:
                    self.picker_scroll = max(0, self.picker_scroll - 1)
                    return True

                if event.key == pygame.K_DOWN and self.picker_open:
                    picker = self._rects.get("picker")
                    visible = max(
                        1, ((picker.height - 16) // (30 + 8)) if picker else 1
                    )
                    self.picker_scroll = min(
                        max(0, len(self.words) - visible),
                        self.picker_scroll + 1,
                    )
                    return True

                if self.active_field:
                    text = self._manual_field_text()
                    if event.key == pygame.K_LEFT:
                        self.cursor_pos = max(0, self.cursor_pos - 1)
                        self._reset_cursor_blink()
                        return True

                    if event.key == pygame.K_RIGHT:
                        self.cursor_pos = min(len(text), self.cursor_pos + 1)
                        self._reset_cursor_blink()
                        return True

                    if event.key == pygame.K_HOME:
                        self.cursor_pos = 0
                        self._reset_cursor_blink()
                        return True

                    if event.key == pygame.K_END:
                        self.cursor_pos = len(text)
                        self._reset_cursor_blink()
                        return True

                    if event.key == pygame.K_BACKSPACE:
                        if self.cursor_pos > 0:
                            self.fields[self.active_field] = (
                                text[: self.cursor_pos - 1] + text[self.cursor_pos :]
                            )
                            self.cursor_pos -= 1
                        self._reset_cursor_blink()
                        return True

                    if event.key == pygame.K_DELETE:
                        if self.cursor_pos < len(text):
                            self.fields[self.active_field] = (
                                text[: self.cursor_pos] + text[self.cursor_pos + 1 :]
                            )
                        self._reset_cursor_blink()
                        return True

                    if event.key == pygame.K_v and (event.mod & pygame.KMOD_CTRL):
                        self._insert_text_at_cursor(self._clipboard_text())
                        return True

                    if event.unicode:
                        ch = event.unicode
                        if ch.isprintable():
                            self._insert_text_at_cursor(ch)
                            return True

        if (
            event.type == pygame.MOUSEWHEEL
            and self.stage == "manual"
            and self.picker_open
        ):
            picker = self._rects.get("picker")
            if picker and picker.collidepoint(pygame.mouse.get_pos()):
                visible = max(1, (picker.height - 16) // (30 + 8))
                self.picker_scroll = clamp(
                    self.picker_scroll - event.y,
                    0,
                    max(0, len(self.words) - visible),
                )
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not panel.collidepoint(event.pos):
                if self.stage == "choice":
                    self.close()
                return True

            if self.stage == "choice":
                set_btn = self._rects.get("set")
                get_btn = self._rects.get("get")
                if set_btn and set_btn.collidepoint(event.pos):
                    self.open_manual(self.job_kind)
                elif get_btn and get_btn.collidepoint(event.pos):
                    action = self.get_action or (
                        do_translate_action
                        if self.job_kind == "translation"
                        else do_get_meaning_action
                    )
                    self.close()
                    action()
                return True

            if self.stage == "manual":
                selector = self._rects.get("selector")
                picker = self._rects.get("picker")

                if selector and selector.collidepoint(event.pos):
                    self.picker_open = not self.picker_open
                    return True

                if self.picker_open and picker and picker.collidepoint(event.pos):
                    for idx, word, r in self._picker_item_rects(picker):
                        if r.collidepoint(event.pos):
                            self._snapshot_current()
                            self.word_index = idx
                            self.sense_index = 0
                            self._load_current()
                            self.picker_open = False
                            return True

                if self.picker_open:
                    self.picker_open = False
                    return True

                if self.job_kind == "meaning":
                    for sidx, r in self._rects.get("senses", {}).items():
                        if r.collidepoint(event.pos):
                            if sidx != self.sense_index:
                                self._snapshot_current()
                                self.sense_index = sidx
                                self._load_current()
                            return True

                for key, r in self._rects.get("fields", {}).items():
                    if r.collidepoint(event.pos):
                        value = self.fields.get(key, "")
                        target_x = event.pos[0] - (r.x + 8)
                        cursor_pos = 0
                        for i in range(len(value) + 1):
                            if FONT_SM.size(value[:i])[0] >= target_x:
                                cursor_pos = i
                                break
                            cursor_pos = i
                        self._set_active_field(key, cursor_pos)
                        return True

                apply_btn = self._rects.get("apply")
                close_btn = self._rects.get("close")
                if apply_btn and apply_btn.collidepoint(event.pos):
                    self._apply_all()
                    return True
                if close_btn and close_btn.collidepoint(event.pos):
                    self.close()
                    return True

                return True

        return True

    def draw(self, surface, W, H, mouse_pos):
        if not self.visible:
            return
        if self.applying:
            self._apply_step(batch=1)

        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        panel = self._panel_rect(W, H)
        draw_panel(surface, panel, C.PANEL, C.BORDER, radius=16)

        if self.stage == "choice":
            title = "Translation" if self.job_kind == "translation" else "Meaning"
            blit_text(
                surface, f"{title} mode", FONT_LG, C.TEXT, panel.x + 24, panel.y + 20
            )

            blit_text(
                surface,
                "Choose automatic lookup (Get) or manual entry (Set).",
                FONT_SM,
                C.MUTED,
                panel.x + 24,
                panel.y + 56,
            )

            set_btn = pygame.Rect(panel.x + 24, panel.bottom - 54, 110, 30)
            get_btn = pygame.Rect(panel.right - 134, panel.bottom - 54, 110, 30)
            self._rects = {"set": set_btn, "get": get_btn}

            draw_button(
                surface,
                set_btn,
                "Set",
                bg=C.TEAL,
                fg=C.WHITE,
                hovered=set_btn.collidepoint(mouse_pos),
                font=FONT_SM,
            )
            draw_button(
                surface,
                get_btn,
                "Get",
                bg=C.ORANGE,
                fg=C.WHITE,
                hovered=get_btn.collidepoint(mouse_pos),
                font=FONT_SM,
            )
            return

        title = (
            "Manual Translation" if self.job_kind == "translation" else "Manual Meaning"
        )
        blit_text(surface, title, FONT_LG, C.TEXT, panel.x + 24, panel.y + 18)
        blit_text(
            surface,
            "Click the centered list to switch words. Enter stages the current word edits and Apply saves all of them.",
            FONT_SM,
            C.MUTED,
            panel.x + 24,
            panel.y + 48,
        )

        self._rects = {
            "fields": {},
            "senses": {},
            "apply": None,
            "close": None,
            "selector": None,
            "picker": None,
        }
        self._hover_field_key = None

        HOVER_POPUP_KEYS = {"def", "ex1", "ex2", "ex3"}

        field_y = panel.y + 135
        field_h = 30
        field_w = panel.width - 48
        left = panel.x + 24

        def field(label, key, y, height=30):
            blit_text(surface, label, FONT_SM, C.MUTED, left, y - 20)
            r = pygame.Rect(left, y, field_w, height)
            self._rects["fields"][key] = r
            active = self.active_field == key
            draw_panel(
                surface,
                r,
                C.BLUE_BG if active else C.PANEL2,
                C.ACCENT if active else C.BORDER,
                radius=8,
            )
            text = self.fields.get(key, "")
            txt = fit_text_with_ellipsis(text, FONT_SM, r.width - 24)
            blit_text(surface, txt, FONT_SM, C.TEXT, r.x + 8, r.centery, anchor="midleft")

            if active:
                cursor_pos = clamp(self.cursor_pos, 0, len(text))
                prefix = text[:cursor_pos]
                # Keep the visible cursor near the end of the field when the
                # text is longer than the one-line display area.
                display_text = fit_text_with_ellipsis(text, FONT_SM, r.width - 24)
                if display_text != text and cursor_pos > len(display_text):
                    visible_prefix = display_text[:-3] if display_text.endswith("...") else display_text
                    cursor_x = r.x + 8 + FONT_SM.size(visible_prefix)[0]
                else:
                    cursor_x = r.x + 8 + FONT_SM.size(prefix)[0]

                if ((pygame.time.get_ticks() - self.cursor_blink_start) // 500) % 2 == 0:
                    pygame.draw.line(
                        surface,
                        C.ACCENT,
                        (cursor_x, r.y + 6),
                        (cursor_x, r.bottom - 6),
                        2,
                    )

            if self._field_is_dirty(self._current_word(), key):
                tick = FONT_SM.render(special_chars["[OK]"], True, C.GREEN)
                surface.blit(tick, tick.get_rect(midright=(r.right - 10, r.centery)))

            if (
                key in HOVER_POPUP_KEYS
                and text.strip()
                and r.collidepoint(mouse_pos)
            ):
                self._hover_field_key = key

            return r.bottom + 23

        if self.job_kind == "translation":
            field_y = field("Translation:", "translation", field_y, field_h)
        else:
            # 1-10 definition-slot selector buttons
            word = self._current_word()
            sel_row_y = field_y
            btn_gap = 8
            btn_w = (field_w - btn_gap * (self.MAX_SENSES - 1)) // self.MAX_SENSES
            btn_h = 30
            for i in range(self.MAX_SENSES):
                r = pygame.Rect(
                    left + i * (btn_w + btn_gap), sel_row_y, btn_w, btn_h
                )
                self._rects["senses"][i] = r
                is_active = i == self.sense_index
                has_def = self._slot_has_definition(word, i)
                if has_def:
                    bg = C.GREEN if not is_active else C.GREEN
                    fg = C.WHITE
                    border = C.GREEN_BDR if not is_active else C.ACCENT
                else:
                    bg = C.BLUE_BG if is_active else C.PANEL2
                    fg = C.TEXT
                    border = C.ACCENT if is_active else C.BORDER
                draw_panel(surface, r, bg, border, radius=8)
                blit_text(
                    surface,
                    str(i + 1),
                    FONT_SM,
                    fg,
                    r.centerx,
                    r.centery,
                    anchor="center",
                )
            field_y = sel_row_y + btn_h + 35

            field_y = field(
                "Part of speech (n-noun, v-verb, a/s-adjective, r-adverb):",
                "pos",
                field_y,
                field_h,
            )
            field_y = field(
                f"Definition {self.sense_index + 1}:", "def", field_y, field_h
            )
            field_y = field("Example 1:", "ex1", field_y, field_h)
            field_y = field("Example 2:", "ex2", field_y, field_h)
            field_y = field("Example 3:", "ex3", field_y, field_h)

        bar_rect = pygame.Rect(panel.x + 24, panel.bottom - 65, panel.width - 48, 18)
        if self.applying:
            pct = self.apply_done / max(1, self.apply_total)
            pygame.draw.rect(surface, C.PANEL2, bar_rect, border_radius=8)
            fill_rect = pygame.Rect(
                bar_rect.x, bar_rect.y, int(bar_rect.width * pct), bar_rect.height
            )
            if fill_rect.width > 0:
                pygame.draw.rect(surface, C.GREEN, fill_rect, border_radius=8)
            pygame.draw.rect(surface, C.BORDER, bar_rect, 1, border_radius=8)
            blit_text(
                surface,
                f"{self.apply_done}/{self.apply_total}  ({int(100 * self.apply_done / self.apply_total)}%)",
                FONT_SM,
                C.TEXT,
                bar_rect.centerx,
                bar_rect.centery,
                anchor="center",
            )

        apply_btn = pygame.Rect(panel.x + 24, panel.bottom - 40, 110, 30)
        close_btn = pygame.Rect(panel.right - 134, panel.bottom - 40, 110, 30)
        self._rects["apply"] = apply_btn
        self._rects["close"] = close_btn

        draw_button(
            surface,
            apply_btn,
            "Applying…" if self.applying else "Apply",
            bg=C.TEAL if self.applying else C.GREEN,
            fg=C.WHITE,
            hovered=apply_btn.collidepoint(mouse_pos) and not self.applying,
            font=FONT_SM,
        )
        draw_button(
            surface,
            close_btn,
            "Close",
            bg=C.RED,
            fg=C.WHITE,
            hovered=close_btn.collidepoint(mouse_pos) and not self.applying,
            font=FONT_SM,
        )

        selector = pygame.Rect(panel.centerx - 150, panel.y + 76, 300, 32)
        self._rects["selector"] = selector
        draw_button(
            surface,
            selector,
            fit_text_with_ellipsis(self._current_word(), FONT_SM, selector.width - 20),
            bg=C.BLUE_BG,
            fg=C.TEXT,
            hovered=selector.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        if self.picker_open:
            picker = pygame.Rect(
                selector.x, selector.y + 40, selector.w, min(340, panel.height - 130)
            )
            self._rects["picker"] = picker
            draw_panel(surface, picker, C.PANEL2, C.BORDER, radius=12)

            for idx, word, r in self._picker_item_rects(picker):
                selected = idx == self.word_index
                hovered = r.collidepoint(mouse_pos)

                fill = C.BLUE_BG if selected else C.PANEL
                border = C.ACCENT if selected else C.BORDER
                if hovered:
                    fill = lighten(fill, 12)
                    border = lighten(border, 12)

                pygame.draw.rect(surface, fill, r, border_radius=8)
                pygame.draw.rect(surface, border, r, 1, border_radius=8)
                blit_text(
                    surface,
                    fit_text_with_ellipsis(word, FONT_SM, r.width - 28),
                    FONT_SM,
                    C.TEXT,
                    r.x + 10,
                    r.centery,
                    anchor="midleft",
                )

                word_is_dirty = (
                    self._field_is_dirty(word, "translation")
                    if self.job_kind == "translation"
                    else self._word_has_any_dirty_meaning(word)
                )
                if word_is_dirty:
                    tick = FONT_SM.render(special_chars["[OK]"], True, C.GREEN)
                    surface.blit(
                        tick, tick.get_rect(midright=(r.right - 10, r.centery))
                    )

        # Hover popup: show full content of a definition/example field, the
        # same way hovering a word in the results panel shows its details.
        if self._hover_field_key is not None:
            text = self.fields.get(self._hover_field_key, "")
            if text.strip():
                self._draw_field_hover_popup(surface, W, H, mouse_pos, text)

    def _word_has_any_dirty_meaning(self, word):
        """True if any of the up to 10 sense slots differ from saved JSON,
        used to show the picker's green tick for meaning jobs."""
        draft = self.drafts.get(word)
        if not draft:
            return False
        slots = draft.get("senses") or []
        entry = self._existing_entry(word)
        saved_senses = entry.get("senses") or []
        for i, slot in enumerate(slots):
            saved = self._sense_at(saved_senses, i)
            saved_examples = saved.get("examples") or []
            pairs = [
                (slot.get("pos", ""), saved.get("part_of_speech", "")),
                (slot.get("def", ""), saved.get("definition", "")),
                (slot.get("ex1", ""), saved_examples[0] if saved_examples else ""),
                (
                    slot.get("ex2", ""),
                    saved_examples[1] if len(saved_examples) > 1 else "",
                ),
                (
                    slot.get("ex3", ""),
                    saved_examples[2] if len(saved_examples) > 2 else "",
                ),
            ]
            for current, original in pairs:
                if str(current).strip() != str(original).strip() and str(
                    current
                ).strip():
                    return True
        return False

    def _draw_field_hover_popup(self, surface, W, H, mouse_pos, text):
        """Draw a tooltip box near the mouse with the full field text,
        wrapped, matching the style of the results-panel word tooltip."""
        pad = 10
        max_w = min(420, W - 2 * PAD)
        lines = self._wrap_text(text, FONT_SM, max_w - 2 * pad)

        line_h = FONT_SM.get_height() + 3
        tip_w = max_w
        tip_h = pad * 2 + line_h * len(lines)

        tip_rect = pygame.Rect(mouse_pos[0] + 20, mouse_pos[1] + 10, tip_w, tip_h)
        if tip_rect.right > W - PAD:
            tip_rect.right = W - PAD
        if tip_rect.bottom > H - PAD:
            tip_rect.bottom = H - PAD
        if tip_rect.left < PAD:
            tip_rect.left = PAD
        if tip_rect.top < PAD:
            tip_rect.top = PAD

        pygame.draw.rect(surface, C.PANEL, tip_rect, border_radius=10)
        pygame.draw.rect(surface, C.ACCENT, tip_rect, 2, border_radius=10)

        ly = tip_rect.y + pad
        for line in lines:
            blit_text(surface, line, FONT_SM, C.TEXT, tip_rect.x + pad, ly)
            ly += line_h

    @staticmethod
    def _wrap_text(text, font, max_w):
        words = text.split()
        lines, current = [], ""
        for word in words:
            test = (current + " " + word).strip()
            if font.size(test)[0] <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

class ShowWordsModal:
    ROW_H = 40
    ROW_GAP = 5
    ROW_STRIDE = ROW_H + ROW_GAP

    def __init__(self):
        self.visible = False
        self.words = []
        self.language = "greek"
        self.letter_filter = "All"
        self.length_filter = "All"
        self._scroll = 0
        self._dragging_sb = False
        self._drag_offset = 0
        self._max_scroll_cache = 0

        self._picker_kind = None   # "letter" | "length" | None
        self._picker_open = False
        self._picker_scroll = {"letter": 0, "length": 0}

        self._rects = {}
        self.title = "Show Words"
        self.narrow = False

    def show(self, words, language, title="Show Words", narrow=False):
        self.visible = True
        self.words = list(words or [])
        self.language = language

        # letter_filter / length_filter are intentionally NOT reset here so
        # the previously chosen droplist selections persist across
        # close/reopen. If the language changed since the last time this
        # was open, the previous letter_filter may no longer be part of
        # this language's alphabet, so fall back to "All" only in that case.
        letters, lengths = self._options()
        if self.letter_filter not in letters:
            self.letter_filter = "All"
        if self.length_filter not in lengths:
            self.length_filter = "All"

        self._scroll = 0
        self._picker_kind = None
        self._picker_open = False
        self._picker_scroll = {"letter": 0, "length": 0}
        self._dragging_sb = False
        self.title = title
        self.narrow = narrow

    def hide(self):
        self.visible = False
        self._picker_open = False
        self._picker_kind = None
        self._dragging_sb = False

    def _picker_scroll_value(self, kind):
        return self._picker_scroll.get(kind, 0)

    def _set_picker_scroll_value(self, kind, value):
        self._picker_scroll[kind] = max(0, int(value))

    def _panel_rect(self, W, H):
        pw = min(700 if self.narrow else 800, W - 80)
        ph = min(640, H - 60)
        return pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)

    def _filtered_words(self):
        out = []
        for w in self.words:
            if self.length_filter != "All" and len(w) != self.length_filter:
                continue
            if self.letter_filter != "All":
                first = _base_letter(w[:1], self.language)
                if first != self.letter_filter:
                    continue
            out.append(w)
        return out

    def _options(self):
        letters = ["All"] + _display_alphabet(self.language)
        lengths = ["All"] + list(range(1, MAX_WORD_LENGTH + 1))
        return letters, lengths

    @property
    def _max_scroll(self):
        return getattr(self, "_max_scroll_cache", 0)

    def _scrollbar_rects(self, panel):
        visible_h = panel.height - 182
        total_h = len(self._filtered_words()) * self.ROW_STRIDE
        self._max_scroll_cache = max(0, total_h - visible_h)
        if total_h <= visible_h:
            return None, None

        track = pygame.Rect(panel.right - 16, panel.y + 114, 6, panel.height - 170)
        ratio = visible_h / total_h
        thumb_h = max(20, int(track.height * ratio))
        thumb_y = track.y + int(
            (track.height - thumb_h) * self._scroll / max(1, self._max_scroll_cache)
        )
        return track, pygame.Rect(track.x, thumb_y, 6, thumb_h)

    def _picker_rects(self, selector_rect, options):
        """
        Returns:
            picker_rect, visible_option_rects, visible_count
        """
        picker = pygame.Rect(selector_rect.x, selector_rect.bottom + 6, selector_rect.w, 470)
        row_h = 28
        gap = 4
        visible = max(1, (picker.height - 16) // (row_h + gap))

        kind = self._picker_kind
        scroll_val = clamp(self._picker_scroll_value(kind), 0, max(0, len(options) - visible))
        self._set_picker_scroll_value(kind, scroll_val)

        rects = []
        for i, opt in enumerate(options[scroll_val : scroll_val + visible], start=scroll_val):
            r = pygame.Rect(
                picker.x + 10,
                picker.y + 8 + (i - scroll_val) * (row_h + gap),
                picker.width - 20,
                row_h,
            )
            rects.append((i, opt, r))
        return picker, rects, visible

    def _content_height(self, panel):
        list_top = panel.y + 128
        list_bottom = panel.bottom - 54
        return max(
            0,
            len(self._filtered_words()) * self.ROW_STRIDE - (list_bottom - list_top),
        )

    def handle_event(self, event, W, H):
        if not self.visible:
            return False

        panel = self._panel_rect(W, H)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.hide()
                return True

        track, thumb = self._scrollbar_rects(panel)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if thumb and thumb.collidepoint(event.pos):
                self._dragging_sb = True
                self._drag_offset = event.pos[1] - thumb.y
                return True

            if self._picker_open:
                picker = self._rects.get("picker")
                if picker:
                    options = self._rects.get("picker_options", [])
                    if picker.collidepoint(event.pos):
                        for idx, opt, r in options:
                            if r.collidepoint(event.pos):
                                if self._picker_kind == "letter":
                                    self.letter_filter = opt
                                else:
                                    self.length_filter = opt
                                self._picker_open = False
                                self._picker_kind = None
                                self._scroll = 0
                                return True

                # Click inside panel but outside the open dropdown closes it.
                self._picker_open = False
                self._picker_kind = None
                return True

            if not panel.collidepoint(event.pos):
                self.hide()
                return True

            letter_selector = self._rects.get("letter_selector")
            length_selector = self._rects.get("length_selector")

            if letter_selector and letter_selector.collidepoint(event.pos):
                self._picker_kind = "letter"
                self._picker_open = True
                return True

            if length_selector and length_selector.collidepoint(event.pos):
                self._picker_kind = "length"
                self._picker_open = True
                return True

            to_results_btn = self._rects.get("to_results")
            if to_results_btn and to_results_btn.collidepoint(event.pos):
                send_words_to_results(self._filtered_words())
                self.hide()
                return True

            close_btn = self._rects.get("close")
            if close_btn and close_btn.collidepoint(event.pos):
                self.hide()
                return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging_sb = False

        if event.type == pygame.MOUSEMOTION and self._dragging_sb and track and thumb:
            new_y = event.pos[1] - self._drag_offset
            max_thumb_y = track.y + track.height - thumb.height
            ratio = (new_y - track.y) / max(1, max_thumb_y - track.y)
            self._scroll = max(0, min(self._max_scroll, ratio * self._max_scroll))

        if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEBUTTONDOWN):
            wheel_y = 0
            if event.type == pygame.MOUSEWHEEL:
                wheel_y = event.y
            elif event.button in (4, 5):
                wheel_y = 1 if event.button == 4 else -1

            if wheel_y:
                mp = pygame.mouse.get_pos()

                if self._picker_open:
                    picker = self._rects.get("picker")
                    if picker and picker.collidepoint(mp):
                        letters, lengths = self._options()
                        full_options = letters if self._picker_kind == "letter" else lengths
                        visible = max(1, (picker.height - 16) // (28 + 4))
                        kind = self._picker_kind
                        cur = self._picker_scroll_value(kind)
                        max_scroll = max(0, len(full_options) - visible)
                        self._set_picker_scroll_value(
                            kind,
                            clamp(cur - wheel_y, 0, max_scroll),
                        )
                        return True

                if panel.collidepoint(mp):
                    self._scroll = clamp(self._scroll - wheel_y * 20, 0, self._max_scroll)
                    return True

        return True

    def draw(self, surface, W, H, mouse_pos):
        if not self.visible:
            return

        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        panel = self._panel_rect(W, H)
        draw_panel(surface, panel, C.PANEL, C.BORDER, radius=16)

        blit_text(surface, self.title, FONT_LG, C.TEXT, panel.x + 24, panel.y + 18)
        blit_text(
            surface,
            f"{len(self._filtered_words())} word(s)",
            FONT_SM,
            C.MUTED,
            panel.x + 24,
            panel.y + 50,
        )

        to_results_btn = pygame.Rect(panel.right - 150, panel.y + 18, 126, 30)
        self._rects["to_results"] = to_results_btn
        draw_button(
            surface,
            to_results_btn,
            f"{special_chars['>']} Results",
            bg=C.TEAL,
            fg=C.WHITE,
            hovered=to_results_btn.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        letters, lengths = self._options()

        letter_selector = pygame.Rect(panel.x + 24, panel.y + 82, 150, 30)
        length_selector = pygame.Rect(letter_selector.right + 10, panel.y + 82, 150, 30)
        self._rects["letter_selector"] = letter_selector
        self._rects["length_selector"] = length_selector

        draw_button(
            surface,
            letter_selector,
            f"Start: {self.letter_filter}",
            bg=C.BLUE_BG,
            fg=C.TEXT,
            hovered=letter_selector.collidepoint(mouse_pos),
            font=FONT_SM,
        )
        draw_button(
            surface,
            length_selector,
            f"Length: {self.length_filter}",
            bg=C.BLUE_BG,
            fg=C.TEXT,
            hovered=length_selector.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        list_top = panel.y + 128
        list_bottom = panel.bottom - 54
        visible_words = self._filtered_words()
        line_h = self.ROW_H
        row_stride = self.ROW_STRIDE

        start = clamp(
            self._scroll,
            0,
            max(0, len(visible_words) * row_stride - (list_bottom - list_top)),
        )
        first_row = int(start // row_stride)
        y_off = start % row_stride

        clip = pygame.Rect(panel.x + 20, list_top, panel.width - 40, list_bottom - list_top)
        old_clip = surface.get_clip()
        surface.set_clip(clip)

        hovered_word = None

        available_row_w = panel.width - 56
        widest_word_w = max((FONT_SM.size(w)[0] for w in visible_words), default=0)
        word_col_w = min(int(available_row_w * 0.45), max(120, widest_word_w + 18))
        word_col_w = min(word_col_w, max(90, available_row_w - 80))

        col_gap = 12
        content_pad = 8

        y = list_top - y_off
        for word in visible_words[first_row:]:
            if y > list_bottom:
                break

            row = pygame.Rect(panel.x + 24, y, panel.width - 56, line_h)
            is_hovered = row.collidepoint(mouse_pos) and clip.collidepoint(mouse_pos)

            status = get_word_status(word, self.language)
            if S.state.colorize_status:
                bg_color, bdr_color = status_colors(status)
            else:
                bg_color, bdr_color = C.PANEL2, C.BORDER

            draw_r = row.inflate(int(row.w * 0.015), int(row.h * 0.12)) if is_hovered else row
            if is_hovered:
                bg_color = lighten(bg_color, 10)
                bdr_color = lighten(bdr_color, 10)
                hovered_word = word

            pygame.draw.rect(surface, bg_color, draw_r, border_radius=6)
            pygame.draw.rect(surface, bdr_color, draw_r, 1, border_radius=6)

            translation = get_word_translation(word, self.language)
            definition = get_word_first_definition(word, self.language)

            left_rect = pygame.Rect(
                draw_r.x + content_pad,
                draw_r.y,
                word_col_w,
                draw_r.h,
            )
            right_x = left_rect.right + col_gap
            right_rect = pygame.Rect(
                right_x,
                draw_r.y,
                draw_r.right - right_x - content_pad,
                draw_r.h,
            )

            blit_text(
                surface,
                word,
                FONT_SM,
                C.TEXT,
                left_rect.x,
                left_rect.centery,
                anchor="midleft",
            )

            detail_lines = []
            if translation:
                detail_lines.append((f"{special_chars['>']} {translation}", C.ACCENT))
            if definition:
                detail_lines.append((definition, C.MUTED))

            if detail_lines and right_rect.w > 20:
                detail_font = FONT_SM
                line_gap = 2

                rendered = []
                total_h = 0
                for txt, color in detail_lines:
                    fitted = fit_text_with_ellipsis(txt, detail_font, right_rect.w)
                    rendered.append((fitted, color))
                    total_h += detail_font.size(fitted)[1]
                total_h += line_gap * (len(rendered) - 1)

                cy = draw_r.centery - total_h // 2
                for txt, color in rendered:
                    th = detail_font.size(txt)[1]
                    blit_text(
                        surface,
                        txt,
                        detail_font,
                        color,
                        right_rect.x,
                        cy + th // 2,
                        anchor="midleft",
                    )
                    cy += th + line_gap

            y += row_stride

        surface.set_clip(old_clip)

        track, thumb = self._scrollbar_rects(panel)
        if track:
            pygame.draw.rect(surface, C.PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, C.BORDER, thumb, border_radius=4)

        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 42, 72, 28)
        self._rects["close"] = close_btn
        draw_button(
            surface,
            close_btn,
            "Close",
            bg=C.RED,
            fg=C.WHITE,
            hovered=close_btn.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        if hovered_word is not None:
            lines = [(hovered_word, FONT_MD, C.TEXT)]

            entry = lookup_word_entry(hovered_word, self.language)

            if S.state.show_translation:
                tr = None
                if entry is not None:
                    tr = (
                        entry.get("greek_translation")
                        if self.language == "english"
                        else entry.get("english_translation")
                    )
                tr_text = (
                    f"{hovered_word} {special_chars['>']} {tr}"
                    if tr
                    else f"{hovered_word} {special_chars['>']} (no translation yet)"
                )
                lines.append((tr_text, FONT_SM, C.ACCENT))

            if S.state.show_meaning:
                for ml in format_meaning_lines(entry, self.language):
                    lines.append((ml, FONT_SM, C.MUTED))

            if len(lines) > 1:
                pad = 10
                max_w = 0
                total_h = 0
                gap = 3
                wrapped_lines = []
                for text, font, color in lines:
                    for wline in self._wrap_tooltip(text, font, 380):
                        wrapped_lines.append((wline, font, color))
                        w, h = font.size(wline)
                        max_w = max(max_w, w)
                        total_h += h + gap

                tip_w = min(max_w + pad * 2, W - 2 * PAD)
                tip_h = total_h + pad * 2
                tip_rect = pygame.Rect(mouse_pos[0] + 20, mouse_pos[1] + 10, tip_w, tip_h)
                if tip_rect.right > W - PAD:
                    tip_rect.right = W - PAD
                if tip_rect.bottom > H - PAD:
                    tip_rect.bottom = H - PAD
                if tip_rect.left < PAD:
                    tip_rect.left = PAD
                if tip_rect.top < PAD:
                    tip_rect.top = PAD

                pygame.draw.rect(surface, C.PANEL, tip_rect, border_radius=10)
                pygame.draw.rect(surface, C.ACCENT, tip_rect, 2, border_radius=10)

                ly = tip_rect.y + pad
                for text, font, color in wrapped_lines:
                    surface.blit(font.render(text, True, color), (tip_rect.x + pad, ly))
                    ly += font.size(text)[1] + gap

        # Draw dropdowns last so they appear above everything else.
        self._rects["picker"] = None
        self._rects["picker_options"] = []

        if self._picker_open:
            selector = letter_selector if self._picker_kind == "letter" else length_selector
            options = letters if self._picker_kind == "letter" else lengths

            picker, option_rects, visible = self._picker_rects(selector, options)
            self._rects["picker"] = picker
            self._rects["picker_options"] = option_rects

            draw_panel(surface, picker, C.PANEL2, C.BORDER, radius=12)

            for idx, opt, r in option_rects:
                selected = (
                    (self._picker_kind == "letter" and opt == self.letter_filter)
                    or (self._picker_kind == "length" and opt == self.length_filter)
                )
                hovered = r.collidepoint(mouse_pos)
                fill = C.BLUE_BG if selected else C.PANEL
                border = C.ACCENT if selected else C.BORDER
                if hovered:
                    fill = lighten(fill, 12)
                    border = lighten(border, 12)

                pygame.draw.rect(surface, fill, r, border_radius=8)
                pygame.draw.rect(surface, border, r, 1, border_radius=8)
                blit_text(
                    surface,
                    str(opt),
                    FONT_SM,
                    C.TEXT,
                    r.x + 10,
                    r.centery,
                    anchor="midleft",
                )

    @staticmethod
    def _wrap_tooltip(text, font, max_w):
        if not text:
            return [""]
        words = text.split()
        lines, current = [], ""
        for word in words:
            test = (current + " " + word).strip()
            if font.size(test)[0] <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

class AddWordsModal:
    """Modal to add user-entered words to a chosen text file."""
    ROW_H = 32

    def __init__(self):
        self.visible = False
        self.language = "greek"
        self.file_path = None
        self.title = "Add Words"
        self.input_text = ""
        self.items = []  # words added by user but not yet saved
        self._scroll = 0
        self._saving = False
        self._progress = 0
        self._rects = {}
        self.active_field = None
        self.cursor_pos = 0
        self.cursor_blink_start = pygame.time.get_ticks()
        self._dragging_sb = False
        self._drag_offset = 0
        self._max_scroll = 0

    def show(self, file_path, language):
        self.visible = True
        self.file_path = file_path
        self.language = language
        self.title = f"Add Words to {os.path.basename(file_path) if file_path else 'file'}"
        self.input_text = ""
        self.items = []
        self._saving = False
        self._progress = 0
        # Make input field active immediately and enable text input
        self._set_active_field("input")
        try:
            pygame.key.start_text_input()
        except Exception:
            pass

    def hide(self):
        self.visible = False
        try:
            pygame.key.start_text_input()
        except Exception:
            pass

    def handle_event(self, event, W, H):
        if not self.visible:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.hide()
                return True
            if self.active_field == "input":
                # Cursor/edition keys
                if event.key == pygame.K_RETURN:
                    txt = self.input_text.strip()
                    if txt:
                        self.items.append(txt)
                        self.input_text = ""
                        self._set_active_field("input")
                        self._scroll = max(0, self._max_scroll)
                    return True
                if event.key == pygame.K_BACKSPACE:
                    if self.cursor_pos > 0:
                        self.input_text = (
                            self.input_text[: self.cursor_pos - 1]
                            + self.input_text[self.cursor_pos :]
                        )
                        self.cursor_pos = max(0, self.cursor_pos - 1)
                    return True
                if event.key == pygame.K_DELETE:
                    if self.cursor_pos < len(self.input_text):
                        self.input_text = (
                            self.input_text[: self.cursor_pos]
                            + self.input_text[self.cursor_pos + 1 :]
                        )
                    return True
                if event.key == pygame.K_LEFT:
                    self.cursor_pos = max(0, self.cursor_pos - 1)
                    return True
                if event.key == pygame.K_RIGHT:
                    self.cursor_pos = min(len(self.input_text), self.cursor_pos + 1)
                    return True
                if event.key == pygame.K_HOME:
                    self.cursor_pos = 0
                    return True
                if event.key == pygame.K_END:
                    self.cursor_pos = len(self.input_text)
                    return True
        if event.type == pygame.TEXTINPUT and self.active_field == "input":
            # insert at cursor
            pre = self.input_text[: self.cursor_pos]
            post = self.input_text[self.cursor_pos :]
            self.input_text = pre + event.text + post
            self.cursor_pos += len(event.text)
            return True

        # Mouse / wheel
        if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEBUTTONDOWN):
            wheel_y = 0
            if event.type == pygame.MOUSEWHEEL:
                wheel_y = event.y
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
                wheel_y = 1 if event.button == 4 else -1
            if wheel_y:
                # scroll list
                self._scroll = clamp(self._scroll - wheel_y * 20, 0, self._max_scroll)
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mp = event.pos
            panel = self._panel_rect(W, H)
            if not panel.collidepoint(mp):
                self.hide()
                return True
            # input field click: set cursor position
            inp_rect = self._rects.get("input")
            if inp_rect and inp_rect.collidepoint(mp):
                value = self.input_text
                target_x = mp[0] - (inp_rect.x + 8)
                cursor_pos = 0
                for i in range(len(value) + 1):
                    if FONT_SM.size(value[:i])[0] >= target_x:
                        cursor_pos = i
                        break
                    cursor_pos = i
                self._set_active_field("input", cursor_pos)
                return True

            apply_btn = self._rects.get("apply")
            close_btn = self._rects.get("close")
            # scrollbar thumb handling
            # compute list geometry and scrollbar rects to allow dragging
            list_top = inp_rect.bottom + 12 if inp_rect else panel.y + 100
            list_h = panel.bottom - list_top - 64
            row_stride = self.ROW_H + 6
            total_h = len(self.items) * row_stride
            track, thumb = self._scrollbar_rects(panel, list_top, list_h, total_h)
            if thumb and thumb.collidepoint(mp):
                self._dragging_sb = True
                self._drag_offset = mp[1] - thumb.y
                return True

            if close_btn and close_btn.collidepoint(mp):
                self.hide()
                return True
            if apply_btn and apply_btn.collidepoint(mp):
                # perform save
                self._saving = True
                added, rejected = add_words_to_file(self.file_path, self.items, self.language)
                self._progress = 100
                # show status then close
                S.state.status = f"Added {added} words. Rejected: {len(rejected)}"
                refresh_words_counts()
                self._saving = False
                self.hide()
                return True
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging_sb = False
        if event.type == pygame.MOUSEMOTION and getattr(self, "_dragging_sb", False):
            # dragging scrollbar
            panel = self._panel_rect(W, H)
            inp_rect = self._rects.get("input")
            list_top = inp_rect.bottom + 12 if inp_rect else panel.y + 100
            list_h = panel.bottom - list_top - 64
            row_stride = self.ROW_H + 6
            total_h = len(self.items) * row_stride
            track, thumb = self._scrollbar_rects(panel, list_top, list_h, total_h)
            if track and thumb:
                new_y = event.pos[1] - self._drag_offset
                max_thumb_y = track.y + track.height - thumb.height
                ratio = (new_y - track.y) / max(1, max_thumb_y - track.y)
                self._scroll = max(0, min(self._max_scroll, int(ratio * self._max_scroll)))
            return True
        return True

    def _set_active_field(self, key, cursor_pos=None):
        self.active_field = key
        value = self.input_text if key == "input" else ""
        if cursor_pos is None:
            cursor_pos = len(value)
        self.cursor_pos = clamp(cursor_pos, 0, len(value))
        self.cursor_blink_start = pygame.time.get_ticks()

    def _scrollbar_rects(self, panel, list_top, list_h, total_h):
        # returns (track, thumb) or (None, None)
        self._max_scroll = max(0, total_h - list_h)
        if total_h <= list_h:
            return None, None
        track = pygame.Rect(panel.right - 28, list_top + 2, 8, list_h - 4)
        ratio = list_h / total_h
        thumb_h = max(20, int(track.height * ratio))
        thumb_y = track.y + int((track.height - thumb_h) * (self._scroll / max(1, self._max_scroll)))
        return track, pygame.Rect(track.x, thumb_y, track.width, thumb_h)

    def _panel_rect(self, W, H):
        pw = min(700, W - 80)
        ph = min(420, H - 80)
        return pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)

    def draw(self, surface, W, H, mouse_pos):
        if not self.visible:
            return
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surface.blit(overlay, (0, 0))
        panel = self._panel_rect(W, H)
        draw_panel(surface, panel, C.PANEL, C.BORDER, radius=12)
        blit_text(surface, self.title, FONT_LG, C.TEXT, panel.x + 20, panel.y + 14)

        # Input field (styled like other modals)
        inp_rect = pygame.Rect(panel.x + 20, panel.y + 64, panel.width - 40, 34)
        active = self.active_field == "input"
        draw_panel(surface, inp_rect, C.BLUE_BG if active else C.PANEL2, C.ACCENT if active else C.BORDER, radius=8)
        txt = self.input_text if self.input_text else "Type a word and press Enter"
        color = C.TEXT if self.input_text else C.MUTED
        blit_text(surface, txt, FONT_SM, color, inp_rect.x + 8, inp_rect.centery, anchor="midleft")
        # draw cursor when active
        if active:
            cursor_pos = clamp(getattr(self, "cursor_pos", 0), 0, len(self.input_text))
            prefix = self.input_text[:cursor_pos]
            display_text = fit_text_with_ellipsis(self.input_text, FONT_SM, inp_rect.width - 24)
            if display_text != self.input_text and cursor_pos > len(display_text):
                visible_prefix = display_text[:-3] if display_text.endswith("...") else display_text
                cursor_x = inp_rect.x + 8 + FONT_SM.size(visible_prefix)[0]
            else:
                cursor_x = inp_rect.x + 8 + FONT_SM.size(prefix)[0]
            if ((pygame.time.get_ticks() - getattr(self, "cursor_blink_start", 0)) // 500) % 2 == 0:
                pygame.draw.line(surface, C.ACCENT, (cursor_x, inp_rect.y + 6), (cursor_x, inp_rect.bottom - 6), 2)
        self._rects["input"] = inp_rect

        # Items list
        list_top = inp_rect.bottom + 12
        list_h = panel.bottom - list_top - 64
        clip = pygame.Rect(panel.x + 20, list_top, panel.width - 40, list_h)
        old_clip = surface.get_clip()
        surface.set_clip(clip)
        row_stride = self.ROW_H + 6
        total_h = len(self.items) * row_stride
        self._max_scroll = max(0, total_h - list_h)
        y = list_top - self._scroll
        for i, w in enumerate(self.items):
            r = pygame.Rect(panel.x + 26, y, panel.width - 52 - 12, self.ROW_H)
            hovered = r.collidepoint(mouse_pos)
            # hover effect: slightly highlighted background
            if hovered:
                pygame.draw.rect(surface, C.BLUE_BG, r, border_radius=8)
                pygame.draw.rect(surface, C.ACCENT, r, 2, border_radius=8)
            else:
                pygame.draw.rect(surface, C.PANEL2, r, border_radius=8)
                pygame.draw.rect(surface, C.BORDER, r, 1, border_radius=8)
            blit_text(surface, w, FONT_SM, C.TEXT, r.x + 8, r.centery, anchor="midleft")
            # store rect for potential interactions/hover lookup
            self._rects[f"item_{i}"] = r
            y += row_stride
        surface.set_clip(old_clip)

        # Scrollbar
        if total_h > list_h:
            track = pygame.Rect(panel.right - 28, list_top + 2, 8, list_h - 4)
            pygame.draw.rect(surface, C.PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, C.BORDER, track, 1, border_radius=4)
            ratio = list_h / total_h
            thumb_h = max(20, int(track.height * ratio))
            thumb_y = track.y + int((track.height - thumb_h) * (self._scroll / max(1, self._max_scroll)))
            thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_h)
            pygame.draw.rect(surface, C.ACCENT, thumb, border_radius=4)
            # store scrollbar rects for interaction
            self._rects["_sb_track"] = track
            self._rects["_sb_thumb"] = thumb

        # Buttons
        apply_btn = pygame.Rect(panel.x + 20, panel.bottom - 48, 120, 32)
        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 48, 72, 32)
        self._rects["apply"] = apply_btn
        self._rects["close"] = close_btn
        draw_button(surface, apply_btn, "Apply", bg=C.TEAL, fg=C.WHITE, hovered=apply_btn.collidepoint(mouse_pos), font=FONT_SM)
        draw_button(surface, close_btn, "Close", bg=C.RED, fg=C.WHITE, hovered=close_btn.collidepoint(mouse_pos), font=FONT_SM)

class DeleteWordsModal:
    """Modal to search and delete words from a file."""
    ROW_H = 32

    def __init__(self):
        self.visible = False
        self.language = "greek"
        self.file_path = None
        self.title = "Delete Words"
        self.search_text = ""
        self.matches = []
        self.selected = set()
        self._scroll = 0
        self._rects = {}
        self.active_field = None
        self.cursor_pos = 0
        self.cursor_blink_start = pygame.time.get_ticks()
        self._dragging_sb = False
        self._drag_offset = 0
        self._max_scroll = 0
        # Cache of loaded word-sets for quick membership checks while drawing
        # Keys: 'greek', 'english', 'results' -> set(words)
        self._file_sets = {}
        # Track mtimes to avoid unnecessary reloads
        self._file_mtimes = {}

    def show(self, file_path, language):
        self.visible = True
        self.file_path = file_path
        self.language = language
        self.title = f"Delete Words from {os.path.basename(file_path) if file_path else 'file'}"
        self.search_text = ""
        # Ensure previously selected items that exist in this file appear immediately
        try:
            all_words = list(load_words(self.file_path)) if self.file_path else []
        except Exception:
            all_words = []
        sel_in_file = [w for w in self.selected if w in all_words]
        # show selected items first so the user can confirm/delete them
        self.matches = sel_in_file.copy()
        # keep previous selections if any, do not clear self.selected here
        # make search field active immediately and enable text input
        self._set_active_field("search")
        try:
            pygame.key.start_text_input()
        except Exception:
            pass
        # preload commonly used word-sets once to avoid per-frame disk IO
        try:
            self._load_file_sets()
        except Exception:
            # non-fatal: continue without cache
            self._file_sets = {}
            self._file_mtimes = {}

    def hide(self):
        self.visible = False
        try:
            pygame.key.start_text_input()
        except Exception:
            pass

    def handle_event(self, event, W, H):
        if not self.visible:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.hide()
                return True
            if self.active_field == "search":
                if event.key == pygame.K_RETURN:
                    # perform search
                    all_words = load_words(self.file_path) if self.file_path else []
                    q = self.search_text.strip().casefold()
                    if q:
                        found = [w for w in all_words if q in w.casefold()]
                    else:
                        found = []
                    # ensure selected items remain in the list
                    sel_in_file = [w for w in self.selected if w in all_words]
                    # build matches: selected first, then found excluding selected
                    self.matches = sel_in_file + [w for w in found if w not in self.selected]
                    # reset scroll to top
                    self._scroll = 0
                    return True
                if event.key == pygame.K_BACKSPACE:
                    if self.cursor_pos > 0:
                        self.search_text = (
                            self.search_text[: self.cursor_pos - 1]
                            + self.search_text[self.cursor_pos :]
                        )
                        self.cursor_pos = max(0, self.cursor_pos - 1)
                    return True
                if event.key == pygame.K_DELETE:
                    if self.cursor_pos < len(self.search_text):
                        self.search_text = (
                            self.search_text[: self.cursor_pos]
                            + self.search_text[self.cursor_pos + 1 :]
                        )
                    return True
                if event.key == pygame.K_LEFT:
                    self.cursor_pos = max(0, self.cursor_pos - 1)
                    return True
                if event.key == pygame.K_RIGHT:
                    self.cursor_pos = min(len(self.search_text), self.cursor_pos + 1)
                    return True
                if event.key == pygame.K_HOME:
                    self.cursor_pos = 0
                    return True
                if event.key == pygame.K_END:
                    self.cursor_pos = len(self.search_text)
                    return True
        if event.type == pygame.TEXTINPUT and self.active_field == "search":
            pre = self.search_text[: self.cursor_pos]
            post = self.search_text[self.cursor_pos :]
            self.search_text = pre + event.text + post
            self.cursor_pos += len(event.text)
            return True

        # mouse wheel scrolling
        if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEBUTTONDOWN):
            wheel_y = 0
            if event.type == pygame.MOUSEWHEEL:
                wheel_y = event.y
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
                wheel_y = 1 if event.button == 4 else -1
            if wheel_y:
                self._scroll = clamp(self._scroll - wheel_y * 20, 0, self._max_scroll)
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mp = event.pos
            panel = self._panel_rect(W, H)
            if not panel.collidepoint(mp):
                self.hide()
                return True
            inp_rect = self._rects.get("input")
            if inp_rect and inp_rect.collidepoint(mp):
                # set cursor position based on click
                value = self.search_text
                target_x = mp[0] - (inp_rect.x + 8)
                cursor_pos = 0
                for i in range(len(value) + 1):
                    if FONT_SM.size(value[:i])[0] >= target_x:
                        cursor_pos = i
                        break
                    cursor_pos = i
                self._set_active_field("search", cursor_pos)
                return True

            apply_btn = self._rects.get("apply")
            close_btn = self._rects.get("close")
            # scrollbar thumb handling
            list_top = inp_rect.bottom + 12 if inp_rect else panel.y + 100
            list_h = panel.bottom - list_top - 64
            row_stride = self.ROW_H + 6
            total_h = len(self.matches) * row_stride
            track, thumb = self._scrollbar_rects(panel, list_top, list_h, total_h)
            if thumb and thumb.collidepoint(mp):
                self._dragging_sb = True
                self._drag_offset = mp[1] - thumb.y
                return True

            if close_btn and close_btn.collidepoint(mp):
                self.hide()
                return True
            if apply_btn and apply_btn.collidepoint(mp):
                # delete selected
                deleted = delete_words_from_file(self.file_path, list(self.selected))
                S.state.status = f"Deleted {deleted} words"
                refresh_words_counts()
                self.hide()
                return True
            # check clicks on match rows
            list_top = inp_rect.bottom + 12 if inp_rect else panel.y + 100
            row_stride = self.ROW_H + 6
            list_h = panel.bottom - list_top - 64
            # Only check visible rows to avoid iterating the whole list
            first_idx = max(0, int(self._scroll // row_stride))
            visible_count = int(list_h // row_stride) + 3
            last_idx = min(len(self.matches), first_idx + visible_count)
            y = list_top - self._scroll + first_idx * row_stride
            for i, w in enumerate(self.matches[first_idx:last_idx], start=first_idx):
                r = pygame.Rect(panel.x + 26, y, panel.width - 52 - 12, self.ROW_H)
                if r.collidepoint(mp):
                    if w in self.selected:
                        self.selected.remove(w)
                    else:
                        self.selected.add(w)
                    # keep the selected item in matches even after new searches
                    return True
                y += row_stride
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging_sb = False
        if event.type == pygame.MOUSEMOTION and getattr(self, "_dragging_sb", False):
            panel = self._panel_rect(W, H)
            inp_rect = self._rects.get("input")
            list_top = inp_rect.bottom + 12 if inp_rect else panel.y + 100
            list_h = panel.bottom - list_top - 64
            row_stride = self.ROW_H + 6
            total_h = len(self.matches) * row_stride
            track, thumb = self._scrollbar_rects(panel, list_top, list_h, total_h)
            if track and thumb:
                new_y = event.pos[1] - self._drag_offset
                max_thumb_y = track.y + track.height - thumb.height
                ratio = (new_y - track.y) / max(1, max_thumb_y - track.y)
                self._scroll = max(0, min(self._max_scroll, int(ratio * self._max_scroll)))
            return True
        return True

    def _panel_rect(self, W, H):
        pw = min(700, W - 80)
        ph = min(520, H - 80)
        return pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)

    def _load_file_sets(self):
        """Load greek/english/results files into sets and cache them, skipping reload if mtime unchanged."""
        files = {
            "greek": getattr(S.state, "greek_file", None),
            "english": getattr(S.state, "english_file", None),
            "results": getattr(S.state, "results_file", None),
        }
        for key, path in files.items():
            if not path:
                self._file_sets[key] = set()
                self._file_mtimes[key] = None
                continue
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                mtime = None
            if self._file_mtimes.get(key) == mtime and key in self._file_sets:
                # cached and unchanged
                continue
            try:
                words = set(load_words(path))
            except Exception:
                words = set()
            self._file_sets[key] = words
            self._file_mtimes[key] = mtime

    def _set_active_field(self, key, cursor_pos=None):
        self.active_field = key
        value = self.search_text if key == "search" else ""
        if cursor_pos is None:
            cursor_pos = len(value)
        self.cursor_pos = clamp(cursor_pos, 0, len(value))
        self.cursor_blink_start = pygame.time.get_ticks()

    def _scrollbar_rects(self, panel, list_top, list_h, total_h):
        # returns (track, thumb) or (None, None)
        self._max_scroll = max(0, total_h - list_h)
        if total_h <= list_h:
            return None, None
        track = pygame.Rect(panel.right - 28, list_top + 2, 8, list_h - 4)
        ratio = list_h / total_h
        thumb_h = max(20, int(track.height * ratio))
        thumb_y = track.y + int((track.height - thumb_h) * (self._scroll / max(1, self._max_scroll)))
        return track, pygame.Rect(track.x, thumb_y, track.width, thumb_h)

    def draw(self, surface, W, H, mouse_pos):
        if not self.visible:
            return
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surface.blit(overlay, (0, 0))
        panel = self._panel_rect(W, H)
        draw_panel(surface, panel, C.PANEL, C.BORDER, radius=12)
        blit_text(surface, self.title, FONT_LG, C.TEXT, panel.x + 20, panel.y + 14)

        # Search field (styled like other input fields)
        inp_rect = pygame.Rect(panel.x + 20, panel.y + 64, panel.width - 40, 34)
        active = self.active_field == "search"
        draw_panel(surface, inp_rect, C.BLUE_BG if active else C.PANEL2, C.ACCENT if active else C.BORDER, radius=8)
        txt = self.search_text if self.search_text else "Type sequence and press Enter"
        color = C.TEXT if self.search_text else C.MUTED
        blit_text(surface, txt, FONT_SM, color, inp_rect.x + 8, inp_rect.centery, anchor="midleft")
        # draw cursor when active
        if active:
            cursor_pos = clamp(getattr(self, "cursor_pos", 0), 0, len(self.search_text))
            prefix = self.search_text[:cursor_pos]
            display_text = fit_text_with_ellipsis(self.search_text, FONT_SM, inp_rect.width - 24)
            if display_text != self.search_text and cursor_pos > len(display_text):
                visible_prefix = display_text[:-3] if display_text.endswith("...") else display_text
                cursor_x = inp_rect.x + 8 + FONT_SM.size(visible_prefix)[0]
            else:
                cursor_x = inp_rect.x + 8 + FONT_SM.size(prefix)[0]
            if ((pygame.time.get_ticks() - getattr(self, "cursor_blink_start", 0)) // 500) % 2 == 0:
                pygame.draw.line(surface, C.ACCENT, (cursor_x, inp_rect.y + 6), (cursor_x, inp_rect.bottom - 6), 2)
        self._rects["input"] = inp_rect

        # Selected groups (show chosen words grouped by file/category)
        # Use cached file sets to avoid per-frame disk IO; ensure cache is loaded.
        try:
            if not self._file_sets:
                self._load_file_sets()
        except Exception:
            # fallback to empty sets
            self._file_sets = {}
            self._file_mtimes = {}
        greek_set = self._file_sets.get("greek", set())
        english_set = self._file_sets.get("english", set())
        results_set = self._file_sets.get("results", set())

        groups = {"Greek": [], "English": [], "Save to": []}
        for w in sorted(self.selected):
            if w in greek_set:
                groups["Greek"].append(w)
            if w in english_set:
                groups["English"].append(w)
            if w in results_set:
                groups["Save to"].append(w)

        # Matches list
        list_top = inp_rect.bottom + 12
        list_h = panel.bottom - list_top - 64
        clip = pygame.Rect(panel.x + 20, list_top, panel.width - 40, list_h)
        old_clip = surface.get_clip()
        surface.set_clip(clip)
        row_stride = self.ROW_H + 6
        total_h = len(self.matches) * row_stride
        self._max_scroll = max(0, total_h - list_h)
        y = list_top - self._scroll
        # Only render visible rows to avoid heavy work when matches is large
        first_idx = max(0, int(self._scroll // row_stride))
        visible_count = int(list_h // row_stride) + 3
        last_idx = min(len(self.matches), first_idx + visible_count)
        y = list_top - self._scroll + first_idx * row_stride
        for idx, w in enumerate(self.matches[first_idx:last_idx], start=first_idx):
            r = pygame.Rect(panel.x + 26, y, panel.width - 52 - 12, self.ROW_H)
            selected = w in self.selected
            hovered = r.collidepoint(mouse_pos)
            if selected:
                # red selected style with X marker on the right
                bg_color, bdr_color = C.RED_BG, C.RED_BDR
                # if hovered while selected, slightly change border
                if hovered:
                    pygame.draw.rect(surface, bg_color, r, border_radius=8)
                    pygame.draw.rect(surface, C.DARK, r, 2, border_radius=8)
                else:
                    pygame.draw.rect(surface, bg_color, r, border_radius=8)
                    pygame.draw.rect(surface, bdr_color, r, 1, border_radius=8)
                blit_text(surface, w, FONT_SM, C.TEXT, r.x + 8, r.centery, anchor="midleft")
                m = FONT_SM.render(special_chars["X"], True, C.TEXT)
                surface.blit(m, m.get_rect(midright=(r.right - 8, r.centery)))
            else:
                # normal row, show hover highlight
                if hovered:
                    pygame.draw.rect(surface, C.BLUE_BG, r, border_radius=8)
                    pygame.draw.rect(surface, C.ACCENT, r, 2, border_radius=8)
                else:
                    pygame.draw.rect(surface, C.PANEL2, r, border_radius=8)
                    pygame.draw.rect(surface, C.BORDER, r, 1, border_radius=8)
                blit_text(surface, w, FONT_SM, C.TEXT, r.x + 8, r.centery, anchor="midleft")
            # store rect for interaction/hover
            self._rects[f"match_{idx}"] = r
            y += row_stride
        surface.set_clip(old_clip)

        # Scrollbar
        if total_h > list_h:
            track = pygame.Rect(panel.right - 28, list_top + 2, 8, list_h - 4)
            pygame.draw.rect(surface, C.PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, C.BORDER, track, 1, border_radius=4)
            ratio = list_h / total_h
            thumb_h = max(20, int(track.height * ratio))
            thumb_y = track.y + int((track.height - thumb_h) * (self._scroll / max(1, self._max_scroll)))
            thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_h)
            pygame.draw.rect(surface, C.ACCENT, thumb, border_radius=4)
            self._rects["_sb_track"] = track
            self._rects["_sb_thumb"] = thumb

        # Buttons
        apply_btn = pygame.Rect(panel.x + 20, panel.bottom - 48, 120, 32)
        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 48, 72, 32)
        self._rects["apply"] = apply_btn
        self._rects["close"] = close_btn
        draw_button(surface, apply_btn, "Apply", bg=C.TEAL, fg=C.WHITE, hovered=apply_btn.collidepoint(mouse_pos), font=FONT_SM)
        draw_button(surface, close_btn, "Close", bg=C.RED, fg=C.WHITE, hovered=close_btn.collidepoint(mouse_pos), font=FONT_SM)

class ShowStatisticsModal:
    STAT_ITEMS = [
        ("length", "Length"),
        ("letters", "Letters"),
        ("pos_letters", "Pos. Letters"),
        ("vowels", "Vowels"),
        ("unique", "Unique"),
        ("first_letter", "1st Letter"),
        ("last_letter", "Last Letter"),
        ("ngrams", "Ngrams"),
        # ("syllables", "Syllables"),
    ]

    def __init__(self):
        self.visible = False
        self.words = []
        self.language = "greek"
        self.stat_key = "length"
        self.chart_orientation = "vertical"  # "vertical" | "horizontal"
        self.pos_index = 0
        self.ngram_size = 2
        self.top_n = 25
        self._picker_open = False
        self._picker_scroll = 0
        self._rects = {}
        self.sort_order = "normal"  # normal | ascend | descend
        self._sort_picker_open = False
        self._sort_picker_scroll = 0
        self._picker_dragging = False
        self._picker_drag_offset = 0

    def show(self, words, language):
        self.visible = True
        self.words = list(words or [])
        self.language = language
        # stat_key, chart_orientation, pos_index, ngram_size, top_n, and
        # sort_order are intentionally NOT reset here so the previously
        # chosen droplist/settings persist across close/reopen. Only
        # transient picker UI state resets.
        self._picker_open = False
        self._picker_scroll = 0
        self._sort_picker_open = False
        self._sort_picker_scroll = 0
        
    def hide(self):
        self.visible = False
        self._picker_open = False

    def _ordered_pairs(self, labels, values):
        pairs = list(zip(labels, values))
        if self.sort_order == "ascend":
            pairs.sort(key=lambda p: (p[1], p[0]))
        elif self.sort_order == "descend":
            pairs.sort(key=lambda p: (-p[1], p[0]))
        return pairs
    
    def _panel_rect(self, W, H):
        pw = min(980, W - 60)
        ph = min(680, H - 50)
        return pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)

    def _compute(self):
        words = self.words
        letters = _display_alphabet(self.language)

        if self.stat_key == "length":
            vals = [len(w) for w in words]
            counter = Counter(vals)
            labels = [str(i) for i in range(1, max(counter.keys(), default=1) + 1)]
            data = [counter.get(i, 0) for i in range(1, len(labels) + 1)]
            summary = _stats_summary(vals)
            return labels, data, summary, "Counts by length"

        if self.stat_key == "letters":
            counter = Counter()
            for w in words:
                for ch in _word_letters(w, self.language):
                    counter[ch] += 1
            data = [counter.get(lbl, 0) for lbl in letters]
            summary = _stats_summary(data)
            return letters, data, summary, "Total letter frequency"

        if self.stat_key == "pos_letters":
            counter = Counter()
            for w in words:
                if len(w) > self.pos_index:
                    ch = _base_letter(w[self.pos_index], self.language)
                    if ch:
                        counter[ch] += 1
            data = [counter.get(lbl, 0) for lbl in letters]
            summary = _stats_summary(data)
            return letters, data, summary, f"Letter frequency at position {self.pos_index + 1}"

        if self.stat_key == "vowels":
            ratios = []
            for w in words:
                letters_w = _word_letters(w, self.language)
                if not letters_w:
                    continue
                vc = sum(1 for ch in letters_w if _is_vowel(ch, self.language))
                ratios.append(vc / len(letters_w))
            buckets = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
            labels = [_bucket_label(a, b) for a, b in buckets]
            data = []
            for a, b in buckets:
                if b < 1.0:
                    data.append(sum(1 for r in ratios if a <= r < b))
                else:
                    data.append(sum(1 for r in ratios if a <= r <= b))
            summary = _stats_summary(ratios)
            return labels, data, summary, "Vowel ratio distribution"

        if self.stat_key == "unique":
            vals = [len(set(_word_letters(w, self.language))) for w in words if w]
            counter = Counter(vals)
            labels = [str(i) for i in range(1, max(counter.keys(), default=1) + 1)]
            data = [counter.get(i, 0) for i in range(1, len(labels) + 1)]
            summary = _stats_summary(vals)
            return labels, data, summary, "Unique letters per word"

        if self.stat_key == "first_letter":
            counter = Counter()
            for w in words:
                if w:
                    ch = _base_letter(w[0], self.language)
                    if ch:
                        counter[ch] += 1
            data = [counter.get(lbl, 0) for lbl in letters]
            summary = _stats_summary(data)
            return letters, data, summary, "Starting-letter frequency"

        if self.stat_key == "last_letter":
            counter = Counter()
            for w in words:
                if w:
                    ch = _base_letter(w[-1], self.language)
                    if ch:
                        counter[ch] += 1
            data = [counter.get(lbl, 0) for lbl in letters]
            summary = _stats_summary(data)
            return letters, data, summary, "Ending-letter frequency"

        if self.stat_key == "ngrams":
            n = self.ngram_size
            pairs = _top_ngrams(words, self.language, n=n, top_n=self.top_n)
            labels = [k.upper() for k, _ in pairs]
            data = [v for _, v in pairs]
            summary = _stats_summary(data)
            title = ["Bigram", "Trigram", "Tetragram", "Pentagram"][n-2] + " frequency"
            return labels, data, summary, title

        # syllables
        vals = [_estimate_syllables(w, self.language) for w in words if w]
        counter = Counter(vals)
        labels = [str(i) for i in range(1, max(counter.keys(), default=1) + 1)]
        data = [counter.get(i, 0) for i in range(1, len(labels) + 1)]
        summary = _stats_summary(vals)
        return labels, data, summary, "Estimated syllables per word"

    def _words_for_label(self, label):
        """Returns the list of words belonging to the given bar's label,
        for the given stat_key. Mirrors the bucketing logic in _compute."""
        words = self.words

        if self.stat_key == "length":
            n = int(label)
            return [w for w in words if len(w) == n]

        if self.stat_key == "letters":
            return [w for w in words if label in _word_letters(w, self.language)]

        if self.stat_key == "pos_letters":
            out = []
            for w in words:
                if len(w) > self.pos_index:
                    ch = _base_letter(w[self.pos_index], self.language)
                    if ch == label:
                        out.append(w)
            return out

        if self.stat_key == "vowels":
            buckets = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
            bucket_labels = [_bucket_label(a, b) for a, b in buckets]
            try:
                bi = bucket_labels.index(label)
            except ValueError:
                return []
            a, b = buckets[bi]
            out = []
            for w in words:
                letters_w = _word_letters(w, self.language)
                if not letters_w:
                    continue
                r = sum(1 for ch in letters_w if _is_vowel(ch, self.language)) / len(letters_w)
                if b < 1.0:
                    if a <= r < b:
                        out.append(w)
                else:
                    if a <= r <= b:
                        out.append(w)
            return out

        if self.stat_key == "unique":
            n = int(label)
            return [w for w in words if w and len(set(_word_letters(w, self.language))) == n]

        if self.stat_key == "first_letter":
            return [w for w in words if w and _base_letter(w[0], self.language) == label]

        if self.stat_key == "last_letter":
            return [w for w in words if w and _base_letter(w[-1], self.language) == label]

        if self.stat_key == "ngrams":
            n = self.ngram_size
            target = label.lower()
            out = []
            for w in words:
                letters_w = _word_letters(w, self.language)
                found = False
                for i in range(len(letters_w) - n + 1):
                    if "".join(letters_w[i : i + n]).lower() == target:
                        found = True
                        break
                if found:
                    out.append(w)
            return out

        # syllables
        n = int(label)
        return [w for w in words if w and _estimate_syllables(w, self.language) == n]

    def _draw_graph(self, surface, area, labels, values, mouse_pos):
        """Draw the bar graph and return [(label, value, bar_rect), ...].

        This version tries to use almost all of `area` so the graph starts just
        below the title area and ends just above the footer/Close button area.
        """
        if not labels:
            blit_text(
                surface,
                "No data",
                FONT_MD,
                C.MUTED,
                area.centerx,
                area.centery,
                anchor="center",
            )
            return []

        max_v = max(values) if values else 1
        if max_v <= 0:
            max_v = 1

        bar_rects = []

        # Very small inset so the graph visually breathes, but does not waste space.
        inner = area.inflate(-8, -8)
        inner = inner.clip(area)

        if self.chart_orientation == "vertical":
            n = len(labels)

            # Reserve only tiny strips for the value text above and label text below.
            label_font = FONT_SM
            bottom_label_h = max(label_font.get_height() + 2, 14)
            top_value_h = max(FONT_SM.get_height() + 2, 14)

            plot_top = inner.top + top_value_h
            plot_bottom = inner.bottom - bottom_label_h
            plot_h = max(10, plot_bottom - plot_top)

            # Make the bars fill the width as much as possible.
            gap = 4 if n > 1 else 0
            bar_w = max(8, (inner.width - gap * (n - 1)) // n)

            total_w = bar_w * n + gap * (n - 1)
            x = inner.left + max(0, (inner.width - total_w) // 2)

            prelim = []
            for lbl, val in zip(labels, values):
                h = int(plot_h * (val / max_v))
                bar = pygame.Rect(x, plot_bottom - h, bar_w, h)
                prelim.append((lbl, val, bar))
                x += bar_w + gap

            # The value text above each bar should be just as clickable/
            # hoverable as the bar itself, since a bar for a small value can
            # shrink to just a few pixels tall (or 0) and become impossible
            # to hit. Compute the value-text rect up front and use the
            # union of bar + value-text as the interactive hit area.
            hit_prelim = []
            for lbl, val, bar in prelim:
                val_img = FONT_SM.render(str(val), True, C.TEXT)
                val_rect = val_img.get_rect(midbottom=(bar.centerx, bar.y - 3))
                hit_rect = bar.union(val_rect)
                hit_prelim.append((lbl, val, bar, val_rect, hit_rect))

            hovered_idx = next(
                (
                    i
                    for i, (_, _, _, _, hit) in enumerate(hit_prelim)
                    if hit.collidepoint(mouse_pos)
                ),
                None,
            )

            base_y = inner.bottom - bottom_label_h + 1

            for i, (lbl, val, bar, val_rect, hit_rect) in enumerate(hit_prelim):
                is_hover = i == hovered_idx

                if hovered_idx is None:
                    fill, border = C.ACCENT, C.BORDER
                elif is_hover:
                    fill, border = lighten(C.ACCENT, 25), C.TEXT
                else:
                    fill, border = _dim_color(C.ACCENT), _dim_color(C.BORDER)

                draw_bar = bar.inflate(2, 2) if is_hover else bar
                pygame.draw.rect(surface, fill, draw_bar, border_radius=6)
                pygame.draw.rect(surface, border, draw_bar, 1, border_radius=6)

                val_color = C.TEXT if (hovered_idx is None or is_hover) else C.MUTED
                blit_text(
                    surface,
                    str(val),
                    FONT_SM,
                    val_color,
                    bar.centerx,
                    bar.y - 3,
                    anchor="midbottom",
                )

                lbl_color = C.TEXT if (hovered_idx is None or is_hover) else C.MUTED
                blit_text(
                    surface,
                    fit_text_with_ellipsis(lbl, label_font, bar_w + 4),
                    label_font,
                    lbl_color,
                    bar.centerx,
                    base_y,
                    anchor="midtop",
                )

                bar_rects.append((lbl, val, hit_rect))

        else:
            n = len(labels)

            # Left label column and right value column kept small to maximize bar width.
            max_label_w = max((FONT_SM.size(lbl)[0] for lbl in labels), default=0)
            label_col_w = min(max(90, max_label_w + 8), 160)
            value_col_w = max(FONT_SM.size(str(max_v))[0] + 10, 42)

            gap_left = 8
            gap_right = 8
            bar_left = inner.left + label_col_w + gap_left
            bar_right = inner.right - value_col_w - gap_right
            bar_area_w = max(20, bar_right - bar_left)

            # Rows fill the full height with only a tiny gap.
            gap_y = 2 if n <= 20 else 1
            row_h = max(14, (inner.height - (n - 1) * gap_y) // n)
            total_h = row_h * n + gap_y * (n - 1)
            y = inner.top + max(0, (inner.height - total_h) // 2)

            prelim = []
            for lbl, val in zip(labels, values):
                bar_w = int(bar_area_w * (val / max_v))
                row = pygame.Rect(inner.left, y, inner.width, row_h)
                bar_h = max(8, row_h - 8)
                bar = pygame.Rect(bar_left, y + (row_h - bar_h) // 2, bar_w, bar_h)
                prelim.append((lbl, val, row, bar))
                y += row_h + gap_y

            # Same reasoning as the vertical case: include the value-text
            # rect (drawn to the right of the bar) in the clickable/
            # hoverable area, since a small value can produce a very thin
            # or even zero-width bar.
            hit_prelim = []
            for lbl, val, row, bar in prelim:
                val_img = FONT_SM.render(str(val), True, C.TEXT)
                val_rect = val_img.get_rect(midleft=(bar.right + 8, row.centery))
                hit_rect = bar.union(val_rect)
                hit_prelim.append((lbl, val, row, bar, val_rect, hit_rect))

            hovered_idx = next(
                (
                    i
                    for i, (_, _, _, _, _, hit) in enumerate(hit_prelim)
                    if hit.collidepoint(mouse_pos)
                ),
                None,
            )

            for i, (lbl, val, row, bar, val_rect, hit_rect) in enumerate(hit_prelim):
                is_hover = i == hovered_idx

                if hovered_idx is None:
                    fill, border = C.ACCENT, C.BORDER
                elif is_hover:
                    fill, border = lighten(C.ACCENT, 25), C.TEXT
                else:
                    fill, border = _dim_color(C.ACCENT), _dim_color(C.BORDER)

                lbl_color = C.TEXT if (hovered_idx is None or is_hover) else C.MUTED
                blit_text(
                    surface,
                    fit_text_with_ellipsis(lbl, FONT_SM, label_col_w - 4),
                    FONT_SM,
                    lbl_color,
                    inner.left,
                    row.centery,
                    anchor="midleft",
                )

                draw_bar = bar.inflate(2, 2) if is_hover else bar
                pygame.draw.rect(surface, fill, draw_bar, border_radius=6)
                pygame.draw.rect(surface, border, draw_bar, 1, border_radius=6)

                val_color = C.TEXT if (hovered_idx is None or is_hover) else C.MUTED
                blit_text(
                    surface,
                    str(val),
                    FONT_SM,
                    val_color,
                    bar.right + 8,
                    row.centery,
                    anchor="midleft",
                )

                bar_rects.append((lbl, val, hit_rect))

        return bar_rects

    def handle_event(self, event, W, H):
        if not self.visible:
            return False

        panel = self._panel_rect(W, H)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.hide()
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not panel.collidepoint(event.pos):
                self.hide()
                return True

            stat_selector = self._rects.get("stat_selector")
            orient_btn = self._rects.get("orient_btn")
            sort_btn = self._rects.get("sort_btn")

            if self._picker_open:
                picker = self._rects.get("picker")
                if picker and picker.collidepoint(event.pos):
                    for idx, key, label, r in self._rects.get("picker_items", []):
                        if r.collidepoint(event.pos):
                            self.stat_key = key
                            self._picker_open = False
                            self._picker_scroll = 0
                            return True
                self._picker_open = False
                return True

            if self._sort_picker_open:
                picker = self._rects.get("sort_picker")
                if picker and picker.collidepoint(event.pos):
                    for idx, key, label, r in self._rects.get("sort_picker_items", []):
                        if r.collidepoint(event.pos):
                            self.sort_order = key
                            self._sort_picker_open = False
                            self._sort_picker_scroll = 0
                            return True
                self._sort_picker_open = False
                return True

            if stat_selector and stat_selector.collidepoint(event.pos):
                self._picker_open = True
                self._picker_scroll = 0
                return True

            if orient_btn and orient_btn.collidepoint(event.pos):
                self.chart_orientation = (
                    "horizontal" if self.chart_orientation == "vertical" else "vertical"
                )
                return True

            if sort_btn and sort_btn.collidepoint(event.pos):
                self._sort_picker_open = not self._sort_picker_open
                self._sort_picker_scroll = 0
                return True

            if self.stat_key == "pos_letters" and self._rects.get("pos_selector") and self._rects["pos_selector"].collidepoint(event.pos):
                max_pos = max(1, max((len(w) for w in self.words), default=1))
                self.pos_index = (self.pos_index + 1) % max_pos
                return True

            if self.stat_key == "ngrams" and self._rects.get("ngram_toggle") and self._rects["ngram_toggle"].collidepoint(event.pos):
                self.ngram_size = ((self.ngram_size - 2) + 1) % 4 + 2
                return True

            for lbl, val, bar in self._rects.get("bar_rects", []):
                if bar.collidepoint(event.pos):
                    words_for_bar = self._words_for_label(lbl)
                    stat_label = dict(self.STAT_ITEMS).get(self.stat_key, "")
                    words_modal.show(
                        words_for_bar,
                        self.language,
                        title=f"{stat_label}: {lbl}",
                        narrow=True,
                    )
                    return True

            close_btn = self._rects.get("close")
            if close_btn and close_btn.collidepoint(event.pos):
                self.hide()
                return True

        if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEBUTTONDOWN):
            mp = pygame.mouse.get_pos()
            wheel_y = 0
            if event.type == pygame.MOUSEWHEEL:
                wheel_y = event.y
            elif event.button in (4, 5):
                wheel_y = 1 if event.button == 4 else -1
            if wheel_y:
                if self._picker_open:
                    picker = self._rects.get("picker")
                    if picker and picker.collidepoint(mp):
                        row_h, gap = 28, 4
                        visible = max(1, (picker.height - 16) // (row_h + gap))
                        self._picker_scroll = clamp(
                            self._picker_scroll - wheel_y, 0,
                            max(0, len(self.STAT_ITEMS) - visible),
                        )
                        return True
                if self._sort_picker_open:
                    picker = self._rects.get("sort_picker")
                    if picker and picker.collidepoint(mp):
                        sort_items_len = 3
                        row_h, gap = 28, 4
                        visible = max(1, (picker.height - 16) // (row_h + gap))
                        self._sort_picker_scroll = clamp(
                            self._sort_picker_scroll - wheel_y, 0,
                            max(0, sort_items_len - visible),
                        )
                        return True

        return True

    def draw(self, surface, W, H, mouse_pos):
        if not self.visible:
            return

        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        panel = self._panel_rect(W, H)
        draw_panel(surface, panel, C.PANEL, C.BORDER, radius=16)

        title_rect = blit_text(surface, "Show Statistics", FONT_LG, C.TEXT, panel.x + 24, panel.y + 18)

        stat_selector_w = 160
        orient_btn_w = 120
        sort_btn_w = 120
        controls_y = panel.y + 18 + max(0, (title_rect.height - 30) // 2)

        stat_selector = pygame.Rect(title_rect.right + 18, controls_y, stat_selector_w, 30)
        orient_btn = pygame.Rect(panel.right - orient_btn_w - 10, controls_y, orient_btn_w, 30)
        sort_btn = pygame.Rect(orient_btn.left - sort_btn_w - 10, controls_y, sort_btn_w, 30)

        self._rects["stat_selector"] = stat_selector
        self._rects["orient_btn"] = orient_btn
        self._rects["sort_btn"] = sort_btn

        current_label = dict(self.STAT_ITEMS)[self.stat_key]
        draw_button(
            surface,
            stat_selector,
            current_label,
            bg=C.BLUE_BG,
            fg=C.TEXT,
            hovered=stat_selector.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        draw_button(
            surface,
            orient_btn,
            self.chart_orientation.title(),
            bg=C.TEAL,
            fg=C.WHITE,
            hovered=orient_btn.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        draw_button(
            surface,
            sort_btn,
            self.sort_order.title(),
            bg=C.PURPLE,
            fg=C.WHITE,
            hovered=sort_btn.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        extra_bottom = controls_y + 30

        if self.stat_key == "pos_letters":
            max_pos = max(1, max((len(w) for w in self.words), default=1))
            extra_btn = pygame.Rect(stat_selector.right + 10, controls_y, 160, 30)
            self._rects["pos_selector"] = extra_btn
            draw_button(
                surface,
                extra_btn,
                f"Position: {self.pos_index + 1}/{max_pos}",
                bg=C.BLUE_BG,
                fg=C.TEXT,
                hovered=extra_btn.collidepoint(mouse_pos),
                font=FONT_SM,
            )
            extra_bottom = max(extra_bottom, extra_btn.bottom)

        elif self.stat_key == "ngrams":
            extra_btn = pygame.Rect(stat_selector.right + 10, controls_y, 90, 30)
            self._rects["ngram_toggle"] = extra_btn
            draw_button(
                surface,
                extra_btn,
                ["Bi", "Tri", "Tetra", "Penta"][self.ngram_size-2],
                bg=C.BLUE_BG,
                fg=C.WHITE,
                hovered=extra_btn.collidepoint(mouse_pos),
                font=FONT_SM,
            )
            extra_bottom = max(extra_bottom, extra_btn.bottom)

        else:
            self._rects["pos_selector"] = None
            self._rects["ngram_toggle"] = None

        self._rects["picker"] = None
        self._rects["picker_items"] = []
        self._rects["sort_picker"] = None
        self._rects["sort_picker_items"] = []

        labels, values, summary, subtitle = self._compute()
        subtitle_rect = blit_text(surface, subtitle, FONT_SM, C.TEXT, panel.x + 24, panel.y + 50)
        pairs = self._ordered_pairs(labels, values)
        labels = [p[0] for p in pairs]
        values = [p[1] for p in pairs]

        # Reserve the bottom strip for summary + Close button.
        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 42, 72, 28)
        self._rects["close"] = close_btn

        graph_top = extra_bottom + 20
        graph_bottom = close_btn.top - 5

        graph_area = pygame.Rect(
            panel.x + 12,                 # closer to the modal edge
            graph_top,
            panel.width - 24,             # almost full width
            max(20, graph_bottom - graph_top),
        )

        self._rects["bar_rects"] = self._draw_graph(surface, graph_area, labels, values, mouse_pos)

        if values:
            min_v = min(values)
            max_v = max(values)
        else:
            min_v = 0
            max_v = 0

        mean_v, median_v, std_v = summary
        summary_text = (
            f"Mean: {mean_v:.2f}  {special_chars['*']}  Median: {median_v:.2f}  "
            f"{special_chars['*']}  Std Dev: {std_v:.2f}    |    "
            f"Min: {min_v:.2f}  {special_chars['*']}  Max: {max_v:.2f}"
        )
        blit_text(surface, summary_text, FONT_SM, C.MUTED, panel.x + 24, panel.bottom - 36)

        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 42, 72, 28)
        self._rects["close"] = close_btn
        draw_button(
            surface,
            close_btn,
            "Close",
            bg=C.RED,
            fg=C.WHITE,
            hovered=close_btn.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        # Draw dropdowns last so they stay above the graph and footer widgets.
        if self._picker_open:
            picker = pygame.Rect(stat_selector.x, stat_selector.bottom + 6, stat_selector_w, 300)
            self._rects["picker"] = picker
            draw_panel(surface, picker, C.PANEL2, C.BORDER, radius=12)

            row_h = 28
            gap = 4
            visible = max(1, (picker.height - 16) // (row_h + gap))
            start = clamp(self._picker_scroll, 0, max(0, len(self.STAT_ITEMS) - visible))
            items = []
            for i, (key, label) in enumerate(self.STAT_ITEMS[start : start + visible], start=start):
                r = pygame.Rect(
                    picker.x + 10,
                    picker.y + 8 + (i - start) * (row_h + gap),
                    picker.width - 20,
                    row_h,
                )
                items.append((i, key, label, r))
                fill = C.BLUE_BG if key == self.stat_key else C.PANEL
                border = C.ACCENT if key == self.stat_key else C.BORDER
                hovered = r.collidepoint(mouse_pos)
                if hovered:
                    fill = lighten(fill, 12)
                    border = lighten(border, 12)

                pygame.draw.rect(surface, fill, r, border_radius=8)
                pygame.draw.rect(surface, border, r, 1, border_radius=8)
                blit_text(surface, label, FONT_SM, C.TEXT, r.x + 10, r.centery, anchor="midleft")
            self._rects["picker_items"] = items

        if self._sort_picker_open:
            picker = pygame.Rect(sort_btn.x, sort_btn.bottom + 6, sort_btn.width, 120)
            self._rects["sort_picker"] = picker
            draw_panel(surface, picker, C.PANEL2, C.BORDER, radius=12)

            sort_items = [("normal", "Normal"), ("ascend", "Ascend"), ("descend", "Descend")]
            row_h = 28
            gap = 4
            visible = max(1, (picker.height - 16) // (row_h + gap))
            start = clamp(self._sort_picker_scroll, 0, max(0, len(sort_items) - visible))
            items = []
            for i, (key, label) in enumerate(sort_items[start : start + visible], start=start):
                r = pygame.Rect(
                    picker.x + 10,
                    picker.y + 8 + (i - start) * (row_h + gap),
                    picker.width - 20,
                    row_h,
                )
                items.append((i, key, label, r))
                fill = C.BLUE_BG if key == self.sort_order else C.PANEL
                border = C.ACCENT if key == self.sort_order else C.BORDER
                hovered = r.collidepoint(mouse_pos)
                if hovered:
                    fill = lighten(fill, 12)
                    border = lighten(border, 12)
                pygame.draw.rect(surface, fill, r, border_radius=8)
                pygame.draw.rect(surface, border, r, 1, border_radius=8)
                blit_text(surface, label, FONT_SM, C.TEXT, r.x + 10, r.centery, anchor="midleft")
            self._rects["sort_picker_items"] = items

class SummaryModal:
    """Pygame modal replacement for the old tkinter 'Slots Review' /
    'Patterns Review' popup. Shows the same content (current input-mode
    constraints for whichever finder mode was active when opened), plus a
    Copy button (copies the plain-text summary to the clipboard) and a
    Close button."""

    def __init__(self):
        self.visible = False
        self.finder_mode = "letter_match"
        self._scroll = 0
        self._dragging_sb = False
        self._drag_offset = 0
        self._max_scroll_cache = 0
        self._rects = {}
        self._copied_flash = 0  # frames remaining to show "Copied!" feedback

    def show(self, finder_mode):
        self.visible = True
        self.finder_mode = finder_mode
        self._scroll = 0
        self._copied_flash = 0

    def hide(self):
        self.visible = False

    def _panel_rect(self, W, H):
        pw = min(560, W - 80)
        ph = min(640, H - 60)
        return pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)

    def _title(self):
        return "Patterns Review" if self.finder_mode == "pattern_hunt" else "Slots Review"

    def _lines(self):
        return build_summary_lines()

    def _content_height(self, panel):
        PAD_ = 22
        max_w = panel.width - PAD_ * 2
        line_h = FONT_SM.get_height() + 4
        h = 0
        for text in self._lines():
            if text == "":
                h += line_h
                continue
            for _ in self._wrap(text, FONT_SM, max_w):
                h += line_h
        return h

    @property
    def _max_scroll(self):
        return getattr(self, "_max_scroll_cache", 0)

    def _content_rect(self, panel):
        top = panel.y + 72
        bottom = panel.bottom - 54
        return pygame.Rect(panel.x + 18, top, panel.width - 36, bottom - top)

    def _scrollbar_rects(self, panel):
        content = self._content_rect(panel)
        visible_h = content.height
        total_h = self._content_height(panel)
        self._max_scroll_cache = max(0, total_h - visible_h)
        if total_h <= visible_h:
            return None, None
        track = pygame.Rect(panel.right - 16, content.y, 6, content.height)
        ratio = visible_h / total_h
        thumb_h = max(20, int(track.height * ratio))
        thumb_y = track.y + int(
            (track.height - thumb_h) * self._scroll / max(1, self._max_scroll_cache)
        )
        return track, pygame.Rect(track.x, thumb_y, 6, thumb_h)

    def handle_event(self, event, W, H):
        if not self.visible:
            return False

        panel = self._panel_rect(W, H)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.hide()
                return True

        track, thumb = self._scrollbar_rects(panel)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if thumb and thumb.collidepoint(event.pos):
                self._dragging_sb = True
                self._drag_offset = event.pos[1] - thumb.y
                return True

            if not panel.collidepoint(event.pos):
                self.hide()
                return True

            copy_btn = self._rects.get("copy")
            if copy_btn and copy_btn.collidepoint(event.pos):
                text = "\n".join(self._lines())
                if copy_to_clipboard(text):
                    self._copied_flash = 90
                return True

            close_btn = self._rects.get("close")
            if close_btn and close_btn.collidepoint(event.pos):
                self.hide()
                return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging_sb = False

        if event.type == pygame.MOUSEMOTION and self._dragging_sb and track:
            new_y = event.pos[1] - self._drag_offset
            max_thumb_y = track.y + track.height - thumb.height
            ratio = (new_y - track.y) / max(1, max_thumb_y - track.y)
            self._scroll = max(0, min(self._max_scroll, ratio * self._max_scroll))
            return True

        if event.type == pygame.MOUSEWHEEL:
            if panel.collidepoint(pygame.mouse.get_pos()):
                self._scroll = max(
                    0, min(self._max_scroll, self._scroll - event.y * 20)
                )
                return True

        return True

    def draw(self, surface, W, H, mouse_pos):
        if not self.visible:
            return

        if self._copied_flash > 0:
            self._copied_flash -= 1

        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        panel = self._panel_rect(W, H)
        draw_panel(surface, panel, C.PANEL, C.ACCENT, radius=16)

        blit_text(surface, self._title(), FONT_LG, C.TEXT, panel.x + 22, panel.y + 18)

        content = self._content_rect(panel)

        clip_rect = pygame.Rect(
            content.x - 4, content.y, content.width + 4, content.height
        )
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect)

        line_h = FONT_SM.get_height() + 4
        y = content.y - int(self._scroll)
        for text in self._lines():
            if text == "":
                y += line_h
                continue
            # Section headers (no leading spaces) get accent color/bold feel
            is_header = not text.startswith(" ")
            color = C.ACCENT if is_header else C.TEXT
            font = FONT_MD if is_header else FONT_SM
            for line in self._wrap(text, FONT_SM, content.width):
                if content.y - line_h <= y <= content.bottom:
                    surface.blit(font.render(line, True, color), (content.x, y))
                y += line_h

        surface.set_clip(old_clip)

        track, thumb = self._scrollbar_rects(panel)
        self._scroll = max(0, min(self._max_scroll_cache, self._scroll))
        if track:
            pygame.draw.rect(surface, C.PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, C.BORDER, thumb, border_radius=4)

        copy_btn = pygame.Rect(panel.x + 22, panel.bottom - 42, 110, 28)
        self._rects["copy"] = copy_btn
        copy_label = "Copied!" if self._copied_flash > 0 else "Copy"
        draw_button(
            surface, copy_btn, copy_label,
            bg=C.GREEN if self._copied_flash > 0 else C.TEAL, fg=C.WHITE,
            hovered=copy_btn.collidepoint(mouse_pos), font=FONT_SM,
        )

        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 42, 72, 28)
        self._rects["close"] = close_btn
        draw_button(
            surface, close_btn, "Close", bg=C.RED, fg=C.WHITE,
            hovered=close_btn.collidepoint(mouse_pos), font=FONT_SM
        )

    @staticmethod
    def _wrap(text, font, max_w):
        if not text:
            return [""]
        # Preserve leading whitespace (used for indentation) as a prefix,
        # then word-wrap the remainder.
        stripped = text.lstrip(" ")
        indent = text[: len(text) - len(stripped)]
        words = stripped.split(" ")
        lines, current = [], indent
        for word in words:
            sep = " " if current not in ("", indent) else ""
            test = current + sep + word
            if font.size(test)[0] <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = indent + word
        if current:
            lines.append(current)
        return lines or [indent]
