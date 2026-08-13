#!/usr/bin/env bash

set -e

# Always run from the project root.
cd "$(dirname "$0")/.."

echo "Setting up local dictionaries..."

# Extract JSON dictionaries if they don't already exist.
if [ ! -f words/greek_dictionary.json ]; then
    echo "Extracting Greek dictionary..."
    gzip -dk words/greek_dictionary.json.gz
fi

if [ ! -f words/english_dictionary.json ]; then
    echo "Extracting English dictionary..."
    gzip -dk words/english_dictionary.json.gz
fi

# Keep local .txt and .json words files changes out of Git status.
echo "Configuring local words files..."
git ls-files 'words/*.txt' -z | xargs -0 git update-index --skip-worktree
git ls-files 'words/*.json' -z | xargs -0 git update-index --skip-worktree

echo "Local setup complete."
