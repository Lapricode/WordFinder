import argparse
import nltk
from nltk.corpus import wordnet as wn
from deep_translator import GoogleTranslator

# Download WordNet the first time you run the script
nltk.download("wordnet", quiet=True)

def get_definition(word):
    """Return the first English definition of the word."""
    synsets = wn.synsets(word)

    if not synsets:
        return "No definition found."

    return synsets[0].definition()


def get_greek_translation(word):
    """Translate an English word to Greek."""
    try:
        return GoogleTranslator(source="en", target="el").translate(word)
    except Exception as e:
        return f"Translation failed: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="Translate an English word to Greek and show its English definition."
    )
    parser.add_argument("word", help="English word")

    args = parser.parse_args()
    word = args.word.lower()

    print(f"\nWord: {word}")
    print("-" * 40)

    definition = get_definition(word)
    # translation = get_greek_translation(word)

    print(f"Definition : {definition}")
    # print(f"Greek      : {translation}")


if __name__ == "__main__":
    main()
