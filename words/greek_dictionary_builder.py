import argparse
import json
import os
from pathlib import Path

from charset_normalizer import from_path
from deep_translator import GoogleTranslator
from tqdm import tqdm


def normalize_word(word: str) -> str:
    return word.strip().lower()


def get_english_translation(word: str) -> str | None:
    """
    Translate a Greek word to English.
    """
    try:
        translator = GoogleTranslator(source="el", target="en")
        return translator.translate(word)
    except Exception:
        return None


def read_words(path: Path) -> list[str]:
    """
    Automatically detect the encoding of the input file.
    """
    result = from_path(path).best()

    if result is None:
        raise RuntimeError(f"Could not determine the encoding of {path}")

    encoding = result.encoding
    print(f"Detected input encoding: {encoding}")

    with path.open("r", encoding=encoding) as f:
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


def save_json_atomic(path: Path, data: dict):
    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp, path)


def build_status(translation: str | None) -> str:
    if translation:
        return "ok"
    return "no_translation"


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input-txt",
        default="greek_words.txt",
        help="Text file containing one Greek word per line",
    )
    parser.add_argument(
        "--output-json",
        default = "greek_dictionary.json",
        help="Output JSON file",
    )

    args = parser.parse_args()

    input_file = Path(args.input_txt)
    output_file = Path(args.output_json)

    words = read_words(input_file)
    results = load_json(output_file)

    pending_words = [
        word
        for word in words
        if normalize_word(word) not in results
    ]

    print(f"Total words  : {len(words)}")
    print(f"Already done : {len(results)}")
    print(f"Remaining    : {len(pending_words)}")
    print()

    translator = GoogleTranslator(source="el", target="en")

    for word in tqdm(pending_words, desc="Processing", unit="word"):
        key = normalize_word(word)

        try:
            translation = translator.translate(word)
        except Exception:
            translation = None

        results[key] = {
            "input_word": word,
            "english_translation": translation,
            "status": build_status(translation),
        }

        save_json_atomic(output_file, results)

    print(f"\nFinished! Saved {len(results)} words to '{output_file}'.")


if __name__ == "__main__":
    main()
