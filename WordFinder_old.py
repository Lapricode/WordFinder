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

ENGLISH_LETTERS = [chr(c) for c in range(ord("a"), ord("z") + 1)]
ENGLISH_GROUPS = [(ch, ch.upper()) for ch in ENGLISH_LETTERS]
ENGLISH_GROUP_BY_FIRST = {group[0]: group for group in ENGLISH_GROUPS}

INPUT_MODES = ["valid", "invalid", "exist"]


def match_key(ch: str) -> str:
    return ch.casefold() if ch else ""


def tokens_for_input(letter: str, language: str) -> set[str]:
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


def exist_key_for_input(letter: str, language: str) -> str | None:
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

pygame.init()
pygame.display.set_caption("Word Finder")

WIDTH, HEIGHT = 1400, 700
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
clock = pygame.time.Clock()

FONT = pygame.font.SysFont("segoeui", 17)
FONT_SM = pygame.font.SysFont("segoeui", 14)
FONT_MD = pygame.font.SysFont("segoeui", 18, bold=True)
FONT_LG = pygame.font.SysFont("segoeui", 26, bold=True)
LINK_FONT_SM = pygame.font.SysFont("segoeui", 14)
LINK_FONT_SM.set_underline(True)

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
}

# ─── Layout constants ─────────────────────────────────────────────
MAX_WORD_LENGTH = 35
MAX_MAX_PREVIEW = 50
PAD = 20
GAP = 20

H_HEADER = 50
H_CTRL = 50
H_FILES = 50
H_TOP = H_HEADER + H_CTRL + H_FILES

WORKSPACE_Y = H_TOP + PAD
LEFT_LABEL_W = 150

# Slider x-positions (fixed; not dependent on WIDTH)
_S1X, _S1W = PAD + 8, 280
_S2X, _S2W = _S1X + _S1W + 40, 200


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


def draw_panel(surface, rect, color=PANEL, border_color=BORDER, radius=12):
    pygame.draw.rect(surface, color, rect, border_radius=radius)
    pygame.draw.rect(surface, border_color, rect, 1, border_radius=radius)


def draw_button(surface, rect, label, bg=DARK, fg=WHITE, radius=8, hovered=False):
    draw_rect = (
        rect.inflate(int(rect.width * 0.1), int(rect.height * 0.1)) if hovered else rect
    )
    pygame.draw.rect(surface, bg, draw_rect, border_radius=radius)
    img = FONT.render(label, True, fg)
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


def draw_slider(surface, x, y, w, min_v, max_v, value, label):
    """Horizontal slider. Returns (track_rect, knob_rect)."""
    blit_text(surface, f"{label}  {value}", FONT_SM, MUTED, x, y)
    ty = y + 20
    track = pygame.Rect(x, ty + 5, w, 4)
    pygame.draw.rect(surface, BORDER, track, border_radius=2)
    t = (value - min_v) / max(max_v - min_v, 1)
    fw = int(t * w)
    if fw > 0:
        pygame.draw.rect(
            surface, ACCENT, pygame.Rect(x, ty + 5, fw, 4), border_radius=2
        )
    kx = x + int(t * w)
    knob = pygame.Rect(kx - 9, ty, 18, 14)
    pygame.draw.rect(surface, WHITE, knob, border_radius=7)
    pygame.draw.rect(surface, ACCENT, knob, 2, border_radius=7)
    return track, knob


def short_path(p, n=34):
    return p if len(p) <= n else "…" + p[-(n - 1) :]


def set_theme(mode: str):
    global BG, SLOT, PANEL, PANEL2, BORDER, TEXT, MUTED, ACCENT
    global BLUE_BG, GREEN, GREEN_BG, GREEN_BDR, RED, RED_BG, RED_BDR
    global PURPLE, CYAN, DARK, WHITE, BROWN, BROWN_BG, BROWN_BDR, ORANGE

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


# ══════════════════════════════════════════════════════════════════
#  App state
# ══════════════════════════════════════════════════════════════════


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
        self.input_mode = "valid"
        self.exist_letters = Counter()
        self.selected_pos = 0
        self.valid_sets = [set() for _ in range(5)]
        self.invalid_sets = [set() for _ in range(5)]
        self.search_results = []
        self.status = "Load a word list, then press Search or Enter."
        self.greek_file = resource_path("greek_words.txt")
        self.english_file = resource_path("english_words.txt")
        self.results_file = resource_path("results.txt")
        self.theme = "dark"

    def rebuild_sets(self):
        n = self.word_length
        self.valid_sets = [set() for _ in range(n)]
        self.invalid_sets = [set() for _ in range(n)]
        self.selected_pos = clamp(self.selected_pos, 0, max(n - 1, 0))
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


state = AppState()
set_theme(state.theme)


# ══════════════════════════════════════════════════════════════════
#  File dialogs
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

INFO_TEXT = """Word Finder

Purpose:
This program filters Greek or English word lists by applying slot-based letter rules.
It is useful for solving word puzzles, checking candidate words, and narrowing a list down quickly.

How the filters work:
• Valid: the chosen letter(s) must appear in that slot.
• Invalid: the chosen letter(s) must not appear in that slot.
• Exist: the letter must appear somewhere in the word, regardless of position.
  Repeating a letter in Exist means the word must contain it multiple times.

Main controls:
• Click a slot to select it.
• Type letters to add/remove constraints in the current mode.
• Backspace clears the current mode:
  - Valid/Invalid clears the selected slot or all slots, depending on scope.
  - Exist clears all required letters.
• Enter runs the search.
• Ctrl+S saves results.
• Page Up / Page Down scroll through result pages.
• Arrow Left / Arrow Right move between slots.
• Arrow Up / Arrow Down switch between Valid, Invalid, and Exist.
• Tab switches between Slot and All input scope.
• Space switches between Greek and English.
• Ctrl+I opens this instructions/info window.

Buttons, Sliders, Pill Toggles:
• Greek / English button loads the matching word list.
• Word length slider changes how many slots are shown.
• Max preview slider changes how many results are shown per page.
• Valid / Invalid / Exist pill toggle selects the active input mode.
• Slot / All pill toggle chooses whether input affects one slot or all slots.
• Greek / English pill toggle switches the active search language.
• Search button runs the filter.
• Save button writes the current results to a file.
• Dark / Light button toggles the interface theme.
• Slots Review button opens a summary window showing the current rules.

Language behavior:
Greek mode understands letter groups such as accented forms and common variants.
English mode groups uppercase and lowercase versions of the same letter together.

Tip:
Build the word pattern first with Valid and Invalid, then use Exist to force required letters.
That usually narrows the list fastest.
"""


def get_tk_root():
    global tk_root
    if tk_root is None or not tk_root.winfo_exists():
        tk_root = Tk()
        tk_root.withdraw()
        tk_root.attributes("-topmost", True)
    return tk_root


def _tk_root():
    return get_tk_root()


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
        summary_win = Toplevel(root)
        summary_win.title("Slots Review")
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


def _tk_root():
    r = Tk()
    r.withdraw()
    r.attributes("-topmost", True)
    return r


def open_file_dialog():
    r = _tk_root()
    p = filedialog.askopenfilename(
        parent=r,
        title="Choose word list",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    r.destroy()
    return p or ""


def save_file_dialog(initial="results.txt"):
    r = _tk_root()
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


def cycle_input_mode(step):
    idx = INPUT_MODES.index(state.input_mode)
    state.input_mode = INPUT_MODES[(idx + step) % len(INPUT_MODES)]


def add_exist_letter(letter: str):
    key = exist_key_for_input(letter, state.language)
    if key is None:
        return
    state.exist_letters[key] += 1


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

    r = find_matching_words(
        words,
        state.word_length,
        state.valid_sets,
        state.invalid_sets,
        state.exist_letters,
        state.language,
    )
    state.search_results = r
    state.preview_start = 0
    n = len(r)
    state.status = (
        f'{n} word{"s" if n != 1 else ""} matched'
        f" in {os.path.basename(state.active_file())}"
    )


def do_save():
    if not state.search_results:
        state.status = "Nothing to save — run Search first."
        return

    path = state.results_file.strip() or save_file_dialog()
    if not path:
        state.status = "Save cancelled."
        return

    try:
        with open(path, "w", encoding="utf-8") as f:
            # f.write(f'Language: {state.language}\n'
            #         f'Length:   {state.word_length}\n'
            #         f'Total:    {len(state.search_results)}\n\n')
            for w in state.search_results:
                f.write(w + "\n")

        state.results_file = path
        state.results_count = len(load_words(path))  # recount after saving
        state.status = f"Saved {state.results_count} words → {os.path.basename(path)}"
    except Exception as e:
        state.status = f"Save error: {e}"


def pump_summary_window():
    global summary_win, summary_text, summary_open
    if summary_win is not None and summary_win.winfo_exists():
        try:
            summary_win.update_idletasks()
        except TclError:
            summary_win = None
            summary_text = None
            summary_open = False


# ══════════════════════════════════════════════════════════════════
#  Render sections — each returns the rects needed for hit-testing
# ══════════════════════════════════════════════════════════════════


def render_header():
    pygame.draw.rect(screen, PANEL, (0, 0, WIDTH, H_HEADER))
    pygame.draw.line(screen, BORDER, (0, H_HEADER), (WIDTH, H_HEADER))
    blit_text(
        screen, "Word Finder", FONT_LG, TEXT, PAD + 4, H_HEADER // 2, anchor="midleft"
    )
    blit_text(
        screen,
        "Click Slot  ·  Type Letters  ·  Backspace = Clear"
        "  ·  Enter = Search  ·  ← → = Navigate Slots"
        "  ·  ↑ ↓ = Valid/Invalid/Exist  ·  Tab = Slot/All  ·  Space = Greek/English"
        "  ·  Ctrl+S = Save  ·  Page Up/Down = Scroll Results  ·  Ctrl+I = Info",
        FONT_SM,
        MUTED,
        PAD + 180,
        H_HEADER // 2,
        anchor="midleft",
    )


def render_controls(mouse_pos):
    """Returns t1, k1, t2, k2, mode_rects, scope_rects, lang_rects, search_rect."""
    y0 = H_HEADER
    pygame.draw.rect(screen, PANEL2, (0, y0, WIDTH, H_CTRL))
    pygame.draw.line(screen, BORDER, (0, y0 + H_CTRL), (WIDTH, y0 + H_CTRL))

    cy = y0 + 8

    t1, k1 = draw_slider(
        screen, _S1X, cy, _S1W, 1, MAX_WORD_LENGTH, state.word_length, "Word length"
    )
    t2, k2 = draw_slider(
        screen, _S2X, cy, _S2W, 1, MAX_MAX_PREVIEW, state.max_preview, "Max preview"
    )

    # Valid / Invalid / Exist pill toggle
    mode_idx = {"valid": 0, "invalid": 1, "exist": 2}[state.input_mode]
    mx_x = _S2X + _S2W + 44
    m_rect = pygame.Rect(mx_x, y0 + 9, 260, 32)
    m_rects = draw_pill_toggle(
        screen,
        m_rect,
        ["Valid", "Invalid", "Exist"],
        mode_idx,
        [GREEN, RED, BROWN],
        hovered=m_rect.collidepoint(mouse_pos),
    )

    # Slot / All pill toggle
    scope_x = mx_x + 276
    scope_rect = pygame.Rect(scope_x, y0 + 9, 150, 32)
    scope_rects = draw_pill_toggle(
        screen,
        scope_rect,
        ["Slot", "All"],
        0 if state.input_scope == "single" else 1,
        [ORANGE, ORANGE],
        hovered=scope_rect.collidepoint(mouse_pos),
    )

    # Greek / English pill toggle
    lg_x = scope_x + 166
    lang_rect = pygame.Rect(lg_x, y0 + 9, 170, 32)
    lang_rects = draw_pill_toggle(
        screen,
        lang_rect,
        ["Greek", "English"],
        0 if state.language == "greek" else 1,
        [ACCENT, ACCENT],
        hovered=lang_rect.collidepoint(mouse_pos),
    )

    # Search button
    search_rect = pygame.Rect(WIDTH - PAD - 120, y0 + 7, 120, 36)
    draw_button(
        screen,
        search_rect,
        "Search",
        GREEN,
        hovered=search_rect.collidepoint(mouse_pos),
    )

    return t1, k1, t2, k2, m_rects, scope_rects, lang_rects, search_rect


def render_file_row(mouse_pos):
    """Returns gf_btn, gf_link, ef_btn, ef_link, sp_btn, sp_link, theme_btn, sv_btn."""
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

    # Theme button placed beneath Search
    theme_btn = pygame.Rect(WIDTH - PAD - 120, by + 5, 120, 30)
    theme_label = "Dark" if state.theme == "light" else "Light"
    draw_button(
        screen,
        theme_btn,
        theme_label,
        CYAN,
        WHITE,
        radius=7,
        hovered=theme_btn.collidepoint(mouse_pos),
    )

    # Save button moved left, near the "Save to" link
    SAVE_BTN_X = WIDTH - PAD - 300
    sv_btn = pygame.Rect(SAVE_BTN_X, by, 100, bh)
    draw_button(screen, sv_btn, "Save", PURPLE, hovered=sv_btn.collidepoint(mouse_pos))

    return gf_btn, gf_link, ef_btn, ef_link, sp_btn, sp_link, theme_btn, sv_btn


def _slot_layout():
    gap = 8
    left_edge = PAD + LEFT_LABEL_W
    right_edge = WIDTH - PAD
    available = max(1, right_edge - left_edge)
    n = max(state.word_length, 1)

    # 50% width for slots_num or fewer.
    # Above slots_num, gradually grow toward full width.
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
    slot_h = 32  # fixed height

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


def render_workspace(mouse_pos):
    """Draws slots + condition tables. Returns (sq, sx, ty, gap, table_bottom_y)."""
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

        bdr_col = ACCENT if sel else BORDER
        bdr_w = 3 if sel else 1

        pygame.draw.rect(screen, fill, r, border_radius=10)
        pygame.draw.rect(screen, bdr_col, r, bdr_w, border_radius=10)

        # Position number above each slot
        ni = FONT_SM.render(str(i + 1), True, ACCENT if sel else MUTED)
        screen.blit(ni, ni.get_rect(center=(x + slot_w // 2, ty - 13)))

    # ── Hint line ─────────────────────────────────────────────────
    hint_y = ty + slot_h - 10
    mc = GREEN if state.input_mode == "valid" else RED
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

    for label, sets, bg_c, bdr_c, lbl_c in [
        ("VALID", state.valid_sets, GREEN_BG, GREEN_BDR, GREEN),
        ("INVALID", state.invalid_sets, RED_BG, RED_BDR, RED),
    ]:
        blit_text(screen, label, FONT_MD, lbl_c, PAD, table_y + row_h // 2 - 10)
        for i in range(state.word_length):
            x = sx + i * (slot_w + gap)
            cell = pygame.Rect(x, table_y, slot_w, row_h)
            pygame.draw.rect(screen, bg_c, cell, border_radius=8)
            pygame.draw.rect(screen, bdr_c, cell, 1, border_radius=8)
            letters = "".join(sorted(sets[i]))
            max_text_w = cell.width - 8
            display_letters = fit_text_with_ellipsis(letters, FONT_SM, max_text_w)
            img = FONT_SM.render(
                display_letters or "—", True, TEXT if letters else MUTED
            )
            screen.blit(img, img.get_rect(center=cell.center))
            if cell.collidepoint(mouse_pos):
                letters = "".join(sorted(sets[i])) or "—"
                hover_text = f"{label} slot {i + 1}: {letters}"
                hover_pos = mouse_pos
        table_y += row_h + 6

    exist_rect = pygame.Rect(PAD, table_y, WIDTH - 2 * PAD, row_h)
    pygame.draw.rect(screen, BROWN_BG, exist_rect, border_radius=8)
    pygame.draw.rect(screen, BROWN_BDR, exist_rect, 1, border_radius=8)

    blit_text(screen, "EXIST", FONT_MD, BROWN, PAD, table_y + row_h // 2 - 10)

    letters = format_exist_letters(state.exist_letters)
    img = FONT_SM.render(letters, True, TEXT if letters != "—" else MUTED)
    screen.blit(img, img.get_rect(midleft=(PAD + 90, table_y + row_h // 2)))
    table_y += row_h + 6

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


def render_results(table_bottom_y):
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

    # Status + count
    blit_text(screen, state.status, FONT_SM, MUTED, panel.x + PAD, panel.y + 10)
    cnt = f"{n} total  ·  showing {start_index} - {end_index}"
    blit_text(
        screen, cnt, FONT_SM, ACCENT, panel.right - PAD, panel.y + 10, anchor="topright"
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

    # Adaptive word-chip grid
    grid_y = panel.y + 34
    cols = max(1, (panel.width - 2 * PAD) // 250)
    cw = (panel.width - 2 * PAD - (cols - 1) * GAP) // cols
    ch_h = 26

    for idx, word in enumerate(preview):
        col = idx % cols
        row = idx // cols
        wx = panel.x + PAD + col * (cw + GAP)
        wy = grid_y + row * (ch_h + 4)
        if wy + ch_h > panel.bottom - 8:
            break
        wr = pygame.Rect(wx, wy, cw, ch_h)
        pygame.draw.rect(screen, PANEL2, wr, border_radius=6)
        pygame.draw.rect(screen, BORDER, wr, 1, border_radius=6)
        wimg = FONT_SM.render(word, True, TEXT)
        screen.blit(wimg, wimg.get_rect(midleft=(wx + 8, wy + ch_h // 2)))


# ══════════════════════════════════════════════════════════════════
#  Main loop
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    refresh_words_counts()
    dragging = None  # None | 'wl' | 'mp'
    running = True
    while running:
        screen.fill(BG)

        mouse_pos = pygame.mouse.get_pos()

        render_header()
        t1, k1, t2, k2, mode_rects, scope_rects, lang_rects, search_rect = (
            render_controls(mouse_pos)
        )
        gf_btn, gf_link, ef_btn, ef_link, sp_btn, sp_link, theme_btn, sv_btn = (
            render_file_row(mouse_pos)
        )
        slot_w, slot_h, sx, ty, gap, tby, summary_btn = render_workspace(mouse_pos)
        render_results(tby)

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

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos

                # Sliders
                if t1.collidepoint(mx, my) or k1.collidepoint(mx, my):
                    dragging = "wl"
                elif t2.collidepoint(mx, my) or k2.collidepoint(mx, my):
                    dragging = "mp"

                # Input Mode pill toggle
                elif mode_rects[0].collidepoint(mx, my):
                    state.input_mode = "valid"
                elif mode_rects[1].collidepoint(mx, my):
                    state.input_mode = "invalid"
                elif mode_rects[2].collidepoint(mx, my):
                    state.input_mode = "exist"
                elif summary_btn.collidepoint(mx, my):
                    if summary_open:
                        close_summary_window()
                    else:
                        open_summary_window()

                # Input State pill toggle
                elif scope_rects[0].collidepoint(mx, my):
                    state.input_scope = "single"
                    state.status = "Input scope: Slot"
                elif scope_rects[1].collidepoint(mx, my):
                    state.input_scope = "all"
                    state.status = "Input scope: All"

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

                # file paths handlers
                elif gf_link.collidepoint(mx, my):
                    open_text_file(state.greek_file)
                elif ef_link.collidepoint(mx, my):
                    open_text_file(state.english_file)
                elif sp_link.collidepoint(mx, my):
                    open_text_file(state.results_file)

                # Slot selection
                else:
                    for i in range(state.word_length):
                        r = pygame.Rect(sx + i * (slot_w + gap), ty, slot_w, slot_h)
                        if r.collidepoint(mx, my):
                            state.selected_pos = i
                            break

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                dragging = None

            elif event.type == pygame.MOUSEMOTION:
                if dragging == "wl":
                    rel = clamp(event.pos[0] - _S1X, 0, _S1W)
                    nw = int(round(1 + (rel / _S1W) * (MAX_WORD_LENGTH - 1)))
                    if nw != state.word_length:
                        state.word_length = nw
                        state.rebuild_sets()
                        refresh_summary_window()
                elif dragging == "mp":
                    rel = clamp(event.pos[0] - _S2X, 0, _S2W)
                    state.max_preview = int(
                        round(1 + (rel / _S2W) * (MAX_MAX_PREVIEW - 1))
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
                    if state.input_mode == "exist":
                        state.exist_letters.clear()
                    else:
                        for p in target_positions():
                            if 0 <= p < state.word_length:
                                if state.input_mode == "valid":
                                    state.valid_sets[p].clear()
                                else:
                                    state.invalid_sets[p].clear()
                    refresh_summary_window()
                elif event.key == pygame.K_LEFT:
                    if state.word_length > 0:
                        state.selected_pos = (
                            state.selected_pos - 1
                        ) % state.word_length
                elif event.key == pygame.K_RIGHT:
                    if state.word_length > 0:
                        state.selected_pos = (
                            state.selected_pos + 1
                        ) % state.word_length
                elif event.key == pygame.K_UP:
                    cycle_input_mode(-1)
                elif event.key == pygame.K_DOWN:
                    cycle_input_mode(1)
                elif event.key == pygame.K_TAB:
                    state.input_scope = (
                        "all" if state.input_scope == "single" else "single"
                    )
                    state.status = f'Input scope: {"All" if state.input_scope == "all" else "Slot"}'
                elif event.key == pygame.K_SPACE:
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
                    if info_open:
                        close_info_window()
                    else:
                        open_info_window()
                else:
                    ch = event.unicode
                    if len(ch) == 1 and ch.isalpha():
                        if state.input_mode == "exist":
                            add_exist_letter(ch)
                            refresh_summary_window()
                        else:
                            toggle_letter(ch)
                            refresh_summary_window()

    if summary_win is not None and summary_win.winfo_exists():
        summary_win.destroy()
    if info_win is not None and info_win.winfo_exists():
        info_win.destroy()
    if tk_root is not None and tk_root.winfo_exists():
        tk_root.destroy()

    pygame.quit()
    sys.exit()
