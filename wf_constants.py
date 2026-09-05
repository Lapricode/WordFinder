"""
Constants, color themes, layout metrics, and pygame/font initialization.

Part of the Word Finder application (split from the original single-file
WordFinder.py for maintainability). Behavior is unchanged from the original --
this is a pure refactor.
"""

import os
import sys
import platform
import pygame

GREEK_LETTERS = [
    "αάΑΆ",
    "βΒ",
    "γΓ",
    "δΔ",
    "εέΕΈ",
    "ζΖ",
    "ηήΗΉ",
    "θΘ",
    "ιίΙΊϊΐ",
    "κΚ",
    "λΛ",
    "μΜ",
    "νΝ",
    "ξΞ",
    "οόΟΌ",
    "πΠ",
    "ρΡ",
    "σΣς",
    "τΤ",
    "υύΥΎϋΰ",
    "φΦ",
    "χΧ",
    "ψΨ",
    "ωΩώΏ",
]

GREEK_GROUPS = [tuple(group) for group in GREEK_LETTERS]

GREEK_FIRST_LETTERS = {group[0] for group in GREEK_GROUPS}

GREEK_GROUP_BY_FIRST = {group[0]: group for group in GREEK_GROUPS}

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

INPUT_MODES_LM = ["valid", "invalid", "exist", "absent"]

INPUT_MODES_PH = ["start", "inner", "middle", "end"]

FINDER_MODES = ["letter_match", "pattern_hunt"]

PH_ROWS = ["start", "inner", "middle", "end"]

PH_COLS = ["valid", "invalid", "exist", "absent"]

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

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

use_ascii = False

if use_ascii:
    special_chars = {
        "-": "-",
        "^": "^",
        "v": "v",
        "<": "<",
        ">": ">",
        "*": "*",
        "~": "~",
        "[OK]": "[OK]",
        "X": "X",
        "kb": "kb",
        "<>": "<>",
        "?": "?",
    }
else:
    special_chars = {
        "-": "—",
        "^": "↑",
        "v": "↓",
        "<": "←",
        ">": "→",
        "*": "•",
        "~": "≈",
        "[OK]": "✓",
        "X": "✕",
        "kb": "⌨",
        "<>": "⇄",
        "?": "?",
    }

pygame.init()

pygame.key.set_repeat(300, 30)

pygame.display.set_caption("Word Finder")

WIDTH, HEIGHT = 1400, 700

screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)

clock = pygame.time.Clock()

pygame.font.init()

def normalize_font_name(name: str) -> str:
    return name.lower().replace(" ", "").replace("-", "").replace("_", "")

def pick_font(preferred):
    available = {normalize_font_name(f) for f in pygame.font.get_fonts()}
    for name in preferred:
        key = normalize_font_name(name)
        if key in available:
            return key
    return "dejavusans"

SYSTEM = platform.system()

if SYSTEM == "Windows":
    FONT_FAMILY = pick_font(
        ["Segoe UI Symbol", "Segoe UI", "Arial", "DejaVu Sans", "Noto Sans", "Liberation Sans"]
    )
elif SYSTEM == "Darwin":  # macOS
    FONT_FAMILY = pick_font(
        ["SF Pro Text", "Helvetica Neue", "Arial", "DejaVu Sans", "Noto Sans"]
    )
else:  # Linux
    FONT_FAMILY = pick_font(
        ["DejaVu Sans", "Noto Sans", "Liberation Sans", "Arial", "Segoe UI Symbol", "Segoe UI"]
    )

FONT_DEFAULT = pygame.font.SysFont(FONT_FAMILY, 17)

FONT_SM = pygame.font.SysFont(FONT_FAMILY, 14, bold=True)

FONT_MD = pygame.font.SysFont(FONT_FAMILY, 18, bold=True)

FONT_LG = pygame.font.SysFont(FONT_FAMILY, 26, bold=True)

FONT_XL = pygame.font.SysFont(FONT_FAMILY, 32, bold=True)

LINK_FONT_SM = pygame.font.SysFont(FONT_FAMILY, 14)

LINK_FONT_SM.set_underline(True)

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

ORANGE = (214, 120, 20)

ORANGE_BG = (255, 236, 205)

ORANGE_BDR = (232, 156, 64)

TEAL = (0, 160, 140)

TEAL_BG = (220, 248, 244)

TEAL_BDR = (100, 200, 180)

PINK = (200, 60, 140)

PINK_BG = (250, 230, 242)

PINK_BDR = (210, 140, 185)

PURPLE = (122, 75, 200)

PURPLE_BG = (242, 235, 252)

PURPLE_BDR = (170, 135, 220)

BLACK = (0, 0, 0)

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
    "ORANGE": (214, 120, 20),
    "ORANGE_BG": (255, 236, 205),
    "ORANGE_BDR": (232, 156, 64),
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
    "ORANGE": (255, 175, 70),
    "ORANGE_BG": (78, 56, 22),
    "ORANGE_BDR": (184, 128, 52),
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

STATUS_KEYS = ("ok", "no_translation", "no_meaning", "no_translation_no_meaning")

STATUS_BG = {}

STATUS_BDR = {}

def status_colors(status):
    return STATUS_BG.get(status, PANEL2), STATUS_BDR.get(status, BORDER)

MAX_WORD_LENGTH = 35

MAX_MAX_PREVIEW = 300

PAD = 20

GAP = 20

MIN_RESULTS_PER_ROW = 1

MAX_RESULTS_PER_ROW = 20

H_HEADER = 65  # taller to fit two-line title

H_CTRL = 90

H_FILES = 80

H_TOP = H_HEADER + H_CTRL + H_FILES

WORKSPACE_Y = H_TOP + PAD

LEFT_LABEL_W = 180

REVIEW_BTN_W = 165

REVIEW_BTN_H = 30

RESULTS_TOP_Y = WORKSPACE_Y + PAD + 170

MAX_PATTERN_SLOTS = 10

def clamp(n, lo, hi):
    return max(lo, min(hi, n))

def short_path(p, n=20):
    return p if len(p) <= n else "…" + p[-(n - 1) :]

def set_theme(mode: str):
    global BG, SLOT, PANEL, PANEL2, BORDER, TEXT, MUTED, ACCENT
    global BLUE_BG, GREEN, GREEN_BG, GREEN_BDR, RED, RED_BG, RED_BDR
    global CYAN, DARK, WHITE, BROWN, BROWN_BG, BROWN_BDR, ORANGE, ORANGE_BG, ORANGE_BDR
    global TEAL, TEAL_BG, TEAL_BDR, PINK, PINK_BG, PINK_BDR, PURPLE, PURPLE_BG, PURPLE_BDR
    global STATUS_BG, STATUS_BDR

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
    ORANGE_BG = theme["ORANGE_BG"]
    ORANGE_BDR = theme["ORANGE_BDR"]
    TEAL = theme["TEAL"]
    TEAL_BG = theme["TEAL_BG"]
    TEAL_BDR = theme["TEAL_BDR"]
    PINK = theme["PINK"]
    PINK_BG = theme["PINK_BG"]
    PINK_BDR = theme["PINK_BDR"]
    PURPLE = theme["PURPLE"]
    PURPLE_BG = theme["PURPLE_BG"]
    PURPLE_BDR = theme["PURPLE_BDR"]

    if mode == "dark":
        STATUS_BG = {
            "ok": (38, 54, 82),
            "no_translation": (74, 54, 28),
            "no_meaning": (74, 34, 58),
            "no_translation_no_meaning": (52, 52, 52),
        }
        STATUS_BDR = {
            "ok": (104, 140, 204),
            "no_translation": (182, 128, 58),
            "no_meaning": (182, 88, 150),
            "no_translation_no_meaning": (112, 112, 112),
        }
    else:
        STATUS_BG = {
            "ok": (216, 232, 255),
            "no_translation": (255, 225, 190),
            "no_meaning": (255, 220, 238),
            "no_translation_no_meaning": (226, 226, 226),
        }
        STATUS_BDR = {
            "ok": (126, 172, 230),
            "no_translation": (242, 155, 55),
            "no_meaning": (218, 108, 176),
            "no_translation_no_meaning": (170, 170, 170),
        }
