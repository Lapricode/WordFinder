"""
Core word-matching and pattern-filtering logic.

Part of the Word Finder application (split from the original single-file
WordFinder.py for maintainability). Behavior is unchanged from the original --
this is a pure refactor.
"""

import os
from itertools import product
from collections import Counter

from wf_constants import (
    ENGLISH_GROUP_BY_FIRST, GREEK_GROUP_BY_FIRST, GREEK_CHAR_TO_FIRST,
)


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

    # Deferred import: wf_state imports wf_search (for load_words, pattern
    # matchers), so importing wf_state at module load time here would create a
    # circular import. Importing inside the function (only needed at call time,
    # never at import time) breaks the cycle without changing behavior.
    import wf_state as S

    groups = []

    for ch in seq:

        if S.state.language == "greek":
            first = GREEK_CHAR_TO_FIRST.get(ch)

            if first:
                groups.append(list(GREEK_GROUP_BY_FIRST[first]))
            else:
                groups.append([ch])

        elif S.state.language == "english":
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
