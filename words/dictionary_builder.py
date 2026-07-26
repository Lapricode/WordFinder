#!/usr/bin/env python3
"""
dictionary_builder.py

Builds English/Greek dictionaries using WordNet + Google Translate.

Modes:
    search:
        Recompute translation and meaning for all words in the input text file.
        - English: WordNet senses + Greek translation.
        - Greek: Greek -> English translation + senses from English cache / WordNet.

    repair:
        Do not call translation or WordNet.
        Only normalize existing JSON entries:
        - fix status labels
        - turn translations identical to the original word into null
        - preserve existing senses and translations otherwise

    enrich:
        Do not rerun full translation for existing rows.
        - English: fill missing senses for existing entries only, using WordNet;
          do not redo Greek translation.
        - Greek: fill missing senses for existing entries only, using the existing
          English translation + English cache / WordNet fallback;
          do not redo Greek translation.

Status labels:
    ok
    no_translation
    no_meaning
    no_translation_no_meaning

A translation identical to the source word is treated as missing.
"""

import argparse
import json
import os
from pathlib import Path

import nltk
from nltk.corpus import wordnet as wn
from charset_normalizer import from_path
from deep_translator import GoogleTranslator
from tqdm import tqdm


# ══════════════════════════════════════════════════════════════════
#  Shared helpers
# ══════════════════════════════════════════════════════════════════


def normalize_word(word):
    return word.strip().lower()


def load_json(path):
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json_atomic(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_utf8(path):
    with path.open("r", encoding="utf-8") as f:
        return [x.strip() for x in f if x.strip()]


def read_autodetect(path):
    result = from_path(path).best()
    if result is None:
        raise RuntimeError(f"Could not determine encoding for {path}")
    print(f"Detected input encoding: {result.encoding}")
    with path.open("r", encoding=result.encoding) as f:
        return [x.strip() for x in f if x.strip()]


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


def has_senses(senses):
    return bool(isinstance(senses, list) and senses)


def build_status(source_word, translation, senses):
    """
    Status logic shared by English and Greek dictionaries.
    Translation identical to source is treated as missing.
    """
    effective_translation = clean_translation(source_word, translation)
    has_translation = bool(effective_translation)
    has_meaning = has_senses(senses)

    if has_translation and has_meaning:
        return "ok"
    if not has_translation and not has_meaning:
        return "no_translation_no_meaning"
    if not has_translation:
        return "no_translation"
    return "no_meaning"


def is_single_word(text):
    """
    True only if the text is exactly one alphabetic token.
    Used to decide whether a Greek->English translation can be used
    as a cache key in english_dictionary.json.
    """
    if not text:
        return False
    parts = text.strip().split()
    return len(parts) == 1 and parts[0].isalpha()


# ══════════════════════════════════════════════════════════════════
#  WordNet + translation helpers
# ══════════════════════════════════════════════════════════════════


def get_senses(word, max_senses=None):
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
        synsets = wn.synsets(candidate)

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


def translate_text(word, source, target):
    try:
        return GoogleTranslator(source=source, target=target).translate(word)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  English pipeline
# ══════════════════════════════════════════════════════════════════


def search_english_word(word, max_senses=None):
    senses = get_senses(word, max_senses)
    greek_translation = clean_translation(word, translate_text(word, "en", "el"))
    return {
        "input_word": word,
        "greek_translation": greek_translation,
        "senses": senses,
        "status": build_status(word, greek_translation, senses),
    }


def repair_english_entry(key, entry):
    """
    Repair only existing fields. No translation, no WordNet lookup.
    """
    if not isinstance(entry, dict):
        return {
            "input_word": key,
            "greek_translation": None,
            "senses": [],
            "status": "no_translation_no_meaning",
        }

    input_word = entry.get("input_word", key)
    senses = entry.get("senses")
    if not isinstance(senses, list):
        senses = []

    greek_translation = clean_translation(input_word, entry.get("greek_translation"))

    repaired = dict(entry)
    repaired["input_word"] = input_word
    repaired["greek_translation"] = greek_translation
    repaired["senses"] = senses
    repaired["status"] = build_status(input_word, greek_translation, senses)
    return repaired


def enrich_english_entry(key, entry, max_senses=None):
    """
    Enrich existing entries only.
    - do not redo Greek translation
    - fill missing senses if needed
    """
    if not isinstance(entry, dict):
        # If the row is malformed, repair it without external translation.
        return {
            "input_word": key,
            "greek_translation": None,
            "senses": [],
            "status": "no_translation_no_meaning",
        }

    input_word = entry.get("input_word", key)
    senses = entry.get("senses")
    if not isinstance(senses, list):
        senses = []

    greek_translation = clean_translation(input_word, entry.get("greek_translation"))

    if not senses:
        senses = get_senses(input_word, max_senses)

    enriched = dict(entry)
    enriched["input_word"] = input_word
    enriched["greek_translation"] = greek_translation
    enriched["senses"] = senses
    enriched["status"] = build_status(input_word, greek_translation, senses)
    return enriched


def search_english_results(words, max_senses=None):
    results = {}
    for word in tqdm(words, desc="Searching English", unit="word"):
        results[normalize_word(word)] = search_english_word(word, max_senses)
    return results


def repair_english_results(results):
    repaired = {}
    items = list(results.items())
    for key, entry in tqdm(items, desc="Repairing English entries", unit="entry"):
        repaired[key] = repair_english_entry(key, entry)
    return repaired


def enrich_english_results(results, max_senses=None):
    enriched = {}
    items = list(results.items())
    for key, entry in tqdm(items, desc="Enriching English entries", unit="entry"):
        enriched[key] = enrich_english_entry(key, entry, max_senses)
    return enriched


# ══════════════════════════════════════════════════════════════════
#  Greek pipeline
# ══════════════════════════════════════════════════════════════════


MULTI_WORD_NOTE = (
    "Translation has multiple words; cannot match to a single English dictionary entry."
)


def resolve_senses_for_translation(
    english_translation,
    english_dict,
    english_dict_path,
    max_senses=None,
):
    """
    Given a Greek word's English translation, returns:
        (senses, status, note)

    This may look up english_dict live via WordNet and persist a new entry
    into english_dict / english_dict_path as a side effect if the translation
    isn't already present there.
    """
    if not english_translation or not english_translation.strip():
        return [], "no_translation", None

    if not is_single_word(english_translation):
        return [], "no_meaning", MULTI_WORD_NOTE

    key = normalize_word(english_translation)

    existing = english_dict.get(key)
    if existing is not None:
        existing_senses = existing.get("senses")
        if has_senses(existing_senses):
            return existing_senses, "ok", None

    # Not cached yet, or cached but empty: look it up live via WordNet and
    # cache the result back into english_dictionary.json.
    senses = get_senses(english_translation, max_senses)
    greek_translation_back = clean_translation(
        english_translation, translate_text(english_translation, "en", "el")
    )
    english_dict[key] = {
        "input_word": english_translation,
        "greek_translation": greek_translation_back,
        "senses": senses,
        "status": build_status(english_translation, greek_translation_back, senses),
    }
    save_json_atomic(english_dict_path, english_dict)

    if senses:
        return senses, "ok", None
    return [], "no_meaning", None


def search_greek_word(word, english_dict, english_dict_path, max_senses=None):
    english_translation = clean_translation(word, translate_text(word, "el", "en"))
    senses, status, note = resolve_senses_for_translation(
        english_translation, english_dict, english_dict_path, max_senses
    )

    entry = {
        "input_word": word,
        "english_translation": english_translation,
        "senses": senses,
        "status": status if english_translation else build_status(word, english_translation, senses),
    }
    if note:
        entry["senses_note"] = note
    # Use the shared status logic to ensure identical-to-source translations are treated as missing.
    entry["status"] = build_status(word, english_translation, senses)
    return entry


def repair_greek_entry(key, entry):
    """
    Repair only existing fields. No translation, no WordNet lookup.
    """
    if not isinstance(entry, dict):
        return {
            "input_word": key,
            "english_translation": None,
            "senses": [],
            "status": "no_translation_no_meaning",
        }

    input_word = entry.get("input_word", key)
    senses = entry.get("senses")
    if not isinstance(senses, list):
        senses = []

    english_translation = clean_translation(input_word, entry.get("english_translation"))

    repaired = dict(entry)
    repaired["input_word"] = input_word
    repaired["english_translation"] = english_translation
    repaired["senses"] = senses
    repaired["status"] = build_status(input_word, english_translation, senses)

    # Keep any existing note only if it is still relevant.
    if "senses_note" in repaired and not english_translation:
        repaired.pop("senses_note", None)

    return repaired


def enrich_greek_entry(key, entry, english_dict, english_dict_path, max_senses=None):
    """
    Enrich existing Greek entries only.
    - do not redo Greek translation
    - if an existing English translation is present, backfill senses from
      english_dict first, then WordNet fallback, caching back into english_dict
    """
    if not isinstance(entry, dict):
        return {
            "input_word": key,
            "english_translation": None,
            "senses": [],
            "status": "no_translation_no_meaning",
        }

    input_word = entry.get("input_word", key)
    senses = entry.get("senses")
    if not isinstance(senses, list):
        senses = []

    english_translation = clean_translation(input_word, entry.get("english_translation"))
    note = None

    if english_translation and not senses:
        senses, resolved_status, note = resolve_senses_for_translation(
            english_translation,
            english_dict,
            english_dict_path,
            max_senses,
        )
        # resolved_status is derived from the lookup outcome; the final status is
        # normalized below using the shared status function.

    enriched = dict(entry)
    enriched["input_word"] = input_word
    enriched["english_translation"] = english_translation
    enriched["senses"] = senses
    enriched["status"] = build_status(input_word, english_translation, senses)

    if note:
        enriched["senses_note"] = note
    else:
        enriched.pop("senses_note", None)

    return enriched


def search_greek_results(words, english_dict, english_dict_path, max_senses=None):
    results = {}
    for word in tqdm(words, desc="Searching Greek", unit="word"):
        results[normalize_word(word)] = search_greek_word(
            word, english_dict, english_dict_path, max_senses
        )
    return results


def repair_greek_results(results):
    repaired = {}
    items = list(results.items())
    for key, entry in tqdm(items, desc="Repairing Greek entries", unit="entry"):
        repaired[key] = repair_greek_entry(key, entry)
    return repaired


def enrich_greek_results(results, english_dict, english_dict_path, max_senses=None):
    enriched = {}
    items = list(results.items())
    for key, entry in tqdm(items, desc="Enriching Greek entries", unit="entry"):
        enriched[key] = enrich_greek_entry(
            key, entry, english_dict, english_dict_path, max_senses
        )
    return enriched


# ══════════════════════════════════════════════════════════════════
#  Runners
# ══════════════════════════════════════════════════════════════════


def run_english(args):
    nltk.download("wordnet", quiet=True)
    nltk.download("omw-1.4", quiet=True)

    output_file = Path(args.output_json)

    if args.mode == "search":
        input_file = Path(args.input_txt)
        words = read_utf8(input_file)
        results = search_english_results(words, args.max_senses)
        save_json_atomic(output_file, results)
        print(f"\nFinished! Saved {len(results)} words to '{output_file}'.")
        return

    results = load_json(output_file)

    if args.mode == "repair":
        results = repair_english_results(results)
        save_json_atomic(output_file, results)
        print(f"\nFinished repairing English entries in '{output_file}'.")
        return

    if args.mode == "enrich":
        results = enrich_english_results(results, args.max_senses)
        save_json_atomic(output_file, results)
        print(f"\nFinished enriching English entries in '{output_file}'.")
        return

    raise ValueError(f"Unsupported mode: {args.mode}")


def run_greek(args):
    nltk.download("wordnet", quiet=True)
    nltk.download("omw-1.4", quiet=True)

    output_file = Path(args.output_json)
    english_dict_path = Path(args.english_json)

    if args.mode == "search":
        input_file = Path(args.input_txt)
        words = read_autodetect(input_file)
        english_dict = load_json(english_dict_path)
        results = search_greek_results(
            words, english_dict, english_dict_path, args.max_senses
        )
        save_json_atomic(output_file, results)
        save_json_atomic(english_dict_path, english_dict)
        print(f"\nFinished! Saved {len(results)} words to '{output_file}'.")
        return

    results = load_json(output_file)
    english_dict = load_json(english_dict_path)

    if args.mode == "repair":
        results = repair_greek_results(results)
        save_json_atomic(output_file, results)
        print(f"\nFinished repairing Greek entries in '{output_file}'.")
        return

    if args.mode == "enrich":
        results = enrich_greek_results(
            results, english_dict, english_dict_path, args.max_senses
        )
        save_json_atomic(output_file, results)
        save_json_atomic(english_dict_path, english_dict)
        print(f"\nFinished enriching Greek entries in '{output_file}'.")
        return

    raise ValueError(f"Unsupported mode: {args.mode}")


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="English/Greek dictionary builder")
    parser.add_argument(
        "--mode",
        choices=["search", "repair", "enrich"],
        default="search",
        help=(
            "search = recompute translation and meaning for input words; "
            "repair = normalize existing JSON only; "
            "enrich = backfill missing meanings without rerunning full translation"
        ),
    )

    subparsers = parser.add_subparsers(dest="lang", required=True)

    p_en = subparsers.add_parser("english", help="Build english_dictionary.json")
    p_en.add_argument("--input-txt", default="english_words.txt")
    p_en.add_argument("--output-json", default="english_dictionary.json")
    p_en.add_argument("--max-senses", type=int, default=None)
    p_en.set_defaults(func=run_english)

    p_el = subparsers.add_parser("greek", help="Build greek_dictionary.json")
    p_el.add_argument("--input-txt", default="greek_words.txt")
    p_el.add_argument("--output-json", default="greek_dictionary.json")
    p_el.add_argument(
        "--english-json",
        default="english_dictionary.json",
        help="English dictionary JSON used for senses cross-lookup (read AND written to, as a growing cache)",
    )
    p_el.add_argument("--max-senses", type=int, default=None)
    p_el.set_defaults(func=run_greek)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
