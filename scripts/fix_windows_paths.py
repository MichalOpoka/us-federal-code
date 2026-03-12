#!/usr/bin/env python3
"""Fix Windows-incompatible paths in the usc/ directory.

Shortens directory names by stripping descriptive suffixes (keeping only
type prefix + identifier) and decodes HTML entities. This resolves both
invalid-character and path-too-long issues for Windows compatibility.

Usage:
    # Dry-run on specific paths (shows planned renames)
    python scripts/fix_windows_paths.py "usc/title-18-crimes-and-criminal-procedure/..."

    # Dry-run on entire repo
    python scripts/fix_windows_paths.py --all

    # Actually apply renames (uses git mv)
    python scripts/fix_windows_paths.py --all --apply
"""

import argparse
import html
import os
import re
import subprocess
import sys
import unicodedata

# Matches directory names with a known type prefix, identifier, and descriptive suffix.
# Groups: (1) prefix like "chapter", (2) identifier like "-401" or "-iv"
SHORTEN_RE = re.compile(
    r'^(title|subtitle|division|part|subpart|chapter|subchapter|subdivision)'
    r'(-(?:[0-9]+[a-z]?|[a-z]+))'
    r'(-.+)$'
)

# Special case for "chapters-N-through-N-description"
CHAPTERS_RE = re.compile(
    r'^(chapters-[0-9]+[a-z]?)'
    r'((?:\s|&#160;)?-?through-[0-9]+[a-z]?)'
    r'(-.+)$'
)

# HTML entity pattern for detection
HTML_ENTITY_RE = re.compile(r'&[a-zA-Z]+;|&#[0-9]+;|&#x[0-9a-fA-F]+;')


def shorten_component(name):
    """Shorten a single directory/file name component by stripping descriptions."""
    # Don't touch files (only directories need shortening)
    # Don't touch bracketed names like [sec-5002, [chapter-402-repealed]
    # Don't touch secs-* directories (already short)
    if name.startswith('[') or name.startswith('secs-'):
        return name

    # Special case: chapters-N-through-N-description
    m = CHAPTERS_RE.match(name)
    if m:
        return m.group(1) + m.group(2).replace('&#160;', '').replace('\xa0', '')

    # General case: type-identifier-description
    m = SHORTEN_RE.match(name)
    if m:
        return m.group(1) + m.group(2)

    return name


def decode_entities(name):
    """Decode HTML entities and normalize to ASCII-safe characters."""
    if '&' not in name and '\xa0' not in name:
        return name

    # Decode HTML entities
    decoded = html.unescape(name)

    # Normalize unicode to ASCII where possible
    # NFKD decomposes characters (e.g., É -> E + combining accent)
    normalized = unicodedata.normalize('NFKD', decoded)

    # Keep only ASCII characters, hyphens, dots, brackets, and digits
    result = []
    for ch in normalized:
        if ch.isascii() and (ch.isalnum() or ch in '-_.[]'):
            result.append(ch)
        elif unicodedata.category(ch).startswith('M'):
            # Skip combining marks (accents)
            continue
        elif ch in ('\xa0', '\u00a0'):
            # Non-breaking space -> remove
            continue
        elif ch == '\u2014':  # em dash
            result.append('-')
        elif ch == '\u2019' or ch == '\u2018':  # smart quotes
            result.append("'")
        # Skip other non-ASCII silently

    cleaned = ''.join(result)
    # Collapse multiple consecutive hyphens
    cleaned = re.sub(r'-{2,}', '-', cleaned)
    # Remove trailing hyphens
    cleaned = cleaned.rstrip('-')
    return cleaned


def fix_component(name):
    """Apply both shortening and entity decoding to a path component."""
    shortened = shorten_component(name)
    decoded = decode_entities(shortened)
    return decoded


def compute_renames_for_path(path):
    """Compute renames needed for a single path (all its directory components).

    Returns a list of (old_path, new_path) tuples for directories that need renaming,
    ordered from shallowest to deepest.
    """
    parts = path.split('/')
    renames = []
    old_prefix = []
    new_prefix = []

    for i, part in enumerate(parts):
        old_prefix.append(part)

        # Don't shorten files (last component if it has an extension)
        if i == len(parts) - 1 and '.' in part:
            new_prefix.append(part)
            continue

        new_part = fix_component(part)
        new_prefix.append(new_part)

        if new_part != part:
            renames.append(('/'.join(old_prefix), '/'.join(new_prefix)))

    return renames


def collect_directories(root):
    """Walk the directory tree and collect all directory paths relative to cwd."""
    dirs = []
    for dirpath, dirnames, _filenames in os.walk(root):
        for d in dirnames:
            dirs.append(os.path.join(dirpath, d))
    return dirs


def compute_all_renames(root):
    """Compute all renames needed for the entire tree under root.

    Processes top-down by depth. Each directory that needs renaming gets an
    entry. Parent renames are tracked so child paths use the correct
    (already-renamed) parent path.
    """
    all_dirs = collect_directories(root)
    # Sort by depth (shallowest first) for top-down processing
    all_dirs.sort(key=lambda p: p.count('/'))

    renames = []  # (old_path, new_path) — old_path is the path AFTER parent renames
    # Maps original path prefixes to their renamed versions
    prefix_map = {}  # original_path -> renamed_path

    for d in all_dirs:
        name = os.path.basename(d)
        new_name = fix_component(name)

        # Compute the actual current path of the parent (after prior renames)
        parent_dir = os.path.dirname(d)
        actual_parent = parent_dir
        # Find the longest matching prefix that was renamed
        best_match = ''
        for orig, renamed in prefix_map.items():
            if (parent_dir == orig or parent_dir.startswith(orig + '/')) and len(orig) > len(best_match):
                best_match = orig
        if best_match:
            actual_parent = prefix_map[best_match] + parent_dir[len(best_match):]

        if new_name != name:
            old_path = os.path.join(actual_parent, name)
            new_path = os.path.join(actual_parent, new_name)
            renames.append((old_path, new_path))
            # Track this rename so children use the new path
            prefix_map[d] = os.path.join(actual_parent, new_name)
        elif best_match:
            # Parent was renamed but this dir wasn't — still track for children
            prefix_map[d] = os.path.join(actual_parent, name)

    return renames


def check_collisions(renames):
    """Check if any renames would create collisions within the same parent."""
    # Group by parent directory
    by_parent = {}
    for old_path, new_path in renames:
        parent = os.path.dirname(new_path)
        new_name = os.path.basename(new_path)
        by_parent.setdefault(parent, []).append((old_path, new_name))

    collisions = []
    for parent, entries in by_parent.items():
        seen = {}
        for old_path, new_name in entries:
            lower = new_name.lower()
            if lower in seen:
                collisions.append((old_path, seen[lower], new_name))
            else:
                seen[lower] = old_path

    return collisions


def apply_rename(old_path, new_path):
    """Execute a rename using git mv."""
    result = subprocess.run(
        ['git', 'mv', old_path, new_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR: git mv failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def main():
    use_color = sys.stdout.isatty()
    green = "\033[0;32m" if use_color else ""
    yellow = "\033[0;33m" if use_color else ""
    red = "\033[0;31m" if use_color else ""
    bold = "\033[1m" if use_color else ""
    reset = "\033[0m" if use_color else ""

    parser = argparse.ArgumentParser(
        description="Fix Windows-incompatible paths by shortening directory names.",
    )
    parser.add_argument(
        'paths', nargs='*',
        help='Specific paths to compute renames for (dry-run).',
    )
    parser.add_argument(
        '--all', action='store_true',
        help='Process entire usc/ directory.',
    )
    parser.add_argument(
        '--apply', action='store_true',
        help='Actually perform renames using git mv (default: dry-run).',
    )
    args = parser.parse_args()

    if not args.paths and not args.all:
        parser.print_help(sys.stderr)
        sys.exit(2)

    if args.paths:
        # Single-path mode: show renames for each given path
        all_renames = []
        for path in args.paths:
            path = path.rstrip('/')
            renames = compute_renames_for_path(path)
            all_renames.extend(renames)

        if not all_renames:
            print(f"{green}No renames needed — all paths are already short.{reset}")
            return

        # Deduplicate (same directory could appear in multiple input paths)
        seen = set()
        unique_renames = []
        for old, new in all_renames:
            if old not in seen:
                seen.add(old)
                unique_renames.append((old, new))
        all_renames = unique_renames

    else:
        # --all mode: walk the entire usc/ tree
        root = 'usc'
        if not os.path.isdir(root):
            print(f"Error: '{root}' directory not found.", file=sys.stderr)
            sys.exit(1)

        print(f"Scanning {root}/ ...", file=sys.stderr)
        all_renames = compute_all_renames(root)

        if not all_renames:
            print(f"{green}No renames needed — all paths are already short.{reset}")
            return

    # Check for collisions
    collisions = check_collisions(all_renames)
    if collisions:
        print(f"\n{red}{bold}Collision detected! These directories would have the same name:{reset}")
        for path1, path2, name in collisions:
            print(f"  {path1}")
            print(f"  {path2}")
            print(f"  -> both shorten to: {name}")
        if args.apply:
            print(f"\n{red}Aborting — resolve collisions first.{reset}")
            sys.exit(1)

    # Display renames
    for old_path, new_path in all_renames:
        old_name = os.path.basename(old_path)
        new_name = os.path.basename(new_path)
        parent = os.path.dirname(old_path)
        if parent:
            print(f"  {parent}/{yellow}{old_name}{reset} -> {green}{new_name}{reset}")
        else:
            print(f"  {yellow}{old_name}{reset} -> {green}{new_name}{reset}")

    print(f"\n{bold}{len(all_renames)} director{'y' if len(all_renames) == 1 else 'ies'} to rename{reset}")

    if not args.apply:
        print(f"\n{yellow}Dry run — no changes made. Use --apply to execute renames.{reset}")
        return

    # Apply renames
    print(f"\nApplying renames...")
    success = 0
    failed = 0
    for old_path, new_path in all_renames:
        if apply_rename(old_path, new_path):
            success += 1
        else:
            failed += 1

    print(f"\n{green}{success} renamed successfully.{reset}")
    if failed:
        print(f"{red}{failed} failed.{reset}")
        sys.exit(1)


if __name__ == "__main__":
    main()
