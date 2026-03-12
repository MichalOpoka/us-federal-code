# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

US Federal Code in Markdown format. This is a data-only repository with no build system, tests, or CI. Content is generated externally by the [lawlab](https://github.com/AlextheYounga/lawlab) tool — do not manually edit content under `usc/`.

## Structure

- `usc/` — All legal code content, organized as `title-N-name/subtitle-.../chapter-.../sec-N.md`
- `scripts/` — Utility scripts
- Each directory contains a `frontmatter.md` with introductory text; individual law sections are `sec-*.md` files

## Scripts

### Windows Path Validator
```
# Check specific paths
python scripts/check_windows_paths.py path1 path2

# Pipe from git (do NOT run on entire repo without filtering)
git ls-files | head -50 | python scripts/check_windows_paths.py
```
Validates paths against Windows filesystem limitations (invalid chars, reserved names, path length >240, case collisions). Exits 0 if clean, 1 if issues found.

### Windows Path Fixer
```
# Dry-run on specific paths (shows planned renames)
python scripts/fix_windows_paths.py "usc/title-18-crimes-and-criminal-procedure/..."

# Dry-run on entire repo
python scripts/fix_windows_paths.py --all

# Apply renames using git mv
python scripts/fix_windows_paths.py --all --apply
```
Fixes Windows-incompatible paths by shortening directory names (strips descriptive suffixes, keeping only type prefix + identifier, e.g. `chapter-401-general-provisions` → `chapter-401`) and decoding HTML entities. Dry-run by default; use `--apply` to execute via `git mv`.

### Windows Path Issue Counter
```
python scripts/count_windows_path_issues.py
```
Scans the entire repo via `git ls-files` and prints a compact summary of issue counts by type (e.g. `path-too-long : 3632`). No per-file detail — only `issue : count` lines for types with at least one hit.

## Key Constraints

- Pull requests are not accepted; changes should be proposed via GitHub issues
- The repo has ~70k files with deeply nested paths (up to 486 characters) — avoid operations that enumerate all files unnecessarily
- Content files should not be edited directly; they are generated from the lawlab tool
