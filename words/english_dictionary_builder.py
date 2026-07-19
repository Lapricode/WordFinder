import argparse
import json
import os
from pathlib import Path

import nltk
from nltk.corpus import wordnet as wn
from deep_translator import GoogleTranslator
from tqdm import tqdm


def normalize_word(word: str) -> str:
    return word.strip().lower()


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


def read_words(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


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


def build_status(senses: list[dict], greek_translation: str | None) -> str:
    has_meanings = bool(senses)
    has_translation = bool(greek_translation and greek_translation.strip())

    if has_meanings and has_translation:
        return "ok"
    if not has_meanings and not has_translation:
        return "no_meanings_no_translation"
    if not has_meanings:
        return "no_meanings"
    return "no_translation"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-txt", default = "english_words.txt", help="Text file containing one word per line")
    parser.add_argument("--output-json", default = "english_dictionary.json", help="Output JSON file")
    parser.add_argument(
        "--max-senses",
        type=int,
        default=None,
        help="Maximum number of senses to keep",
    )
    args = parser.parse_args()

    nltk.download("wordnet", quiet=True)
    nltk.download("omw-1.4", quiet=True)

    input_file = Path(args.input_txt)
    output_file = Path(args.output_json)

    words = read_words(input_file)
    results = load_json(output_file)

    pending_words = [
        word for word in words if normalize_word(word) not in results
    ]

    print(f"Total words  : {len(words)}")
    print(f"Already done : {len(results)}")
    print(f"Remaining    : {len(pending_words)}")
    print()

    for word in tqdm(pending_words, desc="Processing", unit="word"):
        key = normalize_word(word)

        senses = get_senses(word, args.max_senses)
        greek_translation = get_greek_translation(word)

        results[key] = {
            "input_word": word,
            "greek_translation": greek_translation,
            "senses": senses,
            "status": build_status(senses, greek_translation),
        }

        save_json_atomic(output_file, results)

    print(f"\nFinished! Saved {len(results)} words to '{output_file}'.")


if __name__ == "__main__":
    main()
