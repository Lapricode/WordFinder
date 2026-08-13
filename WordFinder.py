import os
import sys
import json
import math
import unicodedata
from statistics import mean, median, pstdev
import threading
import queue
import pygame
from tkinter import Tk, filedialog
from collections import Counter
import subprocess
from itertools import product
import platform

# ── Translation / meaning backends (lazy-imported, optional) ──────
try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

try:
    import nltk
    from nltk.corpus import wordnet as wn
except Exception:
    nltk = None
    wn = None


# ══════════════════════════════════════════════════════════════════
#  Core filtering logic
# ══════════════════════════════════════════════════════════════════

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


def _pat_matches_inner(word, pat_info, language):
    """Return True if pat_info appears anywhere in the whole word."""
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


def _pat_matches_middle(word, pat_info, language):
    """Return True if pat_info matches strictly inside word, excluding the
    first and last letters."""
    seq = pat_info["seq"]
    expanded = pat_info["expanded"]

    if not seq:
        return True

    # Strictly inside: there must be at least one character before and after
    if len(word) < len(seq) + 2:
        return False

    interior = word[1:-1]
    if not interior:
        return False

    if expanded:
        # reuse the same sequence-matching logic, but only inside the word
        for start in range(0, len(interior) - len(seq) + 1):
            candidate = interior[start : start + len(seq)]
            ok = True
            for ci, ch_pat in enumerate(seq):
                wch = candidate[ci]
                if language == "greek":
                    if GREEK_CHAR_TO_FIRST.get(ch_pat) != GREEK_CHAR_TO_FIRST.get(wch):
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
            if ok:
                return True
        return False

    return seq in interior


def _pat_matches_row(word, pat_info, row_name, language):
    if row_name == "start":
        return _pat_matches_start(word, pat_info, language)
    if row_name == "inner":
        return _pat_matches_inner(word, pat_info, language)
    if row_name == "middle":
        return _pat_matches_middle(word, pat_info, language)
    return _pat_matches_end(word, pat_info, language)


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


def _check_inner_exist(word, exist_pats):
    if not exist_pats:
        return True
    
    interior = word
    if not interior:
        return False

    requirements = Counter()

    for pat in exist_pats:
        variants = tuple(sorted(_exist_variants(pat)))
        if variants:
            requirements[variants] += 1

    for variants, needed_count in requirements.items():
        found = 0
        for variant in variants:
            found += interior.count(variant)

        if found < needed_count:
            return False

    return True


def _check_middle_exist(word, exist_pats):
    if not exist_pats:
        return True

    interior = word[1 : -1]
    if not interior:
        return False

    requirements = Counter()

    for pat in exist_pats:
        variants = tuple(sorted(_exist_variants(pat)))
        if variants:
            requirements[variants] += 1

    for variants, needed_count in requirements.items():
        found = 0
        for variant in variants:
            found += interior.count(variant)

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
    rows = ["start", "inner", "middle", "end"]
    cols = ["valid", "invalid", "exist", "absent"]

    def row_match(word, pat_info, row_name):
        if row_name == "start":
            return _pat_matches_start(word, pat_info, language)
        if row_name == "inner":
            return _pat_matches_inner(word, pat_info, language)
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
            absent_pats = [
                p
                for p in slots_by_cell[row]["absent"][: counts_by_cell[row]["absent"]]
                if p["seq"]
            ]

            # ABSENT constraints: every pattern in the cell must be absent
            # from the row-specific region of the word.
            for pat in absent_pats:
                if _pat_matches_row(word, pat, row, language):
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


def add_absent_letter(letter: str):
    key = exist_key_for_input(letter, state.language)
    if key is None:
        return
    if key in state.absent_letters:
        state.absent_letters.remove(key)
        state.selected_absent_idx = clamp(
            state.selected_absent_idx, 0, max(len(state.absent_letters) - 1, 0)
        )
    else:
        state.absent_letters.append(key)


def delete_absent_item_at(idx):
    if 0 <= idx < len(state.absent_letters):
        del state.absent_letters[idx]
        state.selected_absent_idx = clamp(
            state.selected_absent_idx, 0, max(len(state.absent_letters) - 1, 0)
        )


def handle_text_input(ch: str):
    if not ch or not ch.isalpha():
        return
    if state.finder_mode == "letter_match":
        if state.input_mode in ("valid", "invalid"):
            toggle_letter(ch)
        elif state.input_mode == "exist":
            add_exist_letter(ch)
        elif state.input_mode == "absent":
            add_absent_letter(ch)
    else:
        ph_add_letter(ch)


def handle_backspace_input():
    """Backspace: removes one letter/character at a time (does not clear
    a whole slot). Exist/Absent already operate on discrete list items, so
    Backspace there deletes just the selected item, same as before."""
    if state.finder_mode == "letter_match":
        if state.input_mode == "exist":
            delete_exist_item_at(state.selected_exist_idx)
        elif state.input_mode == "absent":
            delete_absent_item_at(state.selected_absent_idx)
        else:
            backspace_letter_slot()
    else:
        ph_backspace()


def handle_delete_input():
    """Delete: fully clears the targeted slot(s) in one action, for both
    finder modes."""
    if state.finder_mode == "letter_match":
        if state.input_mode == "exist":
            delete_exist_item_at(state.selected_exist_idx)
        elif state.input_mode == "absent":
            delete_absent_item_at(state.selected_absent_idx)
        else:
            clear_letter_slot()
    else:
        ph_clear_slot()


import unicodedata

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
    if state.language == "english":
        return base.upper() if state.keyboard_caps else base.lower()

    ch = base.upper() if state.keyboard_caps else base.lower()
    return greek_tone_variant(ch, state.keyboard_tone)


def _keyboard_rows():
    if state.language == "english":
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
    draw_panel(surface, kb_rect, PANEL2, BORDER, radius=14)

    blit_text(
        surface,
        f"Virtual Keyboard {special_chars['kb']}",
        FONT_SM,
        MUTED,
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
            bg=BLUE_BG,
            fg=TEXT,
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
        bg=RED,
        fg=WHITE,
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
        "Caps on" if state.keyboard_caps else "Caps off",
        bg=ORANGE if state.keyboard_caps else BROWN,
        fg=WHITE,
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
            bg=BLUE_BG,
            fg=TEXT,
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
        tone_labels[state.keyboard_tone],
        bg=PURPLE if state.keyboard_tone else DARK,
        fg=WHITE,
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
        "Greek" if state.language == "greek" else "English",
        bg=CYAN,
        fg=WHITE,
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
                bg=BLUE_BG,
                fg=TEXT,
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
                bg=BLUE_BG,
                fg=TEXT,
                radius=7,
                hovered=r.collidepoint(mouse_pos),
                font=FONT_SM,
            )

    # Store rectangles for mouse handling
    _results_keyboard_rects["panel"] = kb_rect
    _results_keyboard_rects["keys"] = key_rects
    _results_keyboard_rects["controls"] = controls

    return kb_rect.top


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ══════════════════════════════════════════════════════════════════
#  Translation / Meaning backend
#  (adapted from the standalone enrichment scripts the user supplied)
# ══════════════════════════════════════════════════════════════════

_NLTK_READY = False
_TRANSLATOR_CACHE = {}
_meanings_cache = {}  # path -> {"mtime": float, "data": dict}
_results_legend_rects = {"toggle": None, "items": {}}
_results_action_rects = {"show_words": None, "show_stats": None, "keyboard": None}
_results_keyboard_rects = {"panel": None, "keys": [], "controls": {}}
ENRICHMENT_SAVE_EVERY_WORDS = 10  # 1 = save every word, higher = faster


def ensure_nltk_ready():
    """Lazily download wordnet corpora once, only when meanings are requested."""
    global _NLTK_READY
    if _NLTK_READY or nltk is None:
        return
    try:
        nltk.download("wordnet", quiet=True)
        nltk.download("omw-1.4", quiet=True)
        _NLTK_READY = True
    except Exception:
        pass


def normalize_word(word: str) -> str:
    return word.strip().lower()


def translate_text(word: str, source: str, target: str):
    """Generic translate wrapper; returns None on failure."""
    if GoogleTranslator is None:
        return None

    key = (source, target)
    translator = _TRANSLATOR_CACHE.get(key)
    if translator is None:
        translator = GoogleTranslator(source=source, target=target)
        _TRANSLATOR_CACHE[key] = translator

    try:
        return translator.translate(word)
    except Exception:
        return None


def get_greek_translation(word: str) -> str | None:
    return translate_text(word, "en", "el")


def get_english_translation(word: str) -> str | None:
    return translate_text(word, "el", "en")


def clean_translation(source, translation):
    """
    Normalize translations:
    - None / blank -> None
    - identical to source word -> None
    """
    if translation is None:
        return None
    cleaned = str(translation).strip()
    if not cleaned:
        return None
    if normalize_word(cleaned) == normalize_word(source):
        return None
    return cleaned


def build_status(source_word, translation, senses):
    """
    Shared status logic for English and Greek dictionaries.
    Translation identical to the source word is treated as missing.
    Status labels match dictionary_builder.py:
        ok
        no_translation
        no_meaning
        no_translation_no_meaning
    """
    effective_translation = clean_translation(source_word, translation)
    has_translation = bool(effective_translation)
    has_meaning = bool(isinstance(senses, list) and senses)

    if has_translation and has_meaning:
        return "ok"
    if not has_translation and not has_meaning:
        return "no_translation_no_meaning"
    if not has_translation:
        return "no_translation"
    return "no_meaning"


def build_status_en(source_word, senses, greek_translation):
    return build_status(source_word, greek_translation, senses)


def build_status_el(source_word, english_translation, senses=None):
    return build_status(source_word, english_translation, senses or [])


def load_json_dict(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def is_single_word(text: str) -> bool:
    if not text:
        return False
    parts = text.strip().split()
    return len(parts) == 1 and parts[0].isalpha()


def resolve_senses_for_translation(
    english_translation: str | None,
    english_dict: dict,
    english_dict_path: str,
    max_senses: int | None = None,
):
    if not english_translation or not english_translation.strip():
        return [], "no_translation", None

    if not is_single_word(english_translation):
        return (
            [],
            "no_meaning",
            "Translation has multiple words, and cannot match to a single English dictionary entry.",
        )

    key = normalize_word(english_translation)
    existing = english_dict.get(key)

    if existing is not None and existing.get("senses"):
        return existing["senses"], "ok", None

    if existing is not None and "senses" in existing:
        return [], "no_meaning", None

    senses = get_wordnet_senses(english_translation, max_senses)
    greek_translation_back = get_greek_translation(english_translation)

    english_dict[key] = {
        "input_word": english_translation,
        "greek_translation": greek_translation_back,
        "senses": senses,
        "status": build_status_en(word, senses, greek_translation_back),
    }
    save_json_atomic(english_dict_path, english_dict)
    state.results_cache_dirty = True

    if senses:
        return senses, "ok", None
    return [], "no_meaning", None


def enrich_english_word(word, max_senses=None):
    senses = get_wordnet_senses(word, max_senses)
    greek_translation = get_greek_translation(word)
    return {
        "input_word": word,
        "greek_translation": greek_translation,
        "senses": senses,
        "status": build_status_en(word, senses, greek_translation),
    }


def enrich_greek_word(
    word,
    english_dict=None,
    english_dict_path=None,
    max_senses=None,
):
    if english_dict is None or english_dict_path is None:
        english_translation = get_english_translation(word)
        return {
            "input_word": word,
            "english_translation": english_translation,
            "status": build_status_el(word, english_translation),
        }

    english_translation = get_english_translation(word)
    senses, status, note = resolve_senses_for_translation(
        english_translation,
        english_dict,
        english_dict_path,
        max_senses=max_senses,
    )

    entry = {
        "input_word": word,
        "english_translation": english_translation,
        "senses": senses,
        "status": status,
    }
    if note:
        entry["senses_note"] = note
    return entry


def get_wordnet_senses(word: str, max_senses=None):
    """English word -> list of {part_of_speech, definition, examples}."""
    if wn is None:
        return []
    candidates = [
        word.strip(),
        word.strip().lower(),
        word.strip().replace("-", "_"),
        word.strip().lower().replace("-", "_"),
        word.strip().replace(" ", "_"),
        word.strip().lower().replace(" ", "_"),
    ]
    seen = set()
    senses = []
    for candidate in candidates:
        try:
            synsets = wn.synsets(candidate)
        except Exception:
            synsets = []
        for syn in synsets:
            definition = syn.definition().strip()
            examples = [ex.strip() for ex in syn.examples() if ex.strip()]
            sense_key = (syn.pos(), definition)
            if sense_key in seen:
                continue
            seen.add(sense_key)
            senses.append(
                {
                    "part_of_speech": syn.pos(),
                    "definition": definition,
                    "examples": examples,
                }
            )
            if max_senses is not None and len(senses) >= max_senses:
                return senses
        if senses:
            break
    return senses


# ══════════════════════════════════════════════════════════════════
#  Pygame + fonts
# ══════════════════════════════════════════════════════════════════

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


# ─── Layout constants ─────────────────────────────────────────────
MAX_WORD_LENGTH = 35
MAX_MAX_PREVIEW = 100
PAD = 20
GAP = 20

H_HEADER = 65  # taller to fit two-line title
H_CTRL = 90
H_FILES = 80
H_TOP = H_HEADER + H_CTRL + H_FILES

WORKSPACE_Y = H_TOP + PAD
LEFT_LABEL_W = 180

# Review buttons appearance constants
REVIEW_BTN_W = 165
REVIEW_BTN_H = 30
RESULTS_TOP_Y = WORKSPACE_Y + PAD + 170

# How many pattern slots per mode
MAX_PATTERN_SLOTS = 10


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


def _dim_color(color, toward=None, factor=0.45):
    """Blends `color` toward a muted/background tone, used to de-emphasize
    non-hovered chart bars relative to the hovered one."""
    target = toward if toward is not None else PANEL2
    return tuple(
        int(c + (t - c) * factor) for c, t in zip(color[:3], target[:3])
    )


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


def draw_nav_button(
    surface, rect, direction="left", color=None, hovered=False, enabled=True
):
    """Small triangular prev/next navigation button."""
    base = color if color is not None else ACCENT
    bg = lighten(PANEL2, 14) if (hovered and enabled) else PANEL2
    fg = lighten(base) if (hovered and enabled) else (base if enabled else BORDER)

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


# ══════════════════════════════════════════════════════════════════
#  App state
# ══════════════════════════════════════════════════════════════════


def _make_pattern_slot():
    return {"seq": "", "expanded": False}


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
        pygame.draw.rect(surface, PANEL, panel, border_radius=16)
        pygame.draw.rect(surface, ACCENT, panel, 2, border_radius=16)

        PAD_ = 28
        content_x = panel.x + PAD_
        max_w = panel.width - PAD_ * 2
        y = panel.y + PAD_ - int(self._scroll)

        line_spacing = {
            "title": (FONT_XL, TEXT, 14),
            "heading": (FONT_LG, ACCENT, 6),
            "body": (FONT_SM, MUTED, 4),
            "bullet": (FONT_SM, TEXT, 4),
            "footer": (FONT_SM, MUTED, 4),
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
        pygame.draw.rect(surface, PANEL, panel, border_radius=16)
        pygame.draw.rect(surface, ACCENT, panel, 2, border_radius=16)

        PAD_ = 24
        x = panel.x + PAD_
        y = panel.y + PAD_

        blit_text(surface, self.title, FONT_LG, TEXT, x, y)
        y += FONT_LG.get_linesize() + 10

        total = max(1, self.job.total) if self.job else 1
        done = self.job.done_count if self.job else 0
        pct = clamp(done / total, 0, 1)

        bar_w = panel.width - PAD_ * 2
        bar_h = 22
        bar_rect = pygame.Rect(x, y, bar_w, bar_h)
        pygame.draw.rect(surface, PANEL2, bar_rect, border_radius=8)
        fill_w = int(bar_w * pct)
        if fill_w > 0:
            pygame.draw.rect(
                surface, GREEN, pygame.Rect(x, y, fill_w, bar_h), border_radius=8
            )
        pygame.draw.rect(surface, BORDER, bar_rect, 1, border_radius=8)
        pct_label = f"{done} / {total}  ({int(pct * 100)}%)"
        img = FONT_SM.render(pct_label, True, TEXT)
        surface.blit(img, img.get_rect(center=bar_rect.center))
        y += bar_h + 16

        # Log area
        log_rect = pygame.Rect(x, y, bar_w, panel.bottom - y - 60)
        pygame.draw.rect(surface, PANEL2, log_rect, border_radius=8)
        pygame.draw.rect(surface, BORDER, log_rect, 1, border_radius=8)

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
                color = RED
            elif raw_line.startswith(special_chars["[OK]"]):
                color = ACCENT
            else:
                color = MUTED

            for line in self._wrap(raw_line, FONT_SM, log_rect.width - 16):
                if log_rect.y <= ly <= log_rect.bottom:
                    surface.blit(
                        FONT_SM.render(line, True, color), (log_rect.x + 8, ly)
                    )
                ly += line_h

        surface.set_clip(old_clip)

        track, thumb = self._scrollbar_rects(panel)
        if track:
            pygame.draw.rect(surface, PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, BORDER, thumb, border_radius=4)

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
                RED,
                WHITE,
                radius=7,
                hovered=close_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
        elif paused:
            draw_button(
                surface,
                action_btn,
                "Resume",
                PURPLE,
                WHITE,
                radius=7,
                hovered=action_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
            draw_button(
                surface,
                close_btn,
                "Close",
                RED,
                WHITE,
                radius=7,
                hovered=close_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
        else:
            draw_button(
                surface,
                action_btn,
                "Stop",
                ORANGE,
                WHITE,
                radius=7,
                hovered=action_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
            draw_button(
                surface,
                close_btn,
                "Close",
                RED,
                WHITE,
                radius=7,
                hovered=close_btn.collidepoint(mouse_pos),
                font=FONT_MD,
            )
            blit_text(surface, "Working…", FONT_SM, MUTED, panel.x + PAD_, btn_y)

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
            state.status = (
                f"Nothing to edit {special_chars['-']} search results are empty."
            )
            return

        self.visible = True
        self.stage = "manual"
        self.job_kind = job_kind
        self.words = list(words)
        self.word_index = 0
        self.language = state.language
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
            state.english_meanings_file
            if self.language == "english"
            else state.greek_meanings_file
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
        state.status = f"Staged {self.job_kind} for {word} (press Apply to save)"

    def _apply_all(self):
        self._snapshot_current()
        self.apply_items = list(self.drafts.items())
        self.apply_total = len(self.apply_items)
        self.apply_done = 0
        self.applying = bool(self.apply_items)

        if self.applying:
            state.status = f"Applying {self.apply_total} staged edit(s)…"
        else:
            state.status = "Nothing to save."

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
            state.results_cache_dirty = True
            rebuild_results_cache()
            refresh_visible_results()
            state.status = f"Saved {self.apply_done} staged edit(s)"

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
        draw_panel(surface, panel, PANEL, BORDER, radius=16)

        if self.stage == "choice":
            title = "Translation" if self.job_kind == "translation" else "Meaning"
            blit_text(
                surface, f"{title} mode", FONT_LG, TEXT, panel.x + 24, panel.y + 20
            )

            blit_text(
                surface,
                "Choose automatic lookup (Get) or manual entry (Set).",
                FONT_SM,
                MUTED,
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
                bg=TEAL,
                fg=WHITE,
                hovered=set_btn.collidepoint(mouse_pos),
                font=FONT_SM,
            )
            draw_button(
                surface,
                get_btn,
                "Get",
                bg=ORANGE,
                fg=WHITE,
                hovered=get_btn.collidepoint(mouse_pos),
                font=FONT_SM,
            )
            return

        title = (
            "Manual Translation" if self.job_kind == "translation" else "Manual Meaning"
        )
        blit_text(surface, title, FONT_LG, TEXT, panel.x + 24, panel.y + 18)
        blit_text(
            surface,
            "Click the centered list to switch words. Enter stages the current word edits and Apply saves all of them.",
            FONT_SM,
            MUTED,
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
            blit_text(surface, label, FONT_SM, MUTED, left, y - 20)
            r = pygame.Rect(left, y, field_w, height)
            self._rects["fields"][key] = r
            active = self.active_field == key
            draw_panel(
                surface,
                r,
                BLUE_BG if active else PANEL2,
                ACCENT if active else BORDER,
                radius=8,
            )
            text = self.fields.get(key, "")
            txt = fit_text_with_ellipsis(text, FONT_SM, r.width - 24)
            blit_text(surface, txt, FONT_SM, TEXT, r.x + 8, r.centery, anchor="midleft")

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
                        ACCENT,
                        (cursor_x, r.y + 6),
                        (cursor_x, r.bottom - 6),
                        2,
                    )

            if self._field_is_dirty(self._current_word(), key):
                tick = FONT_SM.render(special_chars["[OK]"], True, GREEN)
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
                    bg = GREEN if not is_active else GREEN
                    fg = WHITE
                    border = GREEN_BDR if not is_active else ACCENT
                else:
                    bg = BLUE_BG if is_active else PANEL2
                    fg = TEXT
                    border = ACCENT if is_active else BORDER
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
            pygame.draw.rect(surface, PANEL2, bar_rect, border_radius=8)
            fill_rect = pygame.Rect(
                bar_rect.x, bar_rect.y, int(bar_rect.width * pct), bar_rect.height
            )
            if fill_rect.width > 0:
                pygame.draw.rect(surface, GREEN, fill_rect, border_radius=8)
            pygame.draw.rect(surface, BORDER, bar_rect, 1, border_radius=8)
            blit_text(
                surface,
                f"{self.apply_done}/{self.apply_total}  ({int(100 * self.apply_done / self.apply_total)}%)",
                FONT_SM,
                TEXT,
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
            bg=TEAL if self.applying else GREEN,
            fg=WHITE,
            hovered=apply_btn.collidepoint(mouse_pos) and not self.applying,
            font=FONT_SM,
        )
        draw_button(
            surface,
            close_btn,
            "Close",
            bg=RED,
            fg=WHITE,
            hovered=close_btn.collidepoint(mouse_pos) and not self.applying,
            font=FONT_SM,
        )

        selector = pygame.Rect(panel.centerx - 150, panel.y + 76, 300, 32)
        self._rects["selector"] = selector
        draw_button(
            surface,
            selector,
            fit_text_with_ellipsis(self._current_word(), FONT_SM, selector.width - 20),
            bg=BLUE_BG,
            fg=TEXT,
            hovered=selector.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        if self.picker_open:
            picker = pygame.Rect(
                selector.x, selector.y + 40, selector.w, min(340, panel.height - 130)
            )
            self._rects["picker"] = picker
            draw_panel(surface, picker, PANEL2, BORDER, radius=12)

            for idx, word, r in self._picker_item_rects(picker):
                selected = idx == self.word_index
                hovered = r.collidepoint(mouse_pos)

                fill = BLUE_BG if selected else PANEL
                border = ACCENT if selected else BORDER
                if hovered:
                    fill = lighten(fill, 12)
                    border = lighten(border, 12)

                pygame.draw.rect(surface, fill, r, border_radius=8)
                pygame.draw.rect(surface, border, r, 1, border_radius=8)
                blit_text(
                    surface,
                    fit_text_with_ellipsis(word, FONT_SM, r.width - 28),
                    FONT_SM,
                    TEXT,
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
                    tick = FONT_SM.render(special_chars["[OK]"], True, GREEN)
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

        pygame.draw.rect(surface, PANEL, tip_rect, border_radius=10)
        pygame.draw.rect(surface, ACCENT, tip_rect, 2, border_radius=10)

        ly = tip_rect.y + pad
        for line in lines:
            blit_text(surface, line, FONT_SM, TEXT, tip_rect.x + pad, ly)
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
        draw_panel(surface, panel, PANEL, BORDER, radius=16)

        blit_text(surface, self.title, FONT_LG, TEXT, panel.x + 24, panel.y + 18)
        blit_text(
            surface,
            f"{len(self._filtered_words())} word(s)",
            FONT_SM,
            MUTED,
            panel.x + 24,
            panel.y + 50,
        )

        to_results_btn = pygame.Rect(panel.right - 150, panel.y + 18, 126, 30)
        self._rects["to_results"] = to_results_btn
        draw_button(
            surface,
            to_results_btn,
            f"{special_chars['>']} Results",
            bg=TEAL,
            fg=WHITE,
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
            bg=BLUE_BG,
            fg=TEXT,
            hovered=letter_selector.collidepoint(mouse_pos),
            font=FONT_SM,
        )
        draw_button(
            surface,
            length_selector,
            f"Length: {self.length_filter}",
            bg=BLUE_BG,
            fg=TEXT,
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
            if state.colorize_status:
                bg_color, bdr_color = status_colors(status)
            else:
                bg_color, bdr_color = PANEL2, BORDER

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
                TEXT,
                left_rect.x,
                left_rect.centery,
                anchor="midleft",
            )

            detail_lines = []
            if translation:
                detail_lines.append((f"{special_chars['>']} {translation}", ACCENT))
            if definition:
                detail_lines.append((definition, MUTED))

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
            pygame.draw.rect(surface, PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, BORDER, thumb, border_radius=4)

        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 42, 72, 28)
        self._rects["close"] = close_btn
        draw_button(
            surface,
            close_btn,
            "Close",
            bg=RED,
            fg=WHITE,
            hovered=close_btn.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        if hovered_word is not None:
            lines = [(hovered_word, FONT_MD, TEXT)]

            entry = lookup_word_entry(hovered_word, self.language)

            if state.show_translation:
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
                lines.append((tr_text, FONT_SM, ACCENT))

            if state.show_meaning:
                for ml in format_meaning_lines(entry, self.language):
                    lines.append((ml, FONT_SM, MUTED))

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

                pygame.draw.rect(surface, PANEL, tip_rect, border_radius=10)
                pygame.draw.rect(surface, ACCENT, tip_rect, 2, border_radius=10)

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

            draw_panel(surface, picker, PANEL2, BORDER, radius=12)

            for idx, opt, r in option_rects:
                selected = (
                    (self._picker_kind == "letter" and opt == self.letter_filter)
                    or (self._picker_kind == "length" and opt == self.length_filter)
                )
                hovered = r.collidepoint(mouse_pos)
                fill = BLUE_BG if selected else PANEL
                border = ACCENT if selected else BORDER
                if hovered:
                    fill = lighten(fill, 12)
                    border = lighten(border, 12)

                pygame.draw.rect(surface, fill, r, border_radius=8)
                pygame.draw.rect(surface, border, r, 1, border_radius=8)
                blit_text(
                    surface,
                    str(opt),
                    FONT_SM,
                    TEXT,
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
                state.status = f"Added {added} words. Rejected: {len(rejected)}"
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
        draw_panel(surface, panel, PANEL, BORDER, radius=12)
        blit_text(surface, self.title, FONT_LG, TEXT, panel.x + 20, panel.y + 14)

        # Input field (styled like other modals)
        inp_rect = pygame.Rect(panel.x + 20, panel.y + 64, panel.width - 40, 34)
        active = self.active_field == "input"
        draw_panel(surface, inp_rect, BLUE_BG if active else PANEL2, ACCENT if active else BORDER, radius=8)
        txt = self.input_text if self.input_text else "Type a word and press Enter"
        color = TEXT if self.input_text else MUTED
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
                pygame.draw.line(surface, ACCENT, (cursor_x, inp_rect.y + 6), (cursor_x, inp_rect.bottom - 6), 2)
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
                pygame.draw.rect(surface, BLUE_BG, r, border_radius=8)
                pygame.draw.rect(surface, ACCENT, r, 2, border_radius=8)
            else:
                pygame.draw.rect(surface, PANEL2, r, border_radius=8)
                pygame.draw.rect(surface, BORDER, r, 1, border_radius=8)
            blit_text(surface, w, FONT_SM, TEXT, r.x + 8, r.centery, anchor="midleft")
            # store rect for potential interactions/hover lookup
            self._rects[f"item_{i}"] = r
            y += row_stride
        surface.set_clip(old_clip)

        # Scrollbar
        if total_h > list_h:
            track = pygame.Rect(panel.right - 28, list_top + 2, 8, list_h - 4)
            pygame.draw.rect(surface, PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, BORDER, track, 1, border_radius=4)
            ratio = list_h / total_h
            thumb_h = max(20, int(track.height * ratio))
            thumb_y = track.y + int((track.height - thumb_h) * (self._scroll / max(1, self._max_scroll)))
            thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_h)
            pygame.draw.rect(surface, ACCENT, thumb, border_radius=4)
            # store scrollbar rects for interaction
            self._rects["_sb_track"] = track
            self._rects["_sb_thumb"] = thumb

        # Buttons
        apply_btn = pygame.Rect(panel.x + 20, panel.bottom - 48, 120, 32)
        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 48, 72, 32)
        self._rects["apply"] = apply_btn
        self._rects["close"] = close_btn
        draw_button(surface, apply_btn, "Apply", bg=TEAL, fg=WHITE, hovered=apply_btn.collidepoint(mouse_pos), font=FONT_SM)
        draw_button(surface, close_btn, "Close", bg=RED, fg=WHITE, hovered=close_btn.collidepoint(mouse_pos), font=FONT_SM)


def is_english_letters_only(word: str) -> bool:
    if not word:
        return False
    allowed = {chr(c) for c in range(ord("a"), ord("z") + 1)}
    allowed |= {ch.upper() for ch in allowed}
    return all(ch in allowed for ch in word)


def is_greek_letters_only(word: str) -> bool:
    if not word:
        return False
    # Build allowed greek characters from GREEK_GROUPS
    allowed = set()
    for g in GREEK_GROUPS:
        for ch in g:
            allowed.add(ch)
    return all(ch in allowed for ch in word)


def add_words_to_file(path, words, language):
    """Add validated words to text file at path; return (added_count, rejected_list)"""
    if not path:
        return 0, list(words)
    try:
        existing = set(load_words(path))
    except Exception:
        existing = set()

    to_add = []
    rejected = []
    for w in words:
        if not w:
            continue
        # basic normalization
        ww = w.strip()
        if language == "english":
            if not is_english_letters_only(ww):
                rejected.append(ww)
                continue
            if ww.isupper():
                ww = ww.lower()
        elif language == "greek":
            if not is_greek_letters_only(ww):
                rejected.append(ww)
                continue
        else:
            # both: accept either english or greek
            if is_english_letters_only(ww):
                if ww.isupper():
                    ww = ww.lower()
            elif not is_greek_letters_only(ww):
                rejected.append(ww)
                continue

        if ww not in existing:
            existing.add(ww)
            to_add.append(ww)

    # write back sorted (case-insensitive)
    try:
        with open(path, "w", encoding="utf-8") as f:
            for w in sorted(existing, key=str.lower):
                f.write(w + "\n")
    except Exception:
        # on error, consider all as rejected
        return 0, words

    return len(to_add), rejected


def delete_words_from_file(path, words_to_delete):
    if not path:
        return 0
    try:
        existing = list(load_words(path))
    except Exception:
        existing = []
    s = set(existing)
    removed = 0
    for w in words_to_delete:
        if w in s:
            s.remove(w)
            removed += 1
    try:
        with open(path, "w", encoding="utf-8") as f:
            for w in sorted(s, key=str.lower):
                f.write(w + "\n")
    except Exception:
        return 0
    return removed


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
                state.status = f"Deleted {deleted} words"
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
            "greek": getattr(state, "greek_file", None),
            "english": getattr(state, "english_file", None),
            "results": getattr(state, "results_file", None),
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
        draw_panel(surface, panel, PANEL, BORDER, radius=12)
        blit_text(surface, self.title, FONT_LG, TEXT, panel.x + 20, panel.y + 14)

        # Search field (styled like other input fields)
        inp_rect = pygame.Rect(panel.x + 20, panel.y + 64, panel.width - 40, 34)
        active = self.active_field == "search"
        draw_panel(surface, inp_rect, BLUE_BG if active else PANEL2, ACCENT if active else BORDER, radius=8)
        txt = self.search_text if self.search_text else "Type sequence and press Enter"
        color = TEXT if self.search_text else MUTED
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
                pygame.draw.line(surface, ACCENT, (cursor_x, inp_rect.y + 6), (cursor_x, inp_rect.bottom - 6), 2)
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
                bg_color, bdr_color = RED_BG, RED_BDR
                # if hovered while selected, slightly change border
                if hovered:
                    pygame.draw.rect(surface, bg_color, r, border_radius=8)
                    pygame.draw.rect(surface, DARK, r, 2, border_radius=8)
                else:
                    pygame.draw.rect(surface, bg_color, r, border_radius=8)
                    pygame.draw.rect(surface, bdr_color, r, 1, border_radius=8)
                blit_text(surface, w, FONT_SM, TEXT, r.x + 8, r.centery, anchor="midleft")
                m = FONT_SM.render(special_chars["X"], True, TEXT)
                surface.blit(m, m.get_rect(midright=(r.right - 8, r.centery)))
            else:
                # normal row, show hover highlight
                if hovered:
                    pygame.draw.rect(surface, BLUE_BG, r, border_radius=8)
                    pygame.draw.rect(surface, ACCENT, r, 2, border_radius=8)
                else:
                    pygame.draw.rect(surface, PANEL2, r, border_radius=8)
                    pygame.draw.rect(surface, BORDER, r, 1, border_radius=8)
                blit_text(surface, w, FONT_SM, TEXT, r.x + 8, r.centery, anchor="midleft")
            # store rect for interaction/hover
            self._rects[f"match_{idx}"] = r
            y += row_stride
        surface.set_clip(old_clip)

        # Scrollbar
        if total_h > list_h:
            track = pygame.Rect(panel.right - 28, list_top + 2, 8, list_h - 4)
            pygame.draw.rect(surface, PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, BORDER, track, 1, border_radius=4)
            ratio = list_h / total_h
            thumb_h = max(20, int(track.height * ratio))
            thumb_y = track.y + int((track.height - thumb_h) * (self._scroll / max(1, self._max_scroll)))
            thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_h)
            pygame.draw.rect(surface, ACCENT, thumb, border_radius=4)
            self._rects["_sb_track"] = track
            self._rects["_sb_thumb"] = thumb

        # Buttons
        apply_btn = pygame.Rect(panel.x + 20, panel.bottom - 48, 120, 32)
        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 48, 72, 32)
        self._rects["apply"] = apply_btn
        self._rects["close"] = close_btn
        draw_button(surface, apply_btn, "Apply", bg=TEAL, fg=WHITE, hovered=apply_btn.collidepoint(mouse_pos), font=FONT_SM)
        draw_button(surface, close_btn, "Close", bg=RED, fg=WHITE, hovered=close_btn.collidepoint(mouse_pos), font=FONT_SM)


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
                MUTED,
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
                val_img = FONT_SM.render(str(val), True, TEXT)
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
                    fill, border = ACCENT, BORDER
                elif is_hover:
                    fill, border = lighten(ACCENT, 25), TEXT
                else:
                    fill, border = _dim_color(ACCENT), _dim_color(BORDER)

                draw_bar = bar.inflate(2, 2) if is_hover else bar
                pygame.draw.rect(surface, fill, draw_bar, border_radius=6)
                pygame.draw.rect(surface, border, draw_bar, 1, border_radius=6)

                val_color = TEXT if (hovered_idx is None or is_hover) else MUTED
                blit_text(
                    surface,
                    str(val),
                    FONT_SM,
                    val_color,
                    bar.centerx,
                    bar.y - 3,
                    anchor="midbottom",
                )

                lbl_color = TEXT if (hovered_idx is None or is_hover) else MUTED
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
                val_img = FONT_SM.render(str(val), True, TEXT)
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
                    fill, border = ACCENT, BORDER
                elif is_hover:
                    fill, border = lighten(ACCENT, 25), TEXT
                else:
                    fill, border = _dim_color(ACCENT), _dim_color(BORDER)

                lbl_color = TEXT if (hovered_idx is None or is_hover) else MUTED
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

                val_color = TEXT if (hovered_idx is None or is_hover) else MUTED
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
        draw_panel(surface, panel, PANEL, BORDER, radius=16)

        title_rect = blit_text(surface, "Show Statistics", FONT_LG, TEXT, panel.x + 24, panel.y + 18)

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
            bg=BLUE_BG,
            fg=TEXT,
            hovered=stat_selector.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        draw_button(
            surface,
            orient_btn,
            self.chart_orientation.title(),
            bg=TEAL,
            fg=WHITE,
            hovered=orient_btn.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        draw_button(
            surface,
            sort_btn,
            self.sort_order.title(),
            bg=PURPLE,
            fg=WHITE,
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
                bg=BLUE_BG,
                fg=TEXT,
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
                bg=BLUE_BG,
                fg=WHITE,
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
        subtitle_rect = blit_text(surface, subtitle, FONT_SM, TEXT, panel.x + 24, panel.y + 50)
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
        blit_text(surface, summary_text, FONT_SM, MUTED, panel.x + 24, panel.bottom - 36)

        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 42, 72, 28)
        self._rects["close"] = close_btn
        draw_button(
            surface,
            close_btn,
            "Close",
            bg=RED,
            fg=WHITE,
            hovered=close_btn.collidepoint(mouse_pos),
            font=FONT_SM,
        )

        # Draw dropdowns last so they stay above the graph and footer widgets.
        if self._picker_open:
            picker = pygame.Rect(stat_selector.x, stat_selector.bottom + 6, stat_selector_w, 300)
            self._rects["picker"] = picker
            draw_panel(surface, picker, PANEL2, BORDER, radius=12)

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
                fill = BLUE_BG if key == self.stat_key else PANEL
                border = ACCENT if key == self.stat_key else BORDER
                hovered = r.collidepoint(mouse_pos)
                if hovered:
                    fill = lighten(fill, 12)
                    border = lighten(border, 12)

                pygame.draw.rect(surface, fill, r, border_radius=8)
                pygame.draw.rect(surface, border, r, 1, border_radius=8)
                blit_text(surface, label, FONT_SM, TEXT, r.x + 10, r.centery, anchor="midleft")
            self._rects["picker_items"] = items

        if self._sort_picker_open:
            picker = pygame.Rect(sort_btn.x, sort_btn.bottom + 6, sort_btn.width, 120)
            self._rects["sort_picker"] = picker
            draw_panel(surface, picker, PANEL2, BORDER, radius=12)

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
                fill = BLUE_BG if key == self.sort_order else PANEL
                border = ACCENT if key == self.sort_order else BORDER
                hovered = r.collidepoint(mouse_pos)
                if hovered:
                    fill = lighten(fill, 12)
                    border = lighten(border, 12)
                pygame.draw.rect(surface, fill, r, border_radius=8)
                pygame.draw.rect(surface, border, r, 1, border_radius=8)
                blit_text(surface, label, FONT_SM, TEXT, r.x + 10, r.centery, anchor="midleft")
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
        draw_panel(surface, panel, PANEL, ACCENT, radius=16)

        blit_text(surface, self._title(), FONT_LG, TEXT, panel.x + 22, panel.y + 18)

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
            color = ACCENT if is_header else TEXT
            font = FONT_MD if is_header else FONT_SM
            for line in self._wrap(text, FONT_SM, content.width):
                if content.y - line_h <= y <= content.bottom:
                    surface.blit(font.render(line, True, color), (content.x, y))
                y += line_h

        surface.set_clip(old_clip)

        track, thumb = self._scrollbar_rects(panel)
        self._scroll = max(0, min(self._max_scroll_cache, self._scroll))
        if track:
            pygame.draw.rect(surface, PANEL2, track, border_radius=4)
            pygame.draw.rect(surface, BORDER, thumb, border_radius=4)

        copy_btn = pygame.Rect(panel.x + 22, panel.bottom - 42, 110, 28)
        self._rects["copy"] = copy_btn
        copy_label = "Copied!" if self._copied_flash > 0 else "Copy"
        draw_button(
            surface, copy_btn, copy_label,
            bg=GREEN if self._copied_flash > 0 else TEAL, fg=WHITE,
            hovered=copy_btn.collidepoint(mouse_pos), font=FONT_SM,
        )

        close_btn = pygame.Rect(panel.right - 96, panel.bottom - 42, 72, 28)
        self._rects["close"] = close_btn
        draw_button(
            surface, close_btn, "Close", bg=RED, fg=WHITE,
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


# ══════════════════════════════════════════════════════════════════
#  Background enrichment worker (runs in a thread, reports via queue)
# ══════════════════════════════════════════════════════════════════


def build_enrichment_entry(job_kind, language, word, existing):
    """
    Translation jobs only fetch translation.
    Meaning jobs only fetch meaning.
    Existing fields that are not being updated are preserved.
    """
    entry = dict(existing or {})
    entry["input_word"] = word

    if language == "english":
        if job_kind == "translation":
            # Always fetch a fresh translation, even if a manual one exists.
            greek_translation = get_greek_translation(word)

            senses = entry.get("senses")
            if not isinstance(senses, list):
                senses = []

            entry["greek_translation"] = greek_translation
            entry["senses"] = senses
            entry["status"] = build_status(word, greek_translation, senses)
            return entry

        # Always fetch fresh WordNet senses, even if manual senses exist.
        senses = get_wordnet_senses(word)

        greek_translation = entry.get("greek_translation")
        entry["greek_translation"] = greek_translation
        entry["senses"] = senses
        entry["status"] = build_status(word, greek_translation, senses)
        return entry

    if job_kind == "translation":
        # Always fetch a fresh translation, even if a manual one exists.
        english_translation = get_english_translation(word)

        senses = entry.get("senses")
        if not isinstance(senses, list):
            senses = []

        entry["english_translation"] = english_translation
        entry["senses"] = senses
        entry["status"] = build_status(word, english_translation, senses)
        return entry

    english_translation = entry.get("english_translation")
    if english_translation:
        senses = get_wordnet_senses(english_translation)
    else:
        senses = []

    entry["english_translation"] = english_translation
    entry["senses"] = senses
    entry["status"] = build_status(word, english_translation, senses)
    return entry


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
    pygame.draw.rect(surface, PANEL2, track, border_radius=6)
    pygame.draw.rect(surface, BORDER, track, 1, border_radius=6)

    fill = pygame.Rect(bar_x, bar_y, int(bar_w * pct), bar_h)
    if fill.width > 0:
        pygame.draw.rect(surface, GREEN, fill, border_radius=6)

    label = f"Searching… {int(pct * 100)}%"
    img = FONT_SM.render(label, True, TEXT)
    surface.blit(img, img.get_rect(center=track.center))

    return bar_h + 12


class AppState:
    def __init__(self):
        self.lm_word_length = 5  # Letter Match's word length
        self.ph_word_length = 5  # Pattern Hunt's word length (used when not "All")
        self.max_preview = MAX_MAX_PREVIEW // 4
        self.preview_start = 0
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


# ══════════════════════════════════════════════════════════════════
#  File dialogs & Tk windows
# ══════════════════════════════════════════════════════════════════

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
        f"Backspace = Erase last  {special_chars["*"]}  Delete = Clear slot  {special_chars["*"]}  (Shift +) {special_chars["<"]} {special_chars[">"]} = Navigate  {special_chars["*"]}  {special_chars["^"]} {special_chars["v"]} = Mode"
        f"  {special_chars["*"]}  Tab = Letter Match/Pattern Hunt  {special_chars["*"]}  Shift+Space = Slot/All  {special_chars["*"]}  Ctrl+Space = Expand (PH)"
    )
    hints2 = (
        f"/ = Greek/English  {special_chars["*"]}  Ctrl+S = Save  {special_chars["*"]}  Page Up/Down = Scroll  {special_chars["*"]}  Shift+/- = Word length  {special_chars["*"]}  Ctrl+/- = Max preview"
        f"  {special_chars["*"]}  +/- = Add/remove PH slot  {special_chars["*"]}  Ctrl+I = Info  {special_chars["*"]}  Enter = Search"
    )
    blit_text(
        screen, hints1, FONT_SM, MUTED, PAD + 200, H_HEADER * 0.28, anchor="midleft"
    )
    blit_text(
        screen, hints2, FONT_SM, MUTED, PAD + 200, H_HEADER * 0.70, anchor="midleft"
    )

    r = 0.25 * H_HEADER
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
    pygame.draw.rect(screen, PANEL2, (0, y0, WIDTH, H_CTRL))
    pygame.draw.line(screen, BORDER, (0, y0 + H_CTRL), (WIDTH, y0 + H_CTRL))

    btn_h = 0.6 * H_CTRL

    # ── Column widths (fixed) ──────────────────────────────────────
    finder_btn_w = 150
    slider_col_w = 300
    mode_w = 300
    scope_w = 200
    lang_w = 200
    search_w = 180
    col_widths = [finder_btn_w, slider_col_w, mode_w, scope_w, lang_w, search_w]

    if sum(col_widths) > WIDTH:
        width_surplus = sum(col_widths) - WIDTH
        width_remove = (width_surplus + 100) / len(col_widths)
        finder_btn_w -= width_remove
        slider_col_w -= width_remove
        mode_w -= width_remove
        scope_w -= width_remove
        lang_w -= width_remove
        search_w -= width_remove
        col_widths = [finder_btn_w, slider_col_w, mode_w, scope_w, lang_w, search_w]

    xs = distribute_columns(WIDTH, PAD, PAD, col_widths)
    finder_x, slider_x, mode_x, scope_x, lang_x, search_x = xs

    # Two stacked rows inside the same 80px header
    pill_h = 0.4 * H_CTRL
    pill_y_default = y0 + (H_CTRL - pill_h) / 2
    if state.finder_mode == "letter_match":
        pill_y_top = y0 + (H_CTRL - pill_h) / 2
    elif state.finder_mode == "pattern_hunt":
        pill_y_top = y0 + (H_CTRL / 2 - pill_h) / 2
        pill_y_bottom = y0 + H_CTRL / 2 + (H_CTRL / 2 - pill_h) / 2

    # ── Finder Mode Button ──────────────────────────────────────────
    finder_btn_rect = pygame.Rect(
        finder_x, y0 + (H_CTRL - btn_h) / 2, finder_btn_w, btn_h
    )
    finder_lbl = (
        "Letter Match" if state.finder_mode == "letter_match" else "Pattern Hunt"
    )
    draw_button(
        screen,
        finder_btn_rect,
        finder_lbl,
        RED,
        WHITE,
        radius=8,
        hovered=finder_btn_rect.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    # ── Sliders (stacked within the slider column) ───────────────────
    sl_w = slider_col_w
    cy1 = y0 + 0.05 * H_FILES
    cy2 = y0 + H_CTRL / 2

    is_all = state.finder_mode == "pattern_hunt" and state.ph_word_length_all
    active_word_length = (
        state.ph_word_length
        if state.finder_mode == "pattern_hunt"
        else state.lm_word_length
    )
    t1, k1 = draw_slider(
        screen,
        slider_x,
        cy1,
        sl_w,
        1,
        MAX_WORD_LENGTH,
        active_word_length,
        "Word length",
        show_all_marker=(state.finder_mode == "pattern_hunt"),
        is_all=is_all,
    )
    t2, k2 = draw_slider(
        screen,
        slider_x,
        cy2,
        sl_w,
        1,
        MAX_MAX_PREVIEW,
        state.max_preview,
        "Max preview",
    )

    # ── Main mode pill toggle ───────────────────────────────────────
    if state.finder_mode == "letter_match":
        mode_labels = ["Valid", "Invalid", "Exist", "Absent"]
        mode_colors = [GREEN, RED, BROWN, ORANGE]
        mode_idx = {
            "valid": 0,
            "invalid": 1,
            "exist": 2,
            "absent": 3,
        }[state.input_mode]
    else:
        mode_labels = ["Start", "Inner", "Middle", "End"]
        mode_colors = [TEAL, CYAN, PURPLE, PINK]
        mode_idx = {
            "start": 0,
            "inner": 1,
            "middle": 2,
            "end": 3,
        }[state.ph_mode]

    m_rect = pygame.Rect(mode_x, pill_y_top, mode_w, pill_h)
    m_rects = draw_pill_toggle(
        screen,
        m_rect,
        mode_labels,
        mode_idx,
        mode_colors,
        hovered=m_rect.collidepoint(mouse_pos),
    )

    # ── Pattern Hunt secondary column toggle, stacked directly below ──
    ph_col_rects = None
    if state.finder_mode == "pattern_hunt":
        ph_col_rect = pygame.Rect(mode_x, pill_y_bottom, mode_w, pill_h)
        ph_col_labels = ["Valid", "Invalid", "Exist", "Absent"]
        ph_col_colors = [GREEN, RED, BROWN, ORANGE]
        ph_col_idx = {
            "valid": 0,
            "invalid": 1,
            "exist": 2,
            "absent": 3,
        }[state.ph_col]
        ph_col_rects = draw_pill_toggle(
            screen,
            ph_col_rect,
            ph_col_labels,
            ph_col_idx,
            ph_col_colors,
            hovered=ph_col_rect.collidepoint(mouse_pos),
        )

    # ── Scope pill toggle (Slot / All) ────────────────────────────
    scope_rect = pygame.Rect(scope_x, pill_y_default, scope_w, pill_h)
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
    lang_rect = pygame.Rect(lang_x, pill_y_default, lang_w, pill_h)
    lang_rects = draw_pill_toggle(
        screen,
        lang_rect,
        ["Greek", "English"],
        0 if state.language == "greek" else 1,
        [CYAN, CYAN],
        hovered=lang_rect.collidepoint(mouse_pos),
    )

    # ── Search button ─────────────────────────────────────────────
    search_rect = pygame.Rect(search_x, y0 + (H_CTRL - btn_h) / 2, search_w, btn_h)
    draw_button(
        screen,
        search_rect,
        f"Search",
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
        ph_col_rects,
    )


def render_file_row(mouse_pos):
    y0 = H_HEADER + H_CTRL
    pygame.draw.rect(screen, BG, (0, y0, WIDTH, H_FILES))
    pygame.draw.line(screen, BORDER, (0, y0 + H_FILES), (WIDTH, y0 + H_FILES))

    by = y0 + (H_FILES - 40) / 2
    bh = 0.5 * H_FILES  # file unit button height
    BW = 90
    unit_w = BW + 6 + 126  # button + gap + label/path area, used only for spacing math

    def file_unit(x, label, path, count):
        br = pygame.Rect(x, by, BW, bh)
        tx = x + BW + 6
        path_img = LINK_FONT_SM.render(short_path(path), True, ACCENT)
        path_rect = path_img.get_rect(topleft=(tx, by + 2))
        screen.blit(path_img, path_rect)
        # plus/minus buttons under the path, left of the count (Pattern Hunt style)
        btn_size = 14
        plus_rect = pygame.Rect(tx, by + 22, btn_size, btn_size)
        minus_rect = pygame.Rect(tx + btn_size + 6, by + 22, btn_size, btn_size)

        plus_hover = plus_rect.collidepoint(mouse_pos)
        minus_hover = minus_rect.collidepoint(mouse_pos)

        pygame.draw.rect(
            screen,
            lighten(GREEN_BG, 18) if plus_hover else GREEN_BG,
            plus_rect,
            border_radius=4,
        )
        pygame.draw.rect(screen, GREEN_BDR, plus_rect, 1, border_radius=4)
        blit_text(screen, "+", FONT_SM, GREEN, plus_rect.centerx, plus_rect.centery, anchor="center")

        pygame.draw.rect(
            screen,
            lighten(RED_BG, 18) if minus_hover else RED_BG,
            minus_rect,
            border_radius=4,
        )
        pygame.draw.rect(screen, RED_BDR, minus_rect, 1, border_radius=4)
        blit_text(screen, "-", FONT_SM, RED, minus_rect.centerx, minus_rect.centery, anchor="center")

        blit_text(
            screen, f"{count} words", FONT_SM, MUTED, tx + btn_size * 2 + 12, by + 20, anchor="topleft"
        )
        hover_rect = pygame.Rect(tx, by, 126, 36)

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

        if hover_rect.collidepoint(mouse_pos) and path:
            tip_img = FONT_SM.render(path, True, WHITE)
            tip_pad = 6
            tip_rect = tip_img.get_rect(topleft=(mouse_pos[0] + 14, mouse_pos[1] + 14))
            tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
            if tip_rect.right > WIDTH - PAD:
                tip_rect.right = mouse_pos[0] - 14
            pygame.draw.rect(screen, DARK, tip_rect, border_radius=6)
            pygame.draw.rect(screen, BORDER, tip_rect, 1, border_radius=6)
            screen.blit(tip_img, tip_img.get_rect(center=tip_rect.center))

        return br, path_rect, plus_rect, minus_rect

    # ── Column widths for equal spacing across the whole row ──
    action_col_w = 150
    theme_w = 100
    save_w = 130
    col_widths = [unit_w, unit_w, unit_w, action_col_w, action_col_w, save_w, theme_w]

    if sum(col_widths) > WIDTH:
        width_surplus = sum(col_widths) - WIDTH
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

    xs = distribute_columns(WIDTH, PAD, PAD, col_widths)
    greek_x, english_x, saveto_x, translate_x, meaning_x, save_x, theme_x = xs

    # ── Show translation / Show meaning stacked sections ─────────────
    chk_size = 0.3 * H_FILES
    action_btn_h = 0.4 * H_FILES
    chk_y = y0 + 0.1 * H_FILES
    btn_y = y0 + H_FILES / 2

    def draw_checkbox(x, y, checked, label):
        box = pygame.Rect(x, y, chk_size, chk_size)
        pygame.draw.rect(
            screen, (GREEN_BG if checked else PANEL2), box, border_radius=4
        )
        pygame.draw.rect(
            screen, (GREEN if checked else BORDER), box, 2, border_radius=4
        )
        if checked:
            img = FONT_LG.render(special_chars["[OK]"], True, GREEN)
            screen.blit(img, img.get_rect(center=box.center))
        lbl_img = FONT_SM.render(label, True, TEXT)
        screen.blit(lbl_img, lbl_img.get_rect(midleft=(box.right + 8, box.centery)))
        return box

    translate_chk_rect = draw_checkbox(
        translate_x, chk_y, state.show_translation, "Show Translation"
    )
    meaning_chk_rect = draw_checkbox(
        meaning_x, chk_y, state.show_meaning, "Show Meaning"
    )

    translate_btn = pygame.Rect(translate_x, btn_y, action_col_w + 10, action_btn_h)
    meaning_btn = pygame.Rect(meaning_x, btn_y, action_col_w - 10, action_btn_h)

    draw_button(
        screen,
        translate_btn,
        f"Translation {special_chars['<>']}",
        PURPLE,
        WHITE,
        radius=7,
        hovered=translate_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )
    draw_button(
        screen,
        meaning_btn,
        f"Meaning {special_chars['?']}",
        PURPLE,
        WHITE,
        radius=7,
        hovered=meaning_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    # ── Theme + Save (right side) ───────────────────────────────────
    btn_h2 = 0.6 * H_FILES
    btn_y2 = by + (40 - btn_h2) / 2

    sv_btn = pygame.Rect(save_x, btn_y2, save_w, btn_h2)
    draw_button(
        screen,
        sv_btn,
        "Save",
        PURPLE,
        WHITE,
        hovered=sv_btn.collidepoint(mouse_pos),
        font=FONT_LG,
    )

    theme_btn = pygame.Rect(theme_x, btn_y2, theme_w, btn_h2)
    theme_label = "Light" if state.theme == "light" else "Dark"
    draw_button(
        screen,
        theme_btn,
        theme_label,
        ACCENT,
        WHITE,
        radius=7,
        hovered=theme_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    # ── Show Files buttons and paths ─────────────

    sp_btn, sp_link, sp_plus, sp_minus = file_unit(
        saveto_x, "Save to", state.results_file, state.results_count
    )
    ef_btn, ef_link, ef_plus, ef_minus = file_unit(
        english_x, "English", state.english_file, state.english_count
    )
    gf_btn, gf_link, gf_plus, gf_minus = file_unit(greek_x, "Greek", state.greek_file, state.greek_count)

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
    return f"  {special_chars["*"]}  ".join(parts) if parts else f"{special_chars["-"]}"


def render_workspace_lm(mouse_pos):
    """Letter Match workspace. Returns (slot_w, slot_h, sx, ty, gap, table_bottom_y, summary_btn, lm_ui)."""
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
    if state.input_mode == "valid":
        mc = GREEN
    if state.input_mode == "invalid":
        mc = RED
    if state.input_mode == "exist":
        mc = BROWN
    if state.input_mode == "absent":
        mc = ORANGE
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
    hover_text = None
    hover_pos = None

    lm_ui = {
        "valid_cells": [],  # list of (position_index, rect)
        "invalid_cells": [],  # list of (position_index, rect)
        "exist_chips": [],  # list of (exist_index, rect)
        "exist_row": None,  # whole-row rect, clickable even with no chips
    }

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
                display_letters or f"{special_chars["-"]}",
                True,
                TEXT if letters else MUTED,
            )
            screen.blit(img, img.get_rect(center=cell.center))

            lm_ui[f"{mode_str}_cells"].append((i, cell))

            if cell.collidepoint(mouse_pos):
                letters_full = "".join(sorted(sets[i])) or f"{special_chars["-"]}"
                hover_text = f"{label} slot {i + 1}: {letters_full}"
                hover_pos = mouse_pos
        table_y += row_h + 6

    # ── Exist + Absent rows ─────────────────────────────────────────
    exist_items = state.get_exist_items()
    absent_items = state.get_absent_letters()

    exist_row_h = row_h
    half_w = (WIDTH - 3 * PAD) // 2
    exist_rect = pygame.Rect(PAD, table_y, half_w, exist_row_h)
    absent_rect = pygame.Rect(exist_rect.right + PAD, table_y, half_w, exist_row_h)

    lm_ui["exist_row"] = exist_rect
    lm_ui["absent_row"] = absent_rect
    lm_ui["exist_chips"] = []
    lm_ui["absent_chips"] = []

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

    # Highlight Absent row when mode is "absent"
    if state.input_mode == "absent":
        absent_bdr_col = ORANGE
        absent_bdr_w = 3
    else:
        absent_bdr_col = ORANGE_BDR if "ORANGE_BDR" in globals() else BORDER
        absent_bdr_w = 1

    pygame.draw.rect(screen, ORANGE_BG, absent_rect, border_radius=8)
    pygame.draw.rect(screen, absent_bdr_col, absent_rect, absent_bdr_w, border_radius=8)
    blit_text(screen, "ABSENT", FONT_MD, ORANGE, absent_rect.x + 6, table_y + exist_row_h // 2 - 10)

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

            lm_ui["exist_chips"].append((ei, chip_rect))

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
            if chip_x > exist_rect.right - 100:
                break
    else:
        img = FONT_SM.render(f"{special_chars["-"]}", True, MUTED)
        screen.blit(img, img.get_rect(midleft=(PAD + 90, table_y + exist_row_h // 2)))

    if absent_items:
        chip_x = absent_rect.x + 90
        chip_gap = 8
        chip_y = table_y + 4
        chip_h = exist_row_h - 8
        absent_rects_local = []

        for ai, key in absent_items:
            if state.language == "greek":
                group = GREEK_GROUP_BY_FIRST.get(key, (key,))
            else:
                group = ENGLISH_GROUP_BY_FIRST.get(key, (key,))
            label = "".join(group)
            disp = label

            tw_chip = FONT_SM.size(disp)[0] + 16
            chip_rect = pygame.Rect(chip_x, chip_y, tw_chip, chip_h)
            lm_ui["absent_chips"].append((ai, chip_rect))

            is_sel = state.input_mode == "absent" and ai == state.selected_absent_idx
            chip_bg = ORANGE_BDR if is_sel else ORANGE_BG
            chip_bdr = ORANGE if is_sel else ORANGE_BDR
            chip_bdr_w = 2 if is_sel else 1

            pygame.draw.rect(screen, chip_bg, chip_rect, border_radius=6)
            pygame.draw.rect(screen, chip_bdr, chip_rect, chip_bdr_w, border_radius=6)
            img = FONT_SM.render(disp, True, ORANGE if is_sel else TEXT)
            screen.blit(img, img.get_rect(midleft=(chip_x + 8, chip_y + chip_h // 2)))

            if chip_rect.collidepoint(mouse_pos):
                hover_text = f"Absent: {disp}"
                hover_pos = mouse_pos

            absent_rects_local.append(chip_rect)
            chip_x += tw_chip + chip_gap
            if chip_x > absent_rect.right - 100:
                break
    else:
        img = FONT_SM.render(f"{special_chars['-']}", True, MUTED)
        screen.blit(img, img.get_rect(midleft=(absent_rect.x + 90, table_y + exist_row_h // 2)))

    table_y += exist_row_h + 6

    if hover_text:
        tip_font = FONT_SM
        tip_img = tip_font.render(hover_text, True, WHITE)
        tip_pad = 8
        tip_rect = tip_img.get_rect(topleft=(hover_pos[0] + 16, hover_pos[1] + 16))
        tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
        if tip_rect.right > WIDTH - PAD:
            tip_rect.right = WIDTH - PAD
        if tip_rect.bottom > HEIGHT - PAD:
            tip_rect.bottom = HEIGHT - PAD
        if tip_rect.left < PAD:
            tip_rect.left = PAD
        if tip_rect.top < PAD:
            tip_rect.top = PAD
        pygame.draw.rect(screen, DARK, tip_rect, border_radius=8)
        pygame.draw.rect(screen, BORDER, tip_rect, 1, border_radius=8)
        screen.blit(tip_img, tip_img.get_rect(center=tip_rect.center))

    return slot_w, slot_h, sx, ty, gap, RESULTS_TOP_Y, summary_btn, lm_ui


# ─── Pattern Hunt workspace ───────────────────────────────────────


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
        screen,
        summary_btn,
        "Patterns Review",
        DARK,
        WHITE,
        radius=7,
        hovered=summary_btn.collidepoint(mouse_pos),
        font=FONT_MD,
    )

    col_labels = ["Valid", "Invalid", "Exist", "Absent"]
    col_colors = [GREEN, RED, BROWN, ORANGE]
    col_bg = [GREEN_BG, RED_BG, BROWN_BG, BROWN_BG]
    row_labels = ["Start", "Inner", "Middle", "End"]
    row_colors = [TEAL, CYAN, PURPLE, PINK]

    grid_left = PAD + LEFT_LABEL_W
    grid_right = WIDTH - PAD
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

            plus_hover = plus_r.collidepoint(mouse_pos)
            minus_hover = minus_r.collidepoint(mouse_pos)

            pygame.draw.rect(
                screen,
                lighten(GREEN_BG, 18) if plus_hover else GREEN_BG,
                plus_r,
                border_radius=4,
            )
            pygame.draw.rect(screen, GREEN_BDR, plus_r, 1, border_radius=4)

            pygame.draw.rect(
                screen,
                lighten(RED_BG, 18) if minus_hover else RED_BG,
                minus_r,
                border_radius=4,
            )
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
                    else f"{special_chars["-"]}"
                )
                img = FONT_SM.render(
                    disp, True, PURPLE if expanded and seq else (TEXT if seq else MUTED)
                )
                screen.blit(img, img.get_rect(center=sr.center))

                exp_btn = pygame.Rect(sr.right - 15, sr.top + 2, 12, 12)
                exp_hover = exp_btn.collidepoint(mouse_pos)

                base_exp_bg = PURPLE if expanded else BORDER
                pygame.draw.rect(
                    screen,
                    lighten(base_exp_bg, 18) if exp_hover else base_exp_bg,
                    exp_btn,
                    border_radius=3,
                )

                e_img = FONT_SM.render(
                    f"{special_chars["~"]}", True, WHITE if expanded else MUTED
                )
                screen.blit(e_img, e_img.get_rect(center=exp_btn.center))

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
        tip_img = FONT_SM.render(hover_text, True, WHITE)
        tip_pad = 8
        tip_rect = tip_img.get_rect(topleft=(hover_pos[0] + 16, hover_pos[1] + 16))
        tip_rect.inflate_ip(tip_pad * 2, tip_pad * 2)
        if tip_rect.right > WIDTH - PAD:
            tip_rect.right = WIDTH - PAD
        if tip_rect.bottom > HEIGHT - PAD:
            tip_rect.bottom = HEIGHT - PAD
        if tip_rect.left < PAD:
            tip_rect.left = PAD
        if tip_rect.top < PAD:
            tip_rect.top = PAD
        pygame.draw.rect(screen, DARK, tip_rect, border_radius=8)
        pygame.draw.rect(screen, BORDER, tip_rect, 1, border_radius=8)
        screen.blit(tip_img, tip_img.get_rect(center=tip_rect.center))

    return RESULTS_TOP_Y, summary_btn, ph_ui


def render_results(table_bottom_y, mouse_pos=(0, 0)):
    global _result_word_rects, _hover_word_rect
    _result_word_rects = []

    y0 = table_bottom_y + PAD
    h = HEIGHT - y0 - PAD / 2
    if h < 80:
        return None, None

    panel = pygame.Rect(PAD, y0, WIDTH - 2 * PAD, h)
    draw_panel(screen, panel, PANEL, BORDER, radius=12)

    progress_h = draw_search_progress_bar(screen, panel)

    if state.results_cache_dirty:
        rebuild_results_cache()

    panel_words = state.results_visible_words
    n = len(panel_words)

    if n:
        state.preview_start = clamp(state.preview_start, 0, n - 1)
        start_index = state.preview_start + 1
        end_index = min(state.preview_start + state.max_preview, n)
    else:
        state.preview_start = 0
        start_index = 0
        end_index = 0

    n_save = sum(1 for v in state.word_selections.values() if v == "save")
    n_excl = sum(1 for v in state.word_selections.values() if v == "exclude")
    sel_parts = []
    if n_save:
        sel_parts.append(f"{n_save} word(s) selected {special_chars['[OK]']}")
    if n_excl:
        sel_parts.append(f"{n_excl} word(s) excluded {special_chars['X']}")
    sel_str = "  |  " + f"  {special_chars['*']}  ".join(sel_parts) if sel_parts else ""

    top_y = panel.y + 10 + progress_h
    blit_text(screen, state.status, FONT_SM, MUTED, panel.x + PAD, top_y)

    cnt = f"{n} total  {special_chars['*']}  showing {start_index} - {end_index}"
    cnt_w = FONT_SM.size(cnt)[0]
    nav_w, nav_h, nav_gap = 22, 20, 6
    group_w = nav_w * 2 + nav_gap * 2 + cnt_w
    group_x = panel.right - PAD - group_w
    nav_y = panel.y + 8 + progress_h

    prev_rect = pygame.Rect(group_x, nav_y, nav_w, nav_h)
    cnt_x = prev_rect.right + nav_gap
    blit_text(screen, cnt, FONT_SM, ACCENT, cnt_x, top_y, anchor="topleft")
    next_rect = pygame.Rect(cnt_x + cnt_w + nav_gap, nav_y, nav_w, nav_h)

    can_prev = state.preview_start > 0
    can_next = n > 0 and (state.preview_start + state.max_preview) < n
    draw_nav_button(
        screen,
        prev_rect,
        "left",
        hovered=prev_rect.collidepoint(mouse_pos),
        enabled=can_prev,
    )
    draw_nav_button(
        screen,
        next_rect,
        "right",
        hovered=next_rect.collidepoint(mouse_pos),
        enabled=can_next,
    )

    if sel_str:
        blit_text(
            screen,
            sel_str,
            FONT_SM,
            PURPLE,
            panel.centerx,
            top_y,
            anchor="midtop",
        )

    counts = state.results_status_counts

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
        screen,
        toggle_rect,
        "color on" if state.colorize_status else "color off",
        bg=ORANGE if state.colorize_status else BROWN,
        fg=WHITE,
        radius=8,
        hovered=hovered_toggle,
        font=FONT_SM,
    )

    x = toggle_rect.left - 10
    legend_rects = {}

    for key, short_label in reversed(legend_items):
        selected = key in state.status_filters
        mark = special_chars["[OK]"] if selected else special_chars["X"]

        label = f"{short_label} {counts.get(key, 0)}"
        label_w = FONT_SM.size(label)[0]
        chip_w = label_w + 42
        chip_rect = pygame.Rect(x - chip_w, legend_y - 11, chip_w, 22)

        hovered = chip_rect.collidepoint(mouse_pos)

        if state.colorize_status:
            fill = STATUS_BG.get(key, PANEL2)
            border = STATUS_BDR.get(key, BORDER)
        else:
            fill = PANEL2
            border = BORDER

        if hovered:
            fill = lighten(fill, 14)
            border = lighten(border, 14)

        pygame.draw.rect(screen, fill, chip_rect, border_radius=10)
        pygame.draw.rect(screen, border, chip_rect, 1, border_radius=10)

        mark_rect = pygame.Rect(chip_rect.x + 5, chip_rect.y + 5, 12, 12)
        mark_fill = GREEN_BG if selected else RED_BG
        mark_border = GREEN_BDR if selected else RED_BDR
        pygame.draw.rect(screen, mark_fill, mark_rect, border_radius=4)
        pygame.draw.rect(screen, mark_border, mark_rect, 1, border_radius=4)

        mark_img = FONT_SM.render(mark, True, TEXT)
        screen.blit(mark_img, mark_img.get_rect(center=mark_rect.center))

        blit_text(
            screen,
            label,
            FONT_SM,
            TEXT,
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
        screen,
        keyboard_rect,
        f"{special_chars['kb']} on" if state.keyboard_on else f"{special_chars['kb']} off",
        bg=ORANGE if state.keyboard_on else BROWN,
        fg=WHITE,
        radius=8,
        hovered=keyboard_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )

    draw_button(
        screen,
        show_words_rect,
        "Show Words",
        bg=TEAL,
        fg=WHITE,
        radius=8,
        hovered=show_words_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )
    draw_button(
        screen,
        show_stats_rect,
        "Show Statistics",
        bg=PURPLE,
        fg=WHITE,
        radius=8,
        hovered=show_stats_rect.collidepoint(mouse_pos),
        font=FONT_SM,
    )

    keyboard_top = panel.bottom - 8
    if state.keyboard_on:
        keyboard_top = draw_virtual_keyboard(screen, panel, mouse_pos)

    preview = panel_words[state.preview_start : state.preview_start + state.max_preview]
    if not preview:
        msg = (
            "No categories selected — click a legend chip to show results."
            if not state.status_filters
            else f"No results yet {special_chars['-']} press Enter or click Search."
        )
        blit_text(
            screen,
            msg,
            FONT_MD,
            MUTED,
            panel.x + PAD,
            panel.y + 36 + progress_h,
        )
        return prev_rect, next_rect

    grid_y = panel.y + 34 + progress_h
    cols = max(1, (panel.width - 2 * PAD) // 250)
    cw = (panel.width - 2 * PAD - (cols - 1) * GAP) // cols
    ch_h = 26

    grid_bottom = (keyboard_top - 8) if state.keyboard_on else (panel.bottom - 8)

    _hover_word_rect = None

    for idx, word in enumerate(preview):
        col = idx % cols
        row = idx // cols
        wx = panel.x + PAD + col * (cw + GAP)
        wy = grid_y + row * (ch_h + 4)
        if wy + ch_h > grid_bottom:
            break

        wr = pygame.Rect(wx, wy, cw, ch_h)
        is_hovered = wr.collidepoint(mouse_pos)
        sel_state = state.word_selections.get(word)
        status = state.results_status_map.get(word, "no_translation_no_meaning")

        if sel_state == "save":
            bg_color = GREEN_BG
            bdr_color = GREEN_BDR
            marker = special_chars["[OK]"]
        elif sel_state == "exclude":
            bg_color = RED_BG
            bdr_color = RED_BDR
            marker = special_chars["X"]
        else:
            if state.colorize_status:
                bg_color = STATUS_BG.get(status, PANEL2)
                bdr_color = STATUS_BDR.get(status, BORDER)
            else:
                bg_color = PANEL2
                bdr_color = BORDER
            marker = None

        if is_hovered:
            draw_r = wr.inflate(int(wr.w * 0.1), int(wr.h * 0.1))
            _hover_word_rect = (word, wr)
        else:
            draw_r = wr

        pygame.draw.rect(screen, bg_color, draw_r, border_radius=6)
        pygame.draw.rect(screen, bdr_color, draw_r, 1, border_radius=6)

        wimg = FONT_SM.render(word, True, TEXT)
        screen.blit(wimg, wimg.get_rect(midleft=(draw_r.x + 8, draw_r.centery)))

        if marker is not None:
            m_img = FONT_SM.render(marker, True, TEXT)
            screen.blit(
                m_img, m_img.get_rect(midright=(draw_r.right - 8, draw_r.centery))
            )

        _result_word_rects.append((word, wr))

    # Draw zoom tooltip near mouse for hovered word
    if _hover_word_rect is not None:
        hword, _ = _hover_word_rect

        lines = []  # list of (text, font, color)
        lines.append((hword, FONT_LG, TEXT))

        entry = lookup_word_entry(hword, state.language)

        if state.show_translation:
            tr = None
            if entry is not None:
                tr = (
                    entry.get("greek_translation")
                    if state.language == "english"
                    else entry.get("english_translation")
                )
            tr_text = (
                f"{hword} {special_chars['>']} {tr}"
                if tr
                else f"{hword} {special_chars['>']} (no translation yet)"
            )
            lines.append((tr_text, FONT_MD, ACCENT))

        if state.show_meaning:
            for ml in format_meaning_lines(entry, state.language):
                lines.append((ml, FONT_SM, MUTED))

        max_w = 0
        total_h = 0
        line_gap = 3
        for text, font, color in lines:
            w, h = font.size(text)
            max_w = max(max_w, w)
            total_h += h + line_gap

        tip_pad = 10
        tip_w = min(max_w + tip_pad * 2, WIDTH - 2 * PAD)
        tip_h = total_h + tip_pad * 2

        tip_rect = pygame.Rect(mouse_pos[0] + 20, mouse_pos[1] + 10, tip_w, tip_h)
        if tip_rect.right > WIDTH - PAD:
            tip_rect.right = WIDTH - PAD
        if tip_rect.bottom > HEIGHT - PAD:
            tip_rect.bottom = HEIGHT - PAD
        if tip_rect.left < PAD:
            tip_rect.left = PAD
        if tip_rect.top < PAD:
            tip_rect.top = PAD

        pygame.draw.rect(screen, PANEL, tip_rect, border_radius=10)
        pygame.draw.rect(screen, ACCENT, tip_rect, 2, border_radius=10)

        ly = tip_rect.y + tip_pad
        max_text_w = tip_rect.width - tip_pad * 2
        for text, font, color in lines:
            display_text = fit_text_with_ellipsis(text, font, max_text_w)
            img = font.render(display_text, True, color)
            screen.blit(img, (tip_rect.x + tip_pad, ly))
            ly += font.size(text)[1] + line_gap

    return prev_rect, next_rect


# ══════════════════════════════════════════════════════════════════
#  Main loop
# ══════════════════════════════════════════════════════════════════

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
        info_modal.draw(screen, WIDTH, HEIGHT)
        progress_modal.draw(screen, WIDTH, HEIGHT, mouse_pos)
        enrichment_modal.draw(screen, WIDTH, HEIGHT, mouse_pos)
        stats_modal.draw(screen, WIDTH, HEIGHT, mouse_pos)
        words_modal.draw(screen, WIDTH, HEIGHT, mouse_pos)
        add_modal.draw(screen, WIDTH, HEIGHT, mouse_pos)
        delete_modal.draw(screen, WIDTH, HEIGHT, mouse_pos)
        summary_modal.draw(screen, WIDTH, HEIGHT, mouse_pos)

        pygame.display.flip()
        clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.VIDEORESIZE:
                WIDTH, HEIGHT = event.w, event.h
                screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)

            # Let the enrichment modal get first crack at clicks/keys.
            if enrichment_modal.visible and enrichment_modal.handle_event(
                event, WIDTH, HEIGHT
            ):
                continue

            progress_modal_was_open = progress_modal.visible
            progress_modal.handle_event(event, WIDTH, HEIGHT)
            if progress_modal_was_open:
                continue

            modal_was_open = info_modal.visible
            info_modal.handle_event(event, WIDTH, HEIGHT)
            if modal_was_open:
                continue

            if words_modal.visible and words_modal.handle_event(event, WIDTH, HEIGHT):
                continue

            if add_modal.visible and add_modal.handle_event(event, WIDTH, HEIGHT):
                continue

            if delete_modal.visible and delete_modal.handle_event(event, WIDTH, HEIGHT):
                continue

            if stats_modal.visible and stats_modal.handle_event(event, WIDTH, HEIGHT):
                continue

            if summary_modal.visible and summary_modal.handle_event(event, WIDTH, HEIGHT):
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
                    elif mode_rects[2].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_mode = "exist"
                        else:
                            state.ph_mode = "inner"
                    elif mode_rects[1].collidepoint(mx, my):
                        if state.finder_mode == "letter_match":
                            state.input_mode = "invalid"
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

                        if state.keyboard_on and _results_keyboard_rects.get("panel") is not None:
                            kp = _results_keyboard_rects["panel"]
                            if kp.collidepoint(mx, my):
                                controls = _results_keyboard_rects.get("controls", {})
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
                                for base, r in _results_keyboard_rects.get("keys", []):
                                    if r.collidepoint(mx, my):
                                        handle_text_input(keyboard_char_for(base))
                                        break
                                break

                        # Results panel word selection (left click = save)
                        for word, wr in _result_word_rects:
                            if wr.collidepoint(mx, my):
                                if state.word_selections.get(word) == "save":
                                    del state.word_selections[word]
                                else:
                                    state.word_selections[word] = "save"
                                break

                        # Results action buttons
                        if _results_action_rects.get("keyboard") is not None and _results_action_rects["keyboard"].collidepoint(mx, my):
                            state.keyboard_on = not state.keyboard_on
                            break

                        if _results_action_rects.get("show_words") is not None and _results_action_rects["show_words"].collidepoint(mx, my):
                            words_modal.show(state.results_visible_words, state.language)
                            break

                        if _results_action_rects.get("show_stats") is not None and _results_action_rects["show_stats"].collidepoint(mx, my):
                            stats_modal.show(state.results_visible_words, state.language)
                            break

                        # Results legend toggles
                        if _results_legend_rects.get(
                            "toggle"
                        ) is not None and _results_legend_rects["toggle"].collidepoint(
                            mx, my
                        ):
                            state.colorize_status = not state.colorize_status
                            break

                        clicked_legend = False
                        for status_key, rect in _results_legend_rects.get(
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

    if tk_root is not None and tk_root.winfo_exists():
        tk_root.destroy()

    pygame.quit()
