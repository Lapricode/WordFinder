"""
Application state (AppState), background jobs, and state-mutating action functions.

Part of the Word Finder application (split from the original single-file
WordFinder.py for maintainability). Behavior is unchanged from the original --
this is a pure refactor.
"""

import os
import sys
import threading
import queue
import subprocess
from statistics import mean, median, pstdev
from collections import Counter
from tkinter import Tk, filedialog

import pygame

import wf_constants as C
from wf_constants import (
    ENGLISH_LETTERS, ENGLISH_GROUP_BY_FIRST, GREEK_GROUPS, GREEK_GROUP_BY_FIRST,
    GREEK_CHAR_TO_FIRST, INPUT_MODES_LM, INPUT_MODES_PH, PH_ROWS, PH_COLS,
    MAX_PATTERN_SLOTS, STATUS_KEYS, PAD, FONT_SM,
    clamp, resource_path, set_theme, special_chars, tokens_for_input,
)
from wf_search import (
    load_words, exist_key_for_input, expand_sequence,
    _pat_matches_start, _pat_matches_end, _pat_matches_inner, _pat_matches_middle,
    _check_start_exist, _check_end_exist, _check_inner_exist, _check_middle_exist,
)
from wf_translate import (
    ensure_nltk_ready, normalize_word, clean_translation, build_status,
    load_json_dict, save_json_atomic, build_enrichment_entry,
    ENRICHMENT_SAVE_EVERY_WORDS, _meanings_cache,
)

# progress_modal / words_modal: single ProgressModal / ShowWordsModal instances
# created once by the entrypoint (WordFinder.py) before the main loop starts,
# then assigned onto this module. do_translate_action / do_get_meaning_action
# only run in response to user clicks, which cannot happen before the entrypoint
# has finished setup -- so this matches the original file's forward-reference
# behavior exactly (a single shared namespace where these names exist by the
# time they're actually called).
progress_modal = None
words_modal = None


def _make_pattern_slot():
    return {"seq": "", "expanded": False}


_results_legend_rects = {"toggle": None, "items": {}}

_results_action_rects = {
    "show_words": None,
    "show_stats": None,
    "keyboard": None,
    "per_row_minus": None,
    "per_row_plus": None,
}

_results_scroll_rects = {
    "grid": None,
    "panel": None,
}

_results_keyboard_rects = {"panel": None, "keys": [], "controls": {}}

class EnrichmentJob:
    """Runs Translation / Meaning over a word list on a background thread,
    writing results into the correct JSON file as it goes, and reporting
    progress back to the main thread through a thread-safe queue."""

    def __init__(self, job_kind, words, language):
        self.job_kind = job_kind  # "translation" | "meaning"
        self.words = list(words)
        self.language = language  # "greek" | "english"
        self.progress_queue = queue.Queue()
        self.total = len(self.words)
        self.done_count = 0
        self.cancelled = False
        self.paused = False

        # Event stays set while the worker is allowed to run.
        self._run_event = threading.Event()
        self._run_event.set()

        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        self.paused = True
        self._run_event.clear()

    def resume(self):
        if not self.cancelled and self.done_count < self.total:
            self.paused = False
            self._run_event.set()

    def cancel(self):
        self.cancelled = True
        self.paused = False
        self._run_event.set()

    def _target_path(self):
        if self.job_kind == "translation":
            return (
                state.greek_meanings_file
                if self.language == "greek"
                else state.english_meanings_file
            )
        return (
            state.greek_meanings_file
            if self.language == "greek"
            else state.english_meanings_file
        )

    def _run(self):
        path = self._target_path()
        data = load_json_dict(path)
        english_dict_path = state.english_meanings_file
        english_dict = load_json_dict(english_dict_path)
        pending_writes = 0

        if self.job_kind == "meaning" and self.language == "english":
            ensure_nltk_ready()

        for idx in range(self.done_count, self.total):
            self._run_event.wait()  # blocks while paused
            if self.cancelled:
                break

            word = self.words[idx]
            key = normalize_word(word)
            existing = data.get(key, {})

            try:
                # if self.job_kind == "translation":
                #     if self.language == "english":
                #         greek_translation = get_greek_translation(word)
                #         entry = {
                #             "input_word": word,
                #             "greek_translation": greek_translation,
                #             "senses": existing.get("senses", []),
                #             "status": build_status(word, greek_translation, existing.get("senses", [])),
                #         }
                #     else:
                #         english_translation = get_english_translation(word)
                #         entry = {
                #             "input_word": word,
                #             "english_translation": english_translation,
                #             "senses": existing.get("senses", []),
                #             "status": build_status(word, english_translation, existing.get("senses", [])),
                #         }
                # else:
                #     if self.language == "english":
                #         senses = get_wordnet_senses(word)
                #         entry = {
                #             "input_word": word,
                #             "greek_translation": existing.get("greek_translation"),
                #             "senses": senses,
                #             "status": build_status(word, existing.get("greek_translation"), senses),
                #         }
                #     else:
                #         english_translation = existing.get("english_translation")
                #         senses = get_wordnet_senses(english_translation) if english_translation else []
                #         entry = {
                #             "input_word": word,
                #             "english_translation": english_translation,
                #             "senses": senses,
                #             "status": build_status(word, english_translation, senses),
                #         }
                # data[key] = entry

                entry = build_enrichment_entry(
                    self.job_kind, self.language, word, existing
                )
                data[key] = entry

                pending_writes += 1
                if (
                    pending_writes >= ENRICHMENT_SAVE_EVERY_WORDS
                    or idx == self.total - 1
                ):
                    save_json_atomic(path, data)
                    state.results_cache_dirty = True
                    pending_writes = 0

                self.progress_queue.put(
                    (
                        "result",
                        {
                            "word": word,
                            "entry": entry,
                            "job_kind": self.job_kind,
                            "language": self.language,
                        },
                    )
                )

            except Exception as e:
                self.progress_queue.put(("error", f"{word}: {e}"))

            self.done_count = idx + 1

        if pending_writes:
            save_json_atomic(path, data)
            state.results_cache_dirty = True

        if not self.cancelled and self.done_count >= self.total:
            self.progress_queue.put(("done", None))

class SearchJob:
    def __init__(
        self,
        words,
        finder_mode,
        language,
        word_length,
        valid_sets=None,
        invalid_sets=None,
        exist_letters=None,
        absent_letters=None,
        ph_word_length_all=False,
        ph_slots=None,
        ph_slot_count=None,
        source_name="",
    ):
        self.words = list(words)
        self.finder_mode = finder_mode
        self.language = language
        self.word_length = word_length
        self.valid_sets = valid_sets or []
        self.invalid_sets = invalid_sets or []
        self.exist_letters = exist_letters or Counter()
        self.absent_letters = list(absent_letters or [])
        self.ph_word_length_all = ph_word_length_all
        self.ph_slots = ph_slots or {}
        self.ph_slot_count = ph_slot_count or {}
        self.source_name = source_name

        self.progress_queue = queue.Queue()
        self.total = len(self.words)
        self.done_count = 0
        self.cancelled = False
        self.results = []
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        self.cancelled = True

    def _word_matches(self, word: str) -> bool:
        if self.finder_mode == "letter_match":
            if len(word) != self.word_length:
                return False

            for pos, ch in enumerate(word):
                if self.valid_sets[pos] and ch not in self.valid_sets[pos]:
                    return False
                if self.invalid_sets[pos] and ch in self.invalid_sets[pos]:
                    return False

            if self.absent_letters:
                wc = Counter(word)
                for key in self.absent_letters:
                    if self.language == "greek":
                        group = GREEK_GROUP_BY_FIRST.get(key, (key,))
                    elif self.language == "english":
                        group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
                    else:
                        group = (key,)
                    if sum(wc[ch] for ch in group) > 0:
                        return False
                    
            if self.exist_letters:
                wc = Counter(word)
                for key, needed in self.exist_letters.items():
                    if self.language == "greek":
                        group = GREEK_GROUP_BY_FIRST.get(key, (key,))
                    elif self.language == "english":
                        group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
                    else:
                        group = (key,)

                    if sum(wc[ch] for ch in group) < needed:
                        return False
            return True

        wl = None if self.ph_word_length_all else self.word_length
        if wl is not None and len(word) != wl:
            return False

        rows = ["start", "inner", "middle", "end"]
        ok = True

        def row_match(row_name, pat_info):
            if row_name == "start":
                return _pat_matches_start(word, pat_info, self.language)
            if row_name == "inner":
                return _pat_matches_inner(word, pat_info, self.language)
            if row_name == "middle":
                return _pat_matches_middle(word, pat_info, self.language)
            return _pat_matches_end(word, pat_info, self.language)

        for row in rows:
            valid_pats = [
                p
                for p in self.ph_slots[row]["valid"][: self.ph_slot_count[row]["valid"]]
                if p["seq"]
            ]
            invalid_pats = [
                p
                for p in self.ph_slots[row]["invalid"][
                    : self.ph_slot_count[row]["invalid"]
                ]
                if p["seq"]
            ]
            exist_pats = [
                p
                for p in self.ph_slots[row]["exist"][: self.ph_slot_count[row]["exist"]]
                if p["seq"]
            ]
            absent_pats = [
                p
                for p in self.ph_slots[row]["absent"][: self.ph_slot_count[row]["absent"]]
                if p["seq"]
            ]
            if any(row_match(row, pat) for pat in absent_pats):
                ok = False
                break
            if not ok:
                break

            # EXIST constraints
            if row == "start":
                if not _check_start_exist(word, exist_pats):
                    ok = False
                    break
            elif row == "inner":
                if not _check_inner_exist(word, exist_pats):
                    ok = False
                    break
            elif row == "middle":
                if not _check_middle_exist(word, exist_pats):
                    ok = False
                    break
            else:
                if not _check_end_exist(word, exist_pats):
                    ok = False
                    break

            if valid_pats and not any(row_match(row, p) for p in valid_pats):
                ok = False
                break
            if invalid_pats and any(row_match(row, p) for p in invalid_pats):
                ok = False
                break

        return ok

    def _run(self):
        try:
            for word in self.words:
                if self.cancelled:
                    break
                if self._word_matches(word):
                    self.results.append(word)
                self.done_count += 1
            self.progress_queue.put(("done", self.results))
        except Exception as e:
            self.progress_queue.put(("error", str(e)))

def poll_search_job():
    job = state.search_job
    if job is None:
        return

    try:
        while True:
            kind, payload = job.progress_queue.get_nowait()
            if kind == "done":
                state.search_results = payload
                state.word_selections = {}
                state.preview_start = 0
                state.results_cache_dirty = True
                rebuild_results_cache()
                n = len(payload)
                state.status = (
                    f'{n} word{"s" if n != 1 else ""} matched in {job.source_name}'
                )
                state.search_job = None
            elif kind == "error":
                state.search_results = []
                state.status = f"Search error: {payload}"
                state.search_job = None
    except queue.Empty:
        pass

def draw_search_progress_bar(surface, panel):
    job = state.search_job
    if job is None:
        return 0

    total = max(job.total, 1)
    done = clamp(job.done_count, 0, total)
    pct = done / total

    bar_x = panel.x + PAD
    bar_y = panel.y + 6
    bar_w = panel.width - 2 * PAD
    bar_h = 12

    track = pygame.Rect(bar_x, bar_y, bar_w, bar_h)
    pygame.draw.rect(surface, C.PANEL2, track, border_radius=6)
    pygame.draw.rect(surface, C.BORDER, track, 1, border_radius=6)

    fill = pygame.Rect(bar_x, bar_y, int(bar_w * pct), bar_h)
    if fill.width > 0:
        pygame.draw.rect(surface, C.GREEN, fill, border_radius=6)

    label = f"Searching… {int(pct * 100)}%"
    img = FONT_SM.render(label, True, C.TEXT)
    surface.blit(img, img.get_rect(center=track.center))

    return bar_h + 12

class AppState:
    def __init__(self):
        self.lm_word_length = 5  # Letter Match's word length
        self.ph_word_length = 5  # Pattern Hunt's word length (used when not "All")
        self.max_preview = 25
        self.preview_start = 0
        self.results_per_row = 5  # number of word buttons per row (1-20)
        self.input_scope = "single"
        self.greek_count = 0
        self.english_count = 0
        self.results_count = 0
        self.language = "greek"
        self.show_translation = True
        self.show_meaning = True
        self.english_meanings_file = resource_path("words/english_dictionary.json")
        self.greek_meanings_file = resource_path("words/greek_dictionary.json")
        self._translation_cache = (
            {}
        )  # (lang, word) -> loaded json dict (lazy, per active_file)
        self.colorize_status = True
        self.status_filters = set(STATUS_KEYS)

        self.results_status_map = {}
        self.results_status_counts = Counter()
        self.results_visible_words = []
        self.results_cache_dirty = True

        # ── Letter Match state ──
        self.input_mode = "valid"  # valid / invalid / exist
        self.exist_letters = Counter()
        self.absent_letters = []
        self.selected_pos = 0
        self.selected_exist_idx = 0  # for navigating exist letter items
        self.selected_absent_idx = 0  # for navigating absent letter items
        self.valid_sets = [set() for _ in range(5)]
        self.invalid_sets = [set() for _ in range(5)]
        # Per-position ordered history of toggle-on actions, so Backspace
        # can remove just the most recently added letter/group rather than
        # clearing the whole slot (Delete does the full clear instead).
        self.valid_history = [[] for _ in range(5)]
        self.invalid_history = [[] for _ in range(5)]
        # Store letter data per length, so expanding/shrinking preserves data
        self._stored_valid = {}  # pos -> set
        self._stored_invalid = {}  # pos -> set
        self._prev_word_length = 5

        self.keyboard_on = False
        self.keyboard_caps = False
        self.keyboard_tone = 0  # 0=plain, 1=tonos, 2=diaeresis, 3=both

        # ── Pattern Hunt state ──
        self.finder_mode = "letter_match"  # letter_match / pattern_hunt
        self.ph_mode = "start"  # selected row: start / middle / end
        self.ph_col = "valid"  # selected column: valid / invalid / exist
        self.ph_scope = "single"  # single / all
        self.ph_selected = {row: {col: 0 for col in PH_COLS} for row in PH_ROWS}
        self.ph_slots = {
            row: {
                col: [_make_pattern_slot() for _ in range(MAX_PATTERN_SLOTS)]
                for col in PH_COLS
            }
            for row in PH_ROWS
        }
        self.ph_slot_count = {row: {col: 3 for col in PH_COLS} for row in PH_ROWS}

        # word length "All" mode for Pattern Hunt
        self.ph_word_length_all = True

        self.search_results = []
        self.search_job = None
        self.status = "Load a word list, then press Search or Enter."
        self.greek_file = resource_path("words/greek_words.txt")
        self.english_file = resource_path("words/english_words.txt")
        self.results_file = resource_path("words/results.txt")
        self.theme = "dark"

        # Results selection: word -> "save" | "exclude" | None
        self.word_selections = {}  # word -> "save" | "exclude"

    @property
    def word_length(self):
        """transparently routes to the per-mode word length variable
        so every existing call site (`state.word_length`) keeps working
        without further edits, while Letter Match and Pattern Hunt each
        keep their own independent value."""
        return (
            self.ph_word_length
            if self.finder_mode == "pattern_hunt"
            else self.lm_word_length
        )

    @word_length.setter
    def word_length(self, value):
        if self.finder_mode == "pattern_hunt":
            self.ph_word_length = value
        else:
            self.lm_word_length = value

    def rebuild_sets(self):
        """Called when word_length changes. Preserves existing data.
        Pattern Hunt doesn't use valid_sets/invalid_sets at all,
        so this is a no-op there (its own ph_word_length already changed
        via the property setter above; nothing else needs rebuilding)."""
        if self.finder_mode == "pattern_hunt":
            return

        old_n = self._prev_word_length
        new_n = self.word_length

        # Save current sets into storage
        for p in range(old_n):
            if self.valid_sets[p]:
                self._stored_valid[p] = set(self.valid_sets[p])
            if self.invalid_sets[p]:
                self._stored_invalid[p] = set(self.invalid_sets[p])

        # Rebuild for new length, restoring stored data if available
        self.valid_sets = [set(self._stored_valid.get(p, set())) for p in range(new_n)]
        self.invalid_sets = [
            set(self._stored_invalid.get(p, set())) for p in range(new_n)
        ]

        # Keep per-position history arrays the same length as the sets.
        # Positions that still exist keep their history; new positions start
        # with empty history (their restored set, if any, can still be
        # fully cleared via Delete).
        old_valid_hist = self.valid_history
        old_invalid_hist = self.invalid_history
        self.valid_history = [
            list(old_valid_hist[p]) if p < len(old_valid_hist) else []
            for p in range(new_n)
        ]
        self.invalid_history = [
            list(old_invalid_hist[p]) if p < len(old_invalid_hist) else []
            for p in range(new_n)
        ]

        # When shrinking, discard stored data beyond new_n
        if new_n < old_n:
            for p in range(new_n, old_n):
                self._stored_valid.pop(p, None)
                self._stored_invalid.pop(p, None)

        self.selected_pos = clamp(self.selected_pos, 0, max(new_n - 1, 0))
        self._prev_word_length = new_n
        self.search_results = []
        self.preview_start = 0

    def active_file(self):
        return self.greek_file if self.language == "greek" else self.english_file

    def preview(self):
        return self.search_results[
            self.preview_start : self.preview_start + self.max_preview
        ]

    def clamp_preview_start(self):
        if not self.search_results:
            self.preview_start = 0
            return
        self.preview_start = clamp(self.preview_start, 0, len(self.search_results) - 1)

    def active_ph_mode_modes(self):
        return PH_ROWS

    def ph_selected_slot_idx(self, row=None, col=None):
        row = row if row is not None else self.ph_mode
        col = col if col is not None else self.ph_col
        return self.ph_selected[row][col]

    def ph_visible_slots(self, row=None, col=None):
        row = row if row is not None else self.ph_mode
        col = col if col is not None else self.ph_col
        return self.ph_slot_count[row][col]

    def get_exist_items(self):
        """Return list of (key, count) for exist letters."""
        return list(self.exist_letters.items())

    def get_absent_letters(self):
        """Return list of absent letters."""
        return list(enumerate(state.absent_letters))

    def cycle_input_mode_lm(self, step):
        idx = INPUT_MODES_LM.index(self.input_mode)
        self.input_mode = INPUT_MODES_LM[(idx + step) % len(INPUT_MODES_LM)]

    def cycle_ph_mode(self, step):
        idx = INPUT_MODES_PH.index(self.ph_mode)
        self.ph_mode = INPUT_MODES_PH[(idx + step) % len(INPUT_MODES_PH)]

state = AppState()

set_theme(state.theme)

def ph_cell_key(row=None, col=None):
    row = row if row is not None else state.ph_mode
    col = col if col is not None else state.ph_col
    return row, col

def ph_cell_slots(row=None, col=None):
    row, col = ph_cell_key(row, col)
    return state.ph_slots[row][col]

def ph_cell_count(row=None, col=None):
    row, col = ph_cell_key(row, col)
    return state.ph_slot_count[row][col]

def ph_cell_selected_idx(row=None, col=None):
    row, col = ph_cell_key(row, col)
    return state.ph_selected[row][col]

def ph_set_cell_selected_idx(idx, row=None, col=None):
    row, col = ph_cell_key(row, col)
    cnt = max(1, ph_cell_count(row, col))
    state.ph_selected[row][col] = clamp(idx, 0, cnt - 1)

def ph_adjust_cell_count(delta, row=None, col=None):
    row, col = ph_cell_key(row, col)
    cur = ph_cell_count(row, col)
    new = clamp(cur + delta, 1, MAX_PATTERN_SLOTS)
    if new == cur:
        return
    if new < cur:
        for i in range(new, cur):
            state.ph_slots[row][col][i]["seq"] = ""
            state.ph_slots[row][col][i]["expanded"] = False
    state.ph_slot_count[row][col] = new
    ph_set_cell_selected_idx(state.ph_selected[row][col], row, col)

tk_root = None

enrichment_choice_win = None

manual_entry_win = None

def get_tk_root():
    global tk_root
    if tk_root is None or not tk_root.winfo_exists():
        tk_root = Tk()
        tk_root.withdraw()
        tk_root.attributes("-topmost", True)
    return tk_root

def open_text_file(path):
    if not path or not os.path.exists(path):
        state.status = f"File not found: {path}"
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        state.status = f"Opened: {os.path.basename(path)}"
    except Exception as e:
        state.status = f"Open error: {e}"

def format_set(s):
    return " ".join("".join(sorted(x)) for x in s) if s else f"{special_chars["-"]}"

def copy_to_clipboard(text: str) -> bool:
    """Copies text to the system clipboard.

    Tries the native OS clipboard tool first (clip.exe on Windows, pbcopy
    on macOS, xclip/xsel on Linux). These write the data to the clipboard
    and exit immediately, without needing to stay alive afterwards.

    Falls back to Tk's clipboard (which requires our hidden root to keep
    running and servicing selection requests) only if no native tool is
    available. The Tk fallback can make some paste targets (e.g. Notepad)
    hang or feel slow while waiting on our process, since our main loop is
    pygame's, not Tk's, and can't service those requests promptly - so it's
    a last resort, not the default.
    """
    try:
        if sys.platform.startswith("win"):
            proc = subprocess.Popen(
                ["clip"], stdin=subprocess.PIPE, close_fds=True
            )
            proc.communicate(input=text.encode("utf-16-le"), timeout=5)
            if proc.returncode == 0:
                return True
        elif sys.platform == "darwin":
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, close_fds=True)
            proc.communicate(input=text.encode("utf-8"), timeout=5)
            if proc.returncode == 0:
                return True
        else:
            for cmd in (
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
                ["wl-copy"],
            ):
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                    )
                    proc.communicate(input=text.encode("utf-8"), timeout=5)
                    if proc.returncode == 0:
                        return True
                except FileNotFoundError:
                    continue
    except Exception:
        pass

    # Fallback: Tk clipboard (best-effort; see caveats above).
    try:
        root = get_tk_root()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        return True
    except Exception:
        return False

def build_summary_lines():
    """Builds the text lines for the Slots Review / Patterns Review modal,
    shared between the on-screen display and the copy-to-clipboard action."""
    lines = []
    if state.finder_mode == "letter_match":
        lines.append("VALID")
        for i, s in enumerate(state.valid_sets, 1):
            lines.append(f"  {i}: {format_set(s)}")
        lines.append("")
        lines.append("INVALID")
        for i, s in enumerate(state.invalid_sets, 1):
            lines.append(f"  {i}: {format_set(s)}")
        lines.append("")
        lines.append("EXIST")
        if state.exist_letters:
            parts = []
            for key, count in state.exist_letters.items():
                if state.language == "greek":
                    group = GREEK_GROUP_BY_FIRST.get(key, (key,))
                else:
                    group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
                label = "".join(group)
                parts.append(f"{label} (x{count})" if count > 1 else label)
            lines.append("  " + f" {special_chars["*"]} ".join(parts))
        else:
            lines.append(f"  {special_chars["-"]}")
        lines.append("")
        lines.append("ABSENT")
        if state.absent_letters:
            parts = []
            for key in state.absent_letters:
                if state.language == "greek":
                    group = GREEK_GROUP_BY_FIRST.get(key, (key,))
                else:
                    group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
                parts.append("".join(group))
            lines.append("  " + f" {special_chars["*"]} ".join(parts))
        else:
            lines.append(f"  {special_chars["-"]}")
    else:
        # Pattern Hunt
        for row_name in ["start", "inner", "middle", "end"]:
            lines.append(row_name.upper())
            for col_name in ["valid", "invalid", "exist", "absent"]:
                lines.append(f"  [{col_name.upper()}]")
                count = state.ph_slot_count[row_name][col_name]
                for i in range(count):
                    slot = state.ph_slots[row_name][col_name][i]
                    seq = slot["seq"]
                    exp = slot["expanded"]
                    if seq:
                        disp = expand_sequence(seq, state.language) if exp else seq
                        tag = " [expanded]" if exp else ""
                        lines.append(f"    {i+1}: {disp}{tag}")
                    else:
                        lines.append(f"    {i+1}: {special_chars['-']}")
            lines.append("")
    return lines

def refresh_summary_window():
    """No-op kept for compatibility: the Slots/Patterns Review is now a
    pygame modal (SummaryModal) that reads live state on every draw, so no
    manual refresh call is needed."""
    return

def _tk_root_temp():
    r = Tk()
    r.withdraw()
    r.attributes("-topmost", True)
    return r

def open_file_dialog():
    r = _tk_root_temp()
    p = filedialog.askopenfilename(
        parent=r,
        title="Choose word list",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    r.destroy()
    return p or ""

def save_file_dialog(initial="results.txt"):
    r = _tk_root_temp()
    p = filedialog.asksaveasfilename(
        parent=r,
        title="Save results as",
        initialfile=os.path.basename(initial),
        defaultextension=".txt",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    r.destroy()
    return p or ""

def refresh_words_counts():
    state.greek_count = len(load_words(state.greek_file))
    state.english_count = len(load_words(state.english_file))
    state.results_count = len(load_words(state.results_file))

def rgb_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])

def _sync_meanings_cache(path, data):
    try:
        _meanings_cache[path] = {"mtime": os.path.getmtime(path), "data": data}
    except OSError:
        _meanings_cache[path] = {"mtime": 0, "data": data}

def save_manual_translation(word, translation, language):
    path = (
        state.english_meanings_file
        if language == "english"
        else state.greek_meanings_file
    )
    data = load_json_dict(path)
    key = normalize_word(word)
    existing = data.get(key, {})

    senses = existing.get("senses")
    if not isinstance(senses, list):
        senses = []

    cleaned = clean_translation(word, translation)

    entry = dict(existing)
    entry["input_word"] = word
    if language == "english":
        entry["greek_translation"] = cleaned
    else:
        entry["english_translation"] = cleaned
    entry["senses"] = senses
    entry["status"] = build_status(word, cleaned, senses)

    data[key] = entry
    save_json_atomic(path, data)
    _sync_meanings_cache(path, data)
    state.results_cache_dirty = True

    return entry

def save_manual_meaning(word, senses_input, language):
    """
    senses_input: list of up to MAX_SENSES (10) tuples
        (part_of_speech, definition, examples)
    where examples is a list of up to 3 example strings. Slots with a blank
    definition are dropped entirely (so leaving later slots empty doesn't
    save empty senses).
    """
    path = (
        state.english_meanings_file
        if language == "english"
        else state.greek_meanings_file
    )
    data = load_json_dict(path)
    key = normalize_word(word)
    existing = data.get(key, {})

    senses = []
    for pos, definition, examples in senses_input:
        definition = str(definition or "").strip()
        if not definition:
            continue
        pos = str(pos or "").strip()
        cleaned_examples = [str(ex).strip() for ex in (examples or []) if str(ex).strip()][:3]
        senses.append(
            {
                "part_of_speech": pos,
                "definition": definition,
                "examples": cleaned_examples,
            }
        )

    translation = (
        existing.get("greek_translation")
        if language == "english"
        else existing.get("english_translation")
    )
    translation = clean_translation(word, translation)

    entry = dict(existing)
    entry["input_word"] = word
    if language == "english":
        entry["greek_translation"] = translation
    else:
        entry["english_translation"] = translation
    entry["senses"] = senses
    entry["status"] = build_status(word, translation, senses)

    data[key] = entry
    save_json_atomic(path, data)
    _sync_meanings_cache(path, data)
    state.results_cache_dirty = True
    return entry

def add_exist_letter(letter: str):
    key = exist_key_for_input(letter, state.language)
    if key is None:
        return
    state.exist_letters[key] += 1

def delete_exist_item_at(idx):
    """Delete the exist letter group at the given index."""
    items = state.get_exist_items()
    if 0 <= idx < len(items):
        key, _ = items[idx]
        del state.exist_letters[key]
        state.selected_exist_idx = clamp(
            state.selected_exist_idx, 0, max(len(state.exist_letters) - 1, 0)
        )

def target_positions():
    return (
        range(state.word_length)
        if state.input_scope == "all"
        else (state.selected_pos,)
    )

def toggle_letter(letter):
    targets = tokens_for_input(letter, state.language)
    if not targets:
        return
    for p in target_positions():
        if p < 0 or p >= state.word_length:
            continue
        tgt = (
            state.valid_sets[p]
            if state.input_mode == "valid"
            else state.invalid_sets[p]
        )
        hist = (
            state.valid_history[p]
            if state.input_mode == "valid"
            else state.invalid_history[p]
        )
        turned_on = False
        for tok in targets:
            if tok in tgt:
                tgt.remove(tok)
            else:
                tgt.add(tok)
                turned_on = True
        # Drop any previous history entry for this exact group (it may have
        # just been toggled off), then record it as the most recent
        # toggle-on action so Backspace can undo precisely this group.
        if frozenset(targets) in hist:
            hist.remove(frozenset(targets))
        if turned_on:
            hist.append(frozenset(targets))

def backspace_letter_slot():
    """Removes only the most recently toggled-on letter/group from the
    targeted Valid/Invalid slot(s), leaving the rest of the slot intact.
    (Delete/clear_letter_slot fully empties the slot instead.)"""
    for p in target_positions():
        if p < 0 or p >= state.word_length:
            continue
        tgt = (
            state.valid_sets[p]
            if state.input_mode == "valid"
            else state.invalid_sets[p]
        )
        hist = (
            state.valid_history[p]
            if state.input_mode == "valid"
            else state.invalid_history[p]
        )
        if hist:
            last = hist.pop()
            tgt.difference_update(last)
        elif tgt:
            # No tracked history (e.g. data restored from a resize) but the
            # slot isn't empty: fall back to clearing one arbitrary letter
            # rather than doing nothing.
            tgt.pop()

def clear_letter_slot():
    """Fully clears the targeted Valid/Invalid slot(s) and their history."""
    for p in target_positions():
        if p < 0 or p >= state.word_length:
            continue
        if state.input_mode == "valid":
            state.valid_sets[p].clear()
            state.valid_history[p].clear()
        else:
            state.invalid_sets[p].clear()
            state.invalid_history[p].clear()

def ph_target_slots():
    row, col = ph_cell_key()
    count = ph_cell_count(row, col)
    if state.ph_scope == "all":
        return list(range(count))
    return [ph_cell_selected_idx(row, col)]

def ph_add_letter(ch):
    row, col = ph_cell_key()
    for idx in ph_target_slots():
        slot = ph_cell_slots(row, col)[idx]
        slot["seq"] += ch

def ph_backspace():
    """Removes the last character of the sequence in the current Pattern
    Hunt slot(s), one letter at a time."""
    row, col = ph_cell_key()
    for idx in ph_target_slots():
        slot = ph_cell_slots(row, col)[idx]
        if slot["seq"]:
            slot["seq"] = slot["seq"][:-1]
            if not slot["seq"]:
                slot["expanded"] = False

def ph_clear_slot():
    """Fully clears the current Pattern Hunt slot(s) in one action."""
    row, col = ph_cell_key()
    for idx in ph_target_slots():
        slot = ph_cell_slots(row, col)[idx]
        slot["seq"] = ""
        slot["expanded"] = False

def ph_toggle_expand():
    row, col = ph_cell_key()
    for idx in ph_target_slots():
        slot = ph_cell_slots(row, col)[idx]
        if slot["seq"]:
            slot["expanded"] = not slot["expanded"]

def do_search():
    try:
        words = load_words(state.active_file())
    except Exception as e:
        state.search_results = []
        state.status = f"Load error: {e}"
        return

    if not words:
        state.search_results = []
        state.status = (
            f"No words loaded {special_chars['-']} check: {state.active_file()}"
        )
        return

    if state.search_job is not None:
        state.search_job.cancel()

    if state.finder_mode == "letter_match":
        search_job = SearchJob(
            words=words,
            finder_mode="letter_match",
            language=state.language,
            word_length=state.word_length,
            valid_sets=[set(s) for s in state.valid_sets],
            invalid_sets=[set(s) for s in state.invalid_sets],
            exist_letters=Counter(state.exist_letters),
            absent_letters=list(state.absent_letters),
            source_name=os.path.basename(state.active_file()),
        )
    else:
        search_job = SearchJob(
            words=words,
            finder_mode="pattern_hunt",
            language=state.language,
            word_length=state.word_length,
            ph_word_length_all=state.ph_word_length_all,
            ph_slots={
                row: {
                    col: [slot.copy() for slot in state.ph_slots[row][col]]
                    for col in PH_COLS
                }
                for row in PH_ROWS
            },
            ph_slot_count={row: dict(state.ph_slot_count[row]) for row in PH_ROWS},
            source_name=os.path.basename(state.active_file()),
        )

    state.search_job = search_job
    state.status = (
        f"Searching {len(words)} words in {os.path.basename(state.active_file())}…"
    )
    search_job.start()

def do_save():
    # Determine what to save
    to_save_words = []
    marked = [w for w, v in state.word_selections.items() if v == "save"]
    if marked:
        to_save_words = [w for w in state.search_results if w in set(marked)]
    else:
        excluded = {w for w, v in state.word_selections.items() if v == "exclude"}
        to_save_words = [w for w in state.search_results if w not in excluded]

    if not to_save_words:
        state.status = f"Nothing to save {special_chars["-"]} run Search first."
        return
    path = state.results_file.strip() or save_file_dialog()
    if not path:
        state.status = "Save cancelled."
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            for w in to_save_words:
                f.write(w + "\n")
        state.results_file = path
        state.results_count = len(load_words(path))
        state.status = f"Saved {state.results_count} words {special_chars[">"]} {os.path.basename(path)}"
    except Exception as e:
        state.status = f"Save error: {e}"

def get_target_words():
    """
    Target words for Save / Translation / Meaning.

    Priority:
    1) marked "save" words
    2) visible results if any category filters are active
    3) all search results except excluded words
    """
    marked = [w for w, v in state.word_selections.items() if v == "save"]
    if marked:
        marked_set = set(marked)
        return [w for w in state.search_results if w in marked_set]

    # Prefer what is currently visible in the results panel.
    visible = getattr(state, "results_visible_words", None) or []
    if visible:
        excluded = {w for w, v in state.word_selections.items() if v == "exclude"}
        return [w for w in visible if w not in excluded]

    excluded = {w for w, v in state.word_selections.items() if v == "exclude"}
    return [w for w in state.search_results if w not in excluded]

def do_translate_action():
    """kicks off a background EnrichmentJob that translates the
    target words and saves results into the correct JSON file, showing
    progress in progress_modal."""
    words = get_target_words()
    if not words:
        state.status = (
            f"Nothing to translate {special_chars['-']} search results are empty."
        )
        return
    job = EnrichmentJob("translation", words, state.language)
    progress_modal.start(job, f"Translating {len(words)} word(s)…")

def do_get_meaning_action():
    """kicks off a background EnrichmentJob that fetches meanings
    (WordNet senses for English; Greek words only get their translation
    refreshed, since WordNet senses require English) for the target words."""
    words = get_target_words()
    if not words:
        state.status = (
            f"Nothing to look up {special_chars['-']} search results are empty."
        )
        return
    job = EnrichmentJob("meaning", words, state.language)
    progress_modal.start(job, f"Getting meaning for {len(words)} word(s)…")

def _get_cached_json(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    entry = _meanings_cache.get(path)
    if entry is not None and entry["mtime"] == mtime:
        return entry["data"]
    data = load_json_dict(path)
    _meanings_cache[path] = {"mtime": mtime, "data": data}
    return data

def lookup_word_entry(word, language):
    """Returns the raw JSON entry dict for `word` in the given source
    language ('greek' or 'english'), or None if not found."""
    path = (
        state.greek_meanings_file
        if language == "greek"
        else state.english_meanings_file
    )
    data = _get_cached_json(path)
    return data.get(normalize_word(word))

def format_meaning_lines(entry, language):
    lines = []
    senses_limit = 10
    examples_limit = 3
    if entry is None:
        return [f"No saved meaning yet {special_chars['-']} use Meaning."]

    if language == "greek":
        note = entry.get("senses_note")
        if note:
            lines.append(note)

    senses = entry.get("senses") or []
    if not senses:
        lines.append(f"No senses found {special_chars['-']} try Meaning.")
    else:
        pos_names = {
            "n": "noun",
            "v": "verb",
            "a": "adjective",
            "s": "adjective",
            "r": "adverb",
        }
        for i, sense in enumerate(senses[:senses_limit], 1):
            pos = pos_names.get(
                sense.get("part_of_speech", ""), sense.get("part_of_speech", "?")
            )
            definition = sense.get("definition", "")
            examples = sense.get("examples") or []
            lines.append(f"{i}. {pos}: {definition}")
            for ex in examples[:examples_limit]:
                lines.append(f"   eg: {ex}")

    return lines

def get_word_status(word, language):
    entry = lookup_word_entry(word, language)
    return (entry or {}).get("status", "no_translation_no_meaning")

def send_words_to_results(words):
    """Transfers the given word list into the results panel, replacing the
    current search results. Used by the Show Words modal's "-> Results"
    button so its (filtered) word list can be browsed/saved from the main
    results panel just like a normal search."""
    state.search_results = list(words)
    state.word_selections = {}
    state.preview_start = 0
    state.results_cache_dirty = True
    state.status = f"Sent {len(state.search_results)} word(s) to results"

def rebuild_results_cache():
    counts = Counter({k: 0 for k in STATUS_KEYS})
    status_map = {}

    for w in state.search_results:
        st = get_word_status(w, state.language)
        status_map[w] = st
        if st in counts:
            counts[st] += 1

    state.results_status_map = status_map
    state.results_status_counts = counts
    state.results_visible_words = [
        w for w in state.search_results if status_map.get(w) in state.status_filters
    ]
    state.results_cache_dirty = False

def refresh_visible_results():
    state.results_visible_words = [
        w
        for w in state.search_results
        if state.results_status_map.get(w) in state.status_filters
    ]

def _display_alphabet(language: str):
    if language == "greek":
        return [group[0].upper() for group in GREEK_GROUPS]
    return [ch.upper() for ch in ENGLISH_LETTERS]

def _base_letter(ch: str, language: str):
    if not ch or not ch.isalpha():
        return None
    if language == "greek":
        return GREEK_CHAR_TO_FIRST.get(ch, ch).upper()
    return ch.upper()

def _word_letters(word: str, language: str):
    return [_base_letter(ch, language) for ch in word if _base_letter(ch, language)]

def _is_vowel(ch: str, language: str):
    if not ch:
        return False
    if language == "greek":
        return ch in {"Α", "Ε", "Η", "Ι", "Ο", "Υ", "Ω"}
    return ch in {"A", "E", "I", "O", "U", "Y"}

def _count_vowel_groups(word: str, language: str):
    letters = _word_letters(word, language)
    if not letters:
        return 0
    groups = 0
    in_group = False
    for ch in letters:
        if _is_vowel(ch, language):
            if not in_group:
                groups += 1
                in_group = True
        else:
            in_group = False
    if language == "english" and letters[-1] == "E" and groups > 1:
        groups -= 1
    return max(groups, 1)

def _estimate_syllables(word: str, language: str):
    # Simple vowel-group heuristic with a light English silent-E adjustment.
    return _count_vowel_groups(word, language)

def _stats_summary(values):
    if not values:
        return (0, 0, 0)
    if len(values) == 1:
        return (values[0], values[0], 0)
    return (mean(values), median(values), pstdev(values))

def _bucket_label(start_frac, end_frac):
    return f"{int(start_frac * 100)}–{int(end_frac * 100)}%"

def _top_ngrams(words, language, n=2, top_n=15):
    counter = Counter()
    for word in words:
        letters = _word_letters(word, language)
        for i in range(len(letters) - n + 1):
            seq = "".join(letters[i : i + n])
            counter[seq] += 1
    return counter.most_common(top_n)

def get_word_translation(word, language):
    """Returns a short translation string for the hover tooltip, or None."""
    entry = lookup_word_entry(word, language)
    if entry is None:
        return None
    if language == "english":
        return entry.get("greek_translation")
    else:
        return entry.get("english_translation")

def get_word_first_definition(word, language):
    """Returns only the first saved sense's definition text for `word`,
    or None if no senses are saved. Used for compact single-line display
    (e.g. in the Show Words list) rather than the full multi-sense tooltip."""
    entry = lookup_word_entry(word, language)
    if entry is None:
        return None
    senses = entry.get("senses") or []
    if not senses:
        return None
    definition = senses[0].get("definition", "")
    return definition or None

def format_progress_result_lines(job_kind, entry, language):
    """
    Returns the extra lines shown under each processed word in the progress modal.
    - translate: just the translation line
    - meaning: translation line (if available) + meaning lines
    """
    if entry is None:
        return [f"No saved result yet {special_chars['-']} use the button again."]

    translation = (
        entry.get("greek_translation")
        if language == "english"
        else entry.get("english_translation")
    )

    if job_kind == "translation":
        if translation:
            return [f"Translation {special_chars['-']} {translation}"]
        return [f"No translation found {special_chars['-']} try Translate."]

    lines = []
    if translation:
        lines.append(f"Translation {special_chars['-']} {translation}")
    lines.extend(format_meaning_lines(entry, language))
    return lines

def toggle_finder_mode():
    if state.finder_mode == "letter_match":
        state.finder_mode = "pattern_hunt"
    else:
        state.finder_mode = "letter_match"
    state.search_results = []
    state.word_selections = {}
    state.preview_start = 0
    state.ph_mode = "start"
    state.ph_col = "valid"
    state.status = f"Switched to {'Pattern Hunt' if state.finder_mode == 'pattern_hunt' else 'Letter Match'}"
    refresh_summary_window()
