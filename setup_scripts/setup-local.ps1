# Always run from the project root.
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "Setting up local dictionaries..."

# Extract JSON dictionaries if they don't already exist.
if (-not (Test-Path "words\greek_dictionary.json")) {
    Write-Host "Extracting Greek dictionary..."
    tar -xzf "words\greek_dictionary.json.gz"
}

if (-not (Test-Path "words\english_dictionary.json")) {
    Write-Host "Extracting English dictionary..."
    tar -xzf "words\english_dictionary.json.gz"
}

# Keep local .txt and .json files changes out of Git status.
Write-Host "Configuring local words files..."
git ls-files "words/*.txt" | ForEach-Object {
    git update-index --skip-worktree $_
}
git ls-files "words/*.json" | ForEach-Object {
    git update-index --skip-worktree $_
}

Write-Host "Local setup complete."
