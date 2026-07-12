from pathlib import Path

ENGLISH_LETTERS = {chr(c) for c in range(ord("a"), ord("z") + 1)}
ENGLISH_LETTERS |= {ch.upper() for ch in ENGLISH_LETTERS}

input_file = Path("words.txt")
# input_file = Path("english_words.txt")
output_file = Path("output.txt")


def is_english_letters_only(word: str) -> bool:
    return bool(word) and all(ch in ENGLISH_LETTERS for ch in word)

words = set()

with input_file.open("r", encoding="utf-8") as f:
    for line in f:
        word = line.strip()

        if not is_english_letters_only(word):
            continue

        # Convert words like "APPLE" -> "apple"
        if word.isupper():
            word = word.lower()

        words.add(word)

with output_file.open("w", encoding="utf-8") as f:
    for word in sorted(words, key=str.lower):
        f.write(word + "\n")
