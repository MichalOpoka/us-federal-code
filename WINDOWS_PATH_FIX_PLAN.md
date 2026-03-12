# Plan: Fix All Windows-Incompatible Paths

## Problem

The repo has 4,493 Windows-incompatible paths:
- **861** paths contain invalid characters (colons `:` in directory names)
- **3,632** paths exceed the 240-character length limit

Root cause: directory names include long descriptive suffixes (e.g., `chapter-401-general-provisions`) and some contain colons from legal titles.

## Solution

`scripts/fix_windows_paths.py` strips descriptive suffixes from directory names, keeping only the type prefix and identifier. This fixes both issues simultaneously — colons are always in the description portion, and shortened names dramatically reduce path lengths.

Examples:
- `title-18-crimes-and-criminal-procedure` → `title-18`
- `chapter-51-reserve-components:-standards-and-procedures-for-retention-and-promotion` → `chapter-51`
- `subchapter-iii-assistance-to-public-and-nonprofit-institutions-...` → `subchapter-iii`

HTML entities in names (`&apos;`, `&mdash;`, `&#160;`) are also decoded and normalized.

## Scope

- **9,280 directories** to rename under `usc/`
- **0 files** need renaming (sec files and frontmatter.md already have short names)
- **0 file content changes** needed (all cross-references are text-based legal citations, not file path links)

## Steps

### 1. Verify dry-run output

```bash
python scripts/fix_windows_paths.py --all
```

Review the output to confirm renames look correct. Check for any collision warnings.

### 2. Apply renames

```bash
python scripts/fix_windows_paths.py --all --apply
```

This uses `git mv` for each rename, so git tracks all moves. Runs top-down (parents first), which means renaming a parent directory automatically moves all its children.

### 3. Verify no remaining issues

```bash
python scripts/count_windows_path_issues.py
```

Expected output: no issues (or `invalid-char` and `path-too-long` counts should be 0).

### 4. Spot-check paths

```bash
# Verify a previously problematic path is now short
ls usc/title-10/subtitle-a/part-ii/chapter-51/

# Verify the longest paths are now within limits
git ls-files | awk '{ print length, $0 }' | sort -rn | head -5
```

### 5. Commit

```bash
git add -A
git commit -m "Shorten directory names for Windows compatibility

Rename 9,280 directories by stripping descriptive suffixes from names,
keeping only the type prefix and identifier (e.g., chapter-401-general-provisions
becomes chapter-401). This resolves all 861 invalid-character issues (colons)
and all 3,632 path-too-long issues."
```

## Risks and Rollback

- **Rollback**: `git reset --hard HEAD~1` reverts everything since all renames are tracked by git
- **No content changes**: file contents are untouched, only directory names change
- **No collisions detected**: dry-run confirms no two directories within the same parent shorten to the same name
