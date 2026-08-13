#!/usr/bin/env python3
# Fix GIMI mod .ini files: convert legacy ps-t texture lines to RabbitFX format.
#
# Before (unfixed):
#     ps-t0 = ResourceSeeleHairADiffuse.0
#     ps-t1 = ResourceSeeleHairALightMap.0
#
# After (fixed):
#     Resource\RabbitFX\Diffuse  = ref ResourceSeeleHairADiffuse.0
#     Resource\RabbitFX\LightMap = ref ResourceSeeleHairALightMap.0
#     ...
# run = CommandList\RabbitFX\SetTextures   <- appended once per CommandList section
#
# Supported map types (matched case-insensitively against the resource name):
#     *Diffuse*     -> Resource\RabbitFX\Diffuse
#     *LightMap*    -> Resource\RabbitFX\LightMap
#     *NormalMap*   -> Resource\RabbitFX\NormalMap
#     *StockingMap* -> Resource\RabbitFX\StockingMap
#
# Usage:
#     python fix_rabbitmods.py [directory] [--dry-run]
#
#     directory  Root folder to search recursively (default: current directory)
#     --dry-run  Preview changes without writing anything
#
# Backup:
#     The original file is copied to DISABLED_OLD_<filename>.ini before edits.

import argparse
import re
import shutil
from pathlib import Path

ERROR_STR:str = "\033[1m\033[0;31mError:\033[0m"
WARN_STR:str  = "\033[1m\033[1;33mWarning:\033[0m"

# ── map-type detection ────────────────────────────────────────────────────────
# Tuples of (lowercase keyword, exact RabbitFX resource name).
# Order matters: more specific entries first so "stockingmap" doesn't match
# before "normalmap", etc.
MAP_KEYWORDS: list[tuple[str, str]] = [
    ("stockingmap", "StockingMap"),
    ("normalmap",   "NormalMap"),
    ("lightmap",    "LightMap"),
    ("diffuse",     "Diffuse"),
]

RABBIT_RUN_LINE = r"run = Commandlist\RabbitFX\SetTextures"

# Regex patterns
RE_SECTION   = re.compile(r"^\[([^\]]+)\]$")          # [SectionName]
RE_PS_T      = re.compile(r"^(\s*)ps-t\d+\s*=\s*(\S+)", re.IGNORECASE)
RE_COMMENT   = re.compile(r"^\s*;")


def detect_map_type(resource_name: str) -> str | None:
    """Return the RabbitFX map name for a resource, or None if unrecognised."""
    lower = resource_name.lower()
    for keyword, rabbit_name in MAP_KEYWORDS:
        if keyword in lower:
            return rabbit_name
    return None


# ── core logic ────────────────────────────────────────────────────────────────

def split_into_sections(lines: list[str]) -> list[tuple[str | None, list[str]]]:
    """
    Split file lines into (section_name, [lines]) chunks.
    Lines before the first header get section_name = None.
    The header line itself is included in the section's line list.
    """
    sections: list[tuple[str | None, list[str]]] = []
    current_name: str | None = None
    current_lines: list[str] = []

    for line in lines:
        bare = line.strip()
        # A real section header: not a comment, starts/ends with [ ]
        m = RE_SECTION.match(bare)
        if m and not RE_COMMENT.match(line):
            sections.append((current_name, current_lines))
            current_name = m.group(1)
            current_lines = [line]
        else:
            current_lines.append(line)

    sections.append((current_name, current_lines))
    return sections


def fix_commandlist_section(sec_lines: list[str]) -> tuple[list[str], bool]:
    """
    Process lines belonging to a CommandList section.
    Returns (new_lines, was_modified).
    """
    new_lines: list[str] = []
    had_replacement = False

    # Check whether run line already present (idempotent)
    already_has_run = any(
        RABBIT_RUN_LINE.lower() in ln.lower() for ln in sec_lines
    )

    for line in sec_lines:
        # Leave comments untouched
        if RE_COMMENT.match(line):
            new_lines.append(line)
            continue

        m = RE_PS_T.match(line)
        if m:
            indent       = m.group(1)
            resource     = m.group(2)
            map_type     = detect_map_type(resource)

            if map_type:
                new_line = (
                    f"{indent}Resource\\RabbitFX\\{map_type}"
                    f" = ref {resource}\n"
                )
                new_lines.append(new_line)
                had_replacement = True
                continue
            # Unknown map type – comment the line out
            new_lines.append(f"{indent};{line.lstrip()}")
            had_replacement = True
        else:
            new_lines.append(line)

    # Append the run line once, just before any trailing blank/comment lines
    if had_replacement and not already_has_run:
        insert_at = len(new_lines)
        while insert_at > 1 and (
            new_lines[insert_at - 1].strip() == ""
            or RE_COMMENT.match(new_lines[insert_at - 1])
        ):
            insert_at -= 1
        new_lines.insert(insert_at, RABBIT_RUN_LINE + "\n")

    return new_lines, had_replacement


def process_content(content: str) -> tuple[str, bool]:
    """
    Apply the RabbitFX fix to the full ini text.
    Returns (fixed_content, any_changes_made).
    """
    lines    = content.splitlines(keepends=True)
    sections = split_into_sections(lines)

    result_lines: list[str] = []
    any_modified = False

    for section_name, sec_lines in sections:
        # Apply fix to any section that contains uncommented ps-t lines,
        # regardless of whether it is a CommandList or TextureOverride section.
        has_ps_t = any(
            RE_PS_T.match(ln)
            for ln in sec_lines
            if not RE_COMMENT.match(ln)
        )

        if has_ps_t:
            fixed_lines, changed = fix_commandlist_section(sec_lines)
            result_lines.extend(fixed_lines)
            if changed:
                any_modified = True
        else:
            result_lines.extend(sec_lines)

    return "".join(result_lines), any_modified


def file_needs_fix(content: str) -> bool:
    """Quick check: does the file contain any uncommented ps-t lines?"""
    for line in content.splitlines():
        if RE_COMMENT.match(line):
            continue
        if RE_PS_T.match(line):
            return True
    return False


# ── file-level operations ─────────────────────────────────────────────────────

def fix_file(ini_path: Path, dry_run: bool = False) -> bool:
    """
    Fix a single .ini file in-place.
    Returns True if the file was (or would be) modified.
    """
    try:
        content = ini_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"  [ERROR] Cannot read {ini_path}: {exc}")
        return False

    if not file_needs_fix(content):
        return False

    new_content, modified = process_content(content)

    if not modified:
        return False

    if dry_run:
        print(f"  [DRY RUN] Would fix: {ini_path}")
        return True

    backup_path = ini_path.parent / f"DISABLED_OLD_{ini_path.name}"

    # Safety: don't overwrite an existing backup
    if backup_path.exists():
        print(f"  [SKIP]  Backup already exists, skipping: {ini_path}")
        print(f"           (backup: {backup_path})")
        return False

    shutil.copy2(ini_path, backup_path)
    ini_path.write_text(new_content, encoding="utf-8")

    print(f"  [FIXED] {ini_path}")
    print(f"           Backup → {backup_path.name}")
    return True

def fix(mod_path, is_dry_run):
    print("Fixing mod with RabbitFx..")
    print(f"{WARN_STR}: Need RabbitFx. Download it here ( https://gamebanana.com/mods/608041 ).")

    root = Path(mod_path).resolve()
    if not root.exists():
        print(f"Error: '{root}' does not exist.")
        return

    print(f"Searching for .ini files under: {root}")
    if is_dry_run:
        print("(DRY RUN – no files will be modified)\n")
    else:
        print()

    fixed   = 0
    skipped = 0
    errors  = 0

    for ini_file in sorted(root.rglob("*.ini")):
        # Never process our own backup files
        if ini_file.name.startswith("DISABLED_OLD_"):
            continue

        try:
            result = fix_file(ini_file, dry_run=is_dry_run)
            if result:
                fixed += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR] {ini_file}: {exc}")
            errors += 1

    print()
    print("─" * 50)
    print(f"Fixed  : {fixed}")
    print(f"Skipped: {skipped}  (no fix needed)")
    if errors:
        print(f"Errors : {errors}")
    print("─" * 50)