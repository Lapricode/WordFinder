import os
import sys
import pygame
from tkinter import Tk, filedialog, Toplevel, Text, Button, END, TclError
from collections import Counter
import subprocess
from itertools import product


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
INPUT_MODES_PH = ["start", "middle", "end"]

FINDER_MODES = ["letter_match", "pattern_hunt"]
PH_ROWS = ["start", "middle", "end"]
PH_COLS = ["valid", "invalid", "exist"]


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


def _pat_matches_start(word, pat_info, language):
    """Return True if pat_info matches the start of word."""
    seq = pat_info["seq"]
    expanded = pat_info["expanded"]
    if not seq:
        return True
    if len(word) < len(seq):
        return False
    if expanded:
        for ci, ch_pat in enumerate(seq):
            wch = word[ci]
            if language == "greek":
                if GREEK_CHAR_TO_FIRST.get(ch_pat) != GREEK_CHAR_TO_FIRST.get(wch):
                    return False
            elif language == "english":
                if ch_pat.lower() != wch.lower():
                    return False
            else:
                if ch_pat != wch:
                    return False
        return True
    else:
        return word.startswith(seq)


def _pat_matches_end(word, pat_info, language):
    """Return True if pat_info matches the end of word."""
    seq = pat_info["seq"]
    expanded = pat_info["expanded"]
    if not seq:
        return True
    if len(word) < len(seq):
        return False
    if expanded:
        suffix = word[-len(seq) :]
        for ci, ch_pat in enumerate(seq):
            wch = suffix[ci]
            if language == "greek":
                if GREEK_CHAR_TO_FIRST.get(ch_pat) != GREEK_CHAR_TO_FIRST.get(wch):
                    return False
            elif language == "english":
                if ch_pat.lower() != wch.lower():
                    return False
            else:
                if ch_pat != wch:
                    return False
        return True
    else:
        return word.endswith(seq)


def _pat_matches_middle(word, pat_info, language):
    """Return True if pat_info appears anywhere in word."""
    seq = pat_info["seq"]
    expanded = pat_info["expanded"]
    if not seq:
        return True
    for start_i in range(len(word) - len(seq) + 1):
        chunk = word[start_i : start_i + len(seq)]
        if expanded:
            match_all = True
            for ci, ch_pat in enumerate(seq):
                wch = chunk[ci]
                if language == "greek":
                    if GREEK_CHAR_TO_FIRST.get(ch_pat) != GREEK_CHAR_TO_FIRST.get(wch):
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
                return True
        else:
            if chunk == seq:
                return True
    return False


def expand_sequence(seq, language):
    """Convert a sequence like 'οσαστ' into 'οόΟΌσΣςαάΑΆσΣςτΤ'.
    Each character position is expanded to its full variant group independently,
    so repeated letters at different positions each emit their full group.
    """
    result = []
    for ch in seq:
        if language == "greek":
            first = GREEK_CHAR_TO_FIRST.get(ch)
            if first:
                grp = GREEK_GROUP_BY_FIRST[first]
                # Append all group chars that are not already at the END of result
                # (avoid appending the same group twice consecutively, but allow
                # the same group to appear again if a different char separates them)
                for gc in grp:
                    result.append(gc)
            else:
                result.append(ch)
        elif language == "english":
            result.append(ch.lower())
            result.append(ch.upper())
        else:
            result.append(ch)
    # Deduplicate only consecutive identical characters to avoid true duplicates
    # within a single expansion group, but keep repeated groups from repeated letters.
    # Strategy: build per-position groups separated by a sentinel, then join.
    # Actually we want: for 'σσ' -> 'ΣσςΣσς', for 'σ' -> 'Σσς'.
    # The simple approach: just return all of them without any dedup.
    return "".join(result)


def _exist_variants(pat_info):
    """
    Returns all literal sequences represented by a Pattern Hunt slot.

    Examples:

    normal:
        ασ
        -> ["ασ"]

    expanded:
        ασ
        -> ["ασ","ας","άσ","άς", ...]
    """

    seq = pat_info["seq"]

    if not seq:
        return []

    if not pat_info.get("expanded", False):
        return [seq]

    groups = []

    for ch in seq:

        if state.language == "greek":
            first = GREEK_CHAR_TO_FIRST.get(ch)

            if first:
                groups.append(list(GREEK_GROUP_BY_FIRST[first]))
            else:
                groups.append([ch])

        elif state.language == "english":
            groups.append([ch.lower(), ch.upper()])

        else:
            groups.append([ch])

    return ["".join(chars) for chars in product(*groups)]


def _check_start_exist(word, exist_pats):
    if not exist_pats:
        return True

    longest_pat = max(
        (p for p in exist_pats if p["seq"]),
        key=lambda p: len(p["seq"]),
        default=None,
    )

    if longest_pat is None:
        return True

    for p in exist_pats:

        if not p["seq"]:
            continue

        ok = False

        for v in _exist_variants(longest_pat):
            for s in _exist_variants(p):

                if v.startswith(s):
                    ok = True
                    break

            if ok:
                break

        if not ok:
            return False

    return any(word.startswith(v) for v in _exist_variants(longest_pat))


def _check_end_exist(word, exist_pats):
    if not exist_pats:
        return True

    longest_pat = max(
        (p for p in exist_pats if p["seq"]),
        key=lambda p: len(p["seq"]),
        default=None,
    )

    if longest_pat is None:
        return True

    for p in exist_pats:

        if not p["seq"]:
            continue

        ok = False

        for v in _exist_variants(longest_pat):
            for s in _exist_variants(p):

                if v.endswith(s):
                    ok = True
                    break

            if ok:
                break

        if not ok:
            return False

    return any(word.endswith(v) for v in _exist_variants(longest_pat))


def _check_middle_exist(word, exist_pats):

    if not exist_pats:
        return True

    requirements = Counter()

    for pat in exist_pats:

        variants = tuple(sorted(_exist_variants(pat)))

        if variants:
            requirements[variants] += 1

    for variants, needed_count in requirements.items():

        found = 0

        for variant in variants:
            found += word.count(variant)

        if found < needed_count:
            return False

    return True


def find_pattern_words_grid(
    words_list, word_length, slots_by_cell, counts_by_cell, language
):
    """Filter words by the 3x3 Pattern Hunt grid.

    Semantics used here:
      - Valid   = at least one pattern in the cell must match
      - Invalid = no pattern in the cell may match
      - Exist   = filters the valid patterns in the same row; the row's valid
                  patterns must contain the exist sequence(s) literally
    """
    results = []
    rows = ["start", "middle", "end"]
    cols = ["valid", "invalid", "exist"]

    def row_match(word, pat_info, row_name):
        if row_name == "start":
            return _pat_matches_start(word, pat_info, language)
        if row_name == "middle":
            return _pat_matches_middle(word, pat_info, language)
        return _pat_matches_end(word, pat_info, language)

    for word in words_list:
        if word_length is not None and len(word) != word_length:
            continue

        ok = True

        for row in rows:
            valid_pats = [
                p
                for p in slots_by_cell[row]["valid"][: counts_by_cell[row]["valid"]]
                if p["seq"]
            ]
            invalid_pats = [
                p
                for p in slots_by_cell[row]["invalid"][: counts_by_cell[row]["invalid"]]
                if p["seq"]
            ]
            exist_pats = [
                p
                for p in slots_by_cell[row]["exist"][: counts_by_cell[row]["exist"]]
                if p["seq"]
            ]

            # EXIST constraints
            if row == "start":
                if not _check_start_exist(word, exist_pats):
                    ok = False
                    break

            elif row == "middle":
                if not _check_middle_exist(word, exist_pats):
                    ok = False
                    break

            elif row == "end":
                if not _check_end_exist(word, exist_pats):
                    ok = False
                    break

            # Word must match at least one valid pattern in this row
            if valid_pats and not any(row_match(word, p, row) for p in valid_pats):
                ok = False
                break

            # Word must not match any invalid pattern in this row
            if invalid_pats and any(row_match(word, p, row) for p in invalid_pats):
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


# ══════════════════════════════════════════════════════════════════
#  Pygame + fonts
# ══════════════════════════════════════════════════════════════════

use_ascii = False
if use_ascii:
    special_caracters = {
        "-": "-",
        "^": "^",
        "v": "v",
        "<": "<",
        ">": ">",
        "*": "*",
        "~": "~",
        "[OK]": "[OK]",
    }
else:
    special_caracters = {
        "-": "—",
        "^": "↑",
        "v": "↓",
        "<": "←",
        ">": "→",
        "*": "•",
        "~": "≈",
        "[OK]": "✓",
    }

pygame.init()
pygame.display.set_caption("Word Finder")

WIDTH, HEIGHT = 1400, 700
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
clock = pygame.time.Clock()

FONT_FAMILY = "sans-serif, DejaVu Sans, Noto Sans, Liberation Sans, Book, Regular, segoeui, dejavusans, notosans, arial, liberationsans"

FONT_DEFAULT = pygame.font.SysFont(FONT_FAMILY, 17)
FONT_SM = pygame.font.SysFont(FONT_FAMILY, 14)
FONT_MD = pygame.font.SysFont(FONT_FAMILY, 18, bold=True)
FONT_LG = pygame.font.SysFont(FONT_FAMILY, 26, bold=True)
FONT_XL = pygame.font.SysFont(FONT_FAMILY, 32, bold=True)
LINK_FONT_SM = pygame.font.SysFont(FONT_FAMILY, 14)
LINK_FONT_SM.set_underline(True)

# ─── Colour palette ───────────────────────────────────────────────
BG = (240, 242, 247)
SLOT = (255, 255, 255)
PANEL = (255, 255, 255)
PANEL2 = (248, 249, 252)
BORDER = (213, 218, 230)
TEXT = (0, 0, 0)
MUTED = (108, 116, 136)
ACCENT = (0, 0, 255)
BLUE_BG = (220, 220, 255)
GREEN = (46, 164, 79)
GREEN_BG = (233, 248, 238)
GREEN_BDR = (130, 210, 150)
RED = (204, 58, 58)
RED_BG = (251, 233, 233)
RED_BDR = (220, 140, 140)
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
PURPLE = (122, 75, 200)
PURPLE_BG = (242, 235, 252)
PURPLE_BDR = (170, 135, 220)

LIGHT_THEME = {
    "BG": (240, 242, 247),
    "SLOT": (255, 255, 255),
    "PANEL": (255, 255, 255),
    "PANEL2": (248, 249, 252),
    "BORDER": (213, 218, 230),
    "TEXT": (0, 0, 0),
    "MUTED": (30, 30, 30),
    "ACCENT": (0, 0, 255),
    "BLUE_BG": (220, 220, 255),
    "GREEN": (46, 164, 79),
    "GREEN_BG": (233, 248, 238),
    "GREEN_BDR": (130, 210, 150),
    "RED": (204, 58, 58),
    "RED_BG": (251, 233, 233),
    "RED_BDR": (220, 140, 140),
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
    "PURPLE": (122, 75, 200),
    "PURPLE_BG": (242, 235, 252),
    "PURPLE_BDR": (170, 135, 220),
}

DARK_THEME = {
    "BG": (20, 22, 28),
    "SLOT": (100, 100, 100),
    "PANEL": (30, 33, 41),
    "PANEL2": (36, 40, 50),
    "BORDER": (72, 78, 92),
    "TEXT": (255, 255, 255),
    "MUTED": (200, 200, 200),
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
    "PURPLE": (160, 117, 230),
    "PURPLE_BG": (40, 28, 58),
    "PURPLE_BDR": (120, 90, 180),
}

# ─── Layout constants ─────────────────────────────────────────────
MAX_WORD_LENGTH = 35
MAX_MAX_PREVIEW = 100
PAD = 20
GAP = 20

H_HEADER = 65  # taller to fit two-line title
H_CTRL = 80  # taller ribbon for better spacing
H_FILES = 60
H_TOP = H_HEADER + H_CTRL + H_FILES

WORKSPACE_Y = H_TOP + PAD
LEFT_LABEL_W = 180

# Finder button width in the controls ribbon
FINDER_BTN_W = 130

# Review buttons appearance constants
REVIEW_BTN_W = 165
REVIEW_BTN_H = 30
RESULTS_TOP_Y = WORKSPACE_Y + PAD + 170

# Slider x-positions: right of finder button with some gap
_S1X = PAD + FINDER_BTN_W + 40
_S1W = 300
_S2X = _S1X
_S2W = 300

# How many pattern slots per mode
MAX_PATTERN_SLOTS = 5

# X position for +/- buttons in Pattern Hunt (fixed at left of slot area)
_PH_PM_X = PAD + LEFT_LABEL_W - 22  # just before slots start


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


def lighten(color, amount=35):
    return tuple(min(255, c + amount) for c in color[:3])


def draw_button(
    surface, rect, label, bg=None, fg=None, radius=8, hovered=False, font=None
):
    bg = bg if bg is not None else DARK
    fg = fg if fg is not None else WHITE
    font = font or FONT_DEFAULT
    draw_rect = (
        rect.inflate(int(rect.width * 0.1), int(rect.height * 0.1)) if hovered else rect
    )
    fill = lighten(bg) if hovered else bg
    pygame.draw.rect(surface, fill, draw_rect, border_radius=radius)
    img = font.render(label, True, fg)
    surface.blit(img, img.get_rect(center=draw_rect.center))


def draw_nav_button(surface, rect, direction="left", color=None, hovered=False, enabled=True):
    """Small triangular prev/next navigation button."""
    base = color if color is not None else ACCENT
    fg = lighten(base) if (hovered and enabled) else (base if enabled else BORDER)
    pygame.draw.rect(surface, PANEL2, rect, border_radius=6)
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
        img = FONT_MD.render(lbl, True, fg)
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

    knob = pygame.Rect(kx - 5, ty, 18, 14)
    knob_color = RED if is_all else WHITE
    pygame.draw.rect(surface, knob_color, knob, border_radius=7)
    pygame.draw.rect(surface, ACCENT, knob, 2, border_radius=7)

    if show_all_marker:
        # Draw a small marker at the far left indicating "All" zone
        all_mark = pygame.Rect(x - 5, ty + 2, 5, 5)
        pygame.draw.rect(surface, RED, all_mark, border_radius=3)
        blit_text(surface, "All", FONT_SM, RED, x - 20, ty)

    return track, knob


def short_path(p, n=34):
    return p if len(p) <= n else "…" + p[-(n - 1) :]


def set_theme(mode: str):
    global BG, SLOT, PANEL, PANEL2, BORDER, TEXT, MUTED, ACCENT
    global BLUE_BG, GREEN, GREEN_BG, GREEN_BDR, RED, RED_BG, RED_BDR
    global CYAN, DARK, WHITE, BROWN, BROWN_BG, BROWN_BDR, ORANGE
    global TEAL, TEAL_BG, TEAL_BDR, PINK, PINK_BG, PINK_BDR, PURPLE, PURPLE_BG, PURPLE_BDR

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
    PURPLE = theme["PURPLE"]
    PURPLE_BG = theme["PURPLE_BG"]
    PURPLE_BDR = theme["PURPLE_BDR"]


# ══════════════════════════════════════════════════════════════════
#  App state
# ══════════════════════════════════════════════════════════════════


def _make_pattern_slot():
    return {"seq": "", "expanded": False}


class InfoModal:
    """Full-screen dimmed overlay showing the instructions. Click outside or press Escape to close."""

    CONTENT = [
        (f"Word Finder {special_caracters["-"]} Instructions", "title"),
        ("", "gap"),

        ("Two Modes", "heading"),
        ("The program has two search modes, switchable via the red button at the left "
         "of the controls bar, or by pressing Tab:", "body"),
        (f"Letter Match {special_caracters["-"]} classic slot-based filtering", "bullet"),
        (f"Pattern Hunt {special_caracters["-"]} grid-based pattern filtering", "bullet"),
        ("", "gap"),

        ("Letter Match", "heading"),
        ("Filters words by applying per-slot letter rules.", "body"),
        (f"Three input modes (cycle with {special_caracters["^"]} {special_caracters["v"]} or click the pill toggle):", "body"),
        (f"Valid {special_caracters["-"]} the selected letter group must appear in that slot.", "bullet"),
        (f"Invalid {special_caracters["-"]} the selected letter group must not appear in that slot.", "bullet"),
        (f"Exist {special_caracters["-"]} the letter must appear somewhere in the word. Repeating a letter in "
         "Exist means it must occur multiple times.", "bullet"),
        ("", "gap"),
        ("Navigation:", "body"),
        (f"{special_caracters["<"]} {special_caracters[">"]} arrows: move between slots (Valid/Invalid) or between Exist items.", "bullet"),
        ("Backspace: in Valid/Invalid, clears the selected slot (or all slots if scope "
         "is \"All\"). In Exist, deletes the currently selected Exist letter group.", "bullet"),
        ("Type a letter: adds/removes constraint in current mode.", "bullet"),
        ("The active slot / exist area shows a highlighted border.", "bullet"),
        ("", "gap"),
        ("Slot / All scope (Shift+Space or pill toggle):", "body"),
        (f"Slot {special_caracters["-"]} input affects only the selected slot.", "bullet"),
        (f"All {special_caracters["-"]} input affects all slots at once.", "bullet"),
        ("", "gap"),
        ("When word length increases, previously entered slot data is preserved. Data "
         "is only removed when the word length shrinks past its position.", "body"),
        ("Summary panel shows all current Letter Match constraints.", "body"),
        ("", "gap"),

        ("Pattern Hunt", "heading"),
        ("Filters words by a 3x3 grid: rows are Start / Middle / End and columns are "
         "Valid / Invalid / Exist.", "body"),
        ("", "gap"),
        ("Navigation:", "body"),
        (f"{special_caracters["^"]} {special_caracters["v"]} arrows: move between Start / Middle / End rows.", "bullet"),
        (f"{special_caracters["<"]} {special_caracters[">"]} arrows: move between the slots of a certain cell group.", "bullet"),
        (f"Shift + {special_caracters["<"]} {special_caracters[">"]} arrows: move between Valid / Invalid / Exist columns.", "bullet"),
        ("Click a slot to select it along with its cell group.", "bullet"),
        ("Backspace deletes the current slot content; if the slot becomes empty, its "
         "expand flag is also cleared.", "bullet"),
        ("", "gap"),
        ("Cell behavior:", "body"),
        (f"Valid {special_caracters["-"]} at least one pattern in the cell must match.", "bullet"),
        (f"Invalid {special_caracters["-"]} no pattern in the cell may match.", "bullet"),
        (f"Exist {special_caracters["-"]} every pattern in the cell must appear in the word.", "bullet"),
        ("", "gap"),
        ("Pattern matching rows:", "body"),
        (f"Start {special_caracters["-"]} sequence must match the beginning of the word.", "bullet"),
        (f"Middle {special_caracters["-"]} sequence must appear anywhere in the word.", "bullet"),
        (f"End {special_caracters["-"]} sequence must match the end of the word.", "bullet"),
        ("", "gap"),
        ("Expanded matching (Ctrl+Space or the small corner button): Normal mode keeps "
         "the typed sequence literal. Expanded mode shows and matches all accent/case "
         "variants.", "body"),
        ("The left/right and up/down arrows move between the grid cells, while the "
         "selected cell keeps its own slot index.", "body"),
        ("", "gap"),
        ("Word length in Pattern Hunt: Drag the slider all the way left to set \"Word "
         "Length: All\", which disables length filtering. The slider's left edge is "
         "visually marked in red.", "body"),
        ("", "gap"),
        ("\"Patterns Review\" shows a summary of all current Pattern Hunt rules.", "body"),
        ("", "gap"),

        ("Common Controls", "heading"),
        (f"Enter / Search button {special_caracters["-"]} run the search.", "bullet"),
        (f"Ctrl+S {special_caracters["-"]} save current results to file.", "bullet"),
        (f"Page Up / Page Down {special_caracters["-"]} scroll through result pages.", "bullet"),
        (f"Tab {special_caracters["-"]} toggle between Letter Match and Pattern Hunt.", "bullet"),
        (f"Shift+Space {special_caracters["-"]} toggle Slot and All.", "bullet"),
        (f"/ (slash) {special_caracters["-"]} switch between Greek and English word lists.", "bullet"),
        (f"Ctrl+Space {special_caracters["-"]} expand / collapse Pattern Hunt slot(s).", "bullet"),
        (f"Ctrl+I or the circular i button {special_caracters["-"]} open this instructions window.", "bullet"),
        ("", "gap"),

        ("Results panel:", "heading"),
        (f"Left-click a word {special_caracters["-"]} mark it as \"to save\" (green).", "bullet"),
        (f"Right-click a word {special_caracters["-"]} mark it as \"excluded\" (red).", "bullet"),
        ("Click again to deselect.", "bullet"),
        ("The count of marked/excluded words is shown in the results header.", "bullet"),
        ("Save writes all results (or only marked ones if any are marked).", "bullet"),
        ("", "gap"),

        ("Theme:", "heading"),
        ("The theme button shows \"Light\" when the light theme is active, and \"Dark\" "
         "when the dark theme is active. Click to toggle.", "body"),
        ("", "gap"),

        ("Language behavior:", "heading"),
        ("Greek mode understands accented forms and common letter variants. English "
         "mode groups uppercase and lowercase of the same letter.", "body"),
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
                self._scroll = max(0, min(self._max_scroll, self._scroll - event.y * 20))

    def _panel_rect(self, W, H):
        pw = min(720, W - 80)
        ph = min(640, H - 60)
        return pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)

    def _content_height(self, panel):
        """Recompute the full wrapped content height for the current panel width."""
        PAD_ = 28
        max_w = panel.width - PAD_ * 2
        line_spacing = {
            "title":   (FONT_XL, 14),
            "heading": (FONT_LG, 6),
            "body":    (FONT_SM, 4),
            "bullet":  (FONT_SM, 4),
            "footer":  (FONT_SM, 4),
            "gap":     (None,    10),
        }
        h = 0
        for text, kind in self.CONTENT:
            font, extra_gap = line_spacing.get(kind, line_spacing["body"])
            if font is None:
                h += extra_gap
                continue
            indent = 18 if kind == "bullet" else 0
            prefix = f"{special_caracters["*"]}  " if kind == "bullet" else ""
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
        pygame.draw.rect(surface, PANEL, panel, border_radius=16)
        pygame.draw.rect(surface, ACCENT, panel, 2, border_radius=16)

        PAD_ = 28
        content_x = panel.x + PAD_
        max_w = panel.width - PAD_ * 2
        y = panel.y + PAD_ - int(self._scroll)

        line_spacing = {
            "title":   (FONT_XL, TEXT,   14),
            "heading": (FONT_LG, ACCENT, 6),
            "body":    (FONT_SM, MUTED,  4),
            "bullet":  (FONT_SM, TEXT,   4),
            "footer":  (FONT_SM, MUTED,  4),
            "gap":     (None,    None,   10),
        }

        clip_rect = pygame.Rect(panel.x + 2, panel.y + 2, panel.width - 4, panel.height - 4)
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect)

        for text, kind in self.CONTENT:
            font, color, extra_gap = line_spacing.get(kind, line_spacing["body"])
            if font is None:
                y += extra_gap
                continue
            indent = 18 if kind == "bullet" else 0
            prefix = f"{special_caracters["*"]}  " if kind == "bullet" else ""
            for line in self._wrap(prefix + text, font, max_w - indent):
                if panel.y <= y <= panel.y + panel.height:
                    surface.blit(font.render(line, True, color), (content_x + indent, y))
                y += font.get_height() + extra_gap

        surface.set_clip(old_clip)

        # Clamp scroll now that we know the real max (also refreshes _max_scroll_cache)
        track, thumb = self._scrollbar_rects(panel)
        self._scroll = max(0, min(self._max_scroll_cache, self._scroll))
        if track:
            pygame.draw.rect(surface, PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, BORDER, thumb, border_radius=4)

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


class AppState:
    def __init__(self):
        self.word_length = 5
        self.max_preview = MAX_MAX_PREVIEW // 2
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
        return ["start", "middle", "end"]

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


# ══════════════════════════════════════════════════════════════════
#  File dialogs & Tk windows
# ══════════════════════════════════════════════════════════════════

tk_root = None
summary_tk_root = None
summary_win = None
summary_text = None
summary_open = False


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
    return " ".join("".join(sorted(x)) for x in s) if s else f"{special_caracters["-"]}"


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
            lines.append(f"  {special_caracters["-"]}")
    else:
        # Pattern Hunt
        for row_name in ["start", "middle", "end"]:
            lines.append(row_name.upper())
            for col_name in ["valid", "invalid", "exist"]:
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
                        lines.append(f"    {i+1}: {special_caracters["-"]}")
            lines.append("")
    summary_text.delete("1.0", END)
    summary_text.insert("1.0", "\n".join(lines))


def pump_tk_windows():
    global tk_root, summary_win, summary_text, summary_open
    if tk_root is None or not tk_root.winfo_exists():
        return
    try:
        tk_root.update_idletasks()
        tk_root.update()
    except TclError:
        summary_win = None
        summary_text = None
        summary_open = False


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
    row, col = ph_cell_key()
    for idx in ph_target_slots():
        slot = ph_cell_slots(row, col)[idx]
        if slot["seq"]:
            slot["seq"] = slot["seq"][:-1]
            if not slot["seq"]:
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
        state.status = f"No words loaded {special_caracters["-"]} check: {state.active_file()}"
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
        r = find_pattern_words_grid(
            words, wl, state.ph_slots, state.ph_slot_count, state.language
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
        state.status = f"Nothing to save {special_caracters["-"]} run Search first."
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
        state.status = f"Saved {state.results_count} words {special_caracters[">"]} {os.path.basename(path)}"
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
    state.ph_mode = "start"
    state.ph_col = "valid"
    state.status = f"Switched to {'Pattern Hunt' if state.finder_mode == 'pattern_hunt' else 'Letter Match'}"
    refresh_summary_window()


# ══════════════════════════════════════════════════════════════════
#  Render sections
# ══════════════════════════════════════════════════════════════════

# Global rects for results panel mouse interaction
_result_word_rects = []  # list of (word, rect)
_hover_word_rect = None  # (word, rect) that is hovered
_info_btn_rect = pygame.Rect(0, 0, 0, 0)


def render_header(mouse_pos):
    global _info_btn_rect
    pygame.draw.rect(screen, PANEL, (0, 0, WIDTH, H_HEADER))
    pygame.draw.line(screen, BORDER, (0, H_HEADER), (WIDTH, H_HEADER))

    mode_label = (
        "Letter Match" if state.finder_mode == "letter_match" else "Pattern Hunt"
    )
    title_x = PAD + 4
    lg_h = FONT_LG.get_linesize()
    sm_h = FONT_SM.get_linesize()
    total_title_h = lg_h + sm_h
    title_top = H_HEADER // 2 - total_title_h // 2
    blit_text(
        screen, "Word Finder", FONT_LG, TEXT, title_x, title_top, anchor="topleft"
    )
    blit_text(
        screen,
        f"[{mode_label}]",
        FONT_SM,
        MUTED,
        title_x,
        title_top + lg_h + 1,
        anchor="topleft",
    )

    hints1 = (
        f"Backspace = Clear  ·  Enter = Search  ·  (Shift +) {special_caracters["<"]} {special_caracters[">"]} = Navigate  ·  {special_caracters["^"]} {special_caracters["v"]} = Mode"
        f"  ·  Tab = Letter Match/Pattern Hunt  ·  Shift+Space = Slot/All"
    )
    hints2 = (
        " / = Greek/English  ·  Ctrl+Space = Expand (PH)  ·  Ctrl+S = Save"
        "  ·  Page Up/Down = Scroll  ·  Ctrl+I = Info"
    )
    blit_text(
        screen, hints1, FONT_SM, MUTED, PAD + 200, H_HEADER * 0.28, anchor="midleft"
    )
    blit_text(
        screen, hints2, FONT_SM, MUTED, PAD + 200, H_HEADER * 0.70, anchor="midleft"
    )

    r = 14
    cx = WIDTH - PAD - r
    cy = H_HEADER // 2
    _info_btn_rect = pygame.Rect(cx - r, cy - r, 2 * r, 2 * r)
    # pygame.draw.circle(screen, ACCENT, (cx, cy), r)
    # img = FONT_MD.render("i", True, WHITE)
    # screen.blit(img, img.get_rect(center=(cx, cy - 1)))
    draw_button(
        screen,
        _info_btn_rect,
        "i",
        ACCENT,
        WHITE,
        radius=12,
        hovered=_info_btn_rect.collidepoint(mouse_pos),
        font=FONT_LG,
    )


def render_controls(mouse_pos):
    """Returns t1, k1, t2, k2, mode_rects, scope_rects, lang_rects, search_rect, finder_btn_rect,
    wordlen_track_rect, preview_track_rect  (last two for accurate slider hit-testing)
    """
    y0 = H_HEADER
    pygame.draw.rect(screen, PANEL2, (0, y0, WIDTH, H_CTRL))
    pygame.draw.line(screen, BORDER, (0, y0 + H_CTRL), (WIDTH, y0 + H_CTRL))

    # ── Finder Mode Button (red, left side, ONE LINE) ─────────────
    btn_h = 50
    btn_y = y0 + (H_CTRL - btn_h) / 2
    finder_btn_rect = pygame.Rect(PAD, btn_y, FINDER_BTN_W, btn_h)
    finder_lbl = (
        "Letter Match" if state.finder_mode == "letter_match" else "Pattern Hunt"
    )
    is_hov_finder = finder_btn_rect.collidepoint(mouse_pos)
    draw_button(
        screen, finder_btn_rect, finder_lbl, RED, WHITE,
        radius=8, hovered=is_hov_finder, font=FONT_MD,
    )

    # ── Sliders (stacked, right of finder button) ─────────────────
    # Use the global _S1X/_S1W/_S2X/_S2W which are computed from FINDER_BTN_W
    sl_x1 = _S1X
    sl_w1 = _S1W
    sl_x2 = _S2X
    sl_w2 = _S2W

    # Vertical positions: top slider upper quarter, bottom slider lower quarter
    cy1 = y0 + 2
    cy2 = y0 + H_CTRL / 2 + 2

    # Word length slider
    is_all = state.finder_mode == "pattern_hunt" and state.ph_word_length_all
    t1, k1 = draw_slider(
        screen,
        sl_x1,
        cy1,
        sl_w1,
        1,
        MAX_WORD_LENGTH,
        state.word_length,
        "Word length",
        show_all_marker=(state.finder_mode == "pattern_hunt"),
        is_all=is_all,
    )
    # Max preview slider
    t2, k2 = draw_slider(
        screen, sl_x2, cy2, sl_w2, 1, MAX_MAX_PREVIEW, state.max_preview, "Max preview"
    )

    # ── Mode pill toggle ──────────────────────────────────────────
    if state.finder_mode == "letter_match":
        mode_labels = ["Valid", "Invalid", "Exist"]
        mode_colors = [GREEN, RED, BROWN]
        mode_idx = {"valid": 0, "invalid": 1, "exist": 2}[state.input_mode]
    else:
        mode_labels = ["Start", "Middle", "End"]
        mode_colors = [TEAL, PURPLE, PINK]
        mode_idx = {"start": 0, "middle": 1, "end": 2}[state.ph_mode]

    pill_h = 40
    pill_y = y0 + (H_CTRL - pill_h) / 2
    mx_x = sl_x1 + sl_w1 + 50
    m_rect = pygame.Rect(mx_x, pill_y, 285, pill_h)
    m_rects = draw_pill_toggle(
        screen,
        m_rect,
        mode_labels,
        mode_idx,
        mode_colors,
        hovered=m_rect.collidepoint(mouse_pos),
    )

    # ── Scope pill toggle (Slot / All) ────────────────────────────
    scope_x = mx_x + 330
    scope_rect = pygame.Rect(scope_x, pill_y, 150, pill_h)
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
    lg_x = scope_x + 190
    lang_rect = pygame.Rect(lg_x, pill_y, 175, pill_h)
    lang_rects = draw_pill_toggle(
        screen,
        lang_rect,
        ["Greek", "English"],
        0 if state.language == "greek" else 1,
        [ACCENT, ACCENT],
        hovered=lang_rect.collidepoint(mouse_pos),
    )

    # ── Search button ─────────────────────────────────────────────
    search_rect_h = 50
    search_rect_y = y0 + (H_CTRL - search_rect_h) / 2
    search_rect = pygame.Rect(WIDTH - PAD - 120, search_rect_y, 120, search_rect_h)
    draw_button(
        screen,
        search_rect,
        "Search",
        GREEN,
        WHITE,
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
            screen,
            br,
            label,
            DARK,
            WHITE,
            radius=7,
            hovered=br.collidepoint(mouse_pos),
            font=FONT_MD,
        )
        tx = x + BW + 6
        path_img = LINK_FONT_SM.render(short_path(path), True, ACCENT)
        path_rect = path_img.get_rect(topleft=(tx, by + 1))
        screen.blit(path_img, path_rect)
        blit_text(
            screen,
            f"{count} words",
            FONT_SM,
            MUTED,
            tx,
            by + 20,
            anchor="topleft",
        )
        return br, path_rect

    gf_btn, gf_link = file_unit(PAD, "Greek", state.greek_file, state.greek_count)
    ef_btn, ef_link = file_unit(
        PAD + 350, "English", state.english_file, state.english_count
    )
    sp_btn, sp_link = file_unit(
        PAD + 700, "Save to", state.results_file, state.results_count
    )

    btn_h = 40
    btn_y = by + (H_FILES - bh) / 2
    BW = 120

    # Theme button: shows "Light" when light theme is active, "Dark" when dark is active
    theme_btn = pygame.Rect(WIDTH - PAD - 120, btn_y, BW, btn_h)
    theme_label = "Light" if state.theme == "light" else "Dark"
    draw_button(
        screen,
        theme_btn,
        theme_label,
        CYAN,
        WHITE,
        radius=7,
        hovered=theme_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    # Save button
    SAVE_BTN_X = WIDTH - PAD - 280
    sv_btn = pygame.Rect(SAVE_BTN_X, btn_y, BW, btn_h)
    draw_button(
        screen,
        sv_btn,
        "Save",
        PURPLE,
        WHITE,
        hovered=sv_btn.collidepoint(mouse_pos),
        font=FONT_LG,
    )

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
    return "  ·  ".join(parts) if parts else f"{special_caracters["-"]}"


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

    summary_btn = pygame.Rect(PAD, WORKSPACE_Y, REVIEW_BTN_W, REVIEW_BTN_H)
    draw_button(
        screen,
        summary_btn,
        "Slots Review",
        DARK,
        WHITE,
        radius=7,
        hovered=summary_btn.collidepoint(mouse_pos),
        font=FONT_MD,
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
                display_letters or f"{special_caracters["-"]}", True, TEXT if letters else MUTED
            )
            screen.blit(img, img.get_rect(center=cell.center))
            if cell.collidepoint(mouse_pos):
                letters_full = "".join(sorted(sets[i])) or f"{special_caracters["-"]}"
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
            disp = f"{label}x{count}" if count > 1 else label
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
        img = FONT_SM.render(f"{special_caracters["-"]}", True, MUTED)
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

    return slot_w, slot_h, sx, ty, gap, RESULTS_TOP_Y, summary_btn


# ─── Pattern Hunt workspace ───────────────────────────────────────


def _ph_cell_layout(cell_rect, slot_count):
    btn_w = 16
    inner_pad = 4
    gap = 6
    usable = max(1, cell_rect.width - btn_w - inner_pad * 2 - 6)
    n = max(slot_count, 1)
    slot_w = max(34, min(110, (usable - (n - 1) * gap) // n))
    total_w = n * slot_w + (n - 1) * gap
    sx = cell_rect.x + btn_w + inner_pad + max(0, (usable - total_w) // 2)
    return slot_w, sx, gap, btn_w


def render_workspace_ph(mouse_pos):
    top_y = WORKSPACE_Y + PAD
    summary_btn = pygame.Rect(PAD, WORKSPACE_Y, REVIEW_BTN_W, REVIEW_BTN_H)
    draw_button(
        screen,
        summary_btn,
        "Patterns Review",
        DARK,
        WHITE,
        radius=7,
        hovered=summary_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    col_labels = ["Valid", "Invalid", "Exist"]
    col_colors = [GREEN, RED, BROWN]
    col_bg = [GREEN_BG, RED_BG, BROWN_BG]
    row_labels = ["Start", "Middle", "End"]
    row_colors = [TEAL, PURPLE, PINK]
    row_bg = [TEAL_BG, PURPLE_BG, PINK_BG]

    grid_left = PAD + LEFT_LABEL_W
    grid_right = WIDTH - PAD
    col_gap = 10
    cols = 3
    cell_w = max(190, (grid_right - grid_left - (cols - 1) * col_gap) // cols)
    cell_h = 44
    row_gap = 10
    header_y = top_y - 10
    row_start_y = header_y + 28

    col_hdr_rects = {}
    for ci, (clbl, ccol) in enumerate(zip(col_labels, col_colors)):
        x = grid_left + ci * (cell_w + col_gap)
        r = pygame.Rect(x, header_y, cell_w, 22)
        pygame.draw.rect(screen, ccol, r, border_radius=6)
        img = FONT_MD.render(clbl.upper(), True, WHITE)
        screen.blit(img, img.get_rect(center=r.center))
        col_hdr_rects[PH_COLS[ci]] = r

    ph_ui = {"summary_btn": summary_btn, "cells": {}, "col_hdrs": col_hdr_rects}
    hover_text = None
    hover_pos = None

    for ri, row in enumerate(PH_ROWS):
        y = row_start_y + ri * (cell_h + row_gap)
        row_lbl = row_labels[ri]
        row_col = row_colors[ri]
        blit_text(screen, row_lbl.upper(), FONT_MD, row_col, PAD, y + cell_h // 2 - 10)

        for ci, col in enumerate(PH_COLS):
            x = grid_left + ci * (cell_w + col_gap)
            cell = pygame.Rect(x, y, cell_w, cell_h)
            is_active_cell = (
                state.finder_mode == "pattern_hunt"
                and state.ph_mode == row
                and state.ph_col == col
            )
            cell_border = row_col if is_active_cell else col_colors[ci]
            cell_border_w = 3 if is_active_cell else 1
            pygame.draw.rect(screen, col_bg[ci], cell, border_radius=8)
            pygame.draw.rect(screen, cell_border, cell, cell_border_w, border_radius=8)

            count = ph_cell_count(row, col)
            selected_idx = ph_cell_selected_idx(row, col)
            slots = ph_cell_slots(row, col)
            slot_w, sx, gap, btn_w = _ph_cell_layout(cell, count)

            plus_r = pygame.Rect(cell.x + 2, cell.y + 3, 14, 14)
            minus_r = pygame.Rect(cell.x + 2, cell.y + cell.height - 17, 14, 14)
            pygame.draw.rect(screen, GREEN_BG, plus_r, border_radius=4)
            pygame.draw.rect(screen, RED_BG, minus_r, border_radius=4)
            pygame.draw.rect(screen, GREEN_BDR, plus_r, 1, border_radius=4)
            pygame.draw.rect(screen, RED_BDR, minus_r, 1, border_radius=4)
            blit_text(
                screen,
                "+",
                FONT_SM,
                GREEN,
                plus_r.centerx,
                plus_r.centery,
                anchor="center",
            )
            blit_text(
                screen,
                "-",
                FONT_SM,
                RED,
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
                slot_fill = BLUE_BG if expanded and seq else PANEL2
                slot_bdr = row_col if is_sel_slot else BORDER
                slot_bdr_w = 2 if is_sel_slot else 1
                pygame.draw.rect(screen, slot_fill, sr, border_radius=6)
                pygame.draw.rect(screen, slot_bdr, sr, slot_bdr_w, border_radius=6)

                disp_seq = (
                    expand_sequence(seq, state.language) if (seq and expanded) else seq
                )
                disp = (
                    fit_text_with_ellipsis(disp_seq, FONT_SM, slot_w - 10)
                    if seq
                    else f"{special_caracters["-"]}"
                )
                img = FONT_SM.render(
                    disp, True, PURPLE if expanded and seq else (TEXT if seq else MUTED)
                )
                screen.blit(img, img.get_rect(center=sr.center))

                exp_btn = pygame.Rect(sr.right - 15, sr.top + 2, 12, 12)
                pygame.draw.rect(
                    screen, PURPLE if expanded else BORDER, exp_btn, border_radius=3
                )
                e_img = FONT_SM.render(f"{special_caracters["~"]}", True, WHITE if expanded else MUTED)
                screen.blit(e_img, e_img.get_rect(center=exp_btn.center))

                if sr.collidepoint(mouse_pos):
                    hover_text = f"{row_lbl} / {col_labels[ci]}: {disp_seq or '-'}" + (
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
        tip_img = FONT_SM.render(hover_text, True, WHITE)
        tip_pad = 8
        tip_rect = tip_img.get_rect(topleft=(hover_pos[0] + 16, hover_pos[1] + 16))
        tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
        pygame.draw.rect(screen, DARK, tip_rect, border_radius=8)
        pygame.draw.rect(screen, BORDER, tip_rect, 1, border_radius=8)
        screen.blit(tip_img, tip_img.get_rect(center=tip_rect.center))

    return RESULTS_TOP_Y, summary_btn, ph_ui


def render_results(table_bottom_y, mouse_pos=(0, 0)):
    global _result_word_rects, _hover_word_rect
    _result_word_rects = []

    y0 = table_bottom_y + PAD
    h = HEIGHT - y0 - PAD
    if h < 80:
        return None, None

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
        sel_parts.append(f"{n_save} words to save {special_caracters["[OK]"]}")
    if n_excl:
        sel_parts.append(f"{n_excl} words excluded X")
    sel_str = "  |  " + "  ·  ".join(sel_parts) if sel_parts else ""

    blit_text(screen, state.status, FONT_SM, MUTED, panel.x + PAD, panel.y + 10)

    cnt = f"{n} total  ·  showing {start_index} - {end_index}"
    cnt_w = FONT_SM.size(cnt)[0]
    nav_w, nav_h, nav_gap = 22, 20, 6
    group_w = nav_w * 2 + nav_gap * 2 + cnt_w
    group_x = panel.right - PAD - group_w
    nav_y = panel.y + 8

    prev_rect = pygame.Rect(group_x, nav_y, nav_w, nav_h)
    cnt_x = prev_rect.right + nav_gap
    blit_text(screen, cnt, FONT_SM, ACCENT, cnt_x, panel.y + 10, anchor="topleft")
    next_rect = pygame.Rect(cnt_x + cnt_w + nav_gap, nav_y, nav_w, nav_h)

    can_prev = state.preview_start > 0
    can_next = n > 0 and (state.preview_start + state.max_preview) < n
    draw_nav_button(screen, prev_rect, "left", hovered=prev_rect.collidepoint(mouse_pos), enabled=can_prev)
    draw_nav_button(screen, next_rect, "right", hovered=next_rect.collidepoint(mouse_pos), enabled=can_next)

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
            f"No results yet {special_caracters["-"]} press Enter or click Search.",
            FONT_MD,
            MUTED,
            panel.x + PAD,
            panel.y + 36,
        )
        return prev_rect, next_rect

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

    return prev_rect, next_rect


# ══════════════════════════════════════════════════════════════════
#  Main loop
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    refresh_words_counts()
    info_modal = InfoModal()
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

        page_prev_rect, page_next_rect = render_results(tby, mouse_pos)
        info_modal.draw(screen, WIDTH, HEIGHT)

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

            modal_was_open = info_modal.visible
            info_modal.handle_event(event, WIDTH, HEIGHT)
            if modal_was_open:
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
                            state.ph_mode = "middle"
                    elif mode_rects[2].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_mode = "exist"
                        else:
                            state.ph_mode = "end"

                    # Summary btn
                    elif summary_btn.collidepoint(mx, my):
                        if summary_open:
                            close_summary_window()
                        else:
                            open_summary_window()

                    # Info btn
                    elif _info_btn_rect.collidepoint(mx, my):
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

                    # Results page navigation buttons
                    elif page_prev_rect and page_prev_rect.collidepoint(mx, my):
                        if state.search_results:
                            state.preview_start = max(0, state.preview_start - state.max_preview)
                    elif page_next_rect and page_next_rect.collidepoint(mx, my):
                        if state.search_results:
                            state.preview_start = min(
                                len(state.search_results) - 1,
                                state.preview_start + state.max_preview,
                            )

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

                elif event.key == pygame.K_i and (event.mod & pygame.KMOD_CTRL):
                    info_modal.show()

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
    if tk_root is not None and tk_root.winfo_exists():
        tk_root.destroy()

    pygame.quit()
    sys.exit()
