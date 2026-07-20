"""
dictionary_builder.py

Combined English/Greek dictionary builder.

- "english" subcommand: for each English word, look up WordNet senses and
  translate it to Greek. Saves to english_dictionary.json.
      {
        "input_word": "...",
        "greek_translation": "...",
        "senses": [{"part_of_speech": ..., "definition": ..., "examples": [...]}],
        "status": "ok" | "no_meanings" | "no_translation" | "no_meanings_no_translation"
      }

- "greek" subcommand: for each Greek word, translate it to English, then
  cross-look-up that English translation's senses (first from
  english_dictionary.json, falling back to a live WordNet lookup, which is
  then also cached back into english_dictionary.json). Saves to
  greek_dictionary.json.
      {
        "input_word": "...",
        "english_translation": "...",
        "senses": [...],
        "status": "ok" | "no_translation" | "no_senses" | "multiple_words_translation",
        "senses_note": "..."   (present only when senses were intentionally skipped)
      }

Usage:
    python dictionary_builder.py english --input-txt english_words.txt --output-json english_dictionary.json
    python dictionary_builder.py greek   --input-txt greek_words.txt   --output-json greek_dictionary.json [--english-json english_dictionary.json]
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


def normalize_word(word: str) -> str:
    return word.strip().lower()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json_atomic(path: Path, data: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def read_words_utf8(path: Path) -> list[str]:
    """Used for the English word list (fixed utf-8, matches the original
    english_dictionary_builder behavior)."""
    with path.open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def read_words_autodetect(path: Path) -> list[str]:
    """Used for the Greek word list: auto-detect encoding (matches the
    original greek_dictionary_builder behavior)."""
    result = from_path(path).best()
    if result is None:
        raise RuntimeError(f"Could not determine the encoding of {path}")
    encoding = result.encoding
    print(f"Detected input encoding: {encoding}")
    with path.open("r", encoding=encoding) as f:
        return [line.strip() for line in f if line.strip()]


# ══════════════════════════════════════════════════════════════════
#  English word enrichment (WordNet senses + en -> el translation)
# ══════════════════════════════════════════════════════════════════


def get_senses(word: str, max_senses: int | None = None) -> list[dict]:
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


def get_greek_translation(word: str) -> str | None:
    try:
        translator = GoogleTranslator(source="en", target="el")
        return translator.translate(word)
    except Exception:
        return None


def build_status_english(senses: list[dict], greek_translation: str | None) -> str:
    has_meanings = bool(senses)
    has_translation = bool(greek_translation and greek_translation.strip())

    if has_meanings and has_translation:
        return "ok"
    if not has_meanings and not has_translation:
        return "no_meanings_no_translation"
    if not has_meanings:
        return "no_meanings"
    return "no_translation"


def enrich_english_word(word: str, max_senses: int | None = None) -> dict:
    """Builds one english_dictionary.json entry for `word`."""
    senses = get_senses(word, max_senses)
    greek_translation = get_greek_translation(word)
    return {
        "input_word": word,
        "greek_translation": greek_translation,
        "senses": senses,
        "status": build_status_english(senses, greek_translation),
    }


# ══════════════════════════════════════════════════════════════════
#  Greek word enrichment (el -> en translation + cross-lookup senses)
# ══════════════════════════════════════════════════════════════════


def get_english_translation(word: str) -> str | None:
    try:
        translator = GoogleTranslator(source="el", target="en")
        return translator.translate(word)
    except Exception:
        return None


def is_single_word(text: str) -> bool:
    """True only if `text` is exactly one alphabetic token, so it can be
    matched directly against an english_dictionary.json key."""
    if not text:
        return False
    parts = text.strip().split()
    return len(parts) == 1 and parts[0].isalpha()


MULTI_WORD_NOTE = (
    "Translation has multiple words; cannot match to a single English "
    "dictionary entry."
)


def resolve_senses_for_translation(
    english_translation: str | None,
    english_dict: dict,
    english_dict_path: Path,
    max_senses: int | None = None,
):
    """Given a Greek word's English translation, returns (senses, status,
    senses_note_or_None). May look up english_dict live via WordNet and
    persist a new entry into english_dict / english_dict_path as a side
    effect, if the translation isn't already present there.
    """
    if not english_translation or not english_translation.strip():
        return [], "no_translation", None

    if not is_single_word(english_translation):
        return [], "multiple_words_translation", MULTI_WORD_NOTE

    key = normalize_word(english_translation)

    existing = english_dict.get(key)
    if existing is not None and existing.get("senses"):
        senses = existing["senses"]
        return senses, "ok", None

    if existing is not None and "senses" in existing:
        # Word is cached but has zero senses -- no need to re-query WordNet.
        return [], "no_senses", None

    # Not cached yet: look it up live via WordNet, and cache the result
    # into english_dictionary.json so future runs (English or Greek) reuse it.
    senses = get_senses(english_translation, max_senses)
    greek_translation_back = get_greek_translation(english_translation)
    english_dict[key] = {
        "input_word": english_translation,
        "greek_translation": greek_translation_back,
        "senses": senses,
        "status": build_status_english(senses, greek_translation_back),
    }
    save_json_atomic(english_dict_path, english_dict)

    if senses:
        return senses, "ok", None
    return [], "no_senses", None


def enrich_greek_word(
    word: str,
    english_dict: dict,
    english_dict_path: Path,
    max_senses: int | None = None,
) -> dict:
    """Builds one greek_dictionary.json entry for `word`, including senses
    cross-looked-up from (or added to) the English dictionary."""
    english_translation = get_english_translation(word)
    senses, status, note = resolve_senses_for_translation(
        english_translation, english_dict, english_dict_path, max_senses
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


# ══════════════════════════════════════════════════════════════════
#  Runners
# ══════════════════════════════════════════════════════════════════


def run_english(args):
    nltk.download("wordnet", quiet=True)
    nltk.download("omw-1.4", quiet=True)

    input_file = Path(args.input_txt)
    output_file = Path(args.output_json)

    words = read_words_utf8(input_file)
    results = load_json(output_file)

    pending_words = [w for w in words if normalize_word(w) not in results]

    print(f"Total words  : {len(words)}")
    print(f"Already done : {len(results)}")
    print(f"Remaining    : {len(pending_words)}")
    print()

    for word in tqdm(pending_words, desc="Processing", unit="word"):
        key = normalize_word(word)
        results[key] = enrich_english_word(word, args.max_senses)
        save_json_atomic(output_file, results)

    print(f"\nFinished! Saved {len(results)} words to '{output_file}'.")


def run_greek(args):
    nltk.download("wordnet", quiet=True)
    nltk.download("omw-1.4", quiet=True)

    input_file = Path(args.input_txt)
    output_file = Path(args.output_json)
    english_dict_path = Path(args.english_json)

    words = read_words_autodetect(input_file)
    results = load_json(output_file)
    english_dict = load_json(english_dict_path)

    pending_words = [w for w in words if normalize_word(w) not in results]

    print(f"Total words  : {len(words)}")
    print(f"Already done : {len(results)}")
    print(f"Remaining    : {len(pending_words)}")
    print(f"English dict : {english_dict_path} ({len(english_dict)} entries loaded)")
    print()

    for word in tqdm(pending_words, desc="Processing", unit="word"):
        key = normalize_word(word)
        results[key] = enrich_greek_word(
            word, english_dict, english_dict_path, args.max_senses
        )
        save_json_atomic(output_file, results)

    print(f"\nFinished! Saved {len(results)} words to '{output_file}'.")


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="English/Greek dictionary builder")
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
        help="English dictionary JSON used for senses cross-lookup "
        "(read AND written to, as a growing cache)",
    )
    p_el.add_argument("--max-senses", type=int, default=None)
    p_el.set_defaults(func=run_greek)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
