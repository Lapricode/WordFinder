import os
import sys
import pygame
from tkinter import Tk, filedialog, Toplevel, Text, Button, END, TclError
from collections import Counter
import subprocess

# ══════════════════════════════════════════════════════════════════
#  Core filtering logic
# ══════════════════════════════════════════════════════════════════

GREEK_LETTERS = [
    "αάΑΆ",
    "βΒ",
    "ψΨ",
    "δΔ",
    "εέΕΈ",
    "φΦ",
    "γΓ",
    "ηήΗΉ",
    "ιίΙΊϊΐ",
    "ξΞ",
    "κΚ",
    "λΛ",
    "μΜ",
    "νΝ",
    "οόΟΌ",
    "πΠ",
    "ρΡ",
    "σΣς",
    "τΤ",
    "θΘ",
    "ωΩώΏ",
    "χΧ",
    "υύΥΎϋΰ",
    "ζΖ",
]

GREEK_GROUPS = [tuple(group) for group in GREEK_LETTERS]
GREEK_FIRST_LETTERS = {group[0] for group in GREEK_GROUPS}
GREEK_GROUP_BY_FIRST = {group[0]: group for group in GREEK_GROUPS}

# Build a reverse map: any greek char -> group first letter
GREEK_CHAR_TO_FIRST = {}
for g in GREEK_GROUPS:
    for ch in g:
        GREEK_CHAR_TO_FIRST[ch] = g[0]

ENGLISH_LETTERS = [chr(c) for c in range(ord("a"), ord("z") + 1)]
ENGLISH_GROUPS = [(ch, ch.upper()) for ch in ENGLISH_LETTERS]
ENGLISH_GROUP_BY_FIRST = {group[0]: group for group in ENGLISH_GROUPS}
ENGLISH_CHAR_TO_FIRST = {}
for g in ENGLISH_GROUPS:
    for ch in g:
        ENGLISH_CHAR_TO_FIRST[ch] = g[0]

INPUT_MODES_LM = ["valid", "invalid", "exist"]
INPUT_MODES_PH = ["start", "end", "middle"]

FINDER_MODES = ["letter_match", "pattern_hunt"]


def match_key(ch: str) -> str:
    return ch.casefold() if ch else ""


def tokens_for_input(letter: str, language: str) -> set:
    if not letter:
        return set()
    letter = letter.strip()
    if len(letter) != 1 or not letter.isalpha():
        return set()
    if language == "greek":
        group = GREEK_GROUP_BY_FIRST.get(letter)
        if group is not None:
            return set(group)
    if language == "english":
        group = ENGLISH_GROUP_BY_FIRST.get(letter)
        if group is not None:
            return set(group)
    return {letter}


def normalize_char(ch: str, language: str) -> str:
    return ch.casefold() if ch else ""


def load_words(file_path: str):
    if not os.path.exists(file_path):
        return []
    for enc in ("utf-8", "utf-8-sig", "cp1253", "latin-1"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                return [w.strip() for line in f for w in line.split()]
        except UnicodeDecodeError:
            pass
    raise UnicodeDecodeError("Could not decode file with common encodings")


def find_matching_words(
    words_list, word_length, valid_sets, invalid_sets, exist_letters, language
):
    results = []
    for word in words_list:
        if len(word) != word_length:
            continue
        ok = True
        for pos in range(word_length):
            ch = word[pos]
            if valid_sets[pos] and ch not in valid_sets[pos]:
                ok = False
                break
            if invalid_sets[pos] and ch in invalid_sets[pos]:
                ok = False
                break
        if not ok:
            continue
        if exist_letters:
            wc = Counter(word)
            for key, needed in exist_letters.items():
                if language == "greek":
                    group = GREEK_GROUP_BY_FIRST.get(key, (key,))
                elif language == "english":
                    group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
                else:
                    group = (key,)
                count = sum(wc[ch] for ch in group)
                if count < needed:
                    ok = False
                    break
        if ok:
            results.append(word)
    return results


def find_pattern_words(
    words_list, word_length, start_patterns, end_patterns, middle_patterns, language
):
    """Filter words by pattern hunt rules."""
    results = []
    for word in words_list:
        if word_length is not None and len(word) != word_length:
            continue
        ok = True

        # start patterns: each pattern must match the beginning of the word
        for pat_info in start_patterns:
            seq = pat_info["seq"]
            expanded = pat_info["expanded"]
            if not seq:
                continue
            if len(word) < len(seq):
                ok = False
                break
            if expanded:
                # check char by char with group expansion
                for ci, ch_pat in enumerate(seq):
                    wch = word[ci]
                    if language == "greek":
                        if GREEK_CHAR_TO_FIRST.get(ch_pat) != GREEK_CHAR_TO_FIRST.get(
                            wch
                        ):
                            ok = False
                            break
                    elif language == "english":
                        if ch_pat.lower() != wch.lower():
                            ok = False
                            break
                    else:
                        if ch_pat != wch:
                            ok = False
                            break
                if not ok:
                    break
            else:
                # exact match at start
                if not word.startswith(seq):
                    ok = False
                    break
        if not ok:
            continue

        # end patterns
        for pat_info in end_patterns:
            seq = pat_info["seq"]
            expanded = pat_info["expanded"]
            if not seq:
                continue
            if len(word) < len(seq):
                ok = False
                break
            if expanded:
                suffix = word[-len(seq) :]
                for ci, ch_pat in enumerate(seq):
                    wch = suffix[ci]
                    if language == "greek":
                        if GREEK_CHAR_TO_FIRST.get(ch_pat) != GREEK_CHAR_TO_FIRST.get(
                            wch
                        ):
                            ok = False
                            break
                    elif language == "english":
                        if ch_pat.lower() != wch.lower():
                            ok = False
                            break
                    else:
                        if ch_pat != wch:
                            ok = False
                            break
                if not ok:
                    break
            else:
                if not word.endswith(seq):
                    ok = False
                    break
        if not ok:
            continue

        # middle patterns: appear anywhere in the word
        for pat_info in middle_patterns:
            seq = pat_info["seq"]
            expanded = pat_info["expanded"]
            if not seq:
                continue
            found_mid = False
            for start_i in range(len(word) - len(seq) + 1):
                chunk = word[start_i : start_i + len(seq)]
                if expanded:
                    match_all = True
                    for ci, ch_pat in enumerate(seq):
                        wch = chunk[ci]
                        if language == "greek":
                            if GREEK_CHAR_TO_FIRST.get(
                                ch_pat
                            ) != GREEK_CHAR_TO_FIRST.get(wch):
                                match_all = False
                                break
                        elif language == "english":
                            if ch_pat.lower() != wch.lower():
                                match_all = False
                                break
                        else:
                            if ch_pat != wch:
                                match_all = False
                                break
                    if match_all:
                        found_mid = True
                        break
                else:
                    if chunk == seq:
                        found_mid = True
                        break
            if not found_mid:
                ok = False
                break

        if ok:
            results.append(word)
    return results


def exist_key_for_input(letter: str, language: str):
    if not letter:
        return None
    letter = letter.strip()
    if len(letter) != 1 or not letter.isalpha():
        return None
    if language == "greek" and letter in GREEK_GROUP_BY_FIRST:
        return letter
    if language == "english" and letter in ENGLISH_GROUP_BY_FIRST:
        return letter
    return letter


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def expand_sequence(seq, language):
    """Convert a sequence like 'οσ' into all-variants string like 'ΟΌοόΣσς'"""
    result = []
    for ch in seq:
        if language == "greek":
            first = GREEK_CHAR_TO_FIRST.get(ch)
            if first:
                grp = GREEK_GROUP_BY_FIRST[first]
                # add all chars in group that aren't already added
                for gc in grp:
                    if gc not in result:
                        result.append(gc)
            else:
                if ch not in result:
                    result.append(ch)
        elif language == "english":
            result.append(ch.lower())
            result.append(ch.upper())
        else:
            result.append(ch)
    return "".join(dict.fromkeys(result))  # deduplicate preserving order


# ══════════════════════════════════════════════════════════════════
#  Pygame + fonts
# ══════════════════════════════════════════════════════════════════

pygame.init()
pygame.display.set_caption("Word Finder")

WIDTH, HEIGHT = 1400, 700
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
clock = pygame.time.Clock()

FONT = pygame.font.SysFont("segoeui", 17)
FONT_SM = pygame.font.SysFont("segoeui", 14)
FONT_MD = pygame.font.SysFont("segoeui", 18, bold=True)
FONT_LG = pygame.font.SysFont("segoeui", 26, bold=True)
FONT_XL = pygame.font.SysFont("segoeui", 32, bold=True)
LINK_FONT_SM = pygame.font.SysFont("segoeui", 14)
LINK_FONT_SM.set_underline(True)
FONT_BTN_SMALL = pygame.font.SysFont("segoeui", 13, bold=True)

# ─── Colour palette ───────────────────────────────────────────────
BG = (240, 242, 247)
SLOT = (255, 255, 255)
PANEL = (255, 255, 255)
PANEL2 = (248, 249, 252)
BORDER = (213, 218, 230)
TEXT = (26, 30, 42)
MUTED = (108, 116, 136)
ACCENT = (0, 0, 255)
BLUE_BG = (220, 220, 255)
GREEN = (46, 164, 79)
GREEN_BG = (233, 248, 238)
GREEN_BDR = (130, 210, 150)
RED = (204, 58, 58)
RED_BG = (251, 233, 233)
RED_BDR = (220, 140, 140)
PURPLE = (122, 75, 200)
CYAN = (122, 150, 200)
DARK = (52, 58, 74)
WHITE = (255, 255, 255)
BROWN = (150, 102, 54)
BROWN_BG = (248, 239, 230)
BROWN_BDR = (209, 181, 154)
ORANGE = (255, 165, 0)
TEAL = (0, 160, 140)
TEAL_BG = (220, 248, 244)
TEAL_BDR = (100, 200, 180)
PINK = (200, 60, 140)
PINK_BG = (250, 230, 242)
PINK_BDR = (210, 140, 185)

LIGHT_THEME = {
    "BG": (240, 242, 247),
    "SLOT": (255, 255, 255),
    "PANEL": (255, 255, 255),
    "PANEL2": (248, 249, 252),
    "BORDER": (213, 218, 230),
    "TEXT": (26, 30, 42),
    "MUTED": (108, 116, 136),
    "ACCENT": (0, 0, 255),
    "BLUE_BG": (220, 220, 255),
    "GREEN": (46, 164, 79),
    "GREEN_BG": (233, 248, 238),
    "GREEN_BDR": (130, 210, 150),
    "RED": (204, 58, 58),
    "RED_BG": (251, 233, 233),
    "RED_BDR": (220, 140, 140),
    "PURPLE": (122, 75, 200),
    "CYAN": (122, 150, 200),
    "DARK": (52, 58, 74),
    "WHITE": (255, 255, 255),
    "BROWN": (150, 102, 54),
    "BROWN_BG": (248, 239, 230),
    "BROWN_BDR": (209, 181, 154),
    "ORANGE": (255, 165, 0),
    "TEAL": (0, 160, 140),
    "TEAL_BG": (220, 248, 244),
    "TEAL_BDR": (100, 200, 180),
    "PINK": (200, 60, 140),
    "PINK_BG": (250, 230, 242),
    "PINK_BDR": (210, 140, 185),
}

DARK_THEME = {
    "BG": (20, 22, 28),
    "SLOT": (100, 100, 100),
    "PANEL": (30, 33, 41),
    "PANEL2": (36, 40, 50),
    "BORDER": (72, 78, 92),
    "TEXT": (236, 238, 244),
    "MUTED": (165, 172, 188),
    "ACCENT": (0, 255, 0),
    "BLUE_BG": (20, 20, 55),
    "GREEN": (74, 186, 106),
    "GREEN_BG": (26, 48, 34),
    "GREEN_BDR": (58, 122, 78),
    "RED": (232, 93, 93),
    "RED_BG": (54, 29, 29),
    "RED_BDR": (124, 64, 64),
    "PURPLE": (160, 117, 230),
    "CYAN": (122, 150, 200),
    "DARK": (58, 64, 78),
    "WHITE": (255, 255, 255),
    "BROWN": (204, 150, 96),
    "BROWN_BG": (52, 40, 30),
    "BROWN_BDR": (120, 90, 64),
    "ORANGE": (255, 177, 66),
    "TEAL": (0, 200, 180),
    "TEAL_BG": (20, 50, 46),
    "TEAL_BDR": (60, 140, 120),
    "PINK": (230, 90, 170),
    "PINK_BG": (54, 24, 44),
    "PINK_BDR": (150, 70, 120),
}

# ─── Layout constants ─────────────────────────────────────────────
MAX_WORD_LENGTH = 35
MAX_MAX_PREVIEW = 50
PAD = 20
GAP = 20

H_HEADER = 60
H_CTRL = 80
H_FILES = 50
H_TOP = H_HEADER + H_CTRL + H_FILES

WORKSPACE_Y = H_TOP + PAD
LEFT_LABEL_W = 150

# Slider x-positions (fixed)
_S1X, _S1W = PAD + 8 + 120, 280  # +120 for the mode button on the left
_S2X, _S2W = _S1X, 200  # stacked, same x, shorter

# How many pattern slots per mode
MAX_PATTERN_SLOTS = 12


# ══════════════════════════════════════════════════════════════════
#  Drawing utilities
# ══════════════════════════════════════════════════════════════════


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


def clamp(n, lo, hi):
    return max(lo, min(hi, n))


def blit_text(surface, text, font, color, x, y, anchor="topleft"):
    img = font.render(text, True, color)
    r = img.get_rect()
    setattr(r, anchor, (int(x), int(y)))
    surface.blit(img, r)
    return r


def draw_panel(surface, rect, color=None, border_color=None, radius=12):
    c = color if color is not None else PANEL
    b = border_color if border_color is not None else BORDER
    pygame.draw.rect(surface, c, rect, border_radius=radius)
    pygame.draw.rect(surface, b, rect, 1, border_radius=radius)


def draw_button(
    surface, rect, label, bg=None, fg=None, radius=8, hovered=False, font=None
):
    bg = bg if bg is not None else DARK
    fg = fg if fg is not None else WHITE
    font = font or FONT
    draw_rect = (
        rect.inflate(int(rect.width * 0.1), int(rect.height * 0.1)) if hovered else rect
    )
    pygame.draw.rect(surface, bg, draw_rect, border_radius=radius)
    img = font.render(label, True, fg)
    surface.blit(img, img.get_rect(center=draw_rect.center))


def draw_pill_toggle(
    surface, rect, labels, active_idx, colors=None, hovered=False, mouse_pos=None
):
    if colors is None:
        colors = [ACCENT] * len(labels)
    draw_rect = (
        rect.inflate(int(rect.width * 0.1), int(rect.height * 0.1)) if hovered else rect
    )
    draw_panel(surface, draw_rect, PANEL2, BORDER, radius=draw_rect.height // 2)
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
            fg = WHITE
        else:
            fg = MUTED
        img = FONT.render(lbl, True, fg)
        surface.blit(img, img.get_rect(center=sr.center))
        rects.append(sr)
    return rects


def draw_slider(
    surface, x, y, w, min_v, max_v, value, label, show_all_marker=False, is_all=False
):
    """Horizontal slider. Returns (track_rect, knob_rect)."""
    disp_val = "All" if is_all else str(value)
    blit_text(surface, f"{label}  {disp_val}", FONT_SM, MUTED, x, y)
    ty = y + 20
    track = pygame.Rect(x, ty + 5, w, 4)
    pygame.draw.rect(surface, BORDER, track, border_radius=2)

    if show_all_marker:
        # Draw a small marker at the far left indicating "All" zone
        all_mark = pygame.Rect(x, ty + 2, 10, 10)
        pygame.draw.rect(surface, RED, all_mark, border_radius=3)
        blit_text(surface, "All", FONT_SM, RED, x - 15, ty)

    if not is_all:
        t = (value - min_v) / max(max_v - min_v, 1)
        fw = int(t * w)
        if fw > 0:
            pygame.draw.rect(
                surface, ACCENT, pygame.Rect(x, ty + 5, fw, 4), border_radius=2
            )
        kx = x + int(t * w)
    else:
        kx = x

    knob = pygame.Rect(kx - 9, ty, 18, 14)
    knob_color = RED if is_all else WHITE
    pygame.draw.rect(surface, knob_color, knob, border_radius=7)
    pygame.draw.rect(surface, ACCENT, knob, 2, border_radius=7)
    return track, knob


def short_path(p, n=34):
    return p if len(p) <= n else "…" + p[-(n - 1) :]


def set_theme(mode: str):
    global BG, SLOT, PANEL, PANEL2, BORDER, TEXT, MUTED, ACCENT
    global BLUE_BG, GREEN, GREEN_BG, GREEN_BDR, RED, RED_BG, RED_BDR
    global PURPLE, CYAN, DARK, WHITE, BROWN, BROWN_BG, BROWN_BDR, ORANGE
    global TEAL, TEAL_BG, TEAL_BDR, PINK, PINK_BG, PINK_BDR

    theme = DARK_THEME if mode == "dark" else LIGHT_THEME

    BG = theme["BG"]
    SLOT = theme["SLOT"]
    PANEL = theme["PANEL"]
    PANEL2 = theme["PANEL2"]
    BORDER = theme["BORDER"]
    TEXT = theme["TEXT"]
    MUTED = theme["MUTED"]
    ACCENT = theme["ACCENT"]
    BLUE_BG = theme["BLUE_BG"]
    GREEN = theme["GREEN"]
    GREEN_BG = theme["GREEN_BG"]
    GREEN_BDR = theme["GREEN_BDR"]
    RED = theme["RED"]
    RED_BG = theme["RED_BG"]
    RED_BDR = theme["RED_BDR"]
    PURPLE = theme["PURPLE"]
    CYAN = theme["CYAN"]
    DARK = theme["DARK"]
    WHITE = theme["WHITE"]
    BROWN = theme["BROWN"]
    BROWN_BG = theme["BROWN_BG"]
    BROWN_BDR = theme["BROWN_BDR"]
    ORANGE = theme["ORANGE"]
    TEAL = theme["TEAL"]
    TEAL_BG = theme["TEAL_BG"]
    TEAL_BDR = theme["TEAL_BDR"]
    PINK = theme["PINK"]
    PINK_BG = theme["PINK_BG"]
    PINK_BDR = theme["PINK_BDR"]


# ══════════════════════════════════════════════════════════════════
#  App state
# ══════════════════════════════════════════════════════════════════


def _make_pattern_slot():
    return {"seq": "", "expanded": False}


class AppState:
    def __init__(self):
        self.word_length = 5
        self.max_preview = MAX_MAX_PREVIEW
        self.preview_start = 0
        self.input_scope = "single"
        self.greek_count = 0
        self.english_count = 0
        self.results_count = 0
        self.language = "greek"

        # ── Letter Match state ──
        self.input_mode = "valid"  # valid / invalid / exist
        self.exist_letters = Counter()
        self.selected_pos = 0
        self.selected_exist_idx = 0  # for navigating exist letter items
        self.valid_sets = [set() for _ in range(5)]
        self.invalid_sets = [set() for _ in range(5)]
        # Store letter data per length, so expanding/shrinking preserves data
        self._stored_valid = {}  # pos -> set
        self._stored_invalid = {}  # pos -> set
        self._prev_word_length = 5

        # ── Pattern Hunt state ──
        self.finder_mode = "letter_match"  # letter_match / pattern_hunt
        self.ph_mode = "start"  # start / end / middle
        self.ph_scope = "single"  # single / all
        self.ph_selected = {"start": 0, "end": 0, "middle": 0}
        self.ph_slots = {
            "start": [_make_pattern_slot() for _ in range(MAX_PATTERN_SLOTS)],
            "end": [_make_pattern_slot() for _ in range(MAX_PATTERN_SLOTS)],
            "middle": [_make_pattern_slot() for _ in range(MAX_PATTERN_SLOTS)],
        }
        self.ph_slot_count = {
            "start": 3,
            "end": 3,
            "middle": 3,
        }  # visible slots per mode

        # word length "All" mode for Pattern Hunt
        self.ph_word_length_all = False

        self.search_results = []
        self.status = "Load a word list, then press Search or Enter."
        self.greek_file = resource_path("greek_words.txt")
        self.english_file = resource_path("english_words.txt")
        self.results_file = resource_path("results.txt")
        self.theme = "dark"

        # Results selection: word -> "save" | "exclude" | None
        self.word_selections = {}  # word -> "save" | "exclude"

    def rebuild_sets(self):
        """Called when word_length changes. Preserves existing data."""
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
        return ["start", "end", "middle"]

    def ph_selected_slot_idx(self):
        return self.ph_selected.get(self.ph_mode, 0)

    def ph_visible_slots(self, mode=None):
        m = mode if mode else self.ph_mode
        return self.ph_slot_count[m]

    def get_exist_items(self):
        """Return list of (key, count) for exist letters."""
        return list(self.exist_letters.items())

    def cycle_input_mode_lm(self, step):
        idx = INPUT_MODES_LM.index(self.input_mode)
        self.input_mode = INPUT_MODES_LM[(idx + step) % len(INPUT_MODES_LM)]

    def cycle_ph_mode(self, step):
        idx = INPUT_MODES_PH.index(self.ph_mode)
        self.ph_mode = INPUT_MODES_PH[(idx + step) % len(INPUT_MODES_PH)]


state = AppState()
set_theme(state.theme)


# ══════════════════════════════════════════════════════════════════
#  File dialogs & Tk windows
# ══════════════════════════════════════════════════════════════════

tk_root = None
summary_tk_root = None
summary_win = None
summary_text = None
summary_open = False
info_tk_root = None
info_win = None
info_text = None
info_open = False

INFO_TEXT = """Word Finder — Instructions

════════════════════ Two Modes ════════════════════

The program has two search modes, switchable via the red
button at the left of the controls bar, or by pressing Tab:

  • Letter Match — classic slot-based filtering
  • Pattern Hunt  — flexible pattern-sequence filtering


════════════════════ Letter Match ════════════════════

Filters words by applying per-slot letter rules.

Three input modes (cycle with ↑ ↓ or click the pill toggle):
  • Valid   — the selected letter group must appear in that slot.
  • Invalid — the selected letter group must not appear in that slot.
  • Exist   — the letter must appear somewhere in the word.
              Repeating a letter in Exist means it must occur multiple times.

Navigation:
  • ← → arrows: move between slots (Valid/Invalid) or between Exist items.
  • Backspace: in Valid/Invalid, clears the selected slot (or all slots if scope
    is "All"). In Exist, deletes the currently selected Exist letter group.
  • Type a letter: adds/removes constraint in current mode.
  • The active slot / exist area shows a highlighted border.

Slot / All scope (/ key or pill toggle):
  • Slot — input affects only the selected slot.
  • All  — input affects all slots at once.

When word length increases, previously entered slot data is preserved.
Data is only removed when the word length shrinks past its position.

Summary panel shows all current Letter Match constraints.


════════════════════ Pattern Hunt ════════════════════

Filters words by letter-sequence patterns.

Three pattern modes (cycle with ↑ ↓ or click the pill toggle):
  • Start  — the sequence must match the beginning of the word.
  • End    — the sequence must match the end of the word.
  • Middle — the sequence must appear somewhere in the word
             (including start or end).

In each mode there are multiple pattern slots, navigatable with ← → arrows.
Type letters one by one to build a sequence in the selected slot.
Backspace deletes the last letter of the current slot.

Expanded matching (Shift+Space in a slot):
  Normally, "οσ" matches only the literal string "οσ".
  Pressing Shift+Space on a slot expands it to match all accent/case variants,
  e.g. "ΟΌοόΣσς" for "οσ". Press Shift+Space again to collapse.

Slot / All scope (/ key or pill toggle): same as Letter Match.

Word length in Pattern Hunt:
  Drag the slider all the way left to set "Word Length: All", which disables
  length filtering. The slider's left edge is visually marked in red.

"Patterns Review" shows a summary of all current Pattern Hunt rules.


════════════════════ Common Controls ════════════════════

  • Enter / Search button — run the search.
  • Ctrl+S — save current results to file.
  • Page Up / Page Down — scroll through result pages.
  • ↑ ↓ — switch between input modes.
  • Tab — toggle between Letter Match and Pattern Hunt.
  • / (slash) — toggle between Slot and All scope.
  • Space — switch between Greek and English word lists.
  • Ctrl+I — open this instructions window.

Results panel:
  • Left-click a word — mark it as "to save" (green).
  • Right-click a word — mark it as "excluded" (red).
  • Click again to deselect.
  • The count of marked/excluded words is shown in the results header.
  • Save writes all results (or only marked ones if any are marked).

Theme:
  The theme button shows "Light" when the light theme is active,
  and "Dark" when the dark theme is active. Click to toggle.

Language behavior:
  Greek mode understands accented forms and common letter variants.
  English mode groups uppercase and lowercase of the same letter.
"""


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
    return " ".join("".join(sorted(x)) for x in s) if s else "—"


def open_summary_window():
    global summary_win, summary_text, summary_open
    root = get_tk_root()
    if summary_win is None or not summary_win.winfo_exists():
        title = (
            "Patterns Review" if state.finder_mode == "pattern_hunt" else "Slots Review"
        )
        summary_win = Toplevel(root)
        summary_win.title(title)
        summary_win.geometry("520x620")
        summary_win.protocol("WM_DELETE_WINDOW", close_summary_window)
        summary_text = Text(summary_win, wrap="word", font=("Segoe UI", 10))
        summary_text.pack(fill="both", expand=True)
        btn = Button(summary_win, text="Close", command=close_summary_window)
        btn.pack(pady=6)
    else:
        summary_win.deiconify()
        summary_win.lift()
        summary_win.focus_force()
    summary_open = True
    refresh_summary_window()


def close_summary_window():
    global summary_win, summary_text, summary_open
    summary_open = False
    if summary_win is not None and summary_win.winfo_exists():
        summary_win.destroy()
    summary_win = None
    summary_text = None


def refresh_summary_window():
    if not summary_open or summary_win is None or not summary_win.winfo_exists():
        return
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
            lines.append("  " + " · ".join(parts))
        else:
            lines.append("  —")
    else:
        # Pattern Hunt
        for mode_name in ["start", "end", "middle"]:
            lines.append(mode_name.upper())
            for i in range(state.ph_slot_count[mode_name]):
                slot = state.ph_slots[mode_name][i]
                seq = slot["seq"]
                exp = slot["expanded"]
                if seq:
                    disp = expand_sequence(seq, state.language) if exp else seq
                    tag = " [expanded]" if exp else ""
                    lines.append(f"  {i+1}: {disp}{tag}")
                else:
                    lines.append(f"  {i+1}: —")
            lines.append("")
    summary_text.delete("1.0", END)
    summary_text.insert("1.0", "\n".join(lines))


def open_info_window():
    global info_win, info_text, info_open
    root = get_tk_root()
    if info_win is None or not info_win.winfo_exists():
        info_win = Toplevel(root)
        info_win.title("Instructions")
        info_win.geometry("680x760")
        info_win.protocol("WM_DELETE_WINDOW", close_info_window)
        info_text = Text(info_win, wrap="word", font=("Segoe UI", 10))
        info_text.pack(fill="both", expand=True)
        btn = Button(info_win, text="Close", command=close_info_window)
        btn.pack(pady=6)
    else:
        info_win.deiconify()
        info_win.lift()
        info_win.focus_force()
    info_open = True
    refresh_info_window()


def close_info_window():
    global info_win, info_text, info_open
    info_open = False
    if info_win is not None and info_win.winfo_exists():
        info_win.destroy()
    info_win = None
    info_text = None


def refresh_info_window():
    if not info_open or info_win is None or not info_win.winfo_exists():
        return
    info_text.delete("1.0", END)
    info_text.insert("1.0", INFO_TEXT)


def pump_tk_windows():
    global tk_root, summary_win, summary_text, summary_open
    global info_win, info_text, info_open
    if tk_root is None or not tk_root.winfo_exists():
        return
    try:
        tk_root.update_idletasks()
        tk_root.update()
    except TclError:
        summary_win = None
        summary_text = None
        summary_open = False
        info_win = None
        info_text = None
        info_open = False


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


# ══════════════════════════════════════════════════════════════════
#  App actions
# ══════════════════════════════════════════════════════════════════


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
        for tok in targets:
            if tok in tgt:
                tgt.remove(tok)
            else:
                tgt.add(tok)


def ph_target_slots():
    """Which slot indices are targets in pattern hunt (single or all)."""
    mode = state.ph_mode
    count = state.ph_slot_count[mode]
    if state.ph_scope == "all":
        return list(range(count))
    else:
        return [state.ph_selected[mode]]


def ph_add_letter(ch):
    """Add a letter to the pattern sequence of the selected PH slot(s)."""
    mode = state.ph_mode
    for idx in ph_target_slots():
        slot = state.ph_slots[mode][idx]
        slot["seq"] += ch


def ph_backspace():
    """Remove the last letter from the selected PH slot."""
    mode = state.ph_mode
    for idx in ph_target_slots():
        slot = state.ph_slots[mode][idx]
        if slot["seq"]:
            slot["seq"] = slot["seq"][:-1]
            if not slot["seq"]:
                slot["expanded"] = False


def ph_toggle_expand():
    """Toggle expanded matching for the selected PH slot(s)."""
    mode = state.ph_mode
    for idx in ph_target_slots():
        slot = state.ph_slots[mode][idx]
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
        state.status = f"No words loaded — check: {state.active_file()}"
        return

    if state.finder_mode == "letter_match":
        r = find_matching_words(
            words,
            state.word_length,
            state.valid_sets,
            state.invalid_sets,
            state.exist_letters,
            state.language,
        )
    else:
        wl = None if state.ph_word_length_all else state.word_length
        start_pats = [
            s
            for s in state.ph_slots["start"][: state.ph_slot_count["start"]]
            if s["seq"]
        ]
        end_pats = [
            s for s in state.ph_slots["end"][: state.ph_slot_count["end"]] if s["seq"]
        ]
        mid_pats = [
            s
            for s in state.ph_slots["middle"][: state.ph_slot_count["middle"]]
            if s["seq"]
        ]
        r = find_pattern_words(
            words, wl, start_pats, end_pats, mid_pats, state.language
        )

    state.search_results = r
    state.word_selections = {}
    state.preview_start = 0
    n = len(r)
    state.status = f'{n} word{"s" if n != 1 else ""} matched in {os.path.basename(state.active_file())}'


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
        state.status = "Nothing to save — run Search first."
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
        state.status = f"Saved {state.results_count} words → {os.path.basename(path)}"
    except Exception as e:
        state.status = f"Save error: {e}"


def toggle_finder_mode():
    if state.finder_mode == "letter_match":
        state.finder_mode = "pattern_hunt"
    else:
        state.finder_mode = "letter_match"
    state.search_results = []
    state.word_selections = {}
    state.preview_start = 0
    state.status = f"Switched to {'Pattern Hunt' if state.finder_mode == 'pattern_hunt' else 'Letter Match'}"
    refresh_summary_window()


# ══════════════════════════════════════════════════════════════════
#  Render sections
# ══════════════════════════════════════════════════════════════════

# Global rects for results panel mouse interaction
_result_word_rects = []  # list of (word, rect)
_hover_word_rect = None  # (word, rect) that is hovered


def render_header():
    pygame.draw.rect(screen, PANEL, (0, 0, WIDTH, H_HEADER))
    pygame.draw.line(screen, BORDER, (0, H_HEADER), (WIDTH, H_HEADER))

    mode_label = (
        "Letter Match" if state.finder_mode == "letter_match" else "Pattern Hunt"
    )

    title_x = PAD + 4
    title_y = H_HEADER // 2 - 12

    blit_text(
        screen,
        "Word Finder",
        FONT_LG,
        TEXT,
        title_x,
        title_y,
        anchor="midleft",
    )

    blit_text(
        screen,
        f"[{mode_label}]",
        FONT_SM,
        MUTED,
        title_x,
        title_y + 24,
        anchor="midleft",
    )

    # Key binding hints (updated, without "Click Slot" and "Type Letters")
    hints = (
        "Backspace = Clear  ·  Enter = Search  ·  ← → = Navigate"
        "  ·  ↑ ↓ = Mode  ·  / = Slot/All  ·  Tab = Letter Match/Pattern Hunt"
        "  ·  Space = Greek/English  ·  Ctrl+S = Save  ·  Page Up/Down = Scroll  ·  Ctrl+I = Info"
    )
    blit_text(screen, hints, FONT_SM, MUTED, PAD + 260, H_HEADER // 2, anchor="midleft")


def render_controls(mouse_pos):
    """Returns t1, k1, t2, k2, mode_rects, scope_rects, lang_rects, search_rect, finder_btn_rect"""
    global wordlen_track, preview_track
    y0 = H_HEADER
    pygame.draw.rect(screen, PANEL2, (0, y0, WIDTH, H_CTRL))
    pygame.draw.line(screen, BORDER, (0, y0 + H_CTRL), (WIDTH, y0 + H_CTRL))

    # ── Finder Mode Button (red, left side) ───────────────────────
    finder_btn_height = 50
    finder_btn_rect = pygame.Rect(
        PAD, y0 + (H_CTRL - finder_btn_height) / 2, 120, finder_btn_height
    )
    finder_label = (
        "Letter Match" if state.finder_mode == "letter_match" else "Pattern Hunt"
    )
    draw_button(
        screen,
        finder_btn_rect,
        finder_label,
        RED,
        WHITE,
        radius=8,
        hovered=finder_btn_rect.collidepoint(mouse_pos),
    )

    # ── Sliders (stacked, right of finder button) ─────────────────
    sl_x = PAD + 160
    sl_w = 300
    cy1 = y0 + 2
    cy2 = y0 + H_CTRL / 2

    # Word length slider
    is_all = state.finder_mode == "pattern_hunt" and state.ph_word_length_all
    t1, k1 = draw_slider(
        screen,
        sl_x,
        cy1,
        sl_w,
        1,
        MAX_WORD_LENGTH,
        state.word_length,
        "Word length",
        show_all_marker=(state.finder_mode == "pattern_hunt"),
        is_all=is_all,
    )
    wordlen_track = t1

    # Max preview slider
    t2, k2 = draw_slider(
        screen, sl_x, cy2, sl_w, 1, MAX_MAX_PREVIEW, state.max_preview, "Max preview"
    )
    preview_track = t2

    # ── Mode pill toggle ──────────────────────────────────────────
    if state.finder_mode == "letter_match":
        mode_labels = ["Valid", "Invalid", "Exist"]
        mode_colors = [GREEN, RED, BROWN]
        mode_idx = {"valid": 0, "invalid": 1, "exist": 2}[state.input_mode]
    else:
        mode_labels = ["Start", "End", "Middle"]
        mode_colors = [TEAL, PINK, PURPLE]
        mode_idx = {"start": 0, "end": 1, "middle": 2}[state.ph_mode]

    mx_x = sl_x + sl_w + 60
    mx_h = 35
    m_rect = pygame.Rect(mx_x, y0 + (H_CTRL - mx_h) / 2, 270, mx_h)
    m_rects = draw_pill_toggle(
        screen,
        m_rect,
        mode_labels,
        mode_idx,
        mode_colors,
        hovered=m_rect.collidepoint(mouse_pos),
    )

    # ── Scope pill toggle (Slot / All) ────────────────────────────
    scope_x = mx_x + 320
    scope_h = 35
    scope_rect = pygame.Rect(scope_x, y0 + (H_CTRL - scope_h) / 2, 150, scope_h)
    active_scope = (
        state.input_scope if state.finder_mode == "letter_match" else state.ph_scope
    )
    scope_rects = draw_pill_toggle(
        screen,
        scope_rect,
        ["Slot", "All"],
        0 if active_scope == "single" else 1,
        [ORANGE, ORANGE],
        hovered=scope_rect.collidepoint(mouse_pos),
    )

    # ── Language pill toggle ──────────────────────────────────────
    lg_x = scope_x + 200
    lg_h = 35
    lang_rect = pygame.Rect(lg_x, y0 + (H_CTRL - lg_h) / 2, 170, lg_h)
    lang_rects = draw_pill_toggle(
        screen,
        lang_rect,
        ["Greek", "English"],
        0 if state.language == "greek" else 1,
        [ACCENT, ACCENT],
        hovered=lang_rect.collidepoint(mouse_pos),
    )

    # ── Search button ─────────────────────────────────────────────
    search_rect_height = 40
    search_rect = pygame.Rect(
        WIDTH - PAD - 120,
        y0 + (H_CTRL - search_rect_height) / 2,
        120,
        search_rect_height,
    )
    draw_button(
        screen,
        search_rect,
        "Search",
        GREEN,
        hovered=search_rect.collidepoint(mouse_pos),
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
    )


def render_file_row(mouse_pos):
    y0 = H_HEADER + H_CTRL
    pygame.draw.rect(screen, BG, (0, y0, WIDTH, H_FILES))
    pygame.draw.line(screen, BORDER, (0, y0 + H_FILES), (WIDTH, y0 + H_FILES))

    by = y0 + 6
    bh = H_FILES - 12
    BW = 100

    def file_unit(x, label, path, count):
        br = pygame.Rect(x, by, BW, bh)
        draw_button(
            screen, br, label, DARK, WHITE, radius=7, hovered=br.collidepoint(mouse_pos)
        )
        tx = x + BW + 6
        path_img = LINK_FONT_SM.render(short_path(path), True, ACCENT)
        path_rect = path_img.get_rect(topleft=(tx, by + 1))
        screen.blit(path_img, path_rect)
        blit_text(
            screen, f"{count} words", FONT_SM, MUTED, tx, by + 20, anchor="topleft"
        )
        return br, path_rect

    gf_btn, gf_link = file_unit(PAD, "Greek", state.greek_file, state.greek_count)
    ef_btn, ef_link = file_unit(
        PAD + 370, "English", state.english_file, state.english_count
    )
    sp_btn, sp_link = file_unit(
        PAD + 740, "Save to", state.results_file, state.results_count
    )

    # Theme button: shows "Light" when light theme is active, "Dark" when dark is active
    theme_btn = pygame.Rect(WIDTH - PAD - 120, by + 5, 120, 30)
    theme_label = "Light" if state.theme == "light" else "Dark"
    draw_button(
        screen,
        theme_btn,
        theme_label,
        CYAN,
        WHITE,
        radius=7,
        hovered=theme_btn.collidepoint(mouse_pos),
    )

    SAVE_BTN_X = WIDTH - PAD - 250
    sv_btn = pygame.Rect(SAVE_BTN_X, by, 100, bh)
    draw_button(screen, sv_btn, "Save", PURPLE, hovered=sv_btn.collidepoint(mouse_pos))

    return gf_btn, gf_link, ef_btn, ef_link, sp_btn, sp_link, theme_btn, sv_btn


# ─── Letter Match workspace ───────────────────────────────────────


def _slot_layout():
    gap = 8
    left_edge = PAD + LEFT_LABEL_W
    right_edge = WIDTH - PAD
    available = max(1, right_edge - left_edge)
    n = max(state.word_length, 1)
    slots_num = 5
    slots_perc = 0.75
    if state.word_length <= slots_num:
        total_w = available * slots_perc
    else:
        t = (state.word_length - slots_num) / max(MAX_WORD_LENGTH - slots_num, 1)
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
        if state.language == "greek":
            group = GREEK_GROUP_BY_FIRST.get(key, (key,))
        elif state.language == "english":
            group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
        else:
            group = (key,)
        label = "".join(group)
        parts.append(f"{label} (x{count})" if count > 1 else label)
    return "  ·  ".join(parts) if parts else "—"


def render_workspace_lm(mouse_pos):
    """Letter Match workspace. Returns (slot_w, slot_h, sx, ty, gap, table_bottom_y, summary_btn)."""
    slot_w, slot_h, sx, ty, gap = _slot_layout()

    # ── Position squares ──────────────────────────────────────────
    for i in range(state.word_length):
        x = sx + i * (slot_w + gap)
        r = pygame.Rect(x, ty, slot_w, slot_h)
        sel = i == state.selected_pos
        hv = bool(state.valid_sets[i])
        hi = bool(state.invalid_sets[i])

        if hv and hi:
            fill = BLUE_BG
        elif hv:
            fill = GREEN_BG
        elif hi:
            fill = RED_BG
        else:
            fill = SLOT

        # Highlight border when this slot is selected AND mode matches
        if sel and state.input_mode in ("valid", "invalid"):
            if state.input_mode == "valid":
                bdr_col = GREEN
            else:
                bdr_col = RED
            bdr_w = 3
        elif sel:
            bdr_col = ACCENT
            bdr_w = 3
        else:
            bdr_col = BORDER
            bdr_w = 1

        pygame.draw.rect(screen, fill, r, border_radius=10)
        pygame.draw.rect(screen, bdr_col, r, bdr_w, border_radius=10)

        ni = FONT_SM.render(str(i + 1), True, ACCENT if sel else MUTED)
        screen.blit(ni, ni.get_rect(center=(x + slot_w // 2, ty - 13)))

    # ── Hint line ─────────────────────────────────────────────────
    hint_y = ty + slot_h - 10
    mc = (
        GREEN
        if state.input_mode == "valid"
        else (RED if state.input_mode == "invalid" else BROWN)
    )
    blit_text(
        screen,
        f"Position {state.selected_pos + 1}  |  Mode:",
        FONT_SM,
        MUTED,
        PAD,
        hint_y,
    )
    mode_w = FONT_SM.size(f"Position {state.selected_pos + 1}  |  Mode:")[0]
    blit_text(
        screen, f"  {state.input_mode.upper()}", FONT_SM, mc, PAD + mode_w, hint_y
    )

    # ── Condition tables ──────────────────────────────────────────
    table_y = hint_y + 25
    row_h = 36

    summary_btn = pygame.Rect(PAD, hint_y - 40, 150, 24)
    draw_button(
        screen,
        summary_btn,
        "Slots Review",
        DARK,
        WHITE,
        radius=7,
        hovered=summary_btn.collidepoint(mouse_pos),
    )

    hover_text = None
    hover_pos = None

    for label, sets, bg_c, bdr_c, lbl_c, mode_str in [
        ("VALID", state.valid_sets, GREEN_BG, GREEN_BDR, GREEN, "valid"),
        ("INVALID", state.invalid_sets, RED_BG, RED_BDR, RED, "invalid"),
    ]:
        blit_text(screen, label, FONT_MD, lbl_c, PAD, table_y + row_h // 2 - 10)
        for i in range(state.word_length):
            x = sx + i * (slot_w + gap)
            cell = pygame.Rect(x, table_y, slot_w, row_h)
            # Highlight border if this cell matches selected pos + mode
            if i == state.selected_pos and state.input_mode == mode_str:
                cell_bdr = lbl_c
                cell_bdr_w = 2
            else:
                cell_bdr = bdr_c
                cell_bdr_w = 1
            pygame.draw.rect(screen, bg_c, cell, border_radius=8)
            pygame.draw.rect(screen, cell_bdr, cell, cell_bdr_w, border_radius=8)
            letters = "".join(sorted(sets[i]))
            max_text_w = cell.width - 8
            display_letters = fit_text_with_ellipsis(letters, FONT_SM, max_text_w)
            img = FONT_SM.render(
                display_letters or "—", True, TEXT if letters else MUTED
            )
            screen.blit(img, img.get_rect(center=cell.center))
            if cell.collidepoint(mouse_pos):
                letters_full = "".join(sorted(sets[i])) or "—"
                hover_text = f"{label} slot {i + 1}: {letters_full}"
                hover_pos = mouse_pos
        table_y += row_h + 6

    # ── Exist row ─────────────────────────────────────────────────
    exist_items = state.get_exist_items()
    exist_row_h = row_h
    exist_rect = pygame.Rect(PAD, table_y, WIDTH - 2 * PAD, exist_row_h)

    # Highlighted border for exist row when mode is "exist"
    if state.input_mode == "exist":
        exist_bdr_col = BROWN
        exist_bdr_w = 3
    else:
        exist_bdr_col = BROWN_BDR
        exist_bdr_w = 1

    pygame.draw.rect(screen, BROWN_BG, exist_rect, border_radius=8)
    pygame.draw.rect(screen, exist_bdr_col, exist_rect, exist_bdr_w, border_radius=8)
    blit_text(screen, "EXIST", FONT_MD, BROWN, PAD + 6, table_y + exist_row_h // 2 - 10)

    if exist_items:
        # Draw each exist item as a small chip, navigatable
        chip_x = PAD + 90
        chip_gap = 8
        chip_y = table_y + 4
        chip_h = exist_row_h - 8
        exist_rects_local = []
        for ei, (key, count) in enumerate(exist_items):
            if state.language == "greek":
                group = GREEK_GROUP_BY_FIRST.get(key, (key,))
            else:
                group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
            label = "".join(group)
            disp = f"{label}×{count}" if count > 1 else label
            tw_chip = FONT_SM.size(disp)[0] + 16
            chip_rect = pygame.Rect(chip_x, chip_y, tw_chip, chip_h)
            is_sel = state.input_mode == "exist" and ei == state.selected_exist_idx
            chip_bg = BROWN_BDR if is_sel else BROWN_BG
            chip_bdr = BROWN if is_sel else BROWN_BDR
            chip_bdr_w = 2 if is_sel else 1
            pygame.draw.rect(screen, chip_bg, chip_rect, border_radius=6)
            pygame.draw.rect(screen, chip_bdr, chip_rect, chip_bdr_w, border_radius=6)
            img = FONT_SM.render(disp, True, BROWN if is_sel else TEXT)
            screen.blit(img, img.get_rect(midleft=(chip_x + 8, chip_y + chip_h // 2)))
            if chip_rect.collidepoint(mouse_pos):
                hover_text = f"Exist: {disp}"
                hover_pos = mouse_pos
            exist_rects_local.append(chip_rect)
            chip_x += tw_chip + chip_gap
            if chip_x > exist_rect.right - 40:
                break
    else:
        img = FONT_SM.render("—", True, MUTED)
        screen.blit(img, img.get_rect(midleft=(PAD + 90, table_y + exist_row_h // 2)))

    table_y += exist_row_h + 6

    if hover_text:
        tip_font = FONT_SM
        tip_img = tip_font.render(hover_text, True, WHITE)
        tip_pad = 8
        tip_rect = tip_img.get_rect(topleft=(hover_pos[0] + 16, hover_pos[1] + 16))
        tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
        pygame.draw.rect(screen, DARK, tip_rect, border_radius=8)
        pygame.draw.rect(screen, BORDER, tip_rect, 1, border_radius=8)
        screen.blit(tip_img, tip_img.get_rect(center=tip_rect.center))

    return slot_w, slot_h, sx, ty, gap, table_y, summary_btn


# ─── Pattern Hunt workspace ───────────────────────────────────────


def _ph_slot_layout(mode, num_slots):
    """Layout for pattern hunt slots in one mode row."""
    gap = 8
    left_edge = PAD + LEFT_LABEL_W
    right_edge = WIDTH - PAD - 40  # leave room for +/- buttons
    available = max(1, right_edge - left_edge)
    n = max(num_slots, 1)
    slot_w = max(40, min(120, (available - (n - 1) * gap) // n))
    tw = n * slot_w + (n - 1) * gap
    sx = left_edge
    return slot_w, sx, gap


def render_workspace_ph(mouse_pos):
    """Pattern Hunt workspace. Returns (table_bottom_y, summary_btn, ph_slot_rects)."""
    table_y = WORKSPACE_Y + PAD
    row_h = 40
    row_gap = 10

    mode_styles = {
        "start": ("START", TEAL_BG, TEAL_BDR, TEAL),
        "end": ("END", PINK_BG, PINK_BDR, PINK),
        "middle": ("MIDDLE", BLUE_BG, ACCENT, ACCENT),
    }

    summary_btn = pygame.Rect(PAD, table_y - 2, 165, 24)
    draw_button(
        screen,
        summary_btn,
        "Patterns Review",
        DARK,
        WHITE,
        radius=7,
        hovered=summary_btn.collidepoint(mouse_pos),
    )
    table_y += 30

    ph_slot_rects = {}  # mode -> list of rects
    hover_text = None
    hover_pos = None

    for mode_name in ["start", "end", "middle"]:
        label, bg_c, bdr_c, lbl_c = mode_styles[mode_name]
        num_slots = state.ph_slot_count[mode_name]
        sel_idx = state.ph_selected[mode_name]
        slot_w, sx, gap = _ph_slot_layout(mode_name, num_slots)

        blit_text(screen, label, FONT_MD, lbl_c, PAD, table_y + row_h // 2 - 10)

        rects = []
        for i in range(num_slots):
            x = sx + i * (slot_w + gap)
            slot = state.ph_slots[mode_name][i]
            seq = slot["seq"]
            expanded = slot["expanded"]

            cell = pygame.Rect(x, table_y, slot_w, row_h)

            is_active = mode_name == state.ph_mode
            is_sel = i == sel_idx and is_active

            if expanded and seq:
                cell_bg = BLUE_BG
            else:
                cell_bg = bg_c

            if is_sel:
                cell_bdr = lbl_c
                cell_bdr_w = 3
            else:
                cell_bdr = bdr_c
                cell_bdr_w = 1

            pygame.draw.rect(screen, cell_bg, cell, border_radius=8)
            pygame.draw.rect(screen, cell_bdr, cell, cell_bdr_w, border_radius=8)

            if seq:
                disp_seq = expand_sequence(seq, state.language) if expanded else seq
                disp = fit_text_with_ellipsis(disp_seq, FONT_SM, slot_w - 8)
                img = FONT_SM.render(disp, True, PURPLE if expanded else TEXT)
            else:
                img = FONT_SM.render("—", True, MUTED)
            screen.blit(img, img.get_rect(center=cell.center))

            # Small "expanded" indicator
            if expanded and seq:
                e_img = FONT_SM.render("≈", True, PURPLE)
                screen.blit(
                    e_img, e_img.get_rect(topright=(cell.right - 2, cell.top + 2))
                )

            if cell.collidepoint(mouse_pos):
                disp_full = (
                    expand_sequence(seq, state.language) if expanded else (seq or "-")
                )
                hover_text = f"{label} slot {i+1}: {disp_full}" + (
                    " [expanded]" if expanded else ""
                )
                hover_pos = mouse_pos

            rects.append(cell)

        # +/- buttons to add/remove slots
        pm_x = sx + num_slots * (slot_w + gap) + 4
        plus_r = pygame.Rect(pm_x, table_y + 2, 16, 17)
        minus_r = pygame.Rect(pm_x, table_y + 21, 16, 17)
        pygame.draw.rect(screen, GREEN_BG, plus_r, border_radius=4)
        pygame.draw.rect(screen, GREEN_BDR, plus_r, 1, border_radius=4)
        pygame.draw.rect(screen, RED_BG, minus_r, border_radius=4)
        pygame.draw.rect(screen, RED_BDR, minus_r, 1, border_radius=4)
        blit_text(
            screen, "+", FONT_SM, GREEN, plus_r.centerx, plus_r.centery, anchor="center"
        )
        blit_text(
            screen, "−", FONT_SM, RED, minus_r.centerx, minus_r.centery, anchor="center"
        )

        ph_slot_rects[mode_name] = {"slots": rects, "plus": plus_r, "minus": minus_r}
        table_y += row_h + row_gap

    if hover_text:
        tip_img = FONT_SM.render(hover_text, True, WHITE)
        tip_pad = 8
        tip_rect = tip_img.get_rect(topleft=(hover_pos[0] + 16, hover_pos[1] + 16))
        tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
        pygame.draw.rect(screen, DARK, tip_rect, border_radius=8)
        pygame.draw.rect(screen, BORDER, tip_rect, 1, border_radius=8)
        screen.blit(tip_img, tip_img.get_rect(center=tip_rect.center))

    return table_y, summary_btn, ph_slot_rects


def render_results(table_bottom_y, mouse_pos=(0, 0)):
    global _result_word_rects, _hover_word_rect
    _result_word_rects = []

    y0 = table_bottom_y + PAD
    h = HEIGHT - y0 - PAD
    if h < 80:
        return

    panel = pygame.Rect(PAD, y0, WIDTH - 2 * PAD, h)
    draw_panel(screen, panel, PANEL, BORDER, radius=12)

    n = len(state.search_results)
    if n:
        state.clamp_preview_start()
        start_index = state.preview_start + 1
        end_index = min(state.preview_start + state.max_preview, n)
    else:
        start_index = 0
        end_index = 0

    # Count selections
    n_save = sum(1 for v in state.word_selections.values() if v == "save")
    n_excl = sum(1 for v in state.word_selections.values() if v == "exclude")
    sel_parts = []
    if n_save:
        sel_parts.append(f"{n_save} to save")
    if n_excl:
        sel_parts.append(f"{n_excl} excluded")
    sel_str = "  |  " + "  ·  ".join(sel_parts) if sel_parts else ""

    blit_text(screen, state.status, FONT_SM, MUTED, panel.x + PAD, panel.y + 10)
    cnt = f"{n} total  ·  showing {start_index} - {end_index}"
    blit_text(
        screen, cnt, FONT_SM, ACCENT, panel.right - PAD, panel.y + 10, anchor="topright"
    )
    if sel_str:
        blit_text(
            screen,
            sel_str,
            FONT_SM,
            PURPLE,
            panel.centerx,
            panel.y + 10,
            anchor="midtop",
        )

    preview = state.preview()
    if not preview:
        blit_text(
            screen,
            "No results yet — press Enter or click Search.",
            FONT,
            MUTED,
            panel.x + PAD,
            panel.y + 36,
        )
        return

    grid_y = panel.y + 34
    cols = max(1, (panel.width - 2 * PAD) // 250)
    cw = (panel.width - 2 * PAD - (cols - 1) * GAP) // cols
    ch_h = 26

    _hover_word_rect = None

    for idx, word in enumerate(preview):
        col = idx % cols
        row = idx // cols
        wx = panel.x + PAD + col * (cw + GAP)
        wy = grid_y + row * (ch_h + 4)
        if wy + ch_h > panel.bottom - 8:
            break

        wr = pygame.Rect(wx, wy, cw, ch_h)
        is_hovered = wr.collidepoint(mouse_pos)
        sel_state = state.word_selections.get(word)

        # Background color based on selection
        if sel_state == "save":
            bg_color = GREEN_BG
            bdr_color = GREEN_BDR
        elif sel_state == "exclude":
            bg_color = RED_BG
            bdr_color = RED_BDR
        else:
            bg_color = PANEL2
            bdr_color = BORDER

        if is_hovered:
            draw_r = wr.inflate(int(wr.w * 0.1), int(wr.h * 0.1))
            _hover_word_rect = (word, wr)
        else:
            draw_r = wr

        pygame.draw.rect(screen, bg_color, draw_r, border_radius=6)
        pygame.draw.rect(screen, bdr_color, draw_r, 1, border_radius=6)
        wimg = FONT_SM.render(word, True, TEXT)
        screen.blit(wimg, wimg.get_rect(midleft=(draw_r.x + 8, draw_r.centery)))

        _result_word_rects.append((word, wr))

    # Draw zoom tooltip near mouse for hovered word
    if _hover_word_rect is not None:
        hword, _ = _hover_word_rect
        zoom_img = FONT_LG.render(hword, True, TEXT)
        tip_pad = 10
        tip_rect = zoom_img.get_rect(topleft=(mouse_pos[0] + 20, mouse_pos[1] + 10))
        tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
        # Keep on screen
        if tip_rect.right > WIDTH - PAD:
            tip_rect.right = WIDTH - PAD
        if tip_rect.bottom > HEIGHT - PAD:
            tip_rect.bottom = HEIGHT - PAD
        pygame.draw.rect(screen, PANEL, tip_rect, border_radius=10)
        pygame.draw.rect(screen, ACCENT, tip_rect, 2, border_radius=10)
        screen.blit(zoom_img, zoom_img.get_rect(center=tip_rect.center))


# ══════════════════════════════════════════════════════════════════
#  Main loop
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    refresh_words_counts()
    dragging = None  # None | 'wl' | 'mp'
    running = True

    # Store layout rects across frames for hit-testing
    _lm_slot_sx = 0
    _lm_slot_ty = 0
    _lm_slot_w = 30
    _lm_slot_h = 32
    _lm_slot_gap = 8
    _ph_slot_rects = {}  # set by render_workspace_ph

    while running:
        screen.fill(BG)
        mouse_pos = pygame.mouse.get_pos()

        render_header()
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
        ) = render_controls(mouse_pos)
        gf_btn, gf_link, ef_btn, ef_link, sp_btn, sp_link, theme_btn, sv_btn = (
            render_file_row(mouse_pos)
        )

        if state.finder_mode == "letter_match":
            slot_w, slot_h, sx, ty, gap, tby, summary_btn = render_workspace_lm(
                mouse_pos
            )
            _lm_slot_sx = sx
            _lm_slot_ty = ty
            _lm_slot_w = slot_w
            _lm_slot_h = slot_h
            _lm_slot_gap = gap
        else:
            tby, summary_btn, _ph_slot_rects = render_workspace_ph(mouse_pos)

        render_results(tby, mouse_pos)

        if summary_win is not None and summary_win.winfo_exists():
            try:
                summary_win.update_idletasks()
            except TclError:
                summary_win = None
                summary_text = None
                summary_open = False

        pump_tk_windows()
        pygame.display.flip()
        clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.VIDEORESIZE:
                WIDTH, HEIGHT = event.w, event.h
                screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                btn = event.button

                if btn == 1:
                    # Sliders
                    if t1.collidepoint(mx, my) or k1.collidepoint(mx, my):
                        dragging = "wl"
                        rel = clamp(mx - wordlen_track.left, 0, wordlen_track.width)
                        ratio = rel / wordlen_track.width
                        new_len = round(1 + ratio * (MAX_WORD_LENGTH - 1))
                        if new_len != state.word_length:
                            state.word_length = new_len
                            state.rebuild_sets()

                    elif t2.collidepoint(mx, my) or k2.collidepoint(mx, my):
                        dragging = "mp"
                        rel = clamp(mx - preview_track.left, 0, preview_track.width)
                        ratio = rel / preview_track.width
                        state.max_preview = clamp(
                            round(1 + ratio * (MAX_MAX_PREVIEW - 1)), 1, MAX_MAX_PREVIEW
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
                            state.ph_mode = "end"
                    elif mode_rects[2].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_mode = "exist"
                        else:
                            state.ph_mode = "middle"

                    # Summary btn
                    elif summary_btn.collidepoint(mx, my):
                        if summary_open:
                            close_summary_window()
                        else:
                            open_summary_window()

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
                    elif lang_rects[1].collidepoint(mx, my):
                        state.language = "english"
                        state.status = "Language: English"

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

                    else:
                        if state.finder_mode == "letter_match":
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
                                    break
                        else:
                            # PH slot clicks and +/- buttons
                            clicked_ph = False
                            for mode_name, rdata in _ph_slot_rects.items():
                                if rdata["plus"].collidepoint(mx, my):
                                    if (
                                        state.ph_slot_count[mode_name]
                                        < MAX_PATTERN_SLOTS
                                    ):
                                        state.ph_slot_count[mode_name] += 1
                                    clicked_ph = True
                                    break
                                if rdata["minus"].collidepoint(mx, my):
                                    if state.ph_slot_count[mode_name] > 1:
                                        state.ph_slot_count[mode_name] -= 1
                                        state.ph_selected[mode_name] = clamp(
                                            state.ph_selected[mode_name],
                                            0,
                                            state.ph_slot_count[mode_name] - 1,
                                        )
                                    clicked_ph = True
                                    break
                                for si, sr in enumerate(rdata["slots"]):
                                    if sr.collidepoint(mx, my):
                                        state.ph_mode = mode_name
                                        state.ph_selected[mode_name] = si
                                        clicked_ph = True
                                        break
                                if clicked_ph:
                                    break

                        # Results panel word selection (left click = save)
                        for word, wr in _result_word_rects:
                            if wr.collidepoint(mx, my):
                                if state.word_selections.get(word) == "save":
                                    del state.word_selections[word]
                                else:
                                    state.word_selections[word] = "save"
                                break

                elif btn == 3:
                    # Right click: exclude/deselect in results
                    for word, wr in _result_word_rects:
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
                    rel = clamp(
                        event.pos[0] - wordlen_track.left, 0, wordlen_track.width
                    )
                    ratio = rel / wordlen_track.width
                    new_len = round(1 + ratio * (MAX_WORD_LENGTH - 1))
                    if new_len != state.word_length:
                        state.word_length = new_len
                        state.rebuild_sets()
                    if state.finder_mode == "pattern_hunt":
                        # Left edge = "All"
                        all_zone = int(_S1W * 0.04)
                        if rel <= all_zone:
                            state.ph_word_length_all = True
                        else:
                            state.ph_word_length_all = False
                            nw = int(
                                round(
                                    1
                                    + ((rel - all_zone) / max(_S1W - all_zone, 1))
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
                        nw = int(round(1 + (rel / _S1W) * (MAX_WORD_LENGTH - 1)))
                        if nw != state.word_length:
                            state.word_length = nw
                            state.rebuild_sets()
                            refresh_summary_window()
                elif dragging == "mp":
                    rel = clamp(
                        event.pos[0] - preview_track.left, 0, preview_track.width
                    )
                    ratio = rel / preview_track.width
                    state.max_preview = clamp(
                        round(1 + ratio * (MAX_MAX_PREVIEW - 1)),
                        1,
                        MAX_MAX_PREVIEW,
                    )
                    state.preview_start = clamp(
                        state.preview_start, 0, max(len(state.search_results) - 1, 0)
                    )

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                elif event.key == pygame.K_RETURN:
                    do_search()

                elif event.key == pygame.K_BACKSPACE:
                    if state.finder_mode == "letter_match":
                        if state.input_mode == "exist":
                            # Delete selected exist item
                            delete_exist_item_at(state.selected_exist_idx)
                        else:
                            for p in target_positions():
                                if 0 <= p < state.word_length:
                                    if state.input_mode == "valid":
                                        state.valid_sets[p].clear()
                                    else:
                                        state.invalid_sets[p].clear()
                    else:
                        ph_backspace()
                    refresh_summary_window()

                elif event.key == pygame.K_LEFT:
                    if state.finder_mode == "letter_match":
                        if state.input_mode == "exist":
                            items = state.get_exist_items()
                            if items:
                                state.selected_exist_idx = (
                                    state.selected_exist_idx - 1
                                ) % len(items)
                        else:
                            if state.word_length > 0:
                                state.selected_pos = (
                                    state.selected_pos - 1
                                ) % state.word_length
                    else:
                        mode = state.ph_mode
                        count = state.ph_slot_count[mode]
                        state.ph_selected[mode] = (state.ph_selected[mode] - 1) % count

                elif event.key == pygame.K_RIGHT:
                    if state.finder_mode == "letter_match":
                        if state.input_mode == "exist":
                            items = state.get_exist_items()
                            if items:
                                state.selected_exist_idx = (
                                    state.selected_exist_idx + 1
                                ) % len(items)
                        else:
                            if state.word_length > 0:
                                state.selected_pos = (
                                    state.selected_pos + 1
                                ) % state.word_length
                    else:
                        mode = state.ph_mode
                        count = state.ph_slot_count[mode]
                        state.ph_selected[mode] = (state.ph_selected[mode] + 1) % count

                elif event.key == pygame.K_UP:
                    if state.finder_mode == "letter_match":
                        state.cycle_input_mode_lm(-1)
                    else:
                        state.cycle_ph_mode(-1)

                elif event.key == pygame.K_DOWN:
                    if state.finder_mode == "letter_match":
                        state.cycle_input_mode_lm(1)
                    else:
                        state.cycle_ph_mode(1)

                # Tab = toggle finder mode
                elif event.key == pygame.K_TAB:
                    toggle_finder_mode()

                # / key = toggle Slot/All scope
                elif event.key in (pygame.K_SLASH, pygame.K_QUESTION):
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

                elif event.key == pygame.K_SPACE:
                    if state.finder_mode == "pattern_hunt" and (
                        event.mod & pygame.KMOD_SHIFT
                    ):
                        # Shift+Space in PH = toggle expand
                        ph_toggle_expand()
                        refresh_summary_window()
                    else:
                        state.language = (
                            "english" if state.language == "greek" else "greek"
                        )
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

                elif event.key == pygame.K_i and (event.mod & pygame.KMOD_CTRL):
                    if info_open:
                        close_info_window()
                    else:
                        open_info_window()

                else:
                    ch = event.unicode
                    if len(ch) == 1 and ch.isalpha():
                        if state.finder_mode == "letter_match":
                            if state.input_mode == "exist":
                                add_exist_letter(ch)
                            else:
                                toggle_letter(ch)
                        else:
                            ph_add_letter(ch)
                        refresh_summary_window()

    if summary_win is not None and summary_win.winfo_exists():
        summary_win.destroy()
    if info_win is not None and info_win.winfo_exists():
        info_win.destroy()
    if tk_root is not None and tk_root.winfo_exists():
        tk_root.destroy()

    pygame.quit()
    sys.exit()
