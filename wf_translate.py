"""
Translation and dictionary/meaning lookup backend (NLTK WordNet, Google Translate).

Part of the Word Finder application (split from the original single-file
WordFinder.py for maintainability). Behavior is unchanged from the original --
this is a pure refactor.
"""

import os
import json

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

from wf_constants import GREEK_GROUPS
from wf_search import load_words


_NLTK_READY = False

_TRANSLATOR_CACHE = {}

_meanings_cache = {}  # path -> {"mtime": float, "data": dict}

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
    # Deferred import: wf_state imports wf_translate (for ensure_nltk_ready etc.),
    # so importing wf_state at module load time here would create a circular
    # import. Importing inside the function (only needed at call time) breaks
    # the cycle without changing behavior.
    import wf_state as S
    S.state.results_cache_dirty = True

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
