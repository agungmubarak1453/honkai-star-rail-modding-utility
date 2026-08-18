#!/usr/bin/env python3

# MARK: Script Helpers

import os
import urllib.request

from pathlib import Path

LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "https://raw.githubusercontent.com/agungmubarak1453/honkai-star-rail-modding-utility/main/") 
LOCAL_DIR = os.getenv("LOCAL_DIR")

def get_script(script_path, namespace={}):
    workspace_dir = ""
    
    if LOCAL_MODE:
        script_file = os.path.join(LOCAL_DIR + workspace_dir, script_path)

        print(f"Loading local script: {script_file}")

        with open(script_file, "rb") as f:
            source = f.read()

        filename = script_file
    else:
        script_url = BASE_URL + workspace_dir + script_path

        print(f"Fetching script: {script_url}")

        source = urllib.request.urlopen(script_url).read()
        filename = script_url

    code = compile(source, filename, "exec")

    exec(code, namespace)

    return namespace

# MARK: Body

# Written by petrascyll
#   thanks to zlevir for help dumping and adding fixes during 2.3
#     thanks to sora_ for help collecting the vertex explosion extra position hashes
#     and AGMG discord and everone there for being helpful
# 
# HSR Version 3.0 Fix
#     - Updates all outdated HSR character mods from HSRv1.6 up to HSRv3.0
#     - Edits Caelus mods to work on both Destruction/Preservation paths.
#     - Adds the extra position hash on the mods that need it.
# 
# .exe Fofo icon source: https://www.hoyolab.com/article/22866306
# 

# MARK: BatchedP Fix Start
"""Script to patch ini files to account for new Posing method in HSR 3.2"""

import os
import re
import time
import struct
import argparse
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from textwrap import dedent
import math
from typing import Optional

os.system('') # I hate powershell <3
ERROR_STR:str = "\033[1m\033[0;31mError:\033[0m"
WARN_STR:str  = "\033[1m\033[1;33mWarning:\033[0m"

input_output_manager = get_script("tools/general/input_output_manager.py")

# "NamePart" : (blend_hash, draw_hash, pos_hash)
VALID_HASH_TRIOS = input_output_manager["load_json_data"]("datas/forked_valid_hashes.json")

@dataclass
class INI_Line:
    """Class to represent a line in an ini file"""

    key: str
    value: str
    is_value_pair: bool
    _stripped_lower_key: str = field(init=False, repr=False)
    _stripped_lower_value: str = field(init=False, repr=False)

    def __setattr__(self, name, value)-> None:
        """Override the __setattr__ method to strip and lowercase the key and value"""
        if name == "key":
            self._stripped_lower_key = value.strip().lower()
        elif name == "value":
            self._stripped_lower_value = value.strip().lower()
        super().__setattr__(name, value)

    def has_key(self, key: str) -> bool:
        """Check if the line has a specific key"""
        return self._stripped_lower_key == key.strip().lower()
    
    def key_startswith(self, key: str) -> bool:
        """Check if the line key starts with a specific string"""
        return self._stripped_lower_key.startswith(key.strip().lower())


@dataclass
class Section:
    """Class to represent a section in an ini file"""

    name: str
    lines: list[INI_Line]
    is_header: bool = False

    def has_name(self, name: str) -> bool:
        """Check if the section has a specific name"""
        return self.name.strip().lower()[1:].strip("]") == name.strip().lower()
    
    def name_startswith(self, name: str) -> bool:
        """Check if the section name starts with a specific string"""
        if len(self.name) == 0:
            return False
        return self.name.strip().lower()[1:].startswith(name.strip().lower())

    def add_lines(self, lines: str) -> None:
        """Add lines to the section"""
        self.clear_empty_ending_lines()
        for line in lines.splitlines(keepends=True):
            self.add_single_line(line)
        # we sanitize last line to have no more or less than 1 empty line at the end
        self.clear_empty_ending_lines()
        self.add_single_line("\n\n")

    def add_single_line(self, line: str) -> None:
        key_value: list[str] = line.split("=")
        if len(key_value) == 2:
            key: str = key_value[0]
            value: str = key_value[1]
            self.lines.append(INI_Line(key=key, value=value, is_value_pair=True))
        else:
            self.lines.append(INI_Line(key=line, value="", is_value_pair=False))

    def clear_empty_ending_lines(self) -> None:
        """Remove empty lines at the end of the section"""
        while self.lines and self.lines[-1].key.strip() == "":
            self.lines.pop()

    def comment_out(self) -> None:
        """Comment out the section"""
        self.clear_empty_ending_lines()
        self.name = f";{self.name}"
        for line in self.lines:
            line.key = f";{line.key}"
        self.add_single_line("\n\n")


@dataclass
class Resource:
    name: str
    type: str
    filename: str
    stride: int = 0


@dataclass
class ModelData:
    """Class to represent model data for a character"""

    part_name: str
    blend_resource: Resource
    pos_resource: Resource
    ref_draw_hash: str
    ref_blend_hash: str
    vertcount: int
    blend_consumed: bool = False
    draw_consumed: bool = False
    res_consumed: bool = False


@dataclass
class CommandListCandidate:
    """Class to represent a command list candidate"""
# tuple[bool, Optional[Section], str]
    has_vb0: bool = False
    command_list: Optional[Section] = None
    draw_hash: str = ""
    blend_hash: str = ""
    draw_section_patched: bool = False

def clean_up_indentation(content: str, to_print:list[str]) -> str:
    """Clean up indentation in the ini file content"""
    sections:list[Section] = split_in_sections(content)
    for s in sections:
        s.name = s.name.lstrip()
        depth:int  = 0
        for line in s.lines:
            if line._stripped_lower_key == "":
                continue
            if line.key_startswith("if"):
                depth += 1
            elif line.key_startswith("endif"):
                depth -= 1
            if line.key_startswith("if") or line.key_startswith("elif") or line.key_startswith("else"):
                line.key = "\t" * (depth - 1)  + line.key.lstrip()
            else:
                line.key = "\t" * depth  + line.key.lstrip()
            # line.key = str(depth) + line.key
        s.clear_empty_ending_lines()
        s.add_single_line("\n")

    content = reconstruct_ini_file(sections)
    return content

def split_in_sections(content: str) -> list[Section]:
    """Split the content into sections based on [section] headers"""
    sections: list[Section] = []
    lines: list[str] = content.splitlines(keepends=True)
    curr_section: Section = Section(name="", lines=[], is_header=True)

    for line in lines:
        stripped_line = line.strip()
        if stripped_line.startswith("[") and stripped_line.endswith("]"):
            if curr_section:
                sections.append(curr_section)
            section_name: str = line
            curr_section = Section(name=section_name, lines=[])
            continue
        curr_section.add_single_line(line)
    if curr_section:
        sections.append(curr_section)

    return sections


def reconstruct_ini_file(sections: list[Section]) -> str:
    """Reconstruct the ini file from sections"""
    content: list[str] = []
    for section in sections:
        if not section.is_header:
            content.append(section.name)
        for line in section.lines:
            if line.is_value_pair:
                content.append(f"{line.key}={line.value}")
                continue
            content.append(line.key)
    return "".join(content)


def backup_and_write(
    old_body: str, new_body: str, file_path: Path, to_print: list[str]
) -> None:
    """Backup the original file and write the new content to it"""
    backup_file_path: Path = file_path.with_suffix(".txt")
    try:
        with open(backup_file_path, "w") as f:
            f.write(old_body)
        with open(file_path, "w") as f:
            f.write(new_body)
    except Exception as e:
        to_print.append(f"Error writing to file: {e}")
        return
    else:
        to_print.append(f"Backup created at {backup_file_path}")


def restore_backup(file_path: Path, to_print: list[str]) -> None:
    """Restore the backup of the ini file"""
    backup_file_path: Path = file_path.with_suffix(".txt")
    if not backup_file_path.exists():
        to_print.append(f"\tNo backup found for {file_path}.")
        return
    try:
        with open(backup_file_path, "r") as f:
            content = f.read()
        with open(file_path, "w") as f:
            f.write(content)
        os.remove(backup_file_path)
    except Exception as e:
        to_print.append(f"\tError restoring backup: {e}")
    else:
        to_print.append(f"\tRestored {file_path} from {backup_file_path}.")


def get_resource_data(section: Section) -> tuple[str, int, str]:
    """Get resource data from a section"""
    name: str = section.name.strip()[1:].strip("]")
    stride: int = 0
    filename: str = ""
    for line in section.lines:
        if line.has_key("stride"):
            stride = int(line.value.strip())
        elif line.has_key("filename"):
            filename = line.value.strip()
    return name, stride, filename


def split_in_ifelse_blocks(lines: list[INI_Line]) -> list[list[INI_Line]]:
    """Split lines into ifelse blocks. Only for depth 0"""
    ifelse_blocks: list[list[INI_Line]] = []
    current_block: list[INI_Line] = []
    depth = -1
    for line in lines:
        if line.key_startswith("if"):
            depth += 1
        elif line.key_startswith("elif") or line.key_startswith("else") or line.key_startswith("elseif"):
            if depth == 0 and current_block:
                ifelse_blocks.append(current_block)
                current_block = []
        elif line.key_startswith("endif"):
            depth -= 1
            if depth == -1 and current_block:
                ifelse_blocks.append(current_block)
                current_block = []
        current_block.append(line)
    if current_block:
        ifelse_blocks.append(current_block)
    return ifelse_blocks

def attempt_commandlist_pos_blend_patch(
        sections:list[Section],
        commandlist:str,
        to_print:list[str],
        parent_section:Section, 
        blend_hash:str) -> bool:
    # separate it in ifelseblocks
    # if itdonthave ifelseblocks we continue normally
    # patch each block
    for section in sections:
        if not section.has_name(commandlist):
            continue
        ifelseblocks:list[list[INI_Line]] = split_in_ifelse_blocks(section.lines)
        if len(ifelseblocks) <= 1:
            to_print.append(f"{WARN_STR} {commandlist} doesn't have if else blocks. Probably not a merge mod...")
            return False
        to_print.append(f"Found {commandlist} with ifelse blocks. Attempting to patch...")
        for block in ifelseblocks:
            ifelse_template: str = """{condition}
handling = skip
vb2 = {blend_resource}
if DRAW_TYPE == 1
    vb0 = {pos_resource}
    draw = {vertcount}, 0
endif
{rest_of_section}"""
            condition:Optional[INI_Line] = None
            blend_resource: str = ""
            pos_resource: str = ""
            vertcount: int = 0
            rest_of_block: list[INI_Line] = []
            if (not (block[0].key_startswith("if")
                    or block[0].key_startswith("else")
                    or block[0].key_startswith("elif")) 
                and len(ifelseblocks) > 1):
                continue
            condition = block[0]
            for line in block[1:]:
                if line.has_key("handling"):
                    continue
                if line.has_key("vb0"):
                    pos_resource = line.value.strip()
                elif line.has_key("vb2"):
                    blend_resource = line.value.strip()
                elif line.has_key("draw"):
                    if "," not in line.value:
                        continue
                    vertcount = int(line.value.split(",", 1)[0].strip())
                else:
                    rest_of_block.append(line)
            
            if pos_resource == "" or blend_resource == "" or vertcount == 0:
                to_print.append(
                    f"{ERROR_STR} Missing resource values in {commandlist} block. Can't patch merge mod."
                )
                continue
            block_str:str = ifelse_template.format(
                condition=condition.key.strip(),
                blend_resource=blend_resource,
                pos_resource=pos_resource,
                vertcount=vertcount,
                rest_of_section=reconstruct_ini_file([Section(name="", lines=rest_of_block, is_header=True)]),
            )
            block.clear()
            temp_section:Section = Section(name="", lines=[], is_header=True)
            temp_section.add_lines(block_str)
            temp_section.clear_empty_ending_lines()
            block.extend(temp_section.lines)

        # reconstruct the section with the new blocks
        section.lines.clear()
        for block in ifelseblocks:
            for line in block:
                section.lines.append(line)
        section.clear_empty_ending_lines()
        section.add_single_line("\n")

        for line in parent_section.lines:
            if line.has_key("hash"):
                line.value =  f" {blend_hash}\n"
        
        parent_section.name = parent_section.name.replace("Position", "Blend", 1)

        to_print.append(f"Patched {commandlist} with blend hash {blend_hash}.")
        return True

    to_print.append(f"{WARN_STR} Failed to fetch commandlist {commandlist}.")
    return False

def pos_to_blend_modding_fix(content: str, to_print: list[str]) -> list[Section]:
    """Patch ini file to change modding form pos hash to blend hash override.
    It will only attempt to patch PositionOverrides listed in VALID_HASH_TRIOS."""
    sections: list[Section] = split_in_sections(content)

    blend_template: str = dedent(r"""
                    hash = {blend_hash}
                    handling = skip
                    vb2 = {blend_resource}
                    if DRAW_TYPE == 1
                        vb0 = {pos_resource}
                        draw = {vertcount}, 0
                    endif
                    {rest_of_section}""")
    is_merged_mod: bool = False

    for section in sections:
        if not section.name_startswith("textureoverride"):
            continue
        try:
            section_hash: str = [line._stripped_lower_value for line in section.lines if line.has_key("hash")][0]
            blend_hash = [b for b, _, p in VALID_HASH_TRIOS.values() if section_hash == p][0]
        except IndexError:
            # either hashless section or not in the list
            # to_print.append(
            #     f"Info: {section.name.strip()} doesn't seem to need converting to blend override. Skipping part..."
            # )
            continue
        if any(
            line.has_key("hash")
            and line._stripped_lower_value == blend_hash
            for s in sections
            for line in s.lines
        ):
            section.comment_out()
            to_print.append(
                f"{WARN_STR} {section.name.strip()} already has a blend override, commenting out current section because is probably useless. Skipping part..."
            )
            continue


        pos_resource: str = ""
        blend_resource: str = ""
        vertcount: int = 0
        rest_of_lines: list[str] = []
        commandlistfound:Optional[str] = None

        for line in section.lines:            
            stripped_value: str = line.value.strip().lower()
            if line.has_key("handling") or line.has_key("hash"):
                continue
            if line.has_key("vb0"):
                pos_resource = line.value.strip()
            elif line.has_key("vb2"):
                blend_resource = line.value.strip()
            elif line.has_key("draw"):
                if "," not in stripped_value:
                    continue
                vertcount = int(stripped_value.split(",", 1)[0].strip())
            elif line.has_key("run") and stripped_value.startswith("commandlist"):
                # we are in a merge mod almost certainly. verify for ifelse in commandlsitofund
                commandlistfound = line.value.strip()
                to_print.append(f"Found CommandList {commandlistfound} in {section.name.strip()}. Checking if we are in a merge mod.")
            else:
                if line.is_value_pair:
                    rest_of_lines.append(f"{line.key}={line.value}")
                else:
                    rest_of_lines.append(line.key)
        
        # "CaelusDestructionHead":   ("ce50d7b6", "13e27600", "9e47ee7c"),
        # "CaelusHarmonyHead":       ("da87925e", "13e27600", "9e47ee7c"),
        # "CaelusPreservationHead":  ("8d6ae530", "13e27600", "9e47ee7c"),
        # "CaelusRemembranceHead":   ("8d6ae530", "13e27600", "9e47ee7c"), # repeat
        if section_hash == "9e47ee7c":
            to_print.append(
                f"{WARN_STR} {section.name.strip()} is a Caelus Head. Fix might fail, please verify manually."
            )
            if "destruction" in section.name.lower():
                blend_hash = "ce50d7b6"
            elif "harmony" in section.name.lower():
                blend_hash = "da87925e"
            elif "preservation" in section.name.lower():
                blend_hash = "8d6ae530"
            elif "remembrance" in section.name.lower():
                blend_hash = "8d6ae530"
            else:
                to_print.append(
                    f"{ERROR_STR} {section.name.strip()} is a Caelus Head but couldn't detect correct path. Skipping part..."
                )
                continue

        if commandlistfound:
            if attempt_commandlist_pos_blend_patch(sections, commandlistfound, to_print, section, blend_hash):
                is_merged_mod = True
                continue
            else:
                to_print.append(f"{ERROR_STR} {section.name.strip()} doesn't have a valid format. Skipping...")
                continue
                
        if is_merged_mod:
            to_print.append(f"{WARN_STR} {section.name.strip()} is in a merge mod but doesn't have commandlist. Skipping part...")
            continue

        if pos_resource == "" or blend_resource == "" or vertcount == 0:
            to_print.append(
                f"{ERROR_STR} Missing resource values in {section.name.strip()}. Skipping part..."
            )
            continue
        if rest_of_lines[-1] != "\n":
            rest_of_lines.append("\n")

        blend_str: str = blend_template.format(
            blend_hash=blend_hash,
            pos_resource=pos_resource,
            blend_resource=blend_resource,
            vertcount=vertcount,
            rest_of_section="".join(rest_of_lines),
        )[1:]
        section.lines.clear()
        section.add_lines(blend_str)
        old_name: str = section.name.strip()
        section.name = section.name.replace("Position", "Blend", 1)

        to_print.append(f"Patched {old_name}({section_hash}) -> {section.name.strip()}({blend_hash}).")

    return sections


def gather_model_data(
    sections: list[Section],
    blend_sections: list[Section],
    to_print: list[str],
) -> list[ModelData]:
    model_list: list[ModelData] = []
    for blend_section in blend_sections:
        vertcount: int = 1
        pos_ref: str = ""
        blend_ref: str = ""
        blend_hash: str = ""
        for line in blend_section.lines:
            if line.has_key("draw"):
                if "," not in line.value:
                    to_print.append(
                        f"{ERROR_STR} Invalid draw value in {blend_section.name}. Skipping part..."
                    )
                    # We could recover from this if the draw override section
                    # has a vert count and patch this retroactively but that sounds like a lot of work.
                    # This mod was already broken so the question is "Do we care?"
                    continue
                vertcount = int(line.value.split(",")[0].strip())
            elif line.has_key("hash"):
                blend_hash = line.value.strip().lower()
            elif line.has_key("vb0"):
                pos_ref = line.value.strip()
            elif line.has_key("vb2"):
                blend_ref = line.value.strip()

        if blend_hash == "" or pos_ref == "" or blend_ref == "":
            to_print.append(
                f"{ERROR_STR} Missing hash or resource values in {blend_section.name}. Skipping part..."
            )
            continue

        pos_res_section = [
            s
            for s in sections
            if pos_ref.lower().strip() == s.name.lower().strip()[1:].strip("]")
        ]
        blend_res_section = [
            s
            for s in sections
            if blend_ref.lower().strip() == s.name.lower().strip()[1:].strip("]")
        ]
        if not pos_res_section or not blend_res_section:
            to_print.append(
                f"{ERROR_STR} Missing resource sections for {blend_section.name}. Skipping part..."
            )
            continue
        if len(pos_res_section) + len(blend_res_section) != 2:
            to_print.append(
                f"{ERROR_STR} Multiple resource sections for {blend_section.name}. Unable to decide which to use. Skipping part..."
            )
            continue
        pos_name, pos_stride, pos_file = get_resource_data(pos_res_section[0])
        blend_name, blend_stride, blend_file = get_resource_data(blend_res_section[0])

        try:
            draw_found: str = [
                d for b, d, _ in VALID_HASH_TRIOS.values() if b == blend_hash
            ][0]
        except IndexError:
            # This path should never occurr,
            # we already know the hash is in the list and has a pair
            # assert False, "Missing draw hash for {blend_section.name}"
            continue

        part_name: str = (
            [n for n, (b, _, _) in VALID_HASH_TRIOS.items() if blend_hash == b]
            or [
                "",
            ]
        )[0]
        model_list.append(
            ModelData(
                part_name=part_name,
                vertcount=vertcount,
                ref_draw_hash=draw_found,
                ref_blend_hash=blend_hash,
                pos_resource=Resource(
                    name=pos_name + "CS",
                    type="StructuredBuffer",
                    stride=pos_stride,
                    filename=pos_file,
                ),
                blend_resource=Resource(
                    name=blend_name + "CS",
                    type="StructuredBuffer",
                    stride=blend_stride,
                    filename=blend_file,
                ),
            )
        )
    return model_list


def check_model_data(
    models: list[ModelData], sections: list[Section], to_print: list[str]
) -> None:
    """Verifies if the model data has already been applied to the INI.
    If it does it flags the patch type as consumed so furhter code doesn't attempt to patch it"""
    for m in models:
        blend_sections: list[Section] = [
            s
            for s in sections
            for line in s.lines
            if line.has_key("hash")
            and line.value.strip().lower() == m.ref_blend_hash.lower()
        ]
        blend_patched_sections: list[Section] = [
            s
            for s in blend_sections
            for line in s.lines
            if line.has_key(r"$\SRMI\vertcount") or line.has_key(r"$\SRMI\vertex_count")
        ]
        if blend_patched_sections:
            to_print.append(
                f"{blend_patched_sections[0].name} already patched with Pose Batch Fix. Skipping..."
            )
            m.blend_consumed = True

        draw_sections: list[Section] = [
            s
            for s in sections
            for line in s.lines
            if line.has_key("hash")
            and line.value.strip().lower() == m.ref_draw_hash.lower()
        ]
        draw_patched_sections: list[Section] = [
            s
            for s in draw_sections
            for line in s.lines
            if (
                "DRAW_TYPE != 8".lower() in line._stripped_lower_key
                and "DRAW_TYPE != 1".lower() in line._stripped_lower_key
            )
        ]
        if draw_patched_sections:
            to_print.append(
                f"{draw_patched_sections[0].name} already patched with Pose Batch Fix. Skipping..."
            )
            m.draw_consumed = True

        pos_resources: list[Section] = [
            s
            for s in sections
            if m.pos_resource.name.strip().lower() == s.name.strip().lower()[1:-1]
        ]
        # Technically is possible for blend to exist and not pos or vice versa in which case we should create the missing one-
        # More work for a very unlikely scenario.
        if pos_resources:
            to_print.append(
                f"{m.pos_resource.name} already exists in the INI file. Skipping resource creation..."
            )
            m.res_consumed = True

def attempt_merge_mod_batched_pose_fix(
    sections: list[Section],
    commandlist_candidates: list[CommandListCandidate],
    to_print: list[str],
    res_template: str,
    draw_template: str,
) -> list[Section]:
    """Attempt to patch the ini file to work with the new Batched Pose method."""
    ifel_template:str = r"""{prev_block}
    if DRAW_TYPE == 8
        Resource\SRMI\PositionBuffer = ref {pos_res_name}
        Resource\SRMI\BlendBuffer = ref {blend_res_name}
        $\SRMI\vertex_count = {vertcount}
    endif"""
    blend_merge_template:str = r"""hash = {blend_hash}
run = {commandlist}
{rest_of_blend}"""
    res_template_split:list[str] = res_template.splitlines(keepends=True)
    draw_res_template:str = r"".join(res_template_split[:5])
    blend_pos_res_template:str = r"".join(res_template_split[5:])
    res_merged_str:str = "\n[Constants]\nglobal $_blend_\n\n"
    draw_ifel_template:str = "".join(draw_template.splitlines(keepends=True)[2:])
    for cl in commandlist_candidates:
        if cl.command_list is None: # Shouldn't happen
            to_print.append(f"{ERROR_STR} CommandList for {cl.blend_hash} is missing. Skipping part...")
            continue
        ifel_blocks = split_in_ifelse_blocks(cl.command_list.lines)
        if len(ifel_blocks) <= 1:
            to_print.append(f"{WARN_STR} {cl.command_list.name.strip()} doesn't have if else blocks. Invalid merge mod. Aborting...")
            continue
        # Gather data per CommandList found
        final_cl: str = ""
        final_draw: str = ""
        pos_stride:int = 40
        max_v_count:int = 0
        draw_name: str = "Resource" + cl.draw_hash + "DrawCS"
        for b_i, block in enumerate(ifel_blocks):
            v_count:int = 0
            pos_res:str = ""
            blend_res:str = ""
            for b_line in block:
                if b_line.key_startswith("vb0"):
                    pos_res = b_line.value.strip()
                elif b_line.key_startswith("vb2"):
                    blend_res = b_line.value.strip()
                elif b_line.key_startswith("draw"):
                    if "," not in b_line.value:
                        continue
                    v_count = int(b_line.value.split(",", 1)[0])
                    max_v_count = max(max_v_count, v_count)

            if pos_res == "" or blend_res == "" or v_count == 0:
                if len(ifel_blocks) - 1 == b_i:
                    final_cl +=  reconstruct_ini_file([Section(name="", lines=block, is_header=True)]) + "\n"
                    continue
                to_print.append(
                    f"{ERROR_STR} Missing resource values in {cl.command_list.name.strip()}. Skipping part..."
                )
                continue

            ifel_str:str = ifel_template.format(
                prev_block=reconstruct_ini_file([Section(name="", lines=block, is_header=True)]),
                pos_res_name=pos_res + "CS",
                blend_res_name=blend_res + "CS",
                vertcount=v_count,
            )
            final_cl += ifel_str + "\n"
            try:
                pos_res_section:Section = [s for s in sections
                    if pos_res.lower().strip() == s.name.lower().strip()[1:].strip("]")][0]
                blend_res_section:Section = [s for s in sections
                    if blend_res.lower().strip() == s.name.lower().strip()[1:].strip("]")][0]
            except IndexError:
                to_print.append(
                    f"{ERROR_STR} Missing resource sections for {cl.command_list.name.strip()}. Skipping part..."
                )
                continue

            pos_name, pos_stride, pos_file = get_resource_data(pos_res_section)
            blend_name, blend_stride, blend_file = get_resource_data(blend_res_section)
            res_merged_str += "\n" + blend_pos_res_template.format(
                pos_name=pos_name + "CS",
                blend_name=blend_name + "CS",
                pos_file=pos_file,
                blend_file=blend_file,
                pos_stride=pos_stride,
                blend_stride=blend_stride,
            ) + "\n"

            first_line:INI_Line = block[0]
            if not (first_line.key_startswith("if")
                or first_line.key_startswith("else")
                or first_line.key_startswith("elif")):
                continue
            final_draw += first_line.key
            final_draw += draw_ifel_template.format(draw_resource_name=draw_name) + "\n"
        res_merged_str += draw_res_template.format(
            draw_name=draw_name,
            vertcount=max_v_count,
        )
        # Patch CL
        for sec in sections:
            if sec.name.strip().lower() == cl.command_list.name.strip().lower():
                sec.lines.clear()
                sec.add_lines(final_cl)
                sec.clear_empty_ending_lines()
                sec.add_single_line("\n")
                to_print.append(f"Patched {sec.name.strip()} with Batched Pose Fix.")
                break
        # Patch DRAW section
        for sec in sections:
            for line in sec.lines:
                if line.has_key("hash") and line.value.strip().lower() == cl.draw_hash:
                    sec.lines.clear()
                    sec.add_lines(
                        f"hash = {cl.draw_hash}\n"
                        f"override_vertex_count = {max_v_count}\n"
                        f"override_byte_stride = {pos_stride}\n"
                        f"uav_byte_stride = 4\n"
                    )
                    to_print.append(f"Patched {sec.name.strip()} DrawOverride with Batched Pose Fix.")
                    cl.draw_section_patched = True
                    break

        # If no section was patched above, create a new one after the blend section
        if not cl.draw_section_patched:
            for sec in sections:
                for line in sec.lines:
                    if line.has_key("hash") and line._stripped_lower_value == cl.blend_hash:
                        new_draw_section = Section(
                            name=f"[TextureOverride{cl.draw_hash}Draw]\n",
                            lines=[], is_header=False
                        )
                        new_draw_section.add_lines(
                            f"hash = {cl.draw_hash}\n"
                            f"override_vertex_count = {max_v_count}\n"
                            f"override_byte_stride = {pos_stride}\n"
                            f"uav_byte_stride = 4\n"
                        )
                        sections.insert(sections.index(sec) + 1, new_draw_section)
                        to_print.append(f"Generated DrawOverride section for {cl.draw_hash} with Batched Pose Fix.")
                        cl.draw_section_patched = True
                        break
        # Patch blend section
        for sec in sections:
            rest_of_blend: str = ""
            blend_found: bool = False
            for line in sec.lines:
                if (line.has_key("hash") and line._stripped_lower_value == cl.blend_hash):
                    blend_found = True
                elif line.has_key("run") and line._stripped_lower_value == cl.command_list.name.strip()[1:].strip("]").lower():
                    continue
                else:
                    rest_of_blend += line.key + "=" + line.value if line.is_value_pair else line.key
            if blend_found:
                blend_merged_str: str = blend_merge_template.format(
                    blend_hash=cl.blend_hash,
                    commandlist=cl.command_list.name.strip()[1:].strip("]"),
                    draw_res=draw_name,
                    rest_of_blend=rest_of_blend,
                )
                sec.lines.clear()
                sec.add_lines(blend_merged_str)
                to_print.append(f"Patched {sec.name.strip()} with hash {cl.blend_hash} with Batched Pose Fix.")
                break
        else: # Impossible to reach path
            to_print.append(f"{WARN_STR} Failed to fetch {cl.blend_hash} section. Skipping part...")
    
    appendix_section: Section = Section(name="", lines=[], is_header=True)
    appendix_section.add_lines(res_merged_str)
    sections.append(appendix_section)
    return sections

def is_mod_pose_patched(sections:list[Section]) -> bool:
    """Check if the mod has already been patched with the Batched Pose Fix"""
    for section in sections:
        for line in section.lines:
            if line.has_key(r"$\SRMI\vertcount") or line.has_key(r"$\SRMI\vertex_count"):
                return True
    return False

def batched_pose_fix(
    file_path: Path, sections: list[Section], to_print: list[str]
) -> str:
    """Patch ini file to work with new Batched Pose method"""
    if is_mod_pose_patched(sections):
        to_print.append("File already has Batched Pose Fix applied. Skipping...")
        return reconstruct_ini_file(sections)
    blend_template: str = r"""
if DRAW_TYPE == 8    
    Resource\SRMI\PositionBuffer = ref {pos_res_name}
    Resource\SRMI\BlendBuffer = ref {blend_res_name}
    $\SRMI\vertex_count = {vertcount}
endif"""
    draw_template: str = r"""override_vertex_count = {vertcount}
override_byte_stride = {byte_stride}
uav_byte_stride = 4"""
    res_template: str = r"""[{draw_name}]
type = RWStructuredBuffer
array = {vertcount}
data = R32_FLOAT 1 2 3 4 5 6 7 8 9 10

[{pos_name}]
type = StructuredBuffer
stride = {pos_stride}
filename = {pos_file}

[{blend_name}]
type = StructuredBuffer
stride = {blend_stride}
filename = {blend_file}
"""


    blend_list: list[str] = [b for (b, _, _) in VALID_HASH_TRIOS.values()]
    blend_sections: list[Section] = [
        s
        for s in sections
        for line in s.lines
        if line.has_key("hash")
        and line._stripped_lower_value in blend_list
    ]
    if not blend_sections:
        to_print.append(
            "File doesn't contain any blend override that needs batched pose patching. Skipping..."
        )
        return reconstruct_ini_file(sections)
    
    # ifgotvb0, commandlistsection
    commandlist_candidates:list[CommandListCandidate] = []

    for i, b_section in enumerate(blend_sections):
        commandlist_candidates.append(CommandListCandidate())
        for line in b_section.lines:
            if line.has_key("hash"):
                commandlist_candidates[i].draw_hash  = [d for (b, d, _) in VALID_HASH_TRIOS.values() if b == line._stripped_lower_value][0]
                commandlist_candidates[i].blend_hash = line._stripped_lower_value
            elif line.has_key("vb0"):
                commandlist_candidates[i].has_vb0 = True
            elif line.has_key("run") and line.value.strip().lower().startswith("commandlist"):
                temp_name:str =  line.value.strip()
                commandlist_candidates[i].command_list = ([s for s in sections
                        if s.has_name(temp_name)] or [None,])[0]

    # Checks if all the textureoverride sections have a commandlist and no vb0=
    if all(not cl.has_vb0 and cl.command_list for cl in commandlist_candidates):
        # We in merge mod. Verify CL integrity
        attempt_merge_mod_batched_pose_fix(sections, commandlist_candidates, to_print, res_template, draw_template)
        return reconstruct_ini_file(sections)

    # If we reach this stage, it means we are in a normal mod
    models: list[ModelData] = gather_model_data(sections, blend_sections, to_print)

    # check if the ini needs patching or already has it
    check_model_data(models, sections, to_print)

    # At this point we've gathered all information we need to patch the ini file,
    # any part with data not found won't be patched and the user is already warned about it.
    resources_data: str = ""
    for m in models:
        draw_res_name: str = "Resource" + (m.part_name or m.ref_draw_hash) + "DrawCS"
        if not m.res_consumed:
            resources_data += res_template.format(
                draw_name=draw_res_name,
                pos_name=m.pos_resource.name,
                blend_name=m.blend_resource.name,
                vertcount=m.vertcount,
                pos_stride=m.pos_resource.stride,
                blend_stride=m.blend_resource.stride,
                pos_file=m.pos_resource.filename,
                blend_file=m.blend_resource.filename,
            )
            m.res_consumed = True

    for section in sections:
        if section.is_header or not section.name.strip().lower().startswith(
            "[textureoverride"
        ):
            continue
        section_override_stride: int = 40
        section_hash: str = ""
        to_pop:list[int] = []
        for j, line in enumerate(section.lines):
            if line.has_key("hash"):
                section_hash = line.value.strip().lower()
            elif line.has_key("override_byte_stride"):
                section_override_stride = int(line.value.strip())
                to_pop.append(j)
            elif line.has_key("override_vertex_count"):
                to_pop.append(j)
        for j in to_pop[::-1]:
            section.lines.pop(j)
        if section_hash == "":
            to_print.append(
                f"{WARN_STR} Missing hash value in {section.name.strip()}. Aborting..."
            )
            continue

        for m in models:
            if m.blend_consumed and m.draw_consumed and m.res_consumed:
                continue
            draw_res_name: str = (
                "Resource" + (m.part_name or m.ref_draw_hash) + "DrawCS"
            )
            if m.ref_blend_hash == section_hash and not m.blend_consumed:
                blend_str: str = blend_template.format(
                    vertcount=m.vertcount,
                    pos_res_name=m.pos_resource.name,
                    blend_res_name=m.blend_resource.name,
                    draw_res_name=draw_res_name,
                )
                section.add_lines(blend_str)
                to_print.append(f"{section.name.strip()} Batched Pose Fix applied to Blend Override!")
                m.blend_consumed = True
            elif m.ref_draw_hash == section_hash and not m.draw_consumed:
                if section_override_stride == 1:
                    pos_path: Path = file_path.parent / m.pos_resource.filename
                    if not pos_path.exists():
                        to_print.append(
                            f"{ERROR_STR} Missing resource file for {section.name.strip()} and override_stride. Aborting..."
                        )
                        # Insuficient information to patch Draw section.
                        # We could try to check for blend file but not having a valid position file is already a mod breaking issue.
                        continue
                    pos_size: int = os.path.getsize(pos_path)
                    m.vertcount = math.ceil(pos_size / 40)

                draw_merged_str: str = draw_template.format(
                    vertcount=m.vertcount,
                    byte_stride=section_override_stride,
                    draw_resource_name=draw_res_name,
                )
                section.add_lines(draw_merged_str)
                to_print.append(f"{section.name.strip()} Batched Pose Fix applied to Draw Override!")
                m.draw_consumed = True

    sections[-1].clear_empty_ending_lines()
    sections[-1].add_single_line("\n")
    final_ini_body: str = reconstruct_ini_file(sections)
    if resources_data:
        to_print.append("Resource sections added for Batch Pose Fix")
        resources_data = ("\n\n[Constants]\nglobal $_blend_ = 0\n\n; -------------------- Auto-generated CS resources --------------------\n\n"+
                          resources_data)
        res_sections:list[Section] = split_in_sections(resources_data)
        for section in res_sections:
            section.clear_empty_ending_lines()
            section.add_single_line("\n")
        final_ini_body += reconstruct_ini_file(res_sections)

    return final_ini_body


def directory_checks(dir_path: Path) -> None:
    '''Verifies if the script is being run from a valid directory and if XXMI is installed.'''
    # TODO: Might wanna add SRMI Batched Pose install in here.
    # iterate back over path and find highest /Mods folder
    cursor_dir:Path = dir_path
    highest_mods: Path = dir_path
    found_mods_folder: bool = False
    while True:
        if cursor_dir.name == "":
            # reached root of drive, stop searching
            break
        if cursor_dir.name.lower() == "mods":
            highest_mods = cursor_dir
            found_mods_folder = True
        cursor_dir = cursor_dir.parent

    core_path: Path = highest_mods.parent / "Core"
    if not found_mods_folder:
        print(
            "You seem to be trying to run this script outside of a mods folder. Aborting..."
        )
        return
    if not core_path.exists():
        print(
            "XXMI install was not detected.\n"
            + "Please make sure you have XXMI installed properly.\n"
            + "This script will not work for the old SRMI, it has been deprecated and will no longer be supported.\n"
            + "Please migrate to the new XXMI Launcher then try using the script again.\n"
            + "XXMI migration Guide:  https://leotorrez.github.io/modding/guides/getting-started"
        )
        return
# MARK: Old Fix Start


def fix(
    mod_path,
    is_dry_run,
    ini_file_path=None,
    is_restore_backups=False,
    is_skip_batched_pose=False
):
    print("Fixing mod with Forked Hash Fixer...")

    curr_version = (3,2)

    print(f"HSR Fix v{curr_version[0]}.{curr_version[1]}")
    print(
        f"""- Updates all outdated HSR character mods from HSRv1.6 up to HSR v{curr_version[0]}.{curr_version[1]}\n
        - Edits Caelus mods to work on both Destruction/Preservation paths.\n
        - Adds the extra position hash on the mods that need it.\n
        - Patches mods to the new batched posing system.\n"""
    )

    mod_path_object = Path(mod_path)
    if ini_file_path:
        if ini_file_path.endswith('.ini'):
            print('Passed .ini file:', ini_file_path)
            upgrade_ini(ini_file_path, is_skip_batched_pose)
        else:
            raise Exception('Passed file is not an INI')
    else:
        directory_checks(mod_path_object)
        # Change the CWD to the directory this script is in
        # Nuitka: "Onefile: Finding files" in https://nuitka.net/doc/user-manual.pdf 
        # I'm not using Nuitka anymore but this distinction (probably) also applies for pyinstaller
        # os.chdir(os.path.abspath(os.path.dirname(sys.argv[0])))
        print(f'Current working directory: {mod_path_object}')
        process_folder(mod_path_object, is_restore_backups, is_skip_batched_pose)
    print('Done!')


# SHAMELESSLY (mostly) ripped from genshin fix script
def process_folder(folder_path: Path, is_restore_backups, is_skip_batched_pose):
    for filename in os.listdir(folder_path):
        if 'DESKTOP' in filename.upper():
            continue
        if filename.upper().startswith('DISABLED') and filename.endswith('.ini'):
            continue

        filepath = os.path.join(folder_path, filename)
        if os.path.isdir(filepath):
            process_folder(filepath, is_restore_backups, is_skip_batched_pose)
        elif filename.endswith('.ini'):
            print('Found .ini file:', filepath)
            if is_restore_backups:
                restore_ini(filepath)
            else:
                upgrade_ini(filepath, is_skip_batched_pose)

def restore_ini(filepath: Path):
    basename = os.path.basename(filepath).split('.ini')[0]
    dir_path = os.path.abspath(filepath.split(basename+'.ini')[0])
    candidates = [f for f in  os.listdir(dir_path) 
                if f.startswith('DISABLED_BACKUP_')
                and f.endswith(f'.{basename}.ini')
                and os.path.isfile(os.path.join(dir_path, f))]
    if len(candidates) == 0:
        print(f'\tNo backup found for {filepath}. Skipping...')
        return
    candidates.sort(key=lambda x: os.path.getmtime(os.path.join(dir_path, x)), reverse=True)
    backup_fullpath = os.path.join(dir_path, candidates[0])

    if os.path.exists(filepath):
        os.remove(filepath)
        print(f'\tRemoved: {filepath}')
    os.rename(backup_fullpath, filepath)
    print(f'\tRestored Backup: {candidates[0]} at {dir_path}')
    print()

def upgrade_ini(filepath: Path, is_skip_batched_pose):
    try:
        # Errors occuring here is fine as no write operations to the ini nor any buffers are performed
        ini = Ini(filepath).upgrade(is_skip_batched_pose)
    except Exception as x:
        print('Error occurred: {}'.format(x))
        print('No changes have been applied to {}!'.format(filepath))
        print()
        print(traceback.format_exc())
        print()
        return False

    try:
        # Content of the ini and any modified buffers get written to disk in this function
        # Since the code for this function is more concise and predictable, the chance of it failing
        # is low, but it can happen if Windows doesn't want to cooperate and write for whatever reason.
        ini.save()
    except Exception as x:
        print('Fatal error occurred while saving changes for {}!'.format(filepath))
        print('Its likely that your mod has been corrupted. You must redownload it from the source before attempting to fix it again.')
        print()
        print(traceback.format_exc())
        print()
        return False

    return True


# MARK: Ini
class Ini():
    def __init__(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            self.content = f.read()
            self.filepath = filepath

        # The random ordering of sets is annoying
        # I'll use a list for the hashes that will be iterated on
        # and a set for the hashes I already iterated on
        self.hashes = []
        self.touched = False
        self.done_hashes = set()

        # I must decrease the chance that this script will fail while fixing a mod
        # after it already went ahead and modified some buffers for the fix.
        #     => Only write the modified buffers at the very end after I saved the ini, since I
        #        can provide a backup for the ini, but backing up buffers is not reasonable.
        # If I need to fix the same buffer multiple times: the first time the buffer will 
        # be read from the mod directory, and subsequent fixes for the same buffer filepath
          # will use the modified buffer in the dict
        self.modified_buffers = {
            # buffer_filepath: buffer_data
        }

        # Get all (uncommented) hashes in the ini
        hash_pattern = re.compile(r'\s*hash\s*=\s*([A-Fa-f0-9]*)\s*', flags=re.IGNORECASE)
        for line in self.content.splitlines():
            m = hash_pattern.match(line)
            if m: self.hashes.append(m.group(1))

    def upgrade(self, is_skip_batched_pose):
        while len(self.hashes) > 0:
            hash = self.hashes.pop()
            if hash not in self.done_hashes:
                if hash in hash_commands:
                    print(f'\tUpgrading {hash}')
                    self.execute(hash, hash_commands[hash], {}, tabs=2)
                else:
                    print(f'\tSkipping {hash}: - No upgrade available')
            else:
                print(f'\tSkipping {hash}: / Already Checked/Upgraded')
            self.done_hashes.add(hash)

        to_print    : list[str]     = []
        new_sections: list[Section] = pos_to_blend_modding_fix(self.content, to_print)

        if is_skip_batched_pose:
            print('Skipping Batched Pose Fix')
            result: str = reconstruct_ini_file(new_sections)
        else:
            result: str = batched_pose_fix(self.filepath, new_sections, to_print)

        if self.content != result:
            self.touched = True
            self.content = result

        self.content = clean_up_indentation(self.content, to_print)
        print("\t"+"\n\t".join(to_print))

        return self

    def execute(self, hash, commands, jail: dict, tabs=0):

        for command, kwargs in commands:
            if command == 'info':
                print('{}-{}'.format('\t'*tabs, kwargs))
                continue

            if is_Command_Generator(command):
                print('{}-{}'.format('\t'*tabs, command.__name__))
                if command.__name__ in ('upgrade_else_comment', 'upgrade_else_comment_indexed'):
                    generated_commands = command(self, **kwargs)
                else:
                    generated_commands = command(**kwargs)
                sub_jail = self.execute(hash, generated_commands, jail, tabs=tabs+1)
                jail.update(sub_jail)

            elif is_Hash_Generator(command):
                new_hashes = kwargs
                print('{}-{}: {}'.format('\t'*tabs, command.__name__, new_hashes))

                # Only add the hashes that I haven't already iterated on
                self.hashes.extend(new_hashes.difference(self.done_hashes))

            elif is_Ini_Check(command):
                is_check_passed = command(self, **kwargs)
                if not is_check_passed:
                    print('{}-Upgrade not needed'.format('\t'*tabs))
                    return jail
                
            elif is_Buffer_Command(command):
                self.touched = True
                print('{}-{}'.format('\t'*tabs, command.__name__))
                self.content, new_modified_buffers = command( 
                    ini_content = self.content,
                    ini_filepath = self.filepath,
                    modified_buffers = self.modified_buffers,
                    hash = hash,
                    **kwargs
                )
                self.modified_buffers.update(new_modified_buffers)

            elif is_Command(command):
                self.touched = True
                print('{}-{}'.format('\t'*tabs, command.__name__))

                self.content, jail = command(
                    ini_content=self.content, 
                    hash=hash,
                    jail=jail,
                **kwargs)

            else:
                raise Exception('Huh?', command)

        return jail

    def save(self):
        if self.touched:
            basename = os.path.basename(self.filepath).split('.ini')[0]
            dir_path = os.path.abspath(self.filepath.split(basename+'.ini')[0])
            backup_filename = f'DISABLED_FORKED_BACKUP_{int(time.time())}.{basename}.ini'
            backup_fullpath = os.path.join(dir_path, backup_filename)

            os.rename(self.filepath, backup_fullpath)
            print(f'Created Backup: {backup_filename} at {dir_path}')
            with open(self.filepath, 'w', encoding='utf-8') as updated_ini:
                updated_ini.write(self.content)
            # with open('DISABLED_debug.ini', 'w', encoding='utf-8') as updated_ini:
            #     updated_ini.write(self.content)

            if len(self.modified_buffers) > 0:
                print('Writing updated buffers')
                for filepath, data in self.modified_buffers.items():
                    with open(filepath, 'wb') as f:
                        f.write(data)
                    print('\tSaved: {}'.format(filepath))

            print('Updates applied')
        else:
            print('No changes applied')
        print()

    def has_hash(self, hash):
        return (
            (hash in self.hashes) or
            (hash in self.done_hashes)
        )


# MARK: Regex
# Match the whole section (under the first group) that contains
# a certain uncommented hash at any line. For example:
# Using hash 12345678 matches
#     [TextureOverrideWhatever1_Match]
#     hash = 12345678
#     this = whatever
# and
#     [TextureOverrideWhatever2_Match]
#     ; hash = 87654321
#     hash = 12345678
#     this = whatever
# but not
#     [TextureOverrideWhatever3_NoMatch]
#     ; hash = 12345678
#     hash = 87654321
#     this = whatever
# 
# Last section of an ini won't match since the pattern must match until the next [
# Easy hack is to add '\n[' to the end of the string being matched
# Using VERBOSE flag to ignore whitespace
# https://docs.python.org/3/library/re.html#re.VERBOSE
def get_section_hash_pattern(hash) -> re.Pattern:
    return re.compile(
        r'''
            (
                \[.*\]
                [^\[]*?
                \n\s*hash\s*=\s*{}
                [\s\S]*?
            )
            (?=\s*(?:\s*;.*\n)*\s*\[)\s*
        '''.format(hash),
        flags=re.VERBOSE|re.IGNORECASE
    )

# Can only match Commandlist and Resource sections by title
# Could be used for Override sections as well
# case doesn't matter for titles right? hmm TODO
def get_section_title_pattern(title) -> re.Pattern:
    return re.compile(
        r'''
            (
                \[{}\]
                [\s\S]*?
            )
            (?=\s*(?:\s*;.*\n)*\s*\[)\s*
        '''.format(title),
        flags=re.VERBOSE|re.IGNORECASE
    )

# MARK: Commands

def Command_Generator(func):
    func.command_generator = True
    return func
def is_Command_Generator(func):
    return getattr(func, 'command_generator', False)

def Hash_Generator(func):
    func.hash_generator = True
    return func
def is_Hash_Generator(func):
    return getattr(func, 'hash_generator', False)

def Ini_Check(func):
    func.ini_check = True
    return func
def is_Ini_Check(func):
    return getattr(func, 'ini_check', False)

def Command(func):
    func.command = True
    return func
def is_Command(func):
    return getattr(func, 'command', False)

def Buffer_Command(func):
    func.buffer_command = True
    return func
def is_Buffer_Command(func):
    return getattr(func, 'buffer_command', False)

def get_critical_content(section):
    hash = None
    match_first_index = None
    critical_lines = []
    pattern = re.compile(r'^\s*(.*?)\s*=\s*(.*?)\s*$', flags=re.IGNORECASE)

    for line in section.splitlines():
        line_match = pattern.match(line)
        
        if line.strip().startswith('['):
            continue
        elif line_match and line_match.group(1).lower() == 'hash':
            hash = line_match.group(2)
        elif line_match and line_match.group(1).lower() == 'match_first_index':
            match_first_index = line_match.group(2)
        else:
            critical_lines.append(line)

    return '\n'.join(critical_lines), hash, match_first_index

@Command
def comment_sections(ini_content, hash, jail):
    pattern = get_section_hash_pattern(hash)
    new_ini_content = ''   # ini with all matching sections commented

    prev_j = 0
    section_matches = pattern.finditer(ini_content + '\n[')
    for section_match in section_matches:
        i, j = section_match.span(1)
        commented_section = '\n'.join([';' + line for line in section_match.group(1).splitlines()])

        new_ini_content += ini_content[prev_j:i] + commented_section
        prev_j = j
    
    new_ini_content += ini_content[prev_j:]
    return new_ini_content, jail

@Command
def remove_section(ini_content, hash, jail, *, capture_content=None, capture_position=None):
    pattern = get_section_hash_pattern(hash)
    section_match = pattern.search(ini_content + '\n[')
    if not section_match: raise Exception('Bad regex')
    start, end = section_match.span(1)

    if 'capture_content':
        jail[capture_content] = get_critical_content(section_match.group(1))[0]
    if 'capture_position':
        jail[capture_position] = str(start)

    return ini_content[:start] + ini_content[end:], jail


@Command
def remove_indexed_sections(ini_content, hash, jail, *, capture_content=None, capture_position=None):
    pattern = get_section_hash_pattern(hash)
    new_ini_content = ''   # ini with ib sections removed
    position = -1             # First Occurence Deletion Start Position

    all_section_matches = {}

    prev_j = 0
    section_matches = pattern.finditer(ini_content + '\n[')
    for section_match in section_matches:
        if 'match_first_index' not in section_match.group(1):
            jail['_unindexed_ib_exists'] = True
            if capture_content:
                jail[capture_content] = get_critical_content(section_match.group(1))[0]
        else:
            critical_content, _, match_first_index = get_critical_content(section_match.group(1))
            placeholder = '🤍{}🤍'.format(match_first_index)

            if match_first_index in all_section_matches:
                # these borked inis are too common...
                # prompt the user to pick the correct section
                print('Duplicate IB indexed section found in ini:\n')

                print('Section 1:')
                print(all_section_matches[match_first_index])

                print('\n\nSection 2:')
                print(str(section_match.group(1)))

                # automatically pick Section 2
                if 'ib = null' in all_section_matches[match_first_index]:
                    # overwrite existing section critical content
                    print('Removed Section 1')
                    jail[placeholder] = critical_content
                    all_section_matches[match_first_index] = section_match.group(1)

                # automatically pick Section 1
                elif 'ib = null' in str(section_match.group(1)):
                    # existing section critical content is what the user wants to keep
                    print('Removed Section 2')
                    pass
                
                else:
                    print()
                    print('Please pick the IB indexed section to be used in the upgrade.')
                    print('(You probably want to pick the section without `ib = null` if it exists)')
                    print('Type `1` to pick the first section or `2` to pick the second section, and')
                    user_choice = input('Press `Enter` to confirm your choice: ')

                    try:
                        user_choice = int(user_choice)
                        if user_choice not in [1, 2]:
                            raise Exception()
                    except Exception:
                        raise Exception('Only valid input is `1` or `2`')

                    if user_choice == 1:
                        # existing section critical content is what the user wants to keep
                        pass
                    elif user_choice == 2:
                        # overwrite existing section critical content
                        jail[placeholder] = critical_content
                        all_section_matches[match_first_index] = section_match.group(1)

            else:
                jail[placeholder] = critical_content
                all_section_matches[match_first_index] = section_match.group(1)
    


        i = section_match.span()[0]
        if position == -1: position = i
        new_ini_content += ini_content[prev_j:i]
        prev_j = i + len(section_match.group(1)) + 1

    new_ini_content += ini_content[prev_j:]
    if capture_position:
        jail[capture_position] = str(position)

    return new_ini_content, jail


@Command
def swap_hash(ini_content, hash, jail, *, trg_hash):
    hash_pattern = re.compile(r'^\s*hash\s*=\s*{}\s*$'.format(hash), flags=re.IGNORECASE)

    new_ini_content = []
    for line in ini_content.splitlines():
        m = hash_pattern.match(line)
        if m:
            new_ini_content.append('hash = {}'.format(trg_hash))
            new_ini_content.append(';'+line)
        else:
            new_ini_content.append(line)

    return '\n'.join(new_ini_content), jail


@Command
def create_new_section(ini_content, hash, jail, *, at_position=-1, capture_position=None, jail_condition=None, content):

    # Don't create section if condition must be satisfied but isnt
    if jail_condition and jail_condition not in jail:
        return ini_content, jail

    # Relatively slow but it doesn't matter
    if content[0] == '\n': content = content[1:]
    content = content.replace('\t', '')
    for placeholder, value in jail.items():
        if placeholder.startswith('_'):
            # conditions are not to be used for substitution
            continue

        content = content.replace(placeholder, value)
        if placeholder == at_position: at_position = int(value)

    # Half broken/fixed mods' ini will not have the object indices we're expecting
    # Could also be triggered due to a typo in the hash commands
    for emoji in ['🍰', '🌲', '🤍']:
        if emoji in content:
            print(content)
            raise Exception('Section substitution failed')

    if capture_position:
        jail[capture_position] = str(len(content) + at_position)

    ini_content = ini_content[:at_position] + content + ini_content[at_position:]

    return ini_content, jail


@Buffer_Command
def modify_buffer(ini_content, ini_filepath, modified_buffers, hash, *, operation, payload):

    # Compute new stride value of buffer according to new format
    if operation == 'add_texcoord1':
        stride = struct.calcsize(payload['format'] + payload['format'][-2:])
    elif operation == 'convert_format':
        stride = struct.calcsize(payload['format_conversion'][1])
    else:
        raise Exception('Unimplemented')

    # Need to find all Texcoord Resources used by this hash directly
    # through TextureOverrides or run through Commandlists... 
    pattern = get_section_hash_pattern(hash)
    section_match = pattern.search(ini_content+'\n[')
    resources = process_commandlist(ini_content, section_match.group(1))

    # - Match Resource sections to find filenames of buffers 
    # - Update stride value of resources early instead of iterating again later
    buffer_filenames = []
    line_pattern = re.compile(r'^\s*(filename|stride)\s*=\s*(.*)\s*$', flags=re.IGNORECASE)
    for resource in resources:
        pattern = get_section_title_pattern(resource)
        resource_section_match = pattern.search(ini_content + '\n[')
        if not resource_section_match: continue

        modified_resource_section = []
        for line in resource_section_match.group(1).splitlines():
            line_match = line_pattern.match(line)
            if not line_match:
                modified_resource_section.append(line)
            
            # Capture buffer filename
            elif line_match.group(1) == 'filename':
                modified_resource_section.append(line)
                buffer_filenames.append(line_match.group(2))

            # Update stride value of resource in ini
            elif line_match.group(1) == 'stride':
                modified_resource_section.append('stride = {}'.format(stride))
                modified_resource_section.append(';'+line)

        # Update ini
        modified_resource_section = '\n'.join(modified_resource_section)
        i, j = resource_section_match.span(1)
        ini_content = ini_content[:i] + modified_resource_section + ini_content[j:]


    for buffer_filename in buffer_filenames:
        # Get full buffer filepath using filename and ini filepath 
        buffer_filepath = os.path.abspath(os.path.join(os.path.dirname(ini_filepath), buffer_filename))
        if buffer_filepath not in modified_buffers:
            with open(buffer_filepath, 'rb') as bf:
                buffer = bf.read()
        else:
            buffer = modified_buffers[buffer_filepath]
        
        # Create new modified buffer using existing
        new_buffer = bytearray()
        if operation == 'add_texcoord1':
            old_format = payload['format']
            new_format = old_format + old_format[-2:]

            x, y = 0, 0
            for chunk in struct.iter_unpack(old_format, buffer):
                if payload['value'] == 'copy': x, y = chunk[-2], chunk[-1]
                new_buffer.extend(struct.pack(new_format, *chunk, x, y))

        elif operation == 'convert_format':
            old_format, new_format = payload['format_conversion']
            for chunk in struct.iter_unpack(old_format, buffer):
                new_buffer.extend(struct.pack(new_format, *chunk))
    
        # Modified buffers will be written at the end of this ini's upgrade
        modified_buffers[buffer_filepath] = new_buffer
    
    line_pattern = re.compile(r'^\s*stride\s*=\s*(.*)\s*$', flags=re.IGNORECASE)

    return ini_content, modified_buffers


# Returns all resources used by a commandlist
# Hardcoded to only return vb1 i.e. texcoord resources for now
# (TextureOverride sections are special commandlists)
def process_commandlist(ini_content: str, commandlist: str):
    line_pattern = re.compile(r'^\s*(run|vb1)\s*=\s*(.*)\s*$', flags=re.IGNORECASE)
    resources = []

    for line in commandlist.splitlines():
        line_match = line_pattern.match(line)
        if not line_match: continue

        if line_match.group(1) == 'vb1':
            resources.append(line_match.group(2))

        # Must check the commandlists that are run within the
        # the current commandlist for the resource as well
        # Recursion yay
        elif line_match.group(1) == 'run':
            commandlist_title = line_match.group(2)
            pattern = get_section_title_pattern(commandlist_title)
            commandlist_match = pattern.search(ini_content + '\n[')
            if commandlist_match:
                sub_resources = process_commandlist(ini_content, commandlist_match.group(1))
                resources.extend(sub_resources)

    return resources



@Ini_Check
def check_hash_not_in_ini(ini: Ini, *, hash):
    return (
        (hash not in ini.hashes)
        and
        (hash not in ini.done_hashes)
    )

@Ini_Check
def check_hash_in_ini(ini: Ini, *, hash):
	return (
		(hash in ini.hashes) or
		(hash in ini.done_hashes)
	)


@Ini_Check
def check_any_hashes_in_ini(ini: Ini, *, hashes: tuple[str]):
	return any(
		check_hash_in_ini(ini, hash=h)
		for h in hashes
	)
# @Ini_Check
# def check_main_ib_in_ini(ini: Ini, *, hash):



@Hash_Generator
def try_upgrade():
    pass

@Command_Generator
def upgrade_hash(*, to):
    return [
        (swap_hash, {'trg_hash': to}),
        (try_upgrade, {to})
    ]


@Command_Generator
def upgrade_shared_hash(*, to, flag_hashes: tuple[str], log_info: str):
	return [
		(check_any_hashes_in_ini, {'hashes': flag_hashes}),
		('info', log_info),
		(upgrade_hash, {'to': to})
	]


# Silvermane guard npc vs enemy model have all hashes except for diffuse/lightmap different
# but we can't use the same texcoord file for both variants because the formats differ.
# Create a command that creates new buffer using the existing, but with the modified format
# Not very simple :terifallen:
# Need to identify all usages of the texcoord in the Override and any run Commandlists
# and to recreate the critical content using the new modified buffer. Also need to create 
# resource sections for the new buffer
# 
# Consider this case:
#     [TextureOverride_NPC_Texcoord]
#     hash = 12345678
#     run = CommandList_NPC_Texcoord
#     if $heh == 1
#         vb1 = ResourceTexcoord.3
#     endif
# 
#     [CommandList_NPC_Texcoord]
#     if $whatever == 0
#         vb1 = ResourceTexcoord.0
#     elif $whatever == 1
#         vb1 = ResourceTexcoord.1
#     endif
#
# - Create new override section using the new hash
# - Set its critical content to that of the original section BUT
#     - Replace all Resource mentions with the newly modified resource
#     - If there is a run CommandList:
#         - Replace it with a new CommandList with all Resource mentions replaced by new Resource
#         - If there is a run Commandlist:
#             - Recursion.. fun..
# 
# @Command_Generator
# def multiply_buffer_section(*, titles, hashes, modify_buffer_operation):


@Command_Generator
def multiply_section(*, titles, hashes):
    content = ''
    for i, (title, hash) in enumerate(zip(titles, hashes)):
        content += '\n'.join([
            f'[TextureOverride{title}]',
            f'hash = {hash}',
            '🍰',
            ''
        ])
        if i < len(titles) - 1:
            content += '\n'

    return [
        (remove_section, {'capture_content': '🍰', 'capture_position': '🌲'}),
        (create_new_section, {'at_position': '🌲', 'content': content}),
        (try_upgrade, set(hashes))
    ]

# TODO: Rename this function.
#     - It does not "multiply" similarly to how `multiply_section` creates multiple sections out of one
#     + A true "multiply_indexed_section" is needed to simplify some character fixes (Stelle/Caelus/Yanqing)
@Command_Generator
def multiply_indexed_section(*, title, hash, trg_indices, src_indices):
    unindexed_ib_content = f'''
        [TextureOverride{title}IB]
        hash = {hash}
        🍰

    '''

    alpha = [
        'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J',
        'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T',
        'U', 'V', 'W', 'X', 'Y', 'Z'
    ]
    content = ''
    for i, (trg_index, src_index) in enumerate(zip(trg_indices, src_indices)):
        content += '\n'.join([
            f'[TextureOverride{title}{alpha[i]}]',
            f'hash = {hash}',
            f'match_first_index = {trg_index}',
            f'🤍{src_index}🤍' if src_index != '-1' else 'ib = null',
            ''
        ])
        if i < len(trg_indices) - 1:
            content += '\n'

    return [
        (remove_indexed_sections, {'capture_content': '🍰', 'capture_position': '🌲'}),
        (create_new_section, {'at_position': '🌲', 'content': content}),
        (create_new_section, {'at_position': '🌲', 'content': unindexed_ib_content, 'jail_condition': '_unindexed_ib_exists'}),
        (try_upgrade, {hash})
    ]

@Command_Generator
def upgrade_else_comment(ini: Ini, *, missing, hash):
    return [
        (comment_sections, {})
        if any([ini.has_hash(h) for h in missing])
        else (upgrade_hash, {'to': hash})
    ]

@Command_Generator
def upgrade_else_comment_indexed(ini: Ini, *, missing, hash, title, trg_indices, src_indices):
    return [
        (comment_sections, {})
        if any([ini.has_hash(h) for h in missing])
        else (multiply_indexed_section, {
            'title': title,
            'hash': hash,
            'trg_indices': trg_indices,
            'src_indices': src_indices,
        })
    ]

hash_commands = {
    # MARK: Sparxie

    '337f7de8': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': '51288e6a'})],
    '547d13f7': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': 'b9250480'})],
    'df489315': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': '12f315d4'})],
    'a0dfb1ac': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': '54ee8b35'})],
    '4dcbf0c8': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': '5c2a2064'})],

    'b7124f06': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': 'd507f62a'})],
    '979806ea': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': '3ef2cc18'})],
    'f241b31a': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': 'a4f51f30'})],
    '67ec715e': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': '0e39f0ac'})],
    'fa679826': [('info', 'v3.3 -> v4.4: Sparxie Hash'), (upgrade_hash, {'to': 'd734b734'})],

    # TODO: This is still buggy. Texture is loaded but vertexes are exploded. Find correct fixing!
    # MARK: Stelle
    
    # 'f05d06de': [('info', 'v3.3 -> v3.7: Stelle Hash'), (upgrade_hash, {'to': 'ed04bfc7'})],
    # 'b55c8431': [('info', 'v3.3 -> v3.7: Stelle Hash'), (upgrade_hash, {'to': '195d016d'})],
    # 'f00b6ded': [('info', 'v3.3 -> v3.7: Stelle Hash'), (upgrade_hash, {'to': '454c77a5'})],

    # '7ef7100f66e87ae5': [('info', 'v3.3 -> v3.7: Stelle Hash'), (upgrade_hash, {'to': 'eec35f974a28be87'})],

    # 'fba309df': [
    #     ('info', 'v3.3 -> v3.7: Stelle Body IB Hash'),
    #     (multiply_indexed_section, {
    #         'title': 'FixedStelleDestruction',
    #         'hash': '47695dd6',
    #         'trg_indices': ['0', '35661'],
    #         'src_indices': ['0', '32946'],
    #     })
    # ],

    # '195d016d': [('info', 'v3.7 -> v4.0: Stelle Hash'), (upgrade_hash, {'to': '344c4e99'})],
    # '454c77a5': [('info', 'v3.7 -> v4.0: Stelle Hash'), (upgrade_hash, {'to': '54d45960'})],
    # 'd52d7139': [('info', 'v3.7 -> v4.0: Stelle Hash'), (upgrade_hash, {'to': 'f8209611'})],
    # '78d10c03': [('info', 'v3.7 -> v4.0: Stelle Hash'), (upgrade_hash, {'to': '0e5f975c'})],
    # '69014337': [('info', 'v3.7 -> v4.0: Stelle Hash'), (upgrade_hash, {'to': 'f469bcba'})],

    # '47695dd6': [
    #     ('info', 'v3.7 -> v4.0: Stelle Body IB Hash'),
    #     (multiply_indexed_section, {
    #         'title': 'FixedStelleDestruction',
    #         'hash': 'ef776fb5',
    #         'trg_indices': ['45138', '6603'],
    #         'src_indices': ['0', '35661'],
    #     })
    # ],
    
    # 'f80cc950': [('info', 'v4.0 -> v4.2: Stelle Hash'), (upgrade_hash, {'to': '0d85a303'})],
    # '344c4e99': [('info', 'v4.0 -> v4.2: Stelle Hash'), (upgrade_hash, {'to': '89a23fcd'})],
    # '54d45960': [('info', 'v4.0 -> v4.2: Stelle Hash'), (upgrade_hash, {'to': '43d9095b'})],

    # 'ef776fb5': [
    #     ('info', 'v3.7 -> v4.0: Stelle Body IB Hash'),
    #     (multiply_indexed_section, {
    #         'title': 'FixedStelleDestruction',
    #         'hash': '5bdd3731',
    #         'trg_indices': ['45138', '6717'],
    #         'src_indices': ['45138', '6603'],
    #     })
    # ],
}