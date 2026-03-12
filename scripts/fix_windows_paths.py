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


def compute_all_renames(root, apply=False):
    """Compute (and optionally apply) all renames needed under root.

    Uses os.walk top-down. In apply mode, renames are executed immediately
    via git mv, and dirnames is updated so os.walk descends into renamed dirs.
    In dry-run mode, a path_xlat map tracks planned parent renames for display.
    """
    renames = []
    # In dry-run mode, maps actual filesystem dirpath -> display dirpath
    display_map = {root: root}

    for dirpath, dirnames, _filenames in os.walk(root, topdown=True):
        display_dirpath = display_map.get(dirpath, dirpath) if not apply else dirpath

        new_dirnames = []
        for d in dirnames:
            new_name = fix_component(d)
            actual_full = os.path.join(dirpath, d)
            if new_name != d:
                old_path = os.path.join(display_dirpath, d)
                new_path = os.path.join(display_dirpath, new_name)
                renames.append((old_path, new_path))
                if apply:
                    apply_rename(actual_full, os.path.join(dirpath, new_name))
                else:
                    display_map[actual_full] = new_path
            else:
                if not apply:
                    display_map[actual_full] = os.path.join(display_dirpath, d)
            new_dirnames.append(new_name if apply else d)

        if apply:
            dirnames[:] = new_dirnames
        # In dry-run, leave dirnames unchanged so os.walk can descend

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

        if args.apply:
            # Pre-scan for collisions before applying
            print(f"Scanning {root}/ for collisions...", file=sys.stderr)
            dry_renames = compute_all_renames(root, apply=False)
            collisions = check_collisions(dry_renames)
            if collisions:
                print(f"\n{red}{bold}Collision detected! These directories would have the same name:{reset}")
                for path1, path2, name in collisions:
                    print(f"  {path1}")
                    print(f"  {path2}")
                    print(f"  -> both shorten to: {name}")
                print(f"\n{red}Aborting — resolve collisions first.{reset}")
                sys.exit(1)

            print(f"Applying renames...", file=sys.stderr)
            all_renames = compute_all_renames(root, apply=True)
            print(f"\n{green}{len(all_renames)} directories renamed successfully.{reset}")
            return

        print(f"Scanning {root}/ ...", file=sys.stderr)
        all_renames = compute_all_renames(root, apply=False)

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
    print(f"\n{yellow}Dry run — no changes made. Use --apply to execute renames.{reset}")


if __name__ == "__main__":
    main()
