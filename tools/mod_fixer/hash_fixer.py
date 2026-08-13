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

import urllib.request

os.system('') # I hate powershell <3
ERROR_STR:str = "\033[1m\033[0;31mError:\033[0m"
WARN_STR:str  = "\033[1m\033[1;33mWarning:\033[0m"

BASE_URL = "https://raw.githubusercontent.com/agungmubarak1453/honkai-star-rail-modding-utility/main/"

def get_script(script_path):
    script_url = BASE_URL + "tools/" + script_path

    print(f"Fetching script: {script_url}")

    source = urllib.request.urlopen(script_url).read()
    code = compile(source, script_url, "exec")

    namespace = {}
    exec(code, namespace)

    return namespace

input_output_manager = get_script("general/input_output_manager.py")

# "NamePart" : (blend_hash, draw_hash, pos_hash)
VALID_HASH_TRIOS = input_output_manager["load_json_data"](BASE_URL + "datas/valid_hashes.json")

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
    print("Fixing mod with Hash Fixer...")

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
            backup_filename = f'DISABLED_BACKUP_{int(time.time())}.{basename}.ini'
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
    # MARK: Acheron
    'ca948c6c': [('info', 'v2.1 -> v2.2: Acheron HairA Diffuse Hash'),  (upgrade_hash, {'to': '5ee5cc8d'})],
    '15cacc23': [('info', 'v2.1 -> v2.2: Acheron HairA LightMap Hash'), (upgrade_hash, {'to': 'ba560779'})],

    '18425cc1': [('info', 'v2.2 -> v2.3: Acheron Hair Draw Hash'),         (upgrade_hash, {'to': '111d47a6'})],
    'e775bf51': [('info', 'v2.2 -> v2.3: Acheron Hair Position Hash'),     (upgrade_hash, {'to': '9745dc50'})],
    'f83652e0': [('info', 'v2.2 -> v2.3: Acheron Hair Texcoord Hash'),     (upgrade_hash, {'to': '439a6fd7'})],
    'cb7fd896': [('info', 'v2.2 -> v2.3: Acheron Hair IB Hash'),           (upgrade_hash, {'to': '22284dcd'})],
    '5ee5cc8d': [('info', 'v2.2 -> v2.3: Acheron Hair Diffuse Hash'),      (upgrade_hash, {'to': '6288c7ce'})],
    'e341feb3': [('info', 'v2.2 -> v2.3: Acheron Hair Diffuse Ult Hash'),  (upgrade_hash, {'to': 'fbc56473'})],
    'ba560779': [('info', 'v2.2 -> v2.3: Acheron Hair LightMap Hash'),     (upgrade_hash, {'to': '020bb63f'})],
    '4f794c53': [('info', 'v2.2 -> v2.3: Acheron Hair LightMap Ult Hash'), (upgrade_hash, {'to': 'f0b6c0a5'})],

    '94d0ebac': [('info', 'v2.2 -> v2.3: Acheron Head Diffuse Hash'),      (upgrade_hash, {'to': '772da571'})],
    'f1d40d3b': [('info', 'v2.2 -> v2.3: Acheron Head Diffuse Ult Hash'),  (upgrade_hash, {'to': '19de522c'})],

    '95311311': [('info', 'v2.2 -> v2.3: Acheron Body Texcoord Hash'),     (upgrade_hash, {'to': '17e76a6a'})],
    'b2c64915': [('info', 'v2.2 -> v2.3: Acheron Body Diffuse Hash'),      (upgrade_hash, {'to': 'e88da4d0'})],
    'b8363627': [('info', 'v2.2 -> v2.3: Acheron Body Diffuse Ult Hash'),  (upgrade_hash, {'to': '5788d426'})],
    '2a42c5e4': [('info', 'v2.2 -> v2.3: Acheron Body LightMap Hash'),     (upgrade_hash, {'to': '1248799e'})],
    '60de0907': [('info', 'v2.2 -> v2.3: Acheron Body LightMap Ult Hash'), (upgrade_hash, {'to': 'ec57d1b8'})],

    '92bc6d3a': [('info', 'v2.3 -> v2.4: Acheron Body Draw Hash'),           (upgrade_hash, {'to': 'f6023c2b'})],
    '214bd15a': [('info', 'v2.3 -> v2.4: Acheron Body Position Hash'),       (upgrade_hash, {'to': '45f5804b'})],
    '7ffc98fa': [('info', 'v2.3 -> v2.4: Acheron Body Position Extra Hash'), (upgrade_hash, {'to': 'bc9d2d77'})],
    '17e76a6a': [('info', 'v2.3 -> v2.4: Acheron Body Texcoord Hash'),       (upgrade_hash, {'to': 'da5b680e'})],
    '36536e1b': [('info', 'v2.3 -> v2.4: Acheron Body IB Hash'),             (upgrade_hash, {'to': '6f8c993d'})],
    
    # '45f5804b': [
    #     ('info', 'v2.4: Acheron Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': 'bc9d2d77'}),
    #     (check_hash_not_in_ini, {'hash': '7ffc98fa'}),
    #     (multiply_section, {
    #         'titles': ['AcheronBodyPosition', 'AcheronBodyPosition_Extra'],
    #         'hashes': ['45f5804b', 'bc9d2d77']
    #     })
    # ],

    '9745dc50': [('info', 'v2.3 -> v3.1: Acheron Hair Position Hash'),      (upgrade_hash, {'to': '8ef0c1e2'})],
    'bc9d2d77': [('info', 'v2.4 -> v3.1: Acheron Body Position Extra Hash'),              (comment_sections, {})],
    '7212e8c5': [('info', 'v3.0 -> v3.1: Acheron Body Blend Hash'),         (upgrade_hash, {'to': '9de39691'})],
    'ee6055e3': [('info', 'v3.0 -> v3.1: Acheron Hair Blend Hash'),         (upgrade_hash, {'to': '01912bb7'})],
    'e4645cb9': [('info', 'v3.0 -> v3.1: Acheron HairBack Blend Hash'),     (upgrade_hash, {'to': '0b9522ed'})],
    '567105bf': [('info', 'v3.0 -> v3.1: Acheron HairBack Position Hash'),  (upgrade_hash, {'to': '4fc4180d'})],
    '2f712832': [('info', 'v3.0 -> v3.1: Acheron HairBackUlt Position Hash'),(upgrade_hash, {'to': '36c43580'})],
    'f8b9e830': [('info', 'v3.0 -> v3.1: Acheron Head Blend Hash'),         (upgrade_hash, {'to': '17489664'})],
    '896ef2ee': [('info', 'v3.0 -> v3.1: Acheron Head Position Hash'),      (upgrade_hash, {'to': '90dbef5c'})],

    '45f5804b': [('info', 'v3.0 -> v3.1: Acheron Body Position Hash'), (upgrade_hash, {'to': 'a52830c5'})],
    '111d47a6': [('info', 'v2.3 -> v3.2: Acheron Hair Draw Hash'), (upgrade_hash, {'to': '1e8e72ab'})],
    'f6023c2b': [('info', 'v2.4 -> v3.2: Acheron Body Draw Hash'), (upgrade_hash, {'to': 'f9910926'})],
    '71633585': [('info', 'v3.1 -> v3.2: Acheron HairBackUlt Draw Hash'), (upgrade_hash, {'to': '7ef00088'})],
    '11ccee20': [('info', 'v3.1 -> v3.2: Acheron HairBackUlt Blend Hash'), (upgrade_hash, {'to': 'fe3d9074'})],
    '008800e7': [('info', 'v3.1 -> v3.2: Acheron Head Draw Hash'), (upgrade_hash, {'to': '0f1b35ea'})],
    '6b23c635': [('info', 'v3.1 -> v3.2: Acheron HeadBackUlt Draw Hash'), (upgrade_hash, {'to': '64b0f338'})],

    # MARK: Aglaea
    '119f3414': [('info', 'v3.1 -> v3.2: Aglaea Hair Draw Hash'), (upgrade_hash, {'to': '1e0c0119'})],
    '417405f0': [
		(upgrade_shared_hash, {
			'to': '4ee730fd',
			'flag_hashes': ('c7ad0566', '6ed5a76f', '1f0f1dc6', '457d09a4'),
			'log_info': 'v3.1 -> v3.2: Aglaea Head Draw Hash',
		}),
		(upgrade_shared_hash, {
			'to': '4ee730fd',
			'flag_hashes': ('007cd17b', 'd802ea61', '08b089e7', 'a7f9383f'),
			'log_info': 'v3.1 -> v3.2: Gepard Head Draw Hash',
		}),
	],
    '64b0dde3': [('info', 'v3.1 -> v3.2: Aglaea Body Draw Hash'), (upgrade_hash, {'to': '6b23e8ee'})],


    # MARK: Argenti
    '099cb678': [('info', 'v1.6 -> v2.0: Argenti Body Texcoord Hash'), (upgrade_hash, {'to': '18af7e1c'})],
    '9de080b0': [
        ('info', 'v1.6 -> v2.0: Argenti Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'ArgentiBody',
            'hash': '7d57f432',
            'trg_indices': ['0', '58749'],
            'src_indices': ['0',    '-1'],
        })
    ],

    '040c8f95': [('info', 'v2.2 -> v2.3: Argenti Hair Draw Hash'),     (upgrade_hash, {'to': 'ac883ae6'})],
    '3214c162': [('info', 'v2.2 -> v2.3: Argenti Hair Position Hash'), (upgrade_hash, {'to': '78c72ec8'})],
    '5eede219': [('info', 'v2.2 -> v2.3: Argenti Hair Texcoord Hash'), (upgrade_hash, {'to': '05b75400'})],
    '179d17fe': [('info', 'v2.2 -> v2.3: Argenti Hair IB Hash'),       (upgrade_hash, {'to': '5fab0ace'})],
    'd066d8b7': [('info', 'v2.2 -> v2.3: Argenti Hair Diffuse Hash'),  (upgrade_hash, {'to': '17948e68'})],
    '4925c9dd': [('info', 'v2.2 -> v2.3: Argenti Hair LightMap Hash'), (upgrade_hash, {'to': 'a13c6f7f'})],

    '705196e4': [('info', 'v2.2 -> v2.3: Argenti Head Diffuse Hash'),  (upgrade_hash, {'to': '2945bd23'})],

    'f94c8a7e': [('info', 'v2.2 -> v2.3: Argenti Body Diffuse Hash'),  (upgrade_hash, {'to': 'a4e4c7dc'})],
    '98b6f3be': [('info', 'v2.2 -> v2.3: Argenti Body LightMap Hash'), (upgrade_hash, {'to': '63bb1f26'})],
    
    '78c72ec8': [('info', 'v2.3 -> v3.1: Argenti Hair Position Hash'),      (upgrade_hash, {'to': '6172337a'})],
    '3f920a7c': [('info', 'v3.0 -> v3.1: Argenti Body Blend Hash'),         (upgrade_hash, {'to': 'd0637428'})],
    'cc1a18f7': [('info', 'v3.0 -> v3.1: Argenti Hair Blend Hash'),         (upgrade_hash, {'to': '23eb66a3'})],
    'e0caccfa': [('info', 'v3.0 -> v3.1: Argenti Head Blend Hash'),         (upgrade_hash, {'to': '0f3bb2ae'})],
    '13e52094': [('info', 'v3.0 -> v3.1: Argenti Head Position Hash'),      (upgrade_hash, {'to': '0a503d26'})],

    'ac883ae6': [('info', 'v2.3 -> v3.2: Argenti Hair Draw Hash'), (upgrade_hash, {'to': 'a31b0feb'})],
    '0c349519': [('info', 'v3.1 -> v3.2: Argenti Head Draw Hash'), (upgrade_hash, {'to': '03a7a014'})],
    '9dc7d1aa': [('info', 'v3.1 -> v3.2: Argenti Body Draw Hash'), (upgrade_hash, {'to': '9254e4a7'})],
    '2e306dca': [('info', 'v3.1 -> v3.2: Argenti Body Position Hash'), (upgrade_hash, {'to': '8938505f'})],



    # MARK: Arlan
    'efc1554c': [('info', 'v1.6 -> v2.0: Arlan BodyA LightMap Hash'), (upgrade_hash, {'to': '49f0a509'})],
    'b83d39c9': [('info', 'v1.6 -> v2.0: Arlan BodyB LightMap Hash'), (upgrade_hash, {'to': 'ffaf499a'})],
    '2b98f3d1': [('info', 'v1.6 -> v2.0: Arlan Body Texcoord Hash'),  (upgrade_hash, {'to': '40436908'})],
    'cb3a3965': [
        ('info', 'v1.6 -> v2.0: Arlan Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'ArlanBody',
            'hash': '31ebfc6e',
            'trg_indices': ['0', '23412', '41721', '42429'],
            'src_indices': ['0', '23412',    '-1', '42429'],
        })
    ],

    '21c2354a': [('info', 'v2.2 -> v2.3: Arlan Hair Diffuse Hash'),   (upgrade_hash, {'to': '72ad2a8b'})],
    '1fdfbbdc': [('info', 'v2.2 -> v2.3: Arlan Hair Lightmap Hash'),  (upgrade_hash, {'to': 'b4c6e6a0'})],

    '9a85af8a': [('info', 'v2.2 -> v2.3: Arlan Head Diffuse Hash'),   (upgrade_hash, {'to': 'a8c57de3'})],

    '52e4750b': [('info', 'v2.2 -> v2.3: Arlan BodyA Diffuse Hash'),  (upgrade_hash, {'to': '52b88238'})],
    '49f0a509': [('info', 'v2.2 -> v2.3: Arlan BodyA LightMap Hash'), (upgrade_hash, {'to': 'd8039952'})],
    'd1e827e0': [('info', 'v2.2 -> v2.3: Arlan BodyB Diffuse Hash'),  (upgrade_hash, {'to': 'f90343fb'})],
    'ffaf499a': [('info', 'v2.2 -> v2.3: Arlan BodyB LightMap Hash'), (upgrade_hash, {'to': '2f5ce8b7'})],

    'aa7d97fd': [('info', 'v3.0 -> v3.1: Arlan Body Blend Hash'),           (upgrade_hash, {'to': '458ce9a9'})],
    'b9ac47a5': [('info', 'v3.0 -> v3.1: Arlan Hair Blend Hash'),           (upgrade_hash, {'to': '565d39f1'})],
    '6aee5919': [('info', 'v3.0 -> v3.1: Arlan Hair Position Hash'),        (upgrade_hash, {'to': '735b44ab'})],
    '642d3ecb': [('info', 'v3.0 -> v3.1: Arlan Head Blend Hash'),           (upgrade_hash, {'to': '8bdc409f'})],
    '25060ff7': [('info', 'v3.0 -> v3.1: Arlan Head Position Hash'),        (upgrade_hash, {'to': '3cb31245'})],


    'adce6688': [('info', 'v3.1 -> v3.2: Arlan Hair Draw Hash'), (upgrade_hash, {'to': 'a25d5385'})],
    '0a432b82': [('info', 'v3.1 -> v3.2: Arlan Head Draw Hash'), (upgrade_hash, {'to': '05d01e8f'})],
    '8cc7a1d1': [('info', 'v3.1 -> v3.2: Arlan Body Draw Hash'), (upgrade_hash, {'to': '835494dc'})],
    '3f301db1': [('info', 'v3.1 -> v3.2: Arlan Body Position Hash'), (upgrade_hash, {'to': 'b7db63bc'})],


    # MARK: Asta
    '46c9c299': [('info', 'v1.6 -> v2.0: Asta Body Texcoord Hash'), (upgrade_hash, {'to': '337e94ce'})],
    '099dd85b': [
        ('info', 'v1.6 -> v2.0: Asta Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'AstaBody',
            'hash': '8fb66ce1',
            'trg_indices': ['0',  '4791', '11823', '12510', '47880'],
            'src_indices': ['0', '40161', '49917',    '-1',    '-1'],
        })
    ],

    'cde8d751': [('info', 'v2.2 -> v2.3: Asta Hair Draw Hash'),     (upgrade_hash, {'to': '1ca6cf3d'})],
    '4e29dad2': [('info', 'v2.2 -> v2.3: Asta Hair Position Hash'), (upgrade_hash, {'to': '967c0759'})],
    '6406c03e': [('info', 'v2.2 -> v2.3: Asta Hair Texcoord Hash'), (upgrade_hash, {'to': '4f796933'})],
    '84668635': [('info', 'v2.2 -> v2.3: Asta Hair IB Hash'),       (upgrade_hash, {'to': '36a13222'})],
    '9bd1710d': [('info', 'v2.2 -> v2.3: Asta Hair Diffuse Hash'),  (upgrade_hash, {'to': '2ec320aa'})],
    '8206809f': [('info', 'v2.2 -> v2.3: Asta Hair LightMap Hash'), (upgrade_hash, {'to': '7fd9c40d'})],

    '0fb34dc9': [('info', 'v2.2 -> v2.3: Asta Head Diffuse Hash'),  (upgrade_hash, {'to': 'a53efe63'})],

    'fb0f55f4': [('info', 'v2.2 -> v2.3: Asta BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'e290fff3'})],
    '088765db': [('info', 'v2.2 -> v2.3: Asta BodyA LightMap Hash'), (upgrade_hash, {'to': '687428e3'})],
    '3cc949c8': [('info', 'v2.2 -> v2.3: Asta BodyB Diffuse Hash'),  (upgrade_hash, {'to': '8f61660a'})],
    '701d9092': [('info', 'v2.2 -> v2.3: Asta BodyB LightMap Hash'), (upgrade_hash, {'to': '8893d921'})],

    '967c0759': [('info', 'v2.3 -> v3.1: Asta Hair Position Hash'),         (upgrade_hash, {'to': '8fc91aeb'})],
    'f65d0287': [('info', 'v3.0 -> v3.1: Asta Body Blend Hash'),            (upgrade_hash, {'to': '19ac7cd3'})],
    'a6d492d3': [('info', 'v3.0 -> v3.1: Asta Hair Blend Hash'),            (upgrade_hash, {'to': '4925ec87'})],
    '8fd302a3': [('info', 'v3.0 -> v3.1: Asta Head Blend Hash'),            (upgrade_hash, {'to': '60227cf7'})],
    '6f2e00c4': [('info', 'v3.0 -> v3.1: Asta Head Position Hash'),         (upgrade_hash, {'to': '769b1d76'})],

    '1ca6cf3d': [('info', 'v2.3 -> v3.2: Asta Hair Draw Hash'), (upgrade_hash, {'to': '1335fa30'})],
    '618d1c95': [('info', 'v3.1 -> v3.2: Asta Head Draw Hash'), (upgrade_hash, {'to': '6e1e2998'})],
    '0b10db89': [('info', 'v3.1 -> v3.2: Asta Body Draw Hash'), (upgrade_hash, {'to': '0483ee84'})],
    'b8e767e9': [('info', 'v3.1 -> v3.2: Asta Body Position Hash'), (upgrade_hash, {'to': '86253b68'})],


    # MARK: Aventurine
    'c4c588df': [('info', 'v2.2 -> v2.3: Aventurine Hair Draw Hash'),     (upgrade_hash, {'to': '2a1a1775'})],
    '015c8a86': [('info', 'v2.2 -> v2.3: Aventurine Hair Position Hash'), (upgrade_hash, {'to': '8de65cb9'})],
    '811fa2ca': [('info', 'v2.2 -> v2.3: Aventurine Hair Texcoord Hash'), (upgrade_hash, {'to': '32da43dd'})],
    '015f4887': [('info', 'v2.2 -> v2.3: Aventurine Hair IB Hash'),       (upgrade_hash, {'to': '59d6021b'})],
    '7f4af1d5': [('info', 'v2.2 -> v2.3: Aventurine Hair Diffuse Hash'),  (upgrade_hash, {'to': '7e21ce24'})],
    '3bbbdfcc': [('info', 'v2.2 -> v2.3: Aventurine Hair LightMap Hash'), (upgrade_hash, {'to': '4699613b'})],

    'c484fc3a': [('info', 'v2.2 -> v2.3: Aventurine Head Diffuse Hash'),  (upgrade_hash, {'to': 'd4874355'})],

    '982bd8c4': [('info', 'v2.2 -> v2.3: Aventurine Hair Texcoord Hash'), (upgrade_hash, {'to': '53bdb739'})],
    '53c4098f': [('info', 'v2.2 -> v2.3: Aventurine Hair Diffuse Hash'),  (upgrade_hash, {'to': 'b1cd8482'})],
    '6c801b21': [('info', 'v2.2 -> v2.3: Aventurine Hair LightMap Hash'), (upgrade_hash, {'to': '115d50a7'})],

    '8de65cb9': [('info', 'v2.3 -> v3.1: Aventurine Hair Position Hash'),   (upgrade_hash, {'to': '9453410b'})],
    '8e11bb4f': [('info', 'v3.0 -> v3.1: Aventurine Body Blend Hash'),      (upgrade_hash, {'to': '61e0c51b'})],
    'dbef38cc': [('info', 'v3.0 -> v3.1: Aventurine Hair Blend Hash'),      (upgrade_hash, {'to': '341e4698'})],
    'd6703a6e': [('info', 'v3.0 -> v3.1: Aventurine Head Blend Hash'),      (upgrade_hash, {'to': '3981443a'})],
    'ad82dc30': [('info', 'v3.0 -> v3.1: Aventurine Head Position Hash'),   (upgrade_hash, {'to': 'b437c182'})],

    '2a1a1775': [('info', 'v2.3 -> v3.2: Aventurine Hair Draw Hash'), (upgrade_hash, {'to': '25892278'})],
    '7df52768': [('info', 'v3.1 -> v3.2: Aventurine Head Draw Hash'), (upgrade_hash, {'to': '72661265'})],
    'a9bd2aa3': [('info', 'v3.1 -> v3.2: Aventurine Body Draw Hash'), (upgrade_hash, {'to': 'a62e1fae'})],
    '1a4a96c3': [('info', 'v3.1 -> v3.2: Aventurine Body Position Hash'), (upgrade_hash, {'to': '6bffa54d'})],



    # MARK: Bailu
    'e5417fe2': [('info', 'v1.6 -> v2.0: Bailu Body Texcoord Hash'), (upgrade_hash, {'to': 'd7a8228a'})],
    'dbf90364': [
        ('info', 'v1.6 -> v2.0: Bailu Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'BailuBody',
            'hash': '680253f0',
            'trg_indices': ['0', '33984', '56496', '62601'],
            'src_indices': ['0', '36429',    '-1',    '-1'],
        })
    ],
    # '5dfaf99e': [
    #     ('info', 'v2.1: Bailu Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': 'e2fb7ce0'}),
    #     (multiply_section, {
    #         'titles': ['BailuBodyPosition', 'BailuBodyPosition_Extra'],
    #         'hashes': ['5dfaf99e', 'e2fb7ce0']
    #     })
    # ],

    'e2fb7ce0': [('info', 'v2.2 -> v3.1: Bailu Body Position Extra Hash'),              (comment_sections, {})],
    'd1df61ab': [('info', 'v2.2 -> v2.3: Bailu Hair Diffuse Hash'),   (upgrade_hash, {'to': '1a6134dc'})],
    'dfe514d8': [('info', 'v2.2 -> v2.3: Bailu Hair LightMap Hash'),  (upgrade_hash, {'to': 'dcc96667'})],

    '52a50074': [('info', 'v2.2 -> v2.3: Bailu Head Diffuse Hash'),   (upgrade_hash, {'to': '75770ba0'})],
    
    'e3ea3823': [('info', 'v2.2 -> v2.3: Bailu BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'e430e059'})],
    '74d8fa7a': [('info', 'v2.2 -> v2.3: Bailu BodyA LightMap Hash'), (upgrade_hash, {'to': 'c42c0455'})],
    'de6e235f': [('info', 'v2.2 -> v2.3: Bailu BodyB Diffuse Hash'),  (upgrade_hash, {'to': 'e468513a'})],
    'bdab2370': [('info', 'v2.2 -> v2.3: Bailu BodyB LightMap Hash'), (upgrade_hash, {'to': '8d372ffc'})],

    '96a4a724': [('info', 'v3.0 -> v3.1: Bailu Body Blend Hash'),           (upgrade_hash, {'to': '7955d970'})],
    '68cef846': [('info', 'v3.0 -> v3.1: Bailu Hair Blend Hash'),           (upgrade_hash, {'to': '873f8612'})],
    '1779da3f': [('info', 'v3.0 -> v3.1: Bailu Hair Position Hash'),        (upgrade_hash, {'to': '0eccc78d'})],
    '15a034fc': [('info', 'v3.0 -> v3.1: Bailu Head Blend Hash'),           (upgrade_hash, {'to': 'fa514aa8'})],
    '0ae19e5d': [('info', 'v3.0 -> v3.1: Bailu Head Position Hash'),        (upgrade_hash, {'to': '135483ef'})],


    'a85facf8': [('info', 'v3.1 -> v3.2: Bailu Hair Draw Hash'), (upgrade_hash, {'to': 'a7cc99f5'})],
    'cbf2493c': [('info', 'v3.1 -> v3.2: Bailu Head Draw Hash'), (upgrade_hash, {'to': 'c4617c31'})],
    'ee0d45fe': [('info', 'v3.1 -> v3.2: Bailu Body Draw Hash'), (upgrade_hash, {'to': 'e19e70f3'})],
    '5dfaf99e': [('info', 'v3.0 -> v3.1: Bailu Body Position Hash'), (upgrade_hash, {'to': 'fb4e6152'})],

    # MARK: BlackSwan
    '96f25869': [('info', 'v2.0 -> v2.1: BlackSwan Body Texcoord Hash'), (upgrade_hash, {'to': '562fbdb4'})],
    # '197e8353': [
    #     ('info', 'v2.1: BlackSwan Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '10fb3cab'}),
    #     (multiply_section, {
    #         'titles': ['BlackSwanBodyPosition', 'BlackSwanBodyPosition_Extra'],
    #         'hashes': ['197e8353', '10fb3cab']
    #     })
    # ],

    '10fb3cab': [('info', 'v2.2 -> v3.1: BlackSwan Body Position Extra Hash'),              (comment_sections, {})],
    '5d782765': [('info', 'v2.2 -> v2.3: BlackSwan Hair Diffuse Hash'),     (upgrade_hash, {'to': '9f71dd91'})],
    '4013a662': [('info', 'v2.2 -> v2.3: BlackSwan Hair LightMap Hash'),    (upgrade_hash, {'to': 'b97825d7'})],

    '057dfd1a': [('info', 'v2.2 -> v2.3: BlackSwan Head Diffuse Hash'),     (upgrade_hash, {'to': '7464fbfe'})],
    
    '4ce38332': [('info', 'v2.2 -> v2.3: BlackSwan Body Diffuse Hash'),     (upgrade_hash, {'to': 'a5727e55'})],
    '5527e772': [('info', 'v2.2 -> v2.3: BlackSwan Body LightMap Hash'),    (upgrade_hash, {'to': '7884691d'})],
    '028b385d': [('info', 'v2.2 -> v2.3: BlackSwan Body StockingMap AMD Hash'),   (upgrade_hash, {'to': 'ec1ba003'})],
    '01f66a63': [('info', 'v2.2 -> v2.3: BlackSwan Body StockingMap NVDIA Hash'), (upgrade_hash, {'to': 'd037ddd6'})],

    'b4ec029d': [('info', 'v3.0 -> v3.1: BlackSwan Body Blend Hash'),       (upgrade_hash, {'to': '5b1d7cc9'})],
    '0d8672ce': [('info', 'v3.0 -> v3.1: BlackSwan Hair Blend Hash'),       (upgrade_hash, {'to': 'e2770c9a'})],
    'dc153ce0': [('info', 'v3.0 -> v3.1: BlackSwan Hair Position Hash'),    (upgrade_hash, {'to': 'c5a02152'})],
    'ede8abb0': [('info', 'v3.0 -> v3.1: BlackSwan Head Blend Hash'),       (upgrade_hash, {'to': '0219d5e4'})],
    '33edc9b2': [('info', 'v3.0 -> v3.1: BlackSwan Head Position Hash'),    (upgrade_hash, {'to': '2a58d400'})],
    
    '197e8353': [('info', 'v3.0 -> v3.1: BlackSwan Body Position Hash'), (upgrade_hash, {'to': '094e2119'})],
    'dda5d076': [('info', 'v3.1 -> v3.2: BlackSwan Hair Draw Hash'), (upgrade_hash, {'to': 'd236e57b'})],
    '755e1d94': [('info', 'v3.1 -> v3.2: BlackSwan Head Draw Hash'), (upgrade_hash, {'to': '7acd2899'})],
    'aa893f33': [('info', 'v3.1 -> v3.2: BlackSwan Body Draw Hash'), (upgrade_hash, {'to': 'a51a0a3e'})],


    # MARK: Blade
    'b95b80ad': [('info', 'v1.5 -> v1.6: Blade BodyA LightMap Hash'), (upgrade_hash, {'to': '459ea4f3'})],
    '0b7675c2': [('info', 'v1.5 -> v1.6: Blade BodyB LightMap Hash'), (upgrade_hash, {'to': 'bdbde74c'})],
    
    # This is reverted in 2.3? Extremely weird, investigate later
    # '90237dd2': [('info', 'v1.6 -> v2.0: Blade Head Position Hash'),  (upgrade_hash, {'to': '9bc595ba'})],

    'b931dfc7': [('info', 'v1.6 -> v2.0: Blade Body Texcoord Hash'),  (upgrade_hash, {'to': 'f7896b3e'})],
    '5d03ae61': [
        ('info', 'v1.6 -> v2.0: Blade Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'BladeBody',
            'hash': '0eb1e389',
            'trg_indices': ['0', '35790', '44814'],
            'src_indices': ['0', '35790',    '-1'],
        })
    ],

    '419db05a': [('info', 'v2.2 -> v2.3: Blade Hair Draw Hash'),     (upgrade_hash, {'to': '89af9f25'})],
    '71b698d8': [('info', 'v2.2 -> v2.3: Blade Hair Position Hash'), (upgrade_hash, {'to': 'dd309961'})],
    'ff18d193': [('info', 'v2.2 -> v2.3: Blade Hair Texcoord Hash'), (upgrade_hash, {'to': 'f646a974'})],
    '60d6a2c4': [('info', 'v2.2 -> v2.3: Blade Hair IB Hash'),       (upgrade_hash, {'to': 'ab8b5a42'})],
    '7e354cb4': [('info', 'v2.2 -> v2.3: Blade Hair Diffuse Hash'),  (upgrade_hash, {'to': '7cbac9fe'})],
    '32919d62': [('info', 'v2.2 -> v2.3: Blade Hair LightMap Hash'), (upgrade_hash, {'to': 'bc05281a'})],

    '9bc595ba': [('info', 'v2.2 -> v2.3: Blade Head Position Hash'), (upgrade_hash, {'to': '90237dd2'})],
    '6fa7fbdc': [('info', 'v2.2 -> v2.3: Blade Head Diffuse Hash'),  (upgrade_hash, {'to': '929dfaee'})],

    '1082d394': [('info', 'v2.2 -> v2.3: Blade BodyA Diffuse Hash'),  (upgrade_hash, {'to': '6166ea57'})],
    '459ea4f3': [('info', 'v2.2 -> v2.3: Blade BodyA LightMap Hash'), (upgrade_hash, {'to': 'a273cfa3'})],
    '409cd5c1': [('info', 'v2.2 -> v2.3: Blade BodyB Diffuse Hash'),  (upgrade_hash, {'to': '3a1b9bb1'})],
    'bdbde74c': [('info', 'v2.2 -> v2.3: Blade BodyB LightMap Hash'), (upgrade_hash, {'to': '647809bd'})],

    '4cc66b74': [('info', 'v3.0 -> v3.1: Blade Body Blend Hash'),           (upgrade_hash, {'to': 'a3371520'})],
    'aab6366e': [('info', 'v3.0 -> v3.1: Blade Hair Blend Hash'),           (upgrade_hash, {'to': '4547483a'})],
    'dd309961': [('info', 'v2.3 -> v3.1: Blade Hair Position Hash'),        (upgrade_hash, {'to': 'c48584d3'})],
    '2bc042b8': [('info', 'v3.0 -> v3.1: Blade Head Blend Hash'),           (upgrade_hash, {'to': 'c4313cec'})],
    '90237dd2': [('info', 'v2.3 -> v3.1: Blade Head Position Hash'),        (upgrade_hash, {'to': '89966060'})],

    '89af9f25': [('info', 'v2.3 -> v3.2: Blade Hair Draw Hash'), (upgrade_hash, {'to': '863caa28'})],
    '485280e8': [('info', 'v3.1 -> v3.2: Blade Head Draw Hash'), (upgrade_hash, {'to': '47c1b5e5'})],
    '553ae2f8': [('info', 'v3.1 -> v3.2: Blade Body Draw Hash'), (upgrade_hash, {'to': '5aa9d7f5'})],
    'e6cd5e98': [('info', 'v3.1 -> v3.2: Blade Body Position Hash'), (upgrade_hash, {'to': 'cd89693e'})],



    # MARK: Boothill
    '1e9505b5': [('info', 'v2.2 -> v2.3: Boothill Hair Diffuse Hash'),   (upgrade_hash, {'to': '3b420073'})],
    '8dccfaa1': [('info', 'v2.2 -> v2.3: Boothill Hair LightMap Hash'),  (upgrade_hash, {'to': 'af56a76b'})],

    '4e49ef76': [('info', 'v2.2 -> v2.3: Boothill Head Diffuse Hash'),   (upgrade_hash, {'to': '704d65a9'})],
 
     '845f6f6b': [('info', 'v2.2 -> v2.3: Boothill Draw Hash'),           (upgrade_hash, {'to': 'f261312e'})],
     '37a8d30b': [('info', 'v2.2 -> v2.3: Boothill Position Hash'),       (upgrade_hash, {'to': '41968d4e'})],
     'd0fb7df5': [('info', 'v2.2 -> v2.3: Boothill Texcoord Hash'),       (upgrade_hash, {'to': 'f8dd7e43'})],
     '87f245a6': [('info', 'v2.2 -> v2.3: Boothill IB Hash'),             (upgrade_hash, {'to': '3c3ec92a'})],
     '6d0a3848': [('info', 'v2.2 -> v2.3: Boothill BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'bd451832'})],
    'f914a7fe': [('info', 'v2.2 -> v2.3: Boothill BodyA LightMap Hash'), (upgrade_hash, {'to': 'f36e4a49'})],

    '5183fce7': [('info', 'v3.0 -> v3.1: Boothill Body Blend Hash'),        (upgrade_hash, {'to': 'be7282b3'})],
    'bd451832': [('info', 'v2.3 -> v3.1: Boothill BodyA Diffuse Hash'),     (upgrade_hash, {'to': '86707f18'})],
    'f36e4a49': [('info', 'v2.3 -> v3.1: Boothill BodyA LightMap Hash'),    (upgrade_hash, {'to': '6226eb4c'})],
    'add5290e': [('info', 'v3.0 -> v3.1: Boothill Hair Blend Hash'),        (upgrade_hash, {'to': '4224575a'})],
    'd164f7fd': [('info', 'v3.0 -> v3.1: Boothill Hair Position Hash'),     (upgrade_hash, {'to': 'c8d1ea4f'})],
    'e495cc7d': [('info', 'v3.0 -> v3.1: Boothill Head Blend Hash'),        (upgrade_hash, {'to': '0b64b229'})],
    '80a5d96e': [('info', 'v3.0 -> v3.1: Boothill Head Position Hash'),     (upgrade_hash, {'to': '9910c4dc'})],

    'f261312e': [('info', 'v2.3 -> v3.2: Boothill Body Draw Hash'), (upgrade_hash, {'to': 'fdf20423'})],
    '41968d4e': [('info', 'v2.3 -> v3.2: Boothill Body Position Hash'), (upgrade_hash, {'to': '8dbe6204'})],
    'caa64d35': [('info', 'v3.1 -> v3.2: Boothill Hair Draw Hash'), (upgrade_hash, {'to': 'c5357838'})],
    '18e79418': [('info', 'v3.1 -> v3.2: Boothill Head Draw Hash'), (upgrade_hash, {'to': '1774a115'})],


    # MARK: Bronya
    'f25b360a': [('info', 'v1.5 -> v1.6: Bronya BodyA LightMap Hash'), (upgrade_hash, {'to': '066f1a5a'})],
    '6989bd40': [('info', 'v1.5 -> v1.6: Bronya BodyB LightMap Hash'), (upgrade_hash, {'to': '5161422e'})],
    '7f5e24df': [('info', 'v1.6 -> v2.0: Bronya Hair Draw Hash'),        (upgrade_hash, {'to': '4e327afb'})],
    '8123eaff': [('info', 'v1.6 -> v2.0: Bronya Hair Position Hash'),  (upgrade_hash, {'to': '4265a087'})],
    'd6153000': [('info', 'v1.6 -> v2.0: Bronya Hair Texcoord Hash'),  (upgrade_hash, {'to': '2ec44855'})],
    '70fd4690': [('info', 'v1.6 -> v2.0: Bronya Hair IB Hash'),           (upgrade_hash, {'to': '2d03d71b'})],
    '39d9a850': [('info', 'v1.6 -> v2.0: Bronya Body Texcoord Hash'),  (upgrade_hash, {'to': '0d67a9c3'})],
    '1d057d1a': [
        ('info', 'v1.6 -> v2.0: Bronya Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'BronyaBody',
            'hash': '29d03f40',
            'trg_indices': ['0', '34431', '36345', '60423'],
            'src_indices': ['0',    '-1', '36345',    '-1'],
        })
    ],
    # '198eb408': [
    #     ('info', 'v2.1: Bronya Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '08f2d6dd'}),
    #     (multiply_section, {
    #         'titles': ['BronyaBodyPosition', 'BronyaBodyPosition_Extra'],
    #         'hashes': ['198eb408', '08f2d6dd']
    #     })
    # ],

    '08f2d6dd': [('info', 'v2.2 -> v3.1: Bronya Body Position Extra Hash'),              (comment_sections, {})],
    '79319861': [('info', 'v2.2 -> v2.3: Bronya Hair Diffuse Hash'),      (upgrade_hash, {'to': '7e9a40be'})],
    'c476c030': [('info', 'v2.2 -> v2.3: Bronya Hair LightMap Hash'),     (upgrade_hash, {'to': 'af5183a6'})],

    '901262ce': [('info', 'v2.2 -> v2.3: Bronya Head Diffuse Hash'),      (upgrade_hash, {'to': 'eea06253'})],

    '0b49e488': [('info', 'v2.2 -> v2.3: Bronya BodyA Diffuse Hash'),     (upgrade_hash, {'to': '3ed22aab'})],
    '066f1a5a': [('info', 'v2.2 -> v2.3: Bronya BodyA LightMap Hash'),    (upgrade_hash, {'to': 'b1117be0'})],
    'ac738042': [('info', 'v2.2 -> v2.3: Bronya BodyA StockingMap Hash'), (upgrade_hash, {'to': '45480a99'})],
    'e1c9d15e': [('info', 'v2.2 -> v2.3: Bronya BodyC Diffuse Hash'),     (upgrade_hash, {'to': 'da221a45'})],
    '5161422e': [('info', 'v2.2 -> v2.3: Bronya BodyC LightMap Hash'),    (upgrade_hash, {'to': '643fe76a'})],
    '720783d5': [('info', 'v2.2 -> v2.3: Bronya BodyC StockingMap Hash'), (upgrade_hash, {'to': '789f1abf'})],

    '09c90e7f': [('info', 'v3.0 -> v3.1: Bronya Body Blend Hash'),          (upgrade_hash, {'to': 'e638702b'})],
    'cd417d46': [('info', 'v3.0 -> v3.1: Bronya Hair Blend Hash'),          (upgrade_hash, {'to': '22b00312'})],
    '4265a087': [('info', 'v2.0 -> v3.1: Bronya Hair Position Hash'),       (upgrade_hash, {'to': '5bd0bd35'})],
    '314fb3a3': [('info', 'v3.0 -> v3.1: Bronya Head Blend Hash'),          (upgrade_hash, {'to': 'debecdf7'})],
    '9718281f': [('info', 'v3.0 -> v3.1: Bronya Head Position Hash'),       (upgrade_hash, {'to': '8ead35ad'})],

    '4e327afb': [('info', 'v2.0 -> v3.2: Bronya Hair Draw Hash'), (upgrade_hash, {'to': '41a14ff6'})],
    '198eb408': [('info', 'v3.0 -> v3.1: Bronya Body Position Hash'), (upgrade_hash, {'to': '1147cb6f'})],
    '204acd53': [('info', 'v3.1 -> v3.2: Bronya Head Draw Hash'), (upgrade_hash, {'to': '2fd9f85e'})],
    'aa790868': [('info', 'v3.1 -> v3.2: Bronya Body Draw Hash'), (upgrade_hash, {'to': 'a5ea3d65'})],


    # MARK: Clara
    '7365de7c': [('info', 'v1.6 -> v2.0: Clara Hair Draw Hash'),       (upgrade_hash, {'to': 'bcfb045b'})],
    '8c56882c': [('info', 'v1.6 -> v2.0: Clara Hair Position Hash'), (upgrade_hash, {'to': '486f6900'})],
    '572f5b77': [('info', 'v1.6 -> v2.0: Clara Hair Texcoord Hash'), (upgrade_hash, {'to': '08caadac'})],
    '58982bbd': [('info', 'v1.6 -> v2.0: Clara Hair IB Hash'),       (upgrade_hash, {'to': '338bbeec'})],
    'da981c17': [('info', 'v1.6 -> v2.0: Clara Body Draw Hash'),       (upgrade_hash, {'to': '8c9c698e'})],
    '696fa077': [('info', 'v1.6 -> v2.0: Clara Body Draw Hash'),       (upgrade_hash, {'to': '3f6bd5ee'})],
    '5dfa8761': [('info', 'v1.6 -> v2.0: Clara Body Texcoord Hash'), (upgrade_hash, {'to': 'a444344c'})],
    'f92afebc': [
        ('info', 'v1.6 -> v2.0: Clara Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'ClaraBody',
            'hash': '4a58be98',
            'trg_indices': ['0', '2016', '19290', '50910'],
            'src_indices': ['0',   '-1', '19293',    '-1'],
        })
    ],

    '4c5e718d': [('info', 'v2.2 -> v2.3: Clara Hair Diffuse Hash'),   (upgrade_hash, {'to': 'e730fbcc'})],
    '7fe8d517': [('info', 'v2.2 -> v2.3: Clara Hair LightMap Hash'),  (upgrade_hash, {'to': '4ecb33c7'})],

    'b6ba0179': [('info', 'v2.2 -> v2.3: Clara Head Diffuse Hash'),   (upgrade_hash, {'to': '64cd257f'})],

    'af43bb7c': [('info', 'v2.2 -> v2.3: Clara BodyA Diffuse Hash'),  (upgrade_hash, {'to': '198363bb'})],
    'ffd2f41b': [('info', 'v2.2 -> v2.3: Clara BodyA LightMap Hash'), (upgrade_hash, {'to': 'd73982e5'})],
    'ff7a7e5e': [('info', 'v2.2 -> v2.3: Clara BodyC Diffuse Hash'),  (upgrade_hash, {'to': 'a646bdde'})],
    '6c866716': [('info', 'v2.2 -> v2.3: Clara BodyC LightMap Hash'), (upgrade_hash, {'to': '6f4c03fe'})],

    '486f6900': [('info', 'v2.0 -> v3.1: Clara Hair Position Hash'),        (upgrade_hash, {'to': '51da74b2'})],
    '89e485a2': [('info', 'v3.0 -> v3.1: Clara Body Blend Hash'),           (upgrade_hash, {'to': '6615fbf6'})],
    'd7130c52': [('info', 'v3.0 -> v3.1: Clara Hair Blend Hash'),           (upgrade_hash, {'to': '38e27206'})],
    '01c3ad70': [('info', 'v3.0 -> v3.1: Clara Head Blend Hash'),           (upgrade_hash, {'to': 'ee32d324'})],
    'd252d8ba': [('info', 'v3.0 -> v3.1: Clara Head Position Hash'),        (upgrade_hash, {'to': 'cbe7c508'})],


    'bcfb045b': [('info', 'v2.0 -> v3.2: Clara Hair Draw Hash'), (upgrade_hash, {'to': 'b3683156'})],
    '8c9c698e': [('info', 'v2.0 -> v3.2: Clara Body Draw Hash'), (upgrade_hash, {'to': '830f5c83'})],
    '3f6bd5ee': [('info', 'v2.0 -> v3.2: Clara Body Position Hash'), (upgrade_hash, {'to': 'f4ad6f23'})],
    'c1db0d65': [('info', 'v3.1 -> v3.2: Clara Head Draw Hash'), (upgrade_hash, {'to': 'ce483868'})],


    # MARK: DanHeng
    'de0264c6': [('info', 'v1.4 -> v1.6: DanHeng BodyA LightMap Hash'), (upgrade_hash, {'to': '5e3149d6'})],
    'f01e58df': [('info', 'v1.6 -> v2.0: DanHeng Head Texcoord Hash'),  (upgrade_hash, {'to': '0c5e8d34'})],
    'ab30fd81': [('info', 'v1.6 -> v2.0: DanHeng Body Texcoord Hash'),  (upgrade_hash, {'to': '8bdfb25d'})],
    'f256d83c': [('info', 'v1.6 -> v2.0: DanHeng BodyA Diffuse Hash'),  (upgrade_hash, {'to': '95212661'})],
    'be813760': [
        ('info', 'v1.6 -> v2.0: DanHeng Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'DanHengBody',
            'hash': '457b4223',
            'trg_indices': ['0', '49005'],
            'src_indices': ['0',    '-1'],
        })
    ],

    '02394eab': [('info', 'v2.2 -> v2.3: DanHeng Hair Diffuse Hash'),  (upgrade_hash, {'to': '62604aad'})],
    '98fd88ae': [('info', 'v2.2 -> v2.3: DanHeng Hair LightMap Hash'), (upgrade_hash, {'to': 'e4fd41ae'})],

    '1e764817': [('info', 'v2.2 -> v2.3: DanHeng Head Diffuse Hash'),  (upgrade_hash, {'to': '65a5afa5'})],

    '95212661': [('info', 'v2.2 -> v2.3: DanHeng Body Diffuse Hash'),  (upgrade_hash, {'to': '72b7f37b'})],
    '5e3149d6': [('info', 'v2.2 -> v2.3: DanHeng Body LightMap Hash'), (upgrade_hash, {'to': '01999151'})],
    '01999151': [('info', 'v2.7 -> v3.0: DanHeng Body LightMap Hash'), (upgrade_hash, {'to': '75400c84'})],

    'b7594abd': [('info', 'v3.0 -> v3.1: DanHeng Body Blend Hash'),         (upgrade_hash, {'to': '58a834e9'})],
    '031da129': [('info', 'v3.0 -> v3.1: DanHeng Hair Blend Hash'),         (upgrade_hash, {'to': 'ececdf7d'})],
    'b591da57': [('info', 'v3.0 -> v3.1: DanHeng Hair Position Hash'),      (upgrade_hash, {'to': 'ac24c7e5'})],
    '5bfc6e67': [('info', 'v3.0 -> v3.1: DanHeng Head Blend Hash'),         (upgrade_hash, {'to': 'b40d1033'})],
    '8ed66c8a': [('info', 'v3.0 -> v3.1: DanHeng Head Position Hash'),      (upgrade_hash, {'to': '97637138'})],

    'acf975aa': [('info', 'v3.1 -> v3.2: DanHeng Hair Draw Hash'), (upgrade_hash, {'to': 'a36a40a7'})],
    'cf9c7841': [('info', 'v3.1 -> v3.2: DanHeng Head Draw Hash'), (upgrade_hash, {'to': 'c00f4d4c'})],
    '2c5a53ab': [('info', 'v3.1 -> v3.2: DanHeng Body Draw Hash'), (upgrade_hash, {'to': '23c966a6'})],
    '9fadefcb': [('info', 'v3.1 -> v3.2: DanHeng Body Position Hash'), (upgrade_hash, {'to': '48aa5ec1'})],

    # MARK: DanHengIL
    '9249f149': [('info', 'v1.4 -> v1.6: DanHengIL BodyA LightMap Hash'), (upgrade_hash, {'to': 'ef65d29c'})],
    '0ffb8233': [('info', 'v1.6 -> v2.0: DanHengIL Body Texcoord Hash'),  (upgrade_hash, {'to': '0f8da6ba'})],
    '1a7ee87c': [
        ('info', 'v1.6 -> v2.0: DanHengIL Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'DanHengILBody',
            'hash': '7cb75a5e',
            'trg_indices': ['0', '47133'],
            'src_indices': ['0',    '-1'],
        })
    ],

    '5f6f803e': [('info', 'v2.2 -> v2.3: DanHengIL Hair Diffuse Hash'),  (upgrade_hash, {'to': '779e60a8'})],
    'ec8baa47': [('info', 'v2.2 -> v2.3: DanHengIL Hair LightMap Hash'), (upgrade_hash, {'to': '41840f8a'})],

    'd64ab9dc': [('info', 'v2.2 -> v2.3: DanHengIL Head Diffuse Hash'),  (upgrade_hash, {'to': 'f1b129e2'})],

    '85486705': [('info', 'v2.2 -> v2.3: DanHengIL Body Diffuse Hash'),  (upgrade_hash, {'to': '9300840e'})],
    'ef65d29c': [('info', 'v2.2 -> v2.3: DanHengIL Body LightMap Hash'), (upgrade_hash, {'to': 'b0660300'})],

    '9cbdcefd': [('info', 'v3.0 -> v3.1: DanHengIL Body Blend Hash'),       (upgrade_hash, {'to': '734cb0a9'})],
    '97be0a41': [('info', 'v3.0 -> v3.1: DanHengIL Hair Blend Hash'),       (upgrade_hash, {'to': '784f7415'})],
    '09d4edc5': [('info', 'v3.0 -> v3.1: DanHengIL Hair Position Hash'),    (upgrade_hash, {'to': '1061f077'})],
    '4616d1e7': [('info', 'v3.0 -> v3.1: DanHengIL Head Blend Hash'),       (upgrade_hash, {'to': 'a9e7afb3'})],
    'c7751dba': [('info', 'v3.0 -> v3.1: DanHengIL Head Position Hash'),    (upgrade_hash, {'to': 'dec00008'})],
    'c0933fd1': [('info', 'v3.0 -> v3.1: DanHengIL Horns Draw Hash'),    (upgrade_hash, {'to': 'd9262263'})],

    '2f69b239': [('info', 'v3.1 -> v3.2: DanHengIL Hair Draw Hash'), (upgrade_hash, {'to': '20fa8734'})],
    'e556ac29': [('info', 'v3.1 -> v3.2: DanHengIL Head Draw Hash'), (upgrade_hash, {'to': 'eac59924'})],
    'dc21ac4d': [('info', 'v3.1 -> v3.2: DanHengIL Body Draw Hash'), (upgrade_hash, {'to': 'd3b29940'})],
    '6fd6102d': [('info', 'v3.1 -> v3.2: DanHengIL Body Position Hash'), (upgrade_hash, {'to': '093e22f4'})],


    # MARK: DrRatio
    'd1795906': [('info', 'v1.6 -> v2.0: DrRatio Hair Draw Hash'),        (upgrade_hash, {'to': 'fbcffe5a'})],
    '4d6e85c4': [('info', 'v1.6 -> v2.0: DrRatio Hair Position Hash'), (upgrade_hash, {'to': '5ca10450'})],
    'a8c25bde': [('info', 'v1.6 -> v2.0: DrRatio Hair Texcoord Hash'), (upgrade_hash, {'to': '26a8f257'})],
    'f205cf29': [('info', 'v1.6 -> v2.0: DrRatio Hair IB Hash'),        (upgrade_hash, {'to': '76d7d3f3'})],
    '70238f05': [('info', 'v1.6 -> v2.0: DrRatio Head Draw Hash'),        (upgrade_hash, {'to': '9857f892'})],
    '8dfb8014': [('info', 'v1.6 -> v2.0: DrRatio Head Position Hash'), (upgrade_hash, {'to': 'b88dc8c6'})],
    '874d30a8': [('info', 'v1.6 -> v2.0: DrRatio Head Texcoord Hash'), (upgrade_hash, {'to': '91f740da'})],
    'ad2be93d': [('info', 'v1.6 -> v2.0: DrRatio Head IB Hash'),        (upgrade_hash, {'to': '82bc4a2d'})],
    'dc2c9035': [('info', 'v1.6 -> v2.0: DrRatio Body Draw Hash'),        (upgrade_hash, {'to': 'd5f71e0e'})],
    '6fdb2c55': [('info', 'v1.6 -> v2.0: DrRatio Body Position Hash'), (upgrade_hash, {'to': '6600a26e'})],
    '32ccb687': [('info', 'v1.6 -> v2.0: DrRatio Body Texcoord Hash'), (upgrade_hash, {'to': 'e6b81399'})],
    '4a12ec28': [
        ('info', 'v1.6 -> v2.0: DrRatio Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'DrRatioBody',
            'hash': '37c47042',
            'trg_indices': ['0', '56361'],
            'src_indices': ['0',    '-1'],
        })
    ],

    'fbcffe5a': [('info', 'v2.2 -> v2.3: DrRatio Hair Draw Hash'),     (upgrade_hash, {'to': 'b310931e'})],
    '5ca10450': [('info', 'v2.2 -> v2.3: DrRatio Hair Position Hash'), (upgrade_hash, {'to': '7a9d0dac'})],
    '26a8f257': [('info', 'v2.2 -> v2.3: DrRatio Hair Texcoord Hash'), (upgrade_hash, {'to': '650888fc'})],
    '76d7d3f3': [('info', 'v2.2 -> v2.3: DrRatio Hair IB Hash'),       (upgrade_hash, {'to': '0a520e04'})],
    '013f4f5d': [('info', 'v2.2 -> v2.3: DrRatio Hair Diffuse Hash'),  (upgrade_hash, {'to': '521b3d2d'})],
    '8eccb31c': [('info', 'v2.2 -> v2.3: DrRatio Hair LightMap Hash'), (upgrade_hash, {'to': '5a50e9ba'})],

    '29a331d7': [('info', 'v2.2 -> v2.3: DrRatio Head Diffuse Hash'),  (upgrade_hash, {'to': '4c6a99ed'})],

    'd8ae56ba': [('info', 'v2.2 -> v2.3: DrRatio Body Diffuse Hash'),  (upgrade_hash, {'to': 'e80725f3'})],
    '9fa75d99': [('info', 'v2.2 -> v2.3: DrRatio Body LightMap Hash'), (upgrade_hash, {'to': '4329d27b'})],

    'b88dc8c6': [('info', 'v2.0 -> v3.1: DrRatio Head Position Hash'),      (upgrade_hash, {'to': 'a138d574'})],
    '7a9d0dac': [('info', 'v2.3 -> v3.1: DrRatio Hair Position Hash'),      (upgrade_hash, {'to': '6328101e'})],
    'ec519551': [('info', 'v3.0 -> v3.1: DrRatio Body Blend Hash'),         (upgrade_hash, {'to': '03a0eb05'})],
    '7d37a021': [('info', 'v3.0 -> v3.1: DrRatio Hair Blend Hash'),         (upgrade_hash, {'to': '92c6de75'})],
    '6e1dc670': [('info', 'v3.0 -> v3.1: DrRatio Head Blend Hash'),         (upgrade_hash, {'to': '81ecb824'})],

    '9857f892': [('info', 'v2.0 -> v3.2: DrRatio Head Draw Hash'), (upgrade_hash, {'to': '97c4cd9f'})],
    'd5f71e0e': [('info', 'v2.0 -> v3.2: DrRatio Body Draw Hash'), (upgrade_hash, {'to': 'da642b03'})],
    '6600a26e': [('info', 'v2.0 -> v3.2: DrRatio Body Position Hash'), (upgrade_hash, {'to': '053732e7'})],
    'b310931e': [('info', 'v2.3 -> v3.2: DrRatio Hair Draw Hash'), (upgrade_hash, {'to': 'bc83a613'})],


    # MARK: Feixiao
    # '1ef800bc': [
    #     ('info', 'v2.5: Feixiao Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '85d02e23'}),
    #     (multiply_section, {
    #         'titles': ['FeixiaoBodyPosition', 'FeixiaoBodyPosition_Extra'],
    #         'hashes': ['1ef800bc', '85d02e23']
    #     })
    # ],
    '85d02e23': [('info', 'v2.2 -> v3.1: Feixiao Body Position Extra Hash'),              (comment_sections, {})],

    '704530bd': [('info', 'v3.0 -> v3.1: Feixiao Body Blend Hash'),         (upgrade_hash, {'to': '9fb44ee9'})],
    'b5994a59': [('info', 'v3.0 -> v3.1: Feixiao Hair Blend Hash'),         (upgrade_hash, {'to': '5a68340d'})],
    '33418ff8': [('info', 'v3.0 -> v3.1: Feixiao Hair Position Hash'),      (upgrade_hash, {'to': '2af4924a'})],
    '3e6aa1cc': [('info', 'v3.0 -> v3.1: Feixiao Head Blend Hash'),         (upgrade_hash, {'to': 'd19bdf98'})],
    'fbd97f64': [('info', 'v3.0 -> v3.1: Feixiao Head Position Hash'),      (upgrade_hash, {'to': 'e26c62d6'})],
    'e4943d34': [('info', 'v3.0 -> v3.1: Feixiao Mark Blend Hash'),         (upgrade_hash, {'to': '0b654360'})],
    '39641aa2': [('info', 'v3.0 -> v3.1: Feixiao Mark Position Hash'),      (upgrade_hash, {'to': '20d10710'})],

    '1ef800bc': [('info', 'v3.0 -> v3.1: Feixiao Body Position Hash'), (upgrade_hash, {'to': '9c653391'})],
    '7a972d55': [('info', 'v3.1 -> v3.2: Feixiao Hair Draw Hash'), (upgrade_hash, {'to': '75041858'})],
    '035b9700': [('info', 'v3.1 -> v3.2: Feixiao Head Draw Hash'), (upgrade_hash, {'to': '0cc8a20d'})],
    'ad0fbcdc': [('info', 'v3.1 -> v3.2: Feixiao Body Draw Hash'), (upgrade_hash, {'to': 'a29c89d1'})],

    'b78e9538': [('info', 'v3.1 -> v3.2: Feixiao Mark Draw Hash'), (upgrade_hash, {'to': 'b81da035'})],


    # MARK: Firefly
    '81984c7b': [('info', 'v2.2 -> v2.3 (npc/playable): Firefly Hair Diffuse Hash'),  (upgrade_hash, {'to': 'cc46e8e8'})],
    'cc46e8e8': [('info', 'v2.7 -> v3.0: Firefly Hair Diffuse Hash'),                 (upgrade_hash, {'to': 'e0eeaba2'})],
    '2cc928b2': [('info', 'v2.2 -> v2.3 (npc/playable): Firefly Hair LightMap Hash'), (upgrade_hash, {'to': '38ae656e'})],
    '38ae656e': [('info', 'v2.7 -> v3.0: Firefly Hair LightMap Hash'),                (upgrade_hash, {'to': '61303c45'})],

    '9966e83e': [('info', 'v2.2 -> v2.3 (npc/playable): Firefly Head Diffuse Hash'),  (upgrade_hash, {'to': 'c61c087d'})],

    '8330592e': [('info', 'v2.2 -> v2.3 (npc/playable): Firefly Body Draw Hash'),     (upgrade_hash, {'to': 'da829543'})],
    '30c7e54e': [('info', 'v2.2 -> v2.3 (npc/playable): Firefly Body Position Hash'), (upgrade_hash, {'to': '69752923'})],
    '274d9c39': [('info', 'v2.2 -> v2.3 (npc/playable): Firefly Body Texcoord Hash'), (upgrade_hash, {'to': 'f57c4e74'})],
    '977bcde9': [
        ('info', 'v2.2 -> v2.3 (npc/playable): Firefly Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'FireflyBody',
            'hash': '423c22f1',
            'trg_indices': ['0', '32547', '66561'],
            'src_indices': ['0', '32976', '66429'],
        })
    ],
    'b5be8f4f': [('info', 'v2.2 -> v2.3 (npc/playable): Firefly Body Diffuse Hash'),  (upgrade_hash, {'to': '70c1071f'})],
    '04ea14b2': [('info', 'v2.2 -> v2.3 (npc/playable): Firefly Body LightMap Hash'), (upgrade_hash, {'to': '3f9e2b37'})],

    '681937c7': [('info', 'v3.0 -> v3.1: Firefly Body Blend Hash'),         (upgrade_hash, {'to': '87e84993'})],
    '7981904e': [('info', 'v3.0 -> v3.1: Firefly Hair Blend Hash'),         (upgrade_hash, {'to': '9670ee1a'})],
    'd0ebca93': [('info', 'v3.0 -> v3.1: Firefly Hair Position Hash'),      (upgrade_hash, {'to': 'c95ed721'})],

    'b5ca90ce': [('info', 'v3.0 -> v3.1: Firefly Head Blend Hash'),         (upgrade_hash, {'to': '5a3bee9a'})],
    '60fa9067': [('info', 'v3.0 -> v3.1: Firefly Head Position Hash'),      (upgrade_hash, {'to': '794f8dd5'})],


    '17f203db': [('info', 'v3.1 -> v3.2: Firefly Hair Draw Hash'),          (upgrade_hash, {'to': '186136d6'})],
    '3c61efc2': [('info', 'v3.1 -> v3.2: Firefly Head Draw Hash'),          (upgrade_hash, {'to': '33f2dacf'})],
    'da829543': [('info', 'v2.3 -> v3.2: Firefly Body Draw Hash'),          (upgrade_hash, {'to': 'd511a04e'})],
    '69752923': [('info', 'v2.3 -> v3.2: Firefly Body Position Hash'),      (upgrade_hash, {'to': 'f8fbf6ce'})],
    
    '5a3bee9a': [
        ('info', 'v3.2: Firefly Face Blend: Duplicate blend section for ultimate'),
        (check_hash_not_in_ini, {'hash': '94a5b64e'}),
        (multiply_section, {
            'titles': ['FireflyFaceBlend', 'FireflyFaceBlend_Extra'],
            'hashes': ['5a3bee9a', '94a5b64e']
        })
    ],


    # MARK: Firefly SAM
    '602bb9eb': [('info', 'v2.7 -> v3.0: Firefly SAM Ult Diffuse Hash'), (upgrade_hash, {'to': '006c5936'})],
    '20f1a341': [('info', 'v3.0 -> v3.1: Sam Body Blend Hash'),             (upgrade_hash, {'to': 'cf00dd15'})],
    '6799671e': [('info', 'v3.0 -> v3.1: Sam Body Position Hash'),          (upgrade_hash, {'to': '7e2c7aac'})],

    '3c383ed4': [('info', 'v3.1 -> v3.2: Sam Body Draw Hash'), (upgrade_hash, {'to': '33ab0bd9'})],
    'd631258c': [('info', 'v3.1 -> v3.2: Sam Wings Draw Hash'), (upgrade_hash, {'to': 'd9a21081'})],
    'ebaebdc2': [('info', 'v3.1 -> v3.2: Sam Wings Position Hash'), (upgrade_hash, {'to': 'f21ba070'})],
    '50ee777c': [('info', 'v3.1 -> v3.2: Sam Wings Blend Hash'), (upgrade_hash, {'to': 'bf1f0928'})],

    # MARK: Fugue

    '94f94174': [('info', 'v3.0 -> v3.1: Fugue Body Blend Hash'),    (upgrade_hash, {'to': '7b083f20'})],
    '04d0f9a0': [('info', 'v3.0 -> v3.1: Fugue Tail Blend Hash'),    (upgrade_hash, {'to': 'eb2187f4'})],
    '5332f9ed': [('info', 'v3.0 -> v3.1: Fugue Body Blend Hash'),    (upgrade_hash, {'to': 'bcc387b9'})],
    '6d651fcc': [('info', 'v3.0 -> v3.1: Fugue Face Blend Hash'),    (upgrade_hash, {'to': '82946198'})],

    'c0f48e5a': [('info', 'v3.1 -> v3.2: Fugue Body Draw Hash'),    (upgrade_hash, {'to': 'cf67bb57'})],
    'a69170f8': [('info', 'v3.1 -> v3.2: Fugue Tail Draw Hash'),    (upgrade_hash, {'to': 'a90245f5'})],
    'b36af760': [('info', 'v3.1 -> v3.2: Fugue Hair Draw Hash'),    (upgrade_hash, {'to': 'bcf9c26d'})],
    '1f5a3282': [('info', 'v3.1 -> v3.2: Fugue Head Draw Hash'),    (upgrade_hash, {'to': '10c9078f'})],


    # MARK: FuXuan
    '71906b4e': [('info', 'v1.6 -> v2.0: FuXuan Body Texcoord Hash'), (upgrade_hash, {'to': '45b0663d'})],
    '7d77bdb5': [
        ('info', 'v1.6 -> v2.0: FuXuan Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'FuXuanBody',
            'hash': 'c230f24a',
            'trg_indices': ['0', '39018', '57636', '65415'],
            'src_indices': ['0', '46797',     '-1',   '-1'],
        })
    ],

    '73b1fe83': [('info', 'v2.2 -> v2.3: FuXuan Hair Texcoord Hash'),     (upgrade_hash, {'to': 'f498555d'})],
    'df067d4d': [('info', 'v2.2 -> v2.3: FuXuan Hair Diffuse Hash'),      (upgrade_hash, {'to': 'afb05dab'})],
    'dfc8fb64': [('info', 'v2.2 -> v2.3: FuXuan Hair LightMap Hash'),     (upgrade_hash, {'to': 'd4b96cd1'})],

    '0dd26508': [('info', 'v2.2 -> v2.3: FuXuan Head Diffuse Hash'),      (upgrade_hash, {'to': '0bf30362'})],

    '9e822610': [('info', 'v2.2 -> v2.3: FuXuan BodyA Diffuse Hash'),     (upgrade_hash, {'to': '6455fc0a'})],
    '50b30274': [('info', 'v2.2 -> v2.3: FuXuan BodyA LightMap Hash'),    (upgrade_hash, {'to': '4ba289bf'})],
    '0172c74d': [('info', 'v2.2 -> v2.3: FuXuan BodyB Diffuse Hash'),     (upgrade_hash, {'to': '09c78c66'})],
    'd9171ad6': [('info', 'v2.2 -> v2.3: FuXuan BodyB LightMap Hash'),    (upgrade_hash, {'to': 'ce81f2e6'})],
    '02291372': [('info', 'v2.2 -> v2.3: FuXuan BodyB StockingMap Hash'), (upgrade_hash, {'to': 'c7b3e7bd'})],

    '3f5bd667': [('info', 'v3.0 -> v3.1: FuXuan Body Blend Hash'),          (upgrade_hash, {'to': 'd0aaa833'})],
    '8f1c057c': [('info', 'v3.0 -> v3.1: FuXuan Hair Blend Hash'),          (upgrade_hash, {'to': '60ed7b28'})],
    '5f23a159': [('info', 'v3.0 -> v3.1: FuXuan Hair Position Hash'),       (upgrade_hash, {'to': '4696bceb'})],
    'b11ec441': [('info', 'v3.0 -> v3.1: FuXuan Head Blend Hash'),          (upgrade_hash, {'to': '5eefba15'})],
    'f8d8d92e': [('info', 'v3.0 -> v3.1: FuXuan Head Position Hash'),       (upgrade_hash, {'to': 'e16dc49c'})],

    '84ba05f1': [('info', 'v3.1 -> v3.2: FuXuan Hair Draw Hash'), (upgrade_hash, {'to': '8b2930fc'})],
    'eb684772': [('info', 'v3.1 -> v3.2: FuXuan Head Draw Hash'), (upgrade_hash, {'to': 'e4fb727f'})],
    '529a3934': [('info', 'v3.1 -> v3.2: FuXuan Body Draw Hash'), (upgrade_hash, {'to': '5d090c39'})],
    'e16d8554': [('info', 'v3.1 -> v3.2: FuXuan Body Position Hash'), (upgrade_hash, {'to': '62bdf52f'})],


    # MARK: Gallagher
    '3464c771': [('info', 'v2.2 -> v2.3: Gallagher Hair Draw Hash'),     (upgrade_hash, {'to': '4ce0e733'})],
    'e2a6c3dd': [('info', 'v2.2 -> v2.3: Gallagher Hair Position Hash'), (upgrade_hash, {'to': 'b0198c11'})],
    '8a910c8c': [('info', 'v2.2 -> v2.3: Gallagher Hair Texcoord Hash'), (upgrade_hash, {'to': '9023270b'})],
    'f5c82676': [('info', 'v2.2 -> v2.3: Gallagher Hair IB Hash'),       (upgrade_hash, {'to': 'e9f3a740'})],
    '8590504d': [('info', 'v2.2 -> v2.3: Gallagher Hair Diffuse Hash'),  (upgrade_hash, {'to': '0adf3bf9'})],
    '69d380ac': [('info', 'v2.2 -> v2.3: Gallagher Hair LightMap Hash'), (upgrade_hash, {'to': 'b1f5a889'})],

    '6c2c7e1c': [('info', 'v2.2 -> v2.3: Gallagher Head Diffuse Hash'),  (upgrade_hash, {'to': '81a00110'})],

    '4902ec09': [('info', 'v2.2 -> v2.3: Gallagher Body Diffuse Hash'),  (upgrade_hash, {'to': '585134a8'})],
    '851877a3': [('info', 'v2.2 -> v2.3: Gallagher Body LightMap Hash'), (upgrade_hash, {'to': '39bf93ba'})],

    'b0198c11': [('info', 'v2.3 -> v3.1: Gallagher Hair Position Hash'),    (upgrade_hash, {'to': 'a9ac91a3'})],
    'b8346c8b': [('info', 'v3.0 -> v3.1: Gallagher Body Blend Hash'),       (upgrade_hash, {'to': '57c512df'})],
    'd9d4ed61': [('info', 'v3.0 -> v3.1: Gallagher Hair Blend Hash'),       (upgrade_hash, {'to': '36259335'})],
    '0a7424b1': [('info', 'v3.0 -> v3.1: Gallagher Head Blend Hash'),       (upgrade_hash, {'to': 'e5855ae5'})],
    'ac642ccc': [('info', 'v3.0 -> v3.1: Gallagher Head Position Hash'),    (upgrade_hash, {'to': 'b5d1317e'})],

    '4ce0e733': [('info', 'v2.3 -> v3.2: Gallagher Hair Draw Hash'), (upgrade_hash, {'to': '4373d23e'})],
    '0a3ab5fd': [('info', 'v3.1 -> v3.2: Gallagher Head Draw Hash'), (upgrade_hash, {'to': '05a980f0'})],
    '623f8510': [('info', 'v3.1 -> v3.2: Gallagher Body Draw Hash'), (upgrade_hash, {'to': '6dacb01d'})],
    'd1c83970': [('info', 'v3.1 -> v3.2: Gallagher Body Position Hash'), (upgrade_hash, {'to': '46f13636'})],


    # MARK: Gepard
    'd62bbd0f': [('info', 'v1.6 -> v2.0: Gepard Body Texcoord Hash'), (upgrade_hash, {'to': '04094d7e'})],
    '30aa99d6': [
        ('info', 'v1.6 -> v2.0: Gepard Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'GepardBody',
            'hash': '1e4f876c',
            'trg_indices': ['0', '27621', '55773', '57774'],
            'src_indices': ['0', '31266',     '-1',   '-1'],
        })
    ],

    '71ba118e': [('info', 'v2.2 -> v2.3: Gepard Hair Diffuse Hash'),   (upgrade_hash, {'to': 'a4d9351f'})],
    '12718dd9': [('info', 'v2.2 -> v2.3: Gepard Hair LightMap Hash'),  (upgrade_hash, {'to': '00e5e932'})],

    '67bf8ce8': [('info', 'v2.2 -> v2.3: Gepard Head Diffuse Hash'),   (upgrade_hash, {'to': '32a6a2cc'})],

    '19731fb9': [('info', 'v2.2 -> v2.3: Gepard BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'e70c5ef2'})],
    'da172387': [('info', 'v2.2 -> v2.3: Gepard BodyA LightMap Hash'), (upgrade_hash, {'to': '2ca81203'})],
    '369fb8ef': [('info', 'v2.2 -> v2.3: Gepard BodyB Diffuse Hash'),  (upgrade_hash, {'to': 'aff5c287'})],
    '2482636f': [('info', 'v2.2 -> v2.3: Gepard BodyB LightMap Hash'), (upgrade_hash, {'to': '2ba5e966'})],

    '9875df96': [('info', 'v3.0 -> v3.1: Gepard Body Blend Hash'),          (upgrade_hash, {'to': '7784a1c2'})],
    'ff3a4705': [('info', 'v3.0 -> v3.1: Gepard Hair Blend Hash'),          (upgrade_hash, {'to': '10cb3951'})],
    '26734c62': [('info', 'v3.0 -> v3.1: Gepard Hair Position Hash'),       (upgrade_hash, {'to': '3fc651d0'})],
    '37f39435': [('info', 'v3.0 -> v3.1: Gepard Head Blend Hash'),          (upgrade_hash, {'to': 'd802ea61'})],
    '19c9ccc9': [('info', 'v3.0 -> v3.1: Gepard Head Position Hash'),       (upgrade_hash, {'to': '007cd17b'})],

    '0c9c901c': [('info', 'v3.1 -> v3.2: Gepard Hair Draw Hash'), (upgrade_hash, {'to': '030fa511'})],
    
    '64e03e8e': [('info', 'v3.1 -> v3.2: Gepard Body Draw Hash'), (upgrade_hash, {'to': '6b730b83'})],
    'd71782ee': [('info', 'v3.1 -> v3.2: Gepard Body Position Hash'), (upgrade_hash, {'to': '20cf413e'})],

    # MARK: Guinaifen
    'de1f98c0': [('info', 'v1.6 -> v2.0: Guinaifen Body Draw Hash'),            (upgrade_hash, {'to': '637ad2db'})],
    '6de824a0': [('info', 'v1.6 -> v2.0: Guinaifen Body Position Hash'),        (upgrade_hash, {'to': 'd08d6ebb'})],
    '4b1cdcfc': [('info', 'v1.6 -> v2.0: Guinaifen Body Position Extra Hash'), (upgrade_hash, {'to': '506edd10'})],
    '6e216a03': [('info', 'v1.6 -> v2.0: Guinaifen Body Texcoord Hash'),        (upgrade_hash, {'to': '2eeff76f'})],
    '75d5ec54': [
        ('info', 'v1.6 -> v2.0: Guinaifen Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'GuinaifenBody',
            'hash': '79900144',
            'trg_indices': ['0', '8907', '34146', '54723'],
            'src_indices': ['0',   '-1', '34146',    '-1'],
        })
    ],
    # 'd08d6ebb': [
    #     ('info', 'v2.1: Guinaifen Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '506edd10'}),
    #     (check_hash_not_in_ini, {'hash': '4b1cdcfc'}),
    #     (multiply_section, {
    #         'titles': ['GuinaifenBodyPosition', 'GuinaifenBodyPosition_Extra'],
    #         'hashes': ['d08d6ebb', '506edd10']
    #     })
    # ],

    'c88f1557': [('info', 'v2.2 -> v2.3: Guinaifen Hair Diffuse Hash'),      (upgrade_hash, {'to': 'fbd7db30'})],
    '33043521': [('info', 'v2.2 -> v2.3: Guinaifen Hair LightMap Hash'),     (upgrade_hash, {'to': 'c6e13e26'})],

    '7c097e20': [('info', 'v2.2 -> v2.3: Guinaifen Head Diffuse Hash'),      (upgrade_hash, {'to': '81dd54bc'})],

    'e73b9426': [('info', 'v2.2 -> v2.3: Guinaifen BodyA Diffuse Hash'),     (upgrade_hash, {'to': 'ae6de86c'})],
    'd6a8cff9': [('info', 'v2.2 -> v2.3: Guinaifen BodyA LightMap Hash'),    (upgrade_hash, {'to': '4092649e'})],
    '47551426': [('info', 'v2.2 -> v2.3: Guinaifen BodyA StockingMap Hash'), (upgrade_hash, {'to': 'caf58d2a'})],
    'd5d770b0': [('info', 'v2.2 -> v2.3: Guinaifen BodyC Diffuse Hash'),     (upgrade_hash, {'to': 'b710c78e'})],
    'a72e61d5': [('info', 'v2.2 -> v2.3: Guinaifen BodyC LightMap Hash'),    (upgrade_hash, {'to': '4463cc21'})],

    '637ad2db': [('info', 'v2.0 -> v3.1: Guinaifen Body Draw Hash'),        (upgrade_hash, {'to': '6ce9e7d6'})],
    'd08d6ebb': [('info', 'v3.0 -> v3.1: Guinaifen Body Position Hash'), (upgrade_hash, {'to': '49dbc0a2'})],
    '506edd10': [('info', 'v2.0 -> v3.1: Guinaifen Body Position Extra Hash'),              (comment_sections, {})],
    '93f9c6fc': [('info', 'v3.0 -> v3.1: Guinaifen Body Blend Hash'),       (upgrade_hash, {'to': '7c08b8a8'})],
    '7e75c06e': [('info', 'v3.0 -> v3.1: Guinaifen Hair Blend Hash'),       (upgrade_hash, {'to': '9184be3a'})],
    '1b4cc6bb': [('info', 'v3.0 -> v3.1: Guinaifen Hair Position Hash'),    (upgrade_hash, {'to': '02f9db09'})],
    '3753bbee': [('info', 'v3.0 -> v3.1: Guinaifen Head Blend Hash'),       (upgrade_hash, {'to': 'd8a2c5ba'})],
    '735df382': [('info', 'v3.0 -> v3.1: Guinaifen Head Position Hash'),    (upgrade_hash, {'to': '6ae8ee30'})],

    'f405349a': [('info', 'v3.1 -> v3.2: Guinaifen Hair Draw Hash'), (upgrade_hash, {'to': 'fb960197'})],
    'b853ead4': [('info', 'v3.1 -> v3.2: Guinaifen Head Draw Hash'), (upgrade_hash, {'to': 'b7c0dfd9'})],


    # MARK: Hanya
    'a73510da': [('info', 'v1.6 -> v2.0: Hanya Body Texcoord Hash'), (upgrade_hash, {'to': '69a81bdb'})],
    '42de1256': [
        ('info', 'v1.6 -> v2.0: Hanya Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'HanyaBody',
            'hash': 'b1c2c937',
            'trg_indices': ['0', '28818', '51666', '52734'],
            'src_indices': ['0', '29886',    '-1',    '-1'],
        })
    ],

    '8bc1d1db': [('info', 'v2.2 -> v2.3: Hanya Hair Diffuse Hash'),      (upgrade_hash, {'to': '7b9e82c5'})],
    '18503e31': [('info', 'v2.2 -> v2.3: Hanya Hair LightMap Hash'),     (upgrade_hash, {'to': '44c3983d'})],

    '19cae91f': [('info', 'v2.2 -> v2.3: Hanya Head Diffuse Hash'),      (upgrade_hash, {'to': '6d95729a'})],

    'b6dea863': [('info', 'v2.2 -> v2.3: Hanya BodyA Diffuse Hash'),     (upgrade_hash, {'to': '3a1da416'})],
    'b4d0253c': [('info', 'v2.2 -> v2.3: Hanya BodyA LightMap Hash'),    (upgrade_hash, {'to': '7c08d55d'})],
    '9233c696': [('info', 'v2.2 -> v2.3: Hanya BodyA StockingMap Hash'), (upgrade_hash, {'to': '162667f6'})],
    'e7afec9f': [('info', 'v2.2 -> v2.3: Hanya BodyB Diffuse Hash'),     (upgrade_hash, {'to': 'd927b45a'})],
    'c2817103': [('info', 'v2.2 -> v2.3: Hanya BodyB LightMap Hash'),    (upgrade_hash, {'to': '537979fe'})],
    'ca76ff40': [('info', 'v2.2 -> v2.3: Hanya BodyB StockingMap Hash'), (upgrade_hash, {'to': '61d0592b'})],

    '208022e7': [('info', 'v3.0 -> v3.1: Hanya Body Blend Hash'),           (upgrade_hash, {'to': 'cf715cb3'})],
    'a15c444f': [('info', 'v3.0 -> v3.1: Hanya Hair Blend Hash'),           (upgrade_hash, {'to': '4ead3a1b'})],
    '10952bd7': [('info', 'v3.0 -> v3.1: Hanya Hair Position Hash'),        (upgrade_hash, {'to': '09203665'})],
    '5311cf0a': [('info', 'v3.0 -> v3.1: Hanya Head Blend Hash'),           (upgrade_hash, {'to': 'bce0b15e'})],
    'adf8b2de': [('info', 'v3.0 -> v3.1: Hanya Head Position Hash'),        (upgrade_hash, {'to': 'b44daf6c'})],

    'c6421b31': [('info', 'v3.1 -> v3.2: Hanya Hair Draw Hash'), (upgrade_hash, {'to': 'c9d12e3c'})],
    'ae996433': [('info', 'v3.1 -> v3.2: Hanya Head Draw Hash'), (upgrade_hash, {'to': 'a10a513e'})],
    'ceff860d': [('info', 'v3.1 -> v3.2: Hanya Body Draw Hash'), (upgrade_hash, {'to': 'c16cb300'})],
    '7d083a6d': [('info', 'v3.1 -> v3.2: Hanya Body Position Hash'), (upgrade_hash, {'to': 'be3b14b5'})],


    # MARK: Herta
    '93835e8f': [('info', 'v1.6 -> v2.0: Herta Body Draw Hash'),     (upgrade_hash, {'to': 'c08327f8'})],
    '2074e2ef': [('info', 'v1.6 -> v2.0: Herta Body Position Hash'), (upgrade_hash, {'to': '73749b98'})],
    'c12363b4': [('info', 'v1.6 -> v2.0: Herta Body Texcoord Hash'), (upgrade_hash, {'to': '91c0cb8e'})],
    '5186a9b8': [
        ('info', 'v1.6 -> v2.0: Herta Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'HertaBody',
            'hash': '9553ff35',
            'trg_indices': ['0',  '8814', '53166'],
            'src_indices': ['0',    '-1', '52458'],
        })
    ],

    'd53e94bd': [('info', 'v2.2 -> v2.3: Herta Hair Diffuse Hash'),  (upgrade_hash, {'to': 'ee995067'})],
    '84c9c04b': [('info', 'v2.2 -> v2.3: Herta Hair LightMap Hash'), (upgrade_hash, {'to': '515a7733'})],

    '029aeabf': [('info', 'v2.2 -> v2.3: Herta Head Diffuse Hash'),  (upgrade_hash, {'to': 'e116363f'})],

    '01057b08': [('info', 'v2.2 -> v2.3: Herta Body Diffuse Hash'),  (upgrade_hash, {'to': 'e07c10c9'})],
    '22d89ecd': [('info', 'v2.2 -> v2.3: Herta Body LightMap Hash'), (upgrade_hash, {'to': 'b878ef55'})],

    '383d8083': [('info', 'v3.0 -> v3.1: Herta Body Blend Hash'),           (upgrade_hash, {'to': 'd7ccfed7'})],
    '40ff8968': [('info', 'v3.0 -> v3.1: Herta Hair Blend Hash'),           (upgrade_hash, {'to': 'af0ef73c'})],
    '2d748a84': [('info', 'v3.0 -> v3.1: Herta Hair Position Hash'),        (upgrade_hash, {'to': '34c19736'})],
    'c1948160': [('info', 'v3.0 -> v3.1: Herta Head Blend Hash'),           (upgrade_hash, {'to': '2e65ff34'})],
    '93d98b8b': [('info', 'v3.0 -> v3.1: Herta Head Position Hash'),        (upgrade_hash, {'to': '8a6c9639'})],

    'c08327f8': [('info', 'v2.0 -> v3.2: Herta Body Draw Hash'), (upgrade_hash, {'to': 'cf1012f5'})],
    '73749b98': [('info', 'v2.0 -> v3.2: Herta Body Position Hash'), (upgrade_hash, {'to': '6b999ed4'})],
    'f9eda56d': [('info', 'v3.1 -> v3.2: Herta Hair Draw Hash'), (upgrade_hash, {'to': 'f67e9060'})],
    '011f3657': [('info', 'v3.1 -> v3.2: Herta Head Draw Hash'), (upgrade_hash, {'to': '0e8c035a'})],


    # MARK: Himeko
    '5d98de11': [('info', 'v1.6 -> v2.0: Himeko Body Position Extra Hash'), (upgrade_hash, {'to': '3cfb3645'})],
    '77cb214c': [('info', 'v1.6 -> v2.0: Himeko Body Texcoord Hash'),       (upgrade_hash, {'to': 'b9e9ae3b'})],
    'e4640c8c': [
        ('info', 'v1.6 -> v2.0: Himeko Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'HimekoBody',
            'hash': 'e79e4018',
            'trg_indices': ['0', '27381', '37002', '47634'],
            'src_indices': ['-1',    '0', '37002',    '-1'],
        })
    ],

    'c08f4727': [('info', 'v2.2 -> v2.3: Himeko Hair Texcoord Hash'),  (upgrade_hash, {'to': 'fa440b40'})],
    'fc068361': [('info', 'v2.2 -> v2.3: Himeko Hair Diffuse Hash'),   (upgrade_hash, {'to': 'd4634d6f'})],
    '9adcae2d': [('info', 'v2.2 -> v2.3: Himeko Hair LightMap Hash'),  (upgrade_hash, {'to': 'a700d6b4'})],

    '1acfc83f': [('info', 'v2.2 -> v2.3: Himeko Head Diffuse Hash'),   (upgrade_hash, {'to': '832e3b54'})],

    'f4b0bd6d': [('info', 'v2.2 -> v2.3: Himeko Body Draw Hash'),      (upgrade_hash, {'to': '62d53b1f'})],
    '4747010d': [('info', 'v2.2 -> v2.3: Himeko Body Position Hash'),  (upgrade_hash, {'to': 'd122877f'})],
    'b9e9ae3b': [('info', 'v2.2 -> v2.3: Himeko Body Texcoord Hash'),  (upgrade_hash, {'to': '2bf29f1f'})],
    'e79e4018': [('info', 'v2.2 -> v2.3: Himeko Body IB Hash'),        (upgrade_hash, {'to': '2dc0061c'})],
    'e2f15a68': [('info', 'v2.2 -> v2.3: Himeko BodyA Diffuse Hash'),  (upgrade_hash, {'to': '6920fe29'})],
    '27bf0a6a': [('info', 'v2.2 -> v2.3: Himeko BodyA LightMap Hash'), (upgrade_hash, {'to': '520336ef'})],
    '24e4c5ad': [('info', 'v2.2 -> v2.3: Himeko BodyC Diffuse Hash'),  (upgrade_hash, {'to': 'a769be88'})],
    'ce965b0d': [('info', 'v2.2 -> v2.3: Himeko BodyC LightMap Hash'), (upgrade_hash, {'to': '094b77c6'})],


    '3cfb3645': [('info', 'v2.2 -> v2.3: Himeko Body Position Extra Hash'),  (upgrade_hash, {'to': '5212e2f9'})],
    # 'd122877f': [
    #     ('info', 'v2.3: Himeko Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '5d98de11'}),
    #     (check_hash_not_in_ini, {'hash': '3cfb3645'}),
    #     (check_hash_not_in_ini, {'hash': '5212e2f9'}),
    #     (multiply_section, {
    #         'titles': ['HimekoBodyPosition', 'HimekoBodyPosition_Extra'],
    #         'hashes': ['d122877f', '5212e2f9']
    #     })
    # ],

    '5212e2f9': [('info', 'v2.3 -> v3.1: Himeko Body Position Extra Hash'),              (comment_sections, {})],
    '947bc57e': [('info', 'v3.0 -> v3.1: Himeko Body Blend Hash'),          (upgrade_hash, {'to': '7b8abb2a'})],
    '71a1c8eb': [('info', 'v3.0 -> v3.1: Himeko Hair Blend Hash'),          (upgrade_hash, {'to': '9e50b6bf'})],
    'a8f00e3a': [('info', 'v3.0 -> v3.1: Himeko Hair Position Hash'),       (upgrade_hash, {'to': 'b1451388'})],
    '88093f50': [('info', 'v3.0 -> v3.1: Himeko Head Blend Hash'),          (upgrade_hash, {'to': '67f84104'})],
    '9ca6e275': [('info', 'v3.0 -> v3.1: Himeko Head Position Hash'),       (upgrade_hash, {'to': '8513ffc7'})],
    'd122877f': [('info', 'v3.0 -> v3.1: Himeko Body Position Hash'), (upgrade_hash, {'to': '4ba7ff4b'})],

    '62d53b1f': [('info', 'v2.3 -> v3.2: Himeko Body Draw Hash'), (upgrade_hash, {'to': '6d460e12'})],
    '7c1e9348': [('info', 'v3.1 -> v3.2: Himeko Hair Draw Hash'), (upgrade_hash, {'to': '738da645'})],
    '3f65f415': [('info', 'v3.1 -> v3.2: Himeko Head Draw Hash'), (upgrade_hash, {'to': '30f6c118'})],


    # MARK: Hook
    '0361b6bf': [('info', 'v1.6 -> v2.0: Hook Body Position Hash'), (upgrade_hash, {'to': '9d68704b'})],
    'f1788f95': [('info', 'v1.6 -> v2.0: Hook Body Texcoord Hash'), (upgrade_hash, {'to': '59ccb47b'})],
    '26276c57': [
        ('info', 'v1.6 -> v2.0: Hook Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'HookBody',
            'hash': '0c614d18',
            'trg_indices': ['0', '42189'],
            'src_indices': ['0',    '-1'],
        })
    ],

    'fcd7ee7b': [('info', 'v2.2 -> v2.3: Hook Hair Diffuse Hash'),  (upgrade_hash, {'to': 'f1ca01f3'})],
    'a8e81b3a': [('info', 'v2.2 -> v2.3: Hook Hair LightMap Hash'), (upgrade_hash, {'to': 'db6ff34c'})],

    'd76e33a6': [('info', 'v2.2 -> v2.3: Hook Head Diffuse Hash'),  (upgrade_hash, {'to': '9588db54'})],

    'b8d85743': [('info', 'v2.2 -> v2.3: Hook Body Diffuse Hash'),  (upgrade_hash, {'to': '8ab99329'})],
    'a49680b5': [('info', 'v2.2 -> v2.3: Hook Body LightMap Hash'), (upgrade_hash, {'to': '4a45ac95'})],

    '9d68704b': [('info', 'v2.0 -> v3.1: Hook Body Position Hash'),         (upgrade_hash, {'to': '84dd6df9'})],
    'cf732951': [('info', 'v3.0 -> v3.1: Hook Body Blend Hash'),            (upgrade_hash, {'to': '20825705'})],
    '516052b3': [('info', 'v3.0 -> v3.1: Hook Hair Blend Hash'),            (upgrade_hash, {'to': 'be912ce7'})],
    '2c0285e5': [('info', 'v3.0 -> v3.1: Hook Hair Position Hash'),         (upgrade_hash, {'to': '35b79857'})],
    '0a410eec': [('info', 'v3.0 -> v3.1: Hook Head Blend Hash'),            (upgrade_hash, {'to': 'e5b070b8'})],
    '7d70c461': [('info', 'v3.0 -> v3.1: Hook Head Position Hash'),         (upgrade_hash, {'to': '64c5d9d3'})],

    'e0aa46af': [('info', 'v3.1 -> v3.2: Hook Head Draw Hash'), (upgrade_hash, {'to': 'ef3973a2'})],
    'b0960adf': [('info', 'v3.1 -> v3.2: Hook Body Draw Hash'), (upgrade_hash, {'to': 'bf053fd2'})],

    '53d0ba6a': [('info', 'v3.1 -> v3.2: Hook Hair Draw Hash'), (upgrade_hash, {'to': '5c438f67'})],

    # MARK: Huohuo
    'd9ac0987': [('info', 'v1.6 -> v2.0: Huohuo Body Draw Hash'),       (upgrade_hash, {'to': '67a078bd'})],
    '6a5bb5e7': [('info', 'v1.6 -> v2.0: Huohuo Body Position Hash'), (upgrade_hash, {'to': 'd457c4dd'})],
    '47dbd6aa': [('info', 'v1.6 -> v2.0: Huohuo Body Texcoord Hash'), (upgrade_hash, {'to': '2a306f9c'})],
    'f05d31fb': [
        ('info', 'v1.6 -> v2.0: Huohuo Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'HuohuoBody',
            'hash': 'e9aecd0b',
            'trg_indices': ['0', '45165'],
            'src_indices': ['0',    '-1'],
        })
    ],

    'f8d072c0': [('info', 'v2.2 -> v2.3: Huohuo Hair Diffuse Hash'),  (upgrade_hash, {'to': '057f648d'})],
    'c0f8d106': [('info', 'v2.2 -> v2.3: Huohuo Hair LightMap Hash'), (upgrade_hash, {'to': '772090fc'})],

    '7dbe20be': [('info', 'v2.2 -> v2.3: Huohuo Head Diffuse Hash'),  (upgrade_hash, {'to': '6f1e9080'})],

    '70d3fdb7': [('info', 'v2.2 -> v2.3: Huohuo Body Diffuse Hash'),  (upgrade_hash, {'to': '6598aacd'})],
    '6e5470a5': [('info', 'v2.2 -> v2.3: Huohuo Body LightMap Hash'), (upgrade_hash, {'to': 'afac01be'})],

    'a1b1aafa': [('info', 'v3.0 -> v3.1: Huohuo Body Blend Hash'),          (upgrade_hash, {'to': '4e40d4ae'})],
    '6a7c7d6d': [('info', 'v3.0 -> v3.1: Huohuo Hair Blend Hash'),          (upgrade_hash, {'to': '858d0339'})],
    '21b42643': [('info', 'v3.0 -> v3.1: Huohuo Hair Position Hash'),       (upgrade_hash, {'to': '38013bf1'})],
    'c9bc7a6e': [('info', 'v3.0 -> v3.1: Huohuo Head Blend Hash'),          (upgrade_hash, {'to': '264d043a'})],
    '7c8be987': [('info', 'v3.0 -> v3.1: Huohuo Head Position Hash'),       (upgrade_hash, {'to': '653ef435'})],

    '67a078bd': [('info', 'v2.0 -> v3.2: Huohuo Body Draw Hash'), (upgrade_hash, {'to': '68334db0'})],
    'd457c4dd': [('info', 'v2.0 -> v3.2: Huohuo Body Position Hash'), (upgrade_hash, {'to': '5b0744cf'})],
    'd4259612': [('info', 'v3.1 -> v3.2: Huohuo Hair Draw Hash'), (upgrade_hash, {'to': 'dbb6a31f'})],
    '96d65244': [('info', 'v3.1 -> v3.2: Huohuo Head Draw Hash'), (upgrade_hash, {'to': '99456749'})],



    # MARK: Jade

    'e7048976': [('info', 'v3.0 -> v3.1: Jade Body Blend Hash'),            (upgrade_hash, {'to': '08f5f722'})],
    '93ba2c04': [('info', 'v3.0 -> v3.1: Jade Hair Blend Hash'),            (upgrade_hash, {'to': '7c4b5250'})],
    'e62b239a': [('info', 'v3.0 -> v3.1: Jade Hair Position Hash'),         (upgrade_hash, {'to': 'ff9e3e28'})],
    '7076a247': [('info', 'v3.0 -> v3.1: Jade Head Blend Hash'),            (upgrade_hash, {'to': '9f87dc13'})],
    '4c0adcc6': [('info', 'v3.0 -> v3.1: Jade Head Position Hash'),         (upgrade_hash, {'to': '55bfc174'})],

    '05505aaf': [('info', 'v3.1 -> v3.2: Jade Hair Draw Hash'), (upgrade_hash, {'to': '0ac36fa2'})],
    'bb859078': [('info', 'v3.1 -> v3.2: Jade Head Draw Hash'), (upgrade_hash, {'to': 'b416a575'})],
    'a9a4a852': [('info', 'v3.1 -> v3.2: Jade Body Draw Hash'), (upgrade_hash, {'to': 'a6379d5f'})],
    '1a531432': [('info', 'v3.1 -> v3.2: Jade Body Position Hash'), (upgrade_hash, {'to': 'b0fed430'})],


    # MARK: Jingliu
    '33f9fe71': [('info', 'v1.4 -> v1.6: Jingliu BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'bdbc6dce'})],
    '67344bd9': [('info', 'v1.4 -> v1.6: Jingliu BodyA LightMap Hash'), (upgrade_hash, {'to': '5f55eaff'})],
    '81c023e7': [('info', 'v1.6 -> v2.0: Jingliu Body Texcoord Hash'),  (upgrade_hash, {'to': 'ba517fa0'})],
    '5564183c': [
        ('info', 'v1.6 -> v2.0: Jingliu Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'JingliuBody',
            'hash': 'e8d31b6a',
            'trg_indices': ['0', '51096'],
            'src_indices': ['0',    '-1'],
        })
    ],

    '1bc1cfa0': [('info', 'v2.2 -> v2.3: Jingliu Hair Diffuse Hash'),  (upgrade_hash, {'to': 'f73f74cb'})],
    'fbcefb7e': [('info', 'v2.2 -> v2.3: Jingliu Hair LightMap Hash'), (upgrade_hash, {'to': '70ae9680'})],

    'c36ab82e': [('info', 'v2.2 -> v2.3: Jingliu Head Diffuse Hash'),  (upgrade_hash, {'to': '25dd2c46'})],

    'bdbc6dce': [('info', 'v2.2 -> v2.3: Jingliu Body Diffuse Hash'),  (upgrade_hash, {'to': '74370924'})],
    '5f55eaff': [('info', 'v2.2 -> v2.3: Jingliu Body LightMap Hash'), (upgrade_hash, {'to': 'd3a91ee8'})],

    'cb320050': [('info', 'v3.0 -> v3.1: Jingliu Body Blend Hash'),         (upgrade_hash, {'to': '24c37e04'})],
    'ae0df48a': [('info', 'v3.0 -> v3.1: Jingliu Hair Blend Hash'),         (upgrade_hash, {'to': '41fc8ade'})],
    '35f278be': [('info', 'v3.0 -> v3.1: Jingliu Hair Position Hash'),      (upgrade_hash, {'to': '2c47650c'})],
    'ecf0b54f': [('info', 'v3.0 -> v3.1: Jingliu Head Blend Hash'),         (upgrade_hash, {'to': '0301cb1b'})],
    '6f96493b': [('info', 'v3.0 -> v3.1: Jingliu Head Position Hash'),      (upgrade_hash, {'to': '76235489'})],

    '11ff289a': [('info', 'v3.1 -> v3.2: Jingliu Hair Draw Hash'), (upgrade_hash, {'to': '1e6c1d97'})],
    '953e1172': [('info', 'v3.1 -> v3.2: Jingliu Head Draw Hash'), (upgrade_hash, {'to': '9aad247f'})],
    '73de6056': [('info', 'v3.1 -> v3.2: Jingliu Body Draw Hash'), (upgrade_hash, {'to': '7c4d555b'})],
    'c029dc36': [('info', 'v3.1 -> v3.2: Jingliu Body Position Hash'), (upgrade_hash, {'to': '09a74ad8'})],


    #MARK: Jiaoqiu
    'aaa5a0ff': [('info', 'v3.0 -> v3.1: Jiaoqiu Body Blend Hash'),         (upgrade_hash, {'to': '4554deab'})],
    '1cf0d06c': [('info', 'v3.0 -> v3.1: Jiaoqiu Hair Blend Hash'),         (upgrade_hash, {'to': 'f301ae38'})],
    '667ba145': [('info', 'v3.0 -> v3.1: Jiaoqiu Hair Position Hash'),      (upgrade_hash, {'to': '7fcebcf7'})],
    '91c5de25': [('info', 'v3.0 -> v3.1: Jiaoqiu Head Blend Hash'),         (upgrade_hash, {'to': '7e34a071'})],
    '4c754f6c': [('info', 'v3.0 -> v3.1: Jiaoqiu Head Position Hash'),      (upgrade_hash, {'to': '55c052de'})],

    '393e2b73': [('info', 'v3.1 -> v3.2: Jiaoqiu Hair Draw Hash'), (upgrade_hash, {'to': '36ad1e7e'})],
    '788f41fb': [('info', 'v3.1 -> v3.2: Jiaoqiu Body Draw Hash'), (upgrade_hash, {'to': '771c74f6'})],
    'cb78fd9b': [('info', 'v3.1 -> v3.2: Jiaoqiu Body Position Hash'), (upgrade_hash, {'to': '5d046eeb'})],


    # MARK: JingYuan
    '8f1a29cf': [('info', 'v1.6 -> v2.0: JingYuan Body Texcoord Hash'), (upgrade_hash, {'to': '3423e10d'})],
    '1be11c4f': [
        ('info', 'v1.6 -> v2.0: JingYuan Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'JingYuanBody',
            'hash': '1240ff30',
            'trg_indices': ['0', '11505', '17772', '53565'],
            'src_indices': ['0',    '-1', '17772',    '-1'],
        })
    ],
    '3423e10d': [('info', 'v2.0 -> v2.1: JingYuan Body Texcoord Hash'), (upgrade_hash, {'to': 'ebde517e'})],
    '1240ff30': [
        ('info', 'v2.0 -> v2.1: JingYuan Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'JingYuanBody',
            'hash': 'b2501828',
            'trg_indices': ['0', '11589', '17772', '53565'],
            'src_indices': ['0', '11505', '17772', '53565'],
        })
    ],
    '061dd140': [('info', 'v2.0 -> v2.1: JingYuan Head Draw Hash'),     (upgrade_hash, {'to': 'c8841602'})],
    'ee205a7b': [('info', 'v2.0 -> v2.1: JingYuan Head Position Hash'), (upgrade_hash, {'to': '9d60acea'})],
    '7c112f46': [('info', 'v2.0 -> v2.1: JingYuan Head Texcoord Hash'), (upgrade_hash, {'to': '20110b85'})],
    '22147cfe': [('info', 'v2.0 -> v2.1: JingYuan Head IB Hash'),        (upgrade_hash, {'to': 'a0459b05'})],

    '1da0a14c': [('info', 'v2.2 -> v2.3: JingYuan Hair Diffuse Hash'),   (upgrade_hash, {'to': '1ac1a7fb'})],
    '97eb13d9': [('info', 'v2.2 -> v2.3: JingYuan Hair LightMap Hash'),  (upgrade_hash, {'to': '9f47fa33'})],

    '7dc71e05': [('info', 'v2.2 -> v2.3: JingYuan Head Diffuse Hash'),   (upgrade_hash, {'to': 'f585da62'})],

    '48c0277a': [('info', 'v2.2 -> v2.3: JingYuan BodyA Diffuse Hash'),  (upgrade_hash, {'to': '26735526'})],
    '7dfa92fa': [('info', 'v2.2 -> v2.3: JingYuan BodyA LightMap Hash'), (upgrade_hash, {'to': 'd5b2a23a'})],
    'fd74f596': [('info', 'v2.2 -> v2.3: JingYuan BodyC Diffuse Hash'),  (upgrade_hash, {'to': 'b1b4f581'})],
    '9fe0c156': [('info', 'v2.2 -> v2.3: JingYuan BodyC LightMap Hash'), (upgrade_hash, {'to': '16a2d8bb'})],

    'baaa1347': [('info', 'v2.4 -> v2.5: JingYuan Body Draw Hash'),     (upgrade_hash, {'to': '0b529127'})],
    '095daf27': [('info', 'v2.4 -> v2.5: JingYuan Body Position Hash'), (upgrade_hash, {'to': 'b8a52d47'})],
    'ebde517e': [('info', 'v2.4 -> v2.5: JingYuan Body Texcoord Hash'), (upgrade_hash, {'to': '9f387461'})],
    'b2501828': [
        ('info', 'v2.4 -> v2.5: JingYuan Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'JingYuanBody',
            'hash': 'b1191b83',
            'trg_indices': ['0', '11505', '17778', '53571'],
            'src_indices': ['0', '11589', '17772', '53565'],
        })
    ],

    '9d60acea': [('info', 'v2.1 -> v3.1: JingYuan Head Position Hash'),     (upgrade_hash, {'to': '84d5b158'})],
    'cc58b451': [('info', 'v3.0 -> v3.1: JingYuan Body Blend Hash'),        (upgrade_hash, {'to': '23a9ca05'})],
    'e1d746fc': [('info', 'v3.0 -> v3.1: JingYuan Hair Blend Hash'),        (upgrade_hash, {'to': '0e2638a8'})],
    '31319f5f': [('info', 'v3.0 -> v3.1: JingYuan Hair Position Hash'),     (upgrade_hash, {'to': '288482ed'})],
    '61d571f5': [('info', 'v3.0 -> v3.1: JingYuan Head Blend Hash'),        (upgrade_hash, {'to': '8e240fa1'})],

    'c8841602': [('info', 'v2.1 -> v3.2: JingYuan Head Draw Hash'), (upgrade_hash, {'to': 'c717230f'})],
    '0b529127': [('info', 'v2.5 -> v3.2: JingYuan Body Draw Hash'), (upgrade_hash, {'to': '04c1a42a'})],
    'b8a52d47': [('info', 'v2.5 -> v3.2: JingYuan Body Position Hash'), (upgrade_hash, {'to': '5209eaca'})],
    '457fc548': [('info', 'v3.1 -> v3.2: JingYuan Hair Draw Hash'), (upgrade_hash, {'to': '4aecf045'})],


    # MARK: Kafka
    '51abd7c9': [('info', 'v1.4 -> v1.6: Kafka Body Position Hash'),        (upgrade_hash, {'to': 'deb266a8'})],
    '38072744': [('info', 'v1.4 -> v1.6: Kafka Body Position Extra Hash'), (upgrade_hash, {'to': '17cb3b3e'})],
    'a6813fd5': [('info', 'v1.4 -> v1.6: Kafka Body Texcoord Hash'),        (upgrade_hash, {'to': '190e483a'})],
    'b7401039': [('info', 'v1.4 -> v1.6: Kafka Body IB Hash'),                (upgrade_hash, {'to': '8d847042'})],

    '17cb3b3e': [('info', 'v1.6 -> v2.0: Kafka Body Position Extra Hash'), (upgrade_hash, {'to': 'cd2222f8'})],
    '190e483a': [('info', 'v1.6 -> v2.0: Kafka Body Texcoord Hash'),        (upgrade_hash, {'to': '05ded7f7'})],
    'e25c6ba9': [('info', 'v1.6 -> v2.0: Kafka Body Draw Hash'),            (upgrade_hash, {'to': '6d45dac8'})],
    '8d847042': [
        ('info', 'v1.6 -> v2.0: Kafka Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'KafkaBody',
            'hash': 'fa23099d',
            'trg_indices': ['0', '8787', '16083', '35439', '41406'],
            'src_indices': ['0',   '-1', '16083',    '-1', '41406'],
        })
    ],
    # 'deb266a8': [
    #     ('info', 'v2.1: Kafka Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': 'cd2222f8'}),
    #     (check_hash_not_in_ini, {'hash': '17cb3b3e'}),
    #     (check_hash_not_in_ini, {'hash': '38072744'}),
    #     (multiply_section, {
    #         'titles': ['KafkaBodyPosition', 'KafkaBodyPosition_Extra'],
    #         'hashes': ['deb266a8', 'cd2222f8']
    #     })
    # ],

    'cd60c900': [('info', 'v2.2 -> v2.3: Kafka Hair Texcoord Hash'),     (upgrade_hash, {'to': 'ddbe6ba2'})],
    '55d258a5': [('info', 'v2.2 -> v2.3: Kafka Hair Diffuse Hash'),      (upgrade_hash, {'to': 'cb354b6b'})],
    'dc6aaf17': [('info', 'v2.2 -> v2.3: Kafka Hair LightMap Hash'),     (upgrade_hash, {'to': 'e07efe45'})],

    '1d74e2f5': [('info', 'v2.2 -> v2.3: Kafka Head Diffuse Hash'),      (upgrade_hash, {'to': 'cf90e442'})],

    '05ded7f7': [('info', 'v2.2 -> v2.3: Kafka Body Texcoord Hash'),     (upgrade_hash, {'to': 'd14b435e'})],
    '0da4c671': [('info', 'v2.2 -> v2.3: Kafka BodyA Diffuse Hash'),     (upgrade_hash, {'to': '207c0559'})],
    'cc322c0f': [('info', 'v2.2 -> v2.3: Kafka BodyA LightMap Hash'),    (upgrade_hash, {'to': '32b5b281'})],
    '339785c4': [('info', 'v2.2 -> v2.3: Kafka BodyA StockingMap Hash'), (upgrade_hash, {'to': 'fd0ef162'})],

    'e8e2b6da': [('info', 'v2.2 -> v2.3: Kafka BodyC Diffuse Hash'),     (upgrade_hash, {'to': 'c00b55bc'})],
    '7bd0d180': [('info', 'v2.2 -> v2.3: Kafka BodyC LightMap Hash'),    (upgrade_hash, {'to': '45d15ffb'})],

    'cd2222f8': [('info', 'v2.0 -> v3.1: Kafka Body Position Extra Hash'),               (comment_sections, {})],
    '4babbbd9': [('info', 'v3.0 -> v3.1: Kafka Body Blend Hash'),           (upgrade_hash, {'to': 'a45ac58d'})],
    '91133916': [('info', 'v3.0 -> v3.1: Kafka Hair Blend Hash'),           (upgrade_hash, {'to': '7ee24742'})],
    'cdda77a3': [('info', 'v3.0 -> v3.1: Kafka Hair Position Hash'),        (upgrade_hash, {'to': 'd46f6a11'})],
    'e811b655': [('info', 'v3.0 -> v3.1: Kafka Head Blend Hash'),           (upgrade_hash, {'to': '07e0c801'})],
    '7cbe836d': [('info', 'v3.0 -> v3.1: Kafka Head Position Hash'),        (upgrade_hash, {'to': '650b9edf'})],
    'deb266a8': [('info', 'v3.0 -> v3.1: Kafka Body Position Hash'),          (upgrade_hash, {'to': 'd4973f4a'})],

    '6d45dac8': [('info', 'v2.0 -> v3.2: Kafka Body Draw Hash'),            (upgrade_hash, {'to': '62d6efc5'})],
    '132595c5': [('info', 'v3.1 -> v3.2: Kafka Hair Draw Hash'),             (upgrade_hash, {'to': '1cb6a0c8'})],
    '48576da3': [('info', 'v3.1 -> v3.2: Kafka Head Draw Hash'),             (upgrade_hash, {'to': '47c458ae'})],


    # MARK: Lingsha
    'ea4c4532': [('info', 'v3.0 -> v3.1: Lingsha Body Blend Hash'),         (upgrade_hash, {'to': '05bd3b66'})],
    'bc787aec': [('info', 'v3.0 -> v3.1: Lingsha Hair Blend Hash'),         (upgrade_hash, {'to': '538904b8'})],
    'c207a096': [('info', 'v3.0 -> v3.1: Lingsha Hair Position Hash'),      (upgrade_hash, {'to': 'dbb2bd24'})],
    'dc9cba18': [('info', 'v3.0 -> v3.1: Lingsha Head Blend Hash'),         (upgrade_hash, {'to': '336dc44c'})],
    'e779f220': [('info', 'v3.0 -> v3.1: Lingsha Head Position Hash'),      (upgrade_hash, {'to': 'feccef92'})],

    'bbe8b08e': [('info', 'v3.1 -> v3.2: Lingsha Hair Draw Hash'), (upgrade_hash, {'to': 'b47b8583'})],
    '3b530692': [('info', 'v3.1 -> v3.2: Lingsha Head Draw Hash'), (upgrade_hash, {'to': '34c0339f'})],
    '940b1b19': [('info', 'v3.1 -> v3.2: Lingsha Body Draw Hash'), (upgrade_hash, {'to': '9b982e14'})],
    '27fca779': [('info', 'v3.1 -> v3.2: Lingsha Body Position Hash'), (upgrade_hash, {'to': 'b1dd664a'})],


    # MARK: Luka
    'e0c63ed8': [('info', 'v1.4 -> v1.6: Luka BodyA LightMap Hash'), (upgrade_hash, {'to': '31724118'})],
    '78d83281': [('info', 'v1.4 -> v1.6: Luka BodyB LightMap Hash'), (upgrade_hash, {'to': '58749091'})],

    'f7d86ef0': [('info', 'v1.6 -> v2.0: Luka Body Position Extra Hash'), (upgrade_hash, {'to': '3e55d897'})],
    '098a46fc': [('info', 'v1.6 -> v2.0: Luka Body Texcoord Hash'),       (upgrade_hash, {'to': '11dd3da1'})],
    '5cd5d088': [('info', 'v1.6 -> v2.0: Luka BodyA Diffuse Hash'),       (upgrade_hash, {'to': '3ba22ed5'})],
    '148d7790': [('info', 'v1.6 -> v2.0: Luka BodyB Diffuse Hash'),       (upgrade_hash, {'to': '73fa89cd'})],
    '5332e0c4': [
        ('info', 'v1.6 -> v2.0: Luka Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'LukaBody',
            'hash': 'e0c9f7ec',
            'trg_indices': ['0', '25371', '49992', '52830'],
            'src_indices': ['0', '28209',      '-1',    '-1'],
        })
    ],
    # '03fba4b4': [
    #     ('info', 'v2.1: Luka Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '3e55d897'}),
    #     (check_hash_not_in_ini, {'hash': 'f7d86ef0'}),
    #     (multiply_section, {
    #         'titles': ['LukaBodyPosition', 'LukaBodyPosition_Extra'],
    #         'hashes': ['03fba4b4', '3e55d897']
    #     })
    # ],

    '2427134f': [('info', 'v2.2 -> v2.3: Luka Hair Diffuse Hash'),      (upgrade_hash, {'to': '6e34ac83'})],
    'c6b43fae': [('info', 'v2.2 -> v2.3: Luka Hair LightMap Hash'),     (upgrade_hash, {'to': '6d784dff'})],

    '4d8ef1d8': [('info', 'v2.2 -> v2.3: Luka Head Diffuse Hash'),      (upgrade_hash, {'to': 'e8d263c3'})],

    '3ba22ed5': [('info', 'v2.2 -> v2.3: Luka BodyA Diffuse Hash'),     (upgrade_hash, {'to': 'a026c901'})],
    '31724118': [('info', 'v2.2 -> v2.3: Luka BodyA LightMap Hash'),    (upgrade_hash, {'to': '1762e62c'})],
    '73fa89cd': [('info', 'v2.2 -> v2.3: Luka BodyB Diffuse Hash'),     (upgrade_hash, {'to': '00970f33'})],
    '58749091': [('info', 'v2.2 -> v2.3: Luka BodyB LightMap Hash'),    (upgrade_hash, {'to': '31483729'})],

    '3e55d897': [('info', 'v2.0 -> v3.1: Luka Body Position Extra Hash'),                (comment_sections, {})],
    'e98c3d24': [('info', 'v3.0 -> v3.1: Luka Hair Blend Hash'),            (upgrade_hash, {'to': '067d4370'})],
    'a96bca86': [('info', 'v3.0 -> v3.1: Luka Hair Position Hash'),         (upgrade_hash, {'to': 'b0ded734'})],
    '614df023': [('info', 'v3.0 -> v3.1: Luka Head Blend Hash'),            (upgrade_hash, {'to': '8ebc8e77'})],
    '222b9650': [('info', 'v3.0 -> v3.1: Luka Head Position Hash'),         (upgrade_hash, {'to': '3b9e8be2'})],
    '03fba4b4': [('info', 'v3.0 -> v3.1: Luka Body Position Hash'),            (upgrade_hash, {'to': '27e0c525'})],

    '934c42a2': [('info', 'v3.1 -> v3.2: Luka Hair Draw Hash'), (upgrade_hash, {'to': '9cdf77af'})],
    'a8cf872d': [('info', 'v3.1 -> v3.2: Luka Head Draw Hash'), (upgrade_hash, {'to': 'a75cb220'})],
    'b00c18d4': [('info', 'v3.1 -> v3.2: Luka Body Draw Hash'), (upgrade_hash, {'to': 'bf9f2dd9'})],
    '8ddf531a': [('info', 'v3.1 -> v3.2: Luka Body Blend Hash'), (upgrade_hash, {'to': 'd012ae01'})],


    # MARK: Luocha
    'b5c61afb': [('info', 'v1.6 -> v2.0: Luocha Body Draw Hash'),     (upgrade_hash, {'to': '194a6495'})],
    '0631a69b': [('info', 'v1.6 -> v2.0: Luocha Body Position Hash'), (upgrade_hash, {'to': 'aabdd8f5'})],
    'a67c4fed': [('info', 'v1.6 -> v2.0: Luocha Body Texcoord Hash'), (upgrade_hash, {'to': '80da6fb8'})],
    '6c659c20': [
        ('info', 'v1.6 -> v2.0: Luocha Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'LuochaBody',
            'hash': '149a218b',
            'trg_indices': ['0', '4503', '34437', '45126'],
            'src_indices': ['0',   '-1', '34437',    '-1'],
        })
    ],

    '17542aca': [('info', 'v2.2 -> v2.3: Luocha Hair Diffuse Hash'),      (upgrade_hash, {'to': '9420ae03'})],
    'dadf8929': [('info', 'v2.2 -> v2.3: Luocha Hair LightMap Hash'),     (upgrade_hash, {'to': 'a7e6fa4f'})],

    '8af54c5d': [('info', 'v2.2 -> v2.3: Luocha Head Diffuse Hash'),      (upgrade_hash, {'to': '664f2f29'})],

    'f9d9adb8': [('info', 'v2.2 -> v2.3: Luocha BodyA Diffuse Hash'),     (upgrade_hash, {'to': '7185fd68'})],
    'd8dd2b05': [('info', 'v2.2 -> v2.3: Luocha BodyA LightMap Hash'),    (upgrade_hash, {'to': 'eb99eb88'})],
    'a1fac228': [('info', 'v2.2 -> v2.3: Luocha BodyC Diffuse Hash'),     (upgrade_hash, {'to': '65dec275'})],
    'ff928485': [('info', 'v2.2 -> v2.3: Luocha BodyC LightMap Hash'),    (upgrade_hash, {'to': '45feb69d'})],

    '0a1b224a': [('info', 'v3.0 -> v3.1: Luocha Body Blend Hash'),          (upgrade_hash, {'to': 'e5ea5c1e'})],
    '5484d0a4': [('info', 'v3.0 -> v3.1: Luocha Hair Blend Hash'),          (upgrade_hash, {'to': 'bb75aef0'})],
    '2f7b8290': [('info', 'v3.0 -> v3.1: Luocha Hair Position Hash'),       (upgrade_hash, {'to': '36ce9f22'})],
    '02962a1d': [('info', 'v3.0 -> v3.1: Luocha Head Blend Hash'),          (upgrade_hash, {'to': 'ed675449'})],
    'd5f4ef26': [('info', 'v3.0 -> v3.1: Luocha Head Position Hash'),       (upgrade_hash, {'to': 'cc41f294'})],

    '194a6495': [('info', 'v2.0 -> v3.2: Luocha Body Draw Hash'), (upgrade_hash, {'to': '16d95198'})],
    'aabdd8f5': [('info', 'v2.0 -> v3.2: Luocha Body Position Hash'), (upgrade_hash, {'to': 'd16e462c'})],
    'ad6bae51': [('info', 'v3.1 -> v3.2: Luocha Hair Draw Hash'), (upgrade_hash, {'to': 'a2f89b5c'})],
    '7c78988c': [('info', 'v3.1 -> v3.2: Luocha Head Draw Hash'), (upgrade_hash, {'to': '73ebad81'})],


    # MARK: Lynx
    '8e595209': [('info', 'v1.6 -> v2.0: Lynx Body Texcoord Hash'), (upgrade_hash, {'to': '52a44eba'})],
    'b6019d61': [('info', 'v1.6 -> v2.0: Lynx BodyA Diffuse Hash'), (upgrade_hash, {'to': 'e2bad880'})],
    'e8c4b27f': [
        ('info', 'v1.6 -> v2.0: Lynx Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'LynxBody',
            'hash': '71647b48',
            'trg_indices': ['0', '51510'],
            'src_indices': ['0',    '-1'],
        })
    ],

    '6d27e7f2': [('info', 'v2.2 -> v2.3: Lynx Hair Diffuse Hash'),  (upgrade_hash, {'to': 'f4db275c'})],
    'a874888b': [('info', 'v2.2 -> v2.3: Lynx Hair LightMap Hash'), (upgrade_hash, {'to': '8dc79479'})],

    '3e2ad9b8': [('info', 'v2.2 -> v2.3: Lynx Head Diffuse Hash'),  (upgrade_hash, {'to': 'e5d8fa29'})],

    '52a44eba': [('info', 'v2.2 -> v2.3: Lynx Body Texcoord Hash'), (upgrade_hash, {'to': 'bffadc55'})],
    'e2bad880': [('info', 'v2.2 -> v2.3: Lynx Body Diffuse Hash'),  (upgrade_hash, {'to': '6c664cc4'})],
    '6cb92f15': [('info', 'v2.2 -> v2.3: Lynx Body LightMap Hash'), (upgrade_hash, {'to': '540bf4e4'})],

    # '09667bf6': [
    #     ('info', 'v2.3: Lynx Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '09667bf6'}),
    #     (check_hash_not_in_ini, {'hash': '7b23e3e6'}),
    #     (multiply_section, {
    #         'titles': ['LynxBodyPosition', 'LynxBodyPosition_Extra'],
    #         'hashes': ['09667bf6', '7b23e3e6']
    #     })
    # ],

    '7b23e3e6': [('info', 'v2.3 -> v3.1: Lynx Body Position Hash Extra'),                  (comment_sections, {})],
    'fa9c73b8': [('info', 'v3.0 -> v3.1: Lynx Body Blend Hash'),            (upgrade_hash, {'to': '156d0dec'})],
    '195d3f53': [('info', 'v3.0 -> v3.1: Lynx Hair Blend Hash'),            (upgrade_hash, {'to': 'f6ac4107'})],
    '7ab99fa3': [('info', 'v3.0 -> v3.1: Lynx Hair Position Hash'),         (upgrade_hash, {'to': '630c8211'})],
    'de5813fa': [('info', 'v3.0 -> v3.1: Lynx Head Blend Hash'),            (upgrade_hash, {'to': '31a96dae'})],
    'b636d476': [('info', 'v3.0 -> v3.1: Lynx Head Position Hash'),         (upgrade_hash, {'to': 'af83c9c4'})],
    '09667bf6': [('info', 'v3.0 -> v3.1: Lynx Body Position Hash'),         (upgrade_hash, {'to': '6296fe54'})],

    'e46f88d6': [('info', 'v3.1 -> v3.2: Lynx Hair Draw Hash'), (upgrade_hash, {'to': 'ebfcbddb'})],
    '407d2f48': [('info', 'v3.1 -> v3.2: Lynx Head Draw Hash'), (upgrade_hash, {'to': '4fee1a45'})],
    'ba91c796': [('info', 'v3.1 -> v3.2: Lynx Body Draw Hash'), (upgrade_hash, {'to': 'b502f29b'})],


    # MARK: March7th
    'fcef8885': [('info', 'v1.6 -> v2.0: March7th Body Texcoord Hash'), (upgrade_hash, {'to': 'ecf4648c'})],
     '97ad7623': [
        ('info', 'v1.6 -> v2.0: March7th Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'March7thBody',
            'hash': '5212ce68',
            'trg_indices': ['0', '30828', '41466', '53751'],
            'src_indices': ['0', '32502',    '-1',    '-1'],
        })
    ],

    '1ed7e59d': [('info', 'v2.2 -> v2.3: March7th Hair Texcoord Hash'),  (upgrade_hash, {'to': '948c4e59'})],
    '6bd71ad9': [('info', 'v2.2 -> v2.3: March7th Hair Diffuse Hash'),   (upgrade_hash, {'to': 'e299099f'})],
    '371ca498': [('info', 'v2.2 -> v2.3: March7th Hair LightMap Hash'),  (upgrade_hash, {'to': '89cd27c7'})],

    '2d25d041': [('info', 'v2.2 -> v2.3: March7th Head Diffuse Hash'),   (upgrade_hash, {'to': 'dbbb9b12'})],

    'ecf4648c': [('info', 'v2.2 -> v2.3: March7th Body Texcoord Hash'),  (upgrade_hash, {'to': 'b950fe40'})],
    'e6b35ac0': [('info', 'v2.2 -> v2.3: March7th BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'a9101746'})],
    '8c584d30': [('info', 'v2.2 -> v2.3: March7th BodyA LightMap Hash'), (upgrade_hash, {'to': '87f4596d'})],
    'b57574b3': [('info', 'v2.2 -> v2.3: March7th BodyB Diffuse Hash'),  (upgrade_hash, {'to': 'cada1307'})],
    '2006cd6a': [('info', 'v2.2 -> v2.3: March7th BodyB LightMap Hash'), (upgrade_hash, {'to': '01f9dbb8'})],

    'baaeaaf0': [('info', 'v3.0 -> v3.1: March7th Body Blend Hash'),        (upgrade_hash, {'to': '555fd4a4'})],
    '749c6d11': [('info', 'v3.0 -> v3.1: March7th Hair Blend Hash'),        (upgrade_hash, {'to': '9b6d1345'})],
    '09903e8e': [('info', 'v3.0 -> v3.1: March7th Hair Position Hash'),     (upgrade_hash, {'to': '1025233c'})],
    '694f577b': [('info', 'v3.0 -> v3.1: March7th Head Blend Hash'),        (upgrade_hash, {'to': '86be292f'})],
    'b23869e0': [('info', 'v3.0 -> v3.1: March7th Head Position Hash'),     (upgrade_hash, {'to': 'ab8d7452'})],

    'be2f8ed9': [('info', 'v3.1 -> v3.2: March7thPreservation Hair Draw Hash'), (upgrade_hash, {'to': 'b1bcbbd4'})],
    'e6654dbb': [('info', 'v3.1 -> v3.2: March7thPreservation Body Draw Hash'), (upgrade_hash, {'to': 'e9f678b6'})],
    '5592f1db': [('info', 'v3.1 -> v3.2: March7thPreservation Body Position Hash'), (upgrade_hash, {'to': 'f5491fea'})],


    # MARK: March7thHunt

    '712bac55': [('info', 'v3.0 -> v3.1: March7thHunt Body Blend Hash'),    (upgrade_hash, {'to': '9edad201'})],
    '6f468e3f': [('info', 'v3.0 -> v3.1: March7thHunt Hair Blend Hash'),    (upgrade_hash, {'to': '80b7f06b'})],
    '411425d0': [('info', 'v3.0 -> v3.1: March7thHunt Hair Position Hash'), (upgrade_hash, {'to': '58a13862'})],

    '99361f97': [('info', 'v3.1 -> v3.2: March7thHunt Hair Draw Hash'), (upgrade_hash, {'to': '96a52a9a'})], # same hash as ruan mei
    '49a6a173': [('info', 'v3.1 -> v3.2: March7thHunt Head Draw Hash'), (upgrade_hash, {'to': '4635947e'})],
    '5764cafb': [('info', 'v3.1 -> v3.2: March7thHunt Body Draw Hash'), (upgrade_hash, {'to': '58f7fff6'})],
    'e493769b': [('info', 'v3.1 -> v3.2: March7thHunt Body Position Hash'), (upgrade_hash, {'to': 'e0454a9f'})],



    #MARK: MEM
    # '65e20e67': [('info', 'v3.1 -> v3.2: Position Hash --> Blend Hash'), (upgrade_hash, {'to': '1066f7e6'})],
    "dfecbcfd": [('info', 'v3.1 -> v3.2: Mem Draw Hash'), (upgrade_hash, {'to': 'd07f89f0'})],

    # MARK: Misha
    '0f570849': [('info', 'v2.0 -> v2.1: Misha Head Position Hash'), (upgrade_hash, {'to': 'be8ee647'})],
    '8aa3d867': [('info', 'v2.0 -> v2.1: Misha Head Texcoord Hash'), (upgrade_hash, {'to': 'ee650b42'})],

    'c49badcb': [('info', 'v2.2 -> v2.3: Misha Hair Draw Hash'),     (upgrade_hash, {'to': 'cdc4b6ac'})],
    '4b221f10': [('info', 'v2.2 -> v2.3: Misha Hair Position Hash'), (upgrade_hash, {'to': 'af206cba'})],
    '9980f41b': [('info', 'v2.2 -> v2.3: Misha Hair Texcoord Hash'), (upgrade_hash, {'to': 'e35c9a5a'})],
    '66e3518a': [('info', 'v2.2 -> v2.3: Misha Hair IB Hash'),       (upgrade_hash, {'to': '08e4fb11'})],
    '028905ee': [('info', 'v2.2 -> v2.3: Misha Hair Diffuse Hash'),  (upgrade_hash, {'to': '328e0604'})],
    '8e793185': [('info', 'v2.2 -> v2.3: Misha Hair LightMap Hash'), (upgrade_hash, {'to': 'f66cebd0'})],

    'ee650b42': [('info', 'v2.2 -> v2.3: Misha Head Texcoord Hash'), (upgrade_hash, {'to': '7abbb9e1'})],
    '958056b6': [('info', 'v2.2 -> v2.3: Misha Head Diffuse Hash'),  (upgrade_hash, {'to': '60707bff'})],

    '157dc503': [('info', 'v2.2 -> v2.3: Misha Body Diffuse Hash'),  (upgrade_hash, {'to': '2b17a6a5'})],
    '429f63a8': [('info', 'v2.2 -> v2.3: Misha Body LightMap Hash'), (upgrade_hash, {'to': 'ce79ee01'})],

    'be8ee647': [('info', 'v2.1 -> v3.1: Misha Head Position Hash'),        (upgrade_hash, {'to': 'a73bfbf5'})],
    'af206cba': [('info', 'v2.3 -> v3.1: Misha Hair Position Hash'),        (upgrade_hash, {'to': 'b6957108'})],
    '7cbca09c': [('info', 'v3.0 -> v3.1: Misha Body Blend Hash'),           (upgrade_hash, {'to': '934ddec8'})],
    '3ae2fc69': [('info', 'v3.0 -> v3.1: Misha Hair Blend Hash'),           (upgrade_hash, {'to': 'd513823d'})],
    '999dff73': [('info', 'v3.0 -> v3.1: Misha Head Blend Hash'),           (upgrade_hash, {'to': '766c8127'})],

    'cdc4b6ac': [('info', 'v2.3 -> v3.2: Misha Hair Draw Hash'), (upgrade_hash, {'to': 'c25783a1'})],
    '56ce3fd0': [('info', 'v3.1 -> v3.2: Misha Head Draw Hash'), (upgrade_hash, {'to': '595d0add'})],
    '6652bfc8': [('info', 'v3.1 -> v3.2: Misha Body Draw Hash'), (upgrade_hash, {'to': '69c18ac5'})],
    'd5a503a8': [('info', 'v3.1 -> v3.2: Misha Body Position Hash'), (upgrade_hash, {'to': 'd5d9dd08'})],


    # MARK: Moze
    'dda2bf74': [('info', 'v2.6 -> v2.7: Moze Head Texcoord Hash'), (upgrade_hash, {'to': '1a604ceb'})],
    '7439f4c8': [('info', 'v2.6 -> v2.7: Moze Body Texcoord Hash'), (upgrade_hash, {'to': '84a33c6c'})],

    '86630c6b': [('info', 'v3.0 -> v3.1: Moze Body Blend Hash'),            (upgrade_hash, {'to': '6992723f'})],
    '49534d8c': [('info', 'v3.0 -> v3.1: Moze Hair Blend Hash'),            (upgrade_hash, {'to': 'a6a233d8'})],
    'c88fe0e7': [('info', 'v3.0 -> v3.1: Moze Hair Position Hash'),         (upgrade_hash, {'to': 'd13afd55'})],
    '07f88cc9': [('info', 'v3.0 -> v3.1: Moze Head Blend Hash'),            (upgrade_hash, {'to': 'e809f29d'})],
    '48ddd366': [('info', 'v3.0 -> v3.1: Moze Head Position Hash'),         (upgrade_hash, {'to': '5168ced4'})],

    '806542dc': [('info', 'v3.1 -> v3.2: Moze Hair Draw Hash'), (upgrade_hash, {'to': '8ff677d1'})],
    '0bcc8d2f': [('info', 'v3.1 -> v3.2: Moze Body Draw Hash'), (upgrade_hash, {'to': '045fb822'})],
    'b83b314f': [('info', 'v3.1 -> v3.2: Moze Body Position Hash'), (upgrade_hash, {'to': '590ae82e'})],

    # Mark: Mydei
    '2b0abf3c': [('info', 'v3.1 -> v3.2: Mydei Hair Draw Hash'), (upgrade_hash, {'to': '24998a31'})],
    '5ee19070': [('info', 'v3.1 -> v3.2: Mydei Head Draw Hash'), (upgrade_hash, {'to': '5172a57d'})],
    'dd69365a': [('info', 'v3.1 -> v3.2: Mydei Body Draw Hash'), (upgrade_hash, {'to': 'd2fa0357'})],



    # MARK: Natasha
    'fc66ad46': [('info', 'v1.6 -> v2.0: Natasha Body Position Extra Hash'), (upgrade_hash, {'to': '4958a3f3'})],
    '9ac894b4': [('info', 'v1.6 -> v2.0: Natasha Body Texcoord Hash'),       (upgrade_hash, {'to': 'b9b8b2a1'})],
      '005670d8': [
        ('info', 'v1.6 -> v2.0: Natasha Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'NatashaBody',
            'hash': '68dd15e8',
            'trg_indices': [ '0', '3024', '38907', '45612'],
            'src_indices': ['-1',    '0',    '-1', '38907'],
        })
    ],
    # '0de1ff21': [
    #     ('info', 'v2.1: Natasha Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '4958a3f3'}),
    #     (check_hash_not_in_ini, {'hash': 'fc66ad46'}),
    #     (multiply_section, {
    #         'titles': ['NatashaBodyPosition', 'NatashaBodyPosition_Extra'],
    #         'hashes': ['0de1ff21', '4958a3f3']
    #     })
    # ],

    '5f44fc0d': [('info', 'v2.2 -> v2.3: Natasha Hair Texcoord Hash'),     (upgrade_hash, {'to': 'a9728390'})],
    '595464a6': [('info', 'v2.2 -> v2.3: Natasha Hair Diffuse Hash'),      (upgrade_hash, {'to': '08ac31d1'})],
    'abcc21d1': [('info', 'v2.2 -> v2.3: Natasha Hair LightMap Hash'),     (upgrade_hash, {'to': '260f2286'})],

    '5a9597db': [('info', 'v2.2 -> v2.3: Natasha Head Diffuse Hash'),      (upgrade_hash, {'to': 'b719225a'})],

    'b9b8b2a1': [('info', 'v2.2 -> v2.3: Natasha Body Texcoord Hash'),     (upgrade_hash, {'to': 'f1668e08'})],
    '209f5c65': [('info', 'v2.2 -> v2.3: Natasha BodyB Diffuse Hash'),     (upgrade_hash, {'to': '6f4ab910'})],
    'bfd47fe8': [('info', 'v2.2 -> v2.3: Natasha BodyB LightMap Hash'),    (upgrade_hash, {'to': 'fe813491'})],
    '88be8df6': [('info', 'v2.2 -> v2.3: Natasha BodyB StockingMap Hash'), (upgrade_hash, {'to': 'defb30fc'})],
    '3bd51af4': [('info', 'v2.2 -> v2.3: Natasha BodyD Diffuse Hash'),     (upgrade_hash, {'to': '519ef69f'})],
    '2799f499': [('info', 'v2.2 -> v2.3: Natasha BodyD LightMap Hash'),    (upgrade_hash, {'to': '919da513'})],
    'de96634b': [('info', 'v2.2 -> v2.3: Natasha BodyD StockingMap Hash'), (upgrade_hash, {'to': '236df0fa'})],

    '4958a3f3': [('info', 'v2.0 -> v3.1: Natasha Body Position Extra Hash'),              (comment_sections, {})],
    '23c6f5ac': [('info', 'v3.0 -> v3.1: Natasha Body Blend Hash'),         (upgrade_hash, {'to': 'cc378bf8'})],
    '38e692c7': [('info', 'v3.0 -> v3.1: Natasha Hair Blend Hash'),         (upgrade_hash, {'to': 'd717ec93'})],
    '29539b93': [('info', 'v3.0 -> v3.1: Natasha Hair Position Hash'),      (upgrade_hash, {'to': '30e68621'})],
    '94322ac5': [('info', 'v3.0 -> v3.1: Natasha Head Blend Hash'),         (upgrade_hash, {'to': '7bc35491'})],
    '4a197424': [('info', 'v3.0 -> v3.1: Natasha Head Position Hash'),      (upgrade_hash, {'to': '53ac6996'})],
    '0de1ff21': [('info', 'v3.0 -> v3.1: Natasha Body Position Hash'), (upgrade_hash, {'to': '50edbe41'})],

    '4eb6efa7': [('info', 'v3.1 -> v3.2: Natasha Hair Draw Hash'), (upgrade_hash, {'to': '4125daaa'})],
    'be164341': [('info', 'v3.1 -> v3.2: Natasha Body Draw Hash'), (upgrade_hash, {'to': 'b185764c'})],


    # MARK: Pela
    '6148b897': [('info', 'v1.6 -> v2.0: Pela Body Texcoord Hash'), (upgrade_hash, {'to': '77a2f3bf'})],
      'f4eb23b2': [
        ('info', 'v1.6 -> v2.0: Pela Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'PelaBody',
            'hash': '98dbd548',
            'trg_indices': ['0', '44043'],
            'src_indices': ['0',    '-1'],
        })
    ],

    '934172e5': [('info', 'v2.2 -> v2.3: Pela Hair Diffuse Hash'),     (upgrade_hash, {'to': '7fcd70ea'})],
    '54a11a98': [('info', 'v2.2 -> v2.3: Pela Hair LightMap Hash'),    (upgrade_hash, {'to': '93279a4a'})],

    '0a50c14c': [('info', 'v2.2 -> v2.3: Pela Head Diffuse Hash'),     (upgrade_hash, {'to': '945d61df'})],

    'e02d100c': [('info', 'v2.2 -> v2.3: Pela Body Diffuse Hash'),     (upgrade_hash, {'to': '48fca7f8'})],
    'ffeb1d46': [('info', 'v2.2 -> v2.3: Pela Body LightMap Hash'),    (upgrade_hash, {'to': '21d34147'})],
    '8df14d0a': [('info', 'v2.2 -> v2.3: Pela Body StockingMap Hash'), (upgrade_hash, {'to': '883e4c54'})],

    'b889667f': [('info', 'v3.0 -> v3.1: Pela Body Blend Hash'),            (upgrade_hash, {'to': '5778182b'})],
    '4b1780bb': [('info', 'v3.0 -> v3.1: Pela Hair Blend Hash'),            (upgrade_hash, {'to': 'a4e6feef'})],
    'fd24333c': [('info', 'v3.0 -> v3.1: Pela Hair Position Hash'),         (upgrade_hash, {'to': 'e4912e8e'})],
    '53070a34': [('info', 'v3.0 -> v3.1: Pela Head Blend Hash'),            (upgrade_hash, {'to': 'bcf67460'})],
    'db053da4': [('info', 'v3.0 -> v3.1: Pela Head Position Hash'),         (upgrade_hash, {'to': 'c2b02016'})],

    '18d9ad82': [('info', 'v3.1 -> v3.2: Pela Hair Draw Hash'), (upgrade_hash, {'to': '174a988f'})],
    '87f9b9c3': [('info', 'v3.1 -> v3.2: Pela Head Draw Hash'), (upgrade_hash, {'to': '886a8cce'})],
    '79a43d63': [('info', 'v3.1 -> v3.2: Pela Body Draw Hash'), (upgrade_hash, {'to': '7637086e'})],
    'ca538103': [('info', 'v3.1 -> v3.2: Pela Body Position Hash'), (upgrade_hash, {'to': '27b7176f'})],


    # MARK: Qingque
    '3a305670': [('info', 'v1.6 -> v2.0: Qingque Body Texcoord Hash'), (upgrade_hash, {'to': 'cc2db614'})],
      'daafea36': [
        ('info', 'v1.6 -> v2.0: Qingque Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'QingqueBody',
            'hash': '0a82ceb7',
            'trg_indices': ['0', '23730', '27573', '45615'],
            'src_indices': ['0',    '-1',    '-1', '27765'],
        })
    ],

    '73fbbace': [('info', 'v2.2 -> v2.3: Qingque Hair Diffuse Hash'),   (upgrade_hash, {'to': 'd9e91d27'})],
    '48829296': [('info', 'v2.2 -> v2.3: Qingque Hair LightMap Hash'),  (upgrade_hash, {'to': 'ddabcef6'})],

    'c2559faf': [('info', 'v2.2 -> v2.3: Qingque Head Diffuse Hash'),   (upgrade_hash, {'to': '5421f07d'})],


    '55e1b1f8': [('info', 'v2.2 -> v2.3: Qingque Body Draw Hash'),      (upgrade_hash, {'to': '311daa47'})],
    'e6160d98': [('info', 'v2.2 -> v2.3: Qingque Body Position Hash'),  (upgrade_hash, {'to': '82ea1627'})],
    'cc2db614': [('info', 'v2.2 -> v2.3: Qingque Body Texcoord Hash'),  (upgrade_hash, {'to': 'd97fd893'})],
    '0a82ceb7': [('info', 'v2.2 -> v2.3: Qingque Body IB Hash'),        (upgrade_hash, {'to': '21856dc2'})],

    'ff995bd0': [('info', 'v2.2 -> v2.3: Qingque BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'd92826b3'})],
    '2d563efe': [('info', 'v2.2 -> v2.3: Qingque BodyA LightMap Hash'), (upgrade_hash, {'to': 'a85d8219'})],
    '149c086c': [('info', 'v2.2 -> v2.3: Qingque BodyC Diffuse Hash'),  (upgrade_hash, {'to': '92c74827'})],
    '2b135afe': [('info', 'v2.2 -> v2.3: Qingque BodyC LightMap Hash'), (upgrade_hash, {'to': 'f57f3990'})],

    '109719da': [('info', 'v3.0 -> v3.1: Qingque Body Blend Hash'),         (upgrade_hash, {'to': 'ff66678e'})],
    '1efcf666': [('info', 'v3.0 -> v3.1: Qingque Hair Blend Hash'),         (upgrade_hash, {'to': 'f10d8832'})],
    '926cd87e': [('info', 'v3.0 -> v3.1: Qingque Hair Position Hash'),      (upgrade_hash, {'to': '8bd9c5cc'})],
    '8c6fc97d': [('info', 'v3.0 -> v3.1: Qingque Head Blend Hash'),         (upgrade_hash, {'to': '639eb729'})],
    '968fce83': [('info', 'v3.0 -> v3.1: Qingque Head Position Hash'),      (upgrade_hash, {'to': '8f3ad331'})],

    '311daa47': [('info', 'v2.2 -> v3.2: Qingque Body Draw Hash'), (upgrade_hash, {'to': '3e8e9f4a'})],
    '82ea1627': [('info', 'v2.3 -> v3.2: Qingque Body Position Hash'), (upgrade_hash, {'to': '8020c78e'})],
    '77ba9951': [('info', 'v3.1 -> v3.2: Qingque Hair Draw Hash'), (upgrade_hash, {'to': '7829ac5c'})],
    'c997b5ee': [('info', 'v3.1 -> v3.2: Qingque Head Draw Hash'), (upgrade_hash, {'to': 'c60480e3'})],


    # MARK: Rapa
    '929ed561': [('info', 'v3.0 -> v3.1: Rappa Body Blend Hash'),           (upgrade_hash, {'to': '7d6fab35'})],
    '16da2868': [('info', 'v3.0 -> v3.1: Rappa Hair Blend Hash'),           (upgrade_hash, {'to': 'f92b563c'})],
    'd5d249db': [('info', 'v3.0 -> v3.1: Rappa Hair Position Hash'),        (upgrade_hash, {'to': 'cc675469'})],
    'be6516d2': [('info', 'v3.0 -> v3.1: Rappa Head Blend Hash'),           (upgrade_hash, {'to': '51946886'})],
    '19526add': [('info', 'v3.0 -> v3.1: Rappa Head Position Hash'),        (upgrade_hash, {'to': '00e7776f'})],

    '20eae8c1': [('info', 'v3.1 -> v3.2: Rappa Hair Draw Hash'), (upgrade_hash, {'to': '2f79ddcc'})],
    '4004b137': [('info', 'v3.1 -> v3.2: Rappa Head Draw Hash'), (upgrade_hash, {'to': '4f97843a'})],
    'f4af28d6': [('info', 'v3.1 -> v3.2: Rappa Body Draw Hash'), (upgrade_hash, {'to': 'fb3c1ddb'})],
    '475894b6': [('info', 'v3.1 -> v3.2: Rappa Body Position Hash'), (upgrade_hash, {'to': '92db0310'})],


    # MARK: Robin
    '490e6507': [('info', 'v2.2 -> v2.3: Robin HairA Diffuse Hash'),       (upgrade_hash, {'to': 'b7d76947'})],
    '63aafaed': [('info', 'v2.2 -> v2.3: Robin HairA LightMap Hash'),      (upgrade_hash, {'to': '445abbfc'})],
 
    '07fd3ce1': [('info', 'v2.2 -> v2.3: Robin HeadA Diffuse Hash'),       (upgrade_hash, {'to': '14116af5'})],
 
    '312e2c95': [('info', 'v2.2 -> v2.3: Robin BodyA Diffuse Hash'),       (upgrade_hash, {'to': 'de39f5f2'})],
    '4c249936': [('info', 'v2.2 -> v2.3: Robin BodyA LightMap Hash'),      (upgrade_hash, {'to': '57ba7e2a'})],
 
    '9e6b5969': [('info', 'v2.2 -> v2.3: Robin BodyB StarrySkyMask Hash'), (upgrade_hash, {'to': 'e5ed0f89'})],
 
    'ef273dac': [('info', 'v2.5 -> v2.6: Robin Body Position Hash'),      (upgrade_hash, {'to': '22e9e92a'})],
    '43c5c007': [('info', 'v2.5 -> v2.6: Robin Body Texcoord Hash'),      (upgrade_hash, {'to': 'a65193dc'})],

    '94a0e452': [('info', 'v3.0 -> v3.1: Robin Body Blend Hash'),           (upgrade_hash, {'to': '7b519a06'})],
    '22e9e92a': [('info', 'v2.6 -> v3.1: Robin Body Position Hash'),        (upgrade_hash, {'to': '3b5cf498'})],
    '022d66fa': [('info', 'v3.0 -> v3.1: Robin Hair Blend Hash'),           (upgrade_hash, {'to': 'eddc18ae'})],
    'c659dc72': [('info', 'v3.0 -> v3.1: Robin Hair Position Hash'),        (upgrade_hash, {'to': 'dfecc1c0'})],
    '68e89a79': [('info', 'v3.0 -> v3.1: Robin Head Blend Hash'),           (upgrade_hash, {'to': '8719e42d'})],
    '4eb1753f': [('info', 'v3.0 -> v3.1: Robin Head Position Hash'),        (upgrade_hash, {'to': '5704688d'})],

    '08627b10': [('info', 'v3.1 -> v3.2: Robin Hair Draw Hash'), (upgrade_hash, {'to': '07f14e1d'})],
    '3e3a2a8a': [('info', 'v3.1 -> v3.2: Robin Head Draw Hash'), (upgrade_hash, {'to': '31a91f87'})],
    '5cd081cc': [('info', 'v3.1 -> v3.2: Robin Body Draw Hash'), (upgrade_hash, {'to': '5343b4c1'})],


    # MARK: RuanMei
    '6f3b9090': [('info', 'v1.6 -> v2.0: RuanMei Body Texcoord Hash'),  (upgrade_hash, {'to': '803d3eda'})],
    '35bf6c19': [('info', 'v1.6 -> v2.0: RuanMei BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'fe8145b1'})],
    'c984b1e6': [('info', 'v1.6 -> v2.0: RuanMei BodyA LightMap Hash'), (upgrade_hash, {'to': '9b63577a'})],
    # 'ab4af2cb': [
    #     ('info', 'v2.1: RuanMei Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '7e4f7890'}),
    #     (multiply_section, {
    #         'titles': ['RuanMeiBodyPosition', 'RuanMeiBodyPosition_Extra'],
    #         'hashes': ['ab4af2cb', '7e4f7890']
    #     })
    # ],

    '7e4f7890': [('info', 'v2.2 -> v3.1: RuanMei Body Position Extra Hash'),              (comment_sections, {})],
    'f6491dae': [('info', 'v2.2 -> v2.3: RuanMei HairA Diffuse Hash'),  (upgrade_hash, {'to': '22e8a12f'})],
    '45e0fe2c': [('info', 'v2.2 -> v2.3: RuanMei HairA LightMap Hash'), (upgrade_hash, {'to': '0198e0df'})],
 
    'b3ddcd02': [('info', 'v2.2 -> v2.3: RuanMei HeadA Diffuse Hash'),  (upgrade_hash, {'to': 'fd3d44f8'})],
    
    'fe8145b1': [('info', 'v2.2 -> v2.3: RuanMei BodyA Diffuse Hash'),  (upgrade_hash, {'to': '5387a03e'})],
    '9b63577a': [('info', 'v2.2 -> v2.3: RuanMei BodyA LightMap Hash'), (upgrade_hash, {'to': '93eec3ab'})],

    '2d3d915a': [('info', 'v3.0 -> v3.1: RuanMei Body Blend Hash'),         (upgrade_hash, {'to': 'c2ccef0e'})],
    '3b0cb896': [('info', 'v3.0 -> v3.1: RuanMei Hair Blend Hash'),         (upgrade_hash, {'to': 'd4fdc6c2'})],
    '7ed84bde': [('info', 'v3.0 -> v3.1: RuanMei Hair Position Hash'),      (upgrade_hash, {'to': '676d566c'})],
    '490a691b': [('info', 'v3.0 -> v3.1: RuanMei Head Blend Hash'),         (upgrade_hash, {'to': 'a6fb174f'})],
    '5a981b24': [('info', 'v3.0 -> v3.1: RuanMei Head Position Hash'),      (upgrade_hash, {'to': '432d0696'})],
    'ab4af2cb': [('info', 'v3.0 -> v3.1: RuanMei Body Position Hash'), (upgrade_hash, {'to': '67fa6522'})],

    '921846ab': [('info', 'v3.1 -> v3.2: RuanMei Head Draw Hash'), (upgrade_hash, {'to': '9d8b73a6'})],
    '18bd4eab': [('info', 'v3.1 -> v3.2: RuanMei Body Draw Hash'), (upgrade_hash, {'to': '172e7ba6'})],



    # MARK: Sampo
    '75824b32': [('info', 'v2.2 -> v2.3: Sampo Hair Draw Hash'),     (upgrade_hash, {'to': '31447b51'})],
    'e07731c5': [('info', 'v2.2 -> v2.3: Sampo Hair Position Hash'), (upgrade_hash, {'to': '3095786c'})],
    '529994b6': [('info', 'v2.2 -> v2.3: Sampo Hair Texcoord Hash'), (upgrade_hash, {'to': '5974af55'})],
    'd2e6ad9b': [('info', 'v2.2 -> v2.3: Sampo Hair IB Hash'),       (upgrade_hash, {'to': '96243edc'})],
    'ec28a787': [('info', 'v2.2 -> v2.3: Sampo Hair Diffuse Hash'),  (upgrade_hash, {'to': '36d62e76'})],
    '22c6ec2c': [('info', 'v2.2 -> v2.3: Sampo Hair LightMap Hash'), (upgrade_hash, {'to': '989a13bb'})],

    '3095d3d1': [('info', 'v2.2 -> v2.3: Sampo Head Diffuse Hash'),  (upgrade_hash, {'to': '4c904279'})],

    'a81589e4': [('info', 'v2.2 -> v2.3: Sampo Body Texcoord Hash'), (upgrade_hash, {'to': 'e0274b6f'})],
       '3ac42f7d': [
        ('info', 'v2.2 -> v2.3: Sampo Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'SampoBody',
            'hash': '15761df0',
            'trg_indices': ['0', '20655'],
            'src_indices': ['0', '20637'],
        })
    ],
    '85c01194': [('info', 'v2.2 -> v2.3: Sampo BodyA Diffuse Hash'),  (upgrade_hash, {'to': '297b7f7c'})],
    'e15ccf04': [('info', 'v2.2 -> v2.3: Sampo BodyA LightMap Hash'), (upgrade_hash, {'to': '1251e25b'})],
    '92065503': [('info', 'v2.2 -> v2.3: Sampo BodyB Diffuse Hash'),  (upgrade_hash, {'to': '4fd99756'})],
    '333b2634': [('info', 'v2.2 -> v2.3: Sampo BodyB LightMap Hash'), (upgrade_hash, {'to': '992d119f'})],

    'b9371b3c': [('info', 'v3.0 -> v3.1: Sampo Body Blend Hash'),           (upgrade_hash, {'to': '56c66568'})],
    'd4ab62d7': [('info', 'v3.0 -> v3.1: Sampo Hair Blend Hash'),           (upgrade_hash, {'to': '3b5a1c83'})],
    '3095786c': [('info', 'v2.3 -> v3.1: Sampo Hair Position Hash'),        (upgrade_hash, {'to': '292065de'})],
    'f3f0c980': [('info', 'v3.0 -> v3.1: Sampo Head Blend Hash'),           (upgrade_hash, {'to': '1c01b7d4'})],
    '3b4bdc1f': [('info', 'v3.0 -> v3.1: Sampo Head Position Hash'),        (upgrade_hash, {'to': '22fec1ad'})],

    '31447b51': [('info', 'v2.3 -> v3.2: Sampo Hair Draw Hash'), (upgrade_hash, {'to': '3ed74e5c'})],
    '6656406f': [('info', 'v3.1 -> v3.2: Sampo Head Draw Hash'), (upgrade_hash, {'to': '69c57562'})],
    '8d3b5179': [('info', 'v3.1 -> v3.2: Sampo Body Draw Hash'), (upgrade_hash, {'to': '82a86474'})],
    '3ecced19': [('info', 'v3.1 -> v3.2: Sampo Body Position Hash'), (upgrade_hash, {'to': '2087b78d'})],


    # MARK: Seele
    '41943cc6': [('info', 'v1.6 -> v2.0: Seele Body Texcoord Hash'), (upgrade_hash, {'to': 'fe54239f'})],
       'eb699635': [
        ('info', 'v1.6 -> v2.0: Seele Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'SeeleBody',
            'hash': '6a522a54',
            'trg_indices': ['0', '11550', '19968', '49764'],
            'src_indices': ['0',    '-1', '19968',    '-1'],
        })
    ],

    '8f3bec58': [('info', 'v2.2 -> v2.3: Seele HairA Diffuse Hash'),  (upgrade_hash, {'to': 'ebc707dd'})],
    '4122931f': [('info', 'v2.2 -> v2.3: Seele HairA LightMap Hash'), (upgrade_hash, {'to': 'da303c25'})],
 
    'ef4ec36c': [('info', 'v2.2 -> v2.3: Seele HeadA Diffuse Hash'),  (upgrade_hash, {'to': '75263a6e'})],
    
     'fe54239f': [('info', 'v2.2 -> v2.3: Seele Body Texcoord Hash'),  (upgrade_hash, {'to': '17cba38d'})],

    '8daeb19c': [('info', 'v2.2 -> v2.3: Seele BodyA Diffuse Hash'),  (upgrade_hash, {'to': '600c3a12'})],
    'b06965df': [('info', 'v2.2 -> v2.3: Seele BodyA LightMap Hash'), (upgrade_hash, {'to': '14bb544b'})],
    '1747ac60': [('info', 'v2.2 -> v2.3: Seele BodyC Diffuse Hash'),  (upgrade_hash, {'to': '8e550df4'})],
    '32df70e0': [('info', 'v2.2 -> v2.3: Seele BodyC LightMap Hash'), (upgrade_hash, {'to': 'c6db3a14'})],

    '8a952009': [('info', 'v3.0 -> v3.1: Seele Body Blend Hash'),           (upgrade_hash, {'to': '65645e5d'})],
    'a9013cae': [('info', 'v3.0 -> v3.1: Seele Hair Blend Hash'),           (upgrade_hash, {'to': '46f042fa'})],
    '0eec1b57': [('info', 'v3.0 -> v3.1: Seele Hair Position Hash'),        (upgrade_hash, {'to': '175906e5'})],
    'e9ffad95': [('info', 'v3.0 -> v3.1: Seele Head Blend Hash'),           (upgrade_hash, {'to': '060ed3c1'})],
    'e1a2635f': [('info', 'v3.0 -> v3.1: Seele Head Position Hash'),        (upgrade_hash, {'to': 'f8177eed'})],

    'c6e91591': [('info', 'v3.1 -> v3.2: Seele Hair Draw Hash'), (upgrade_hash, {'to': 'c97a209c'})],
    '4bf88970': [('info', 'v3.1 -> v3.2: Seele Head Draw Hash'), (upgrade_hash, {'to': '446bbc7d'})],
    '45f1986e': [('info', 'v3.1 -> v3.2: Seele Body Draw Hash'), (upgrade_hash, {'to': '4a62ad63'})],
    'f606240e': [('info', 'v3.1 -> v3.2: Seele Body Position Hash'), (upgrade_hash, {'to': 'bb8ec098'})],


    # MARK: Serval
    'c71fc0d0': [('info', 'v1.6 -> v2.0: Serval Body Position Extra Hash'), (upgrade_hash, {'to': '1bdfe263'})],
    '35e3d214': [('info', 'v1.6 -> v2.0: Serval Body Texcoord Hash'),         (upgrade_hash, {'to': '86d77809'})],
    '44885792': [
        ('info', 'v1.6 -> v2.0: Serval Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'ServalBody',
            'hash': 'f092876d',
            'trg_indices': [ '0', '13731', '30048', '58380'],
            'src_indices': ['-1',     '0', '30048',    '-1'],
        })
    ],
    # '383717ed': [
    #     ('info', 'v2.1: Serval Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '1bdfe263'}),
    #     (check_hash_not_in_ini, {'hash': 'c71fc0d0'}),
    #     (multiply_section, {
    #         'titles': ['ServalBodyPosition', 'ServalBodyPosition_Extra'],
    #         'hashes': ['383717ed', '1bdfe263']
    #     })
    # ],

    '59d7157b': [('info', 'v2.2 -> v2.3: Serval HairA Diffuse Hash'),     (upgrade_hash, {'to': '21e4c3cd'})],
    '86144243': [('info', 'v2.2 -> v2.3: Serval HairA LightMap Hash'),    (upgrade_hash, {'to': '79709858'})],
 
    'd00782c7': [('info', 'v2.2 -> v2.3: Serval HeadA Diffuse Hash'),     (upgrade_hash, {'to': 'afd4f008'})],
    
     '8d159053': [('info', 'v2.2 -> v2.3: Serval BodyB Diffuse Hash'),     (upgrade_hash, {'to': '1bc2fa5f'})],
     '7e8fa12b': [('info', 'v2.2 -> v2.3: Serval BodyB LightMap Hash'),    (upgrade_hash, {'to': 'a05979e4'})],
     '6efdb42c': [('info', 'v2.2 -> v2.3: Serval BodyB StockingMap Hash'), (upgrade_hash, {'to': 'c7358fb2'})],
     '269745d0': [('info', 'v2.2 -> v2.3: Serval BodyC Diffuse Hash'),     (upgrade_hash, {'to': '5be64601'})],
     '725d36ab': [('info', 'v2.2 -> v2.3: Serval BodyC LightMap Hash'),    (upgrade_hash, {'to': 'c7bd5694'})],

    'ab709ef7': [('info', 'v3.0 -> v3.1: Serval Body Blend Hash'),          (upgrade_hash, {'to': '4481e0a3'})],
    '1bdfe263': [('info', 'v2.0 -> v3.1: Serval Body Position Extra Hash'),              (comment_sections, {})],
    '5bca39c4': [('info', 'v3.0 -> v3.1: Serval Hair Blend Hash'),          (upgrade_hash, {'to': 'b43b4790'})],
    '591d16e1': [('info', 'v3.0 -> v3.1: Serval Hair Position Hash'),       (upgrade_hash, {'to': '40a80b53'})],
    '876b2a8c': [('info', 'v3.0 -> v3.1: Serval Head Blend Hash'),          (upgrade_hash, {'to': '689a54d8'})],
    '2de93d4b': [('info', 'v3.0 -> v3.1: Serval Head Position Hash'),       (upgrade_hash, {'to': '345c20f9'})],
    '383717ed': [('info', 'v3.0 -> v3.1: Serval Body Position Hash'),        (upgrade_hash, {'to': '026affd1'})],

    '403c9fe7': [('info', 'v3.1 -> v3.2: Serval Hair Draw Hash'), (upgrade_hash, {'to': '4fafaaea'})],
    '8bc0ab8d': [('info', 'v3.1 -> v3.2: Serval Body Draw Hash'), (upgrade_hash, {'to': '84539e80'})],



    # MARK: Sparkle
    # SCYLL SAID NOT TO TOUCH HER
    '28788045': [('info', 'v2.0 -> v2.1: Sparkle Body Texcoord Hash'), (upgrade_hash, {'to': 'd51f3972'})],
    '74660eca': [('info', 'v2.0 -> v2.1: Sparkle Body IB Hash'),       (upgrade_hash, {'to': '68121fd3'})],
    
    '3c22971b': [('info', 'v2.1 -> v2.2: Sparkle BodyA Diffuse Hash'), (upgrade_hash, {'to': 'fac7d488'})],

    '1d7ed602': [('info', 'v2.2 -> v2.3: Sparkle Hair Diffuse Hash'),  (upgrade_hash, {'to': 'a4f91fac'})],
    '07b2e4b7': [('info', 'v2.2 -> v2.3: Sparkle Hair LightMap Hash'), (upgrade_hash, {'to': 'df96b015'})],

    '6594fbb2': [('info', 'v2.2 -> v2.3: Sparkle Head Diffuse Hash'),  (upgrade_hash, {'to': '09733ebc'})],

    'fac7d488': [('info', 'v2.2 -> v2.3: Sparkle Body Diffuse Hash'),  (upgrade_hash, {'to': '17999c91'})],
    'a4974a51': [('info', 'v2.2 -> v2.3: Sparkle Body LightMap Hash'), (upgrade_hash, {'to': 'f806d2e4'})],

    '91b9fb51': [('info', 'v3.0 -> v3.1: Sparkle Body Blend Hash'),         (upgrade_hash, {'to': '7e488505'})],
    '4e477254': [('info', 'v3.0 -> v3.1: Sparkle Hair Blend Hash'),         (upgrade_hash, {'to': 'a1b60c00'})],
    '5b9af3ba': [('info', 'v3.0 -> v3.1: Sparkle Hair Position Hash'),      (upgrade_hash, {'to': '422fee08'})],
    '4873b590': [('info', 'v3.0 -> v3.1: Sparkle Head Blend Hash'),         (upgrade_hash, {'to': 'a782cbc4'})],
    'c2cce86e': [('info', 'v3.0 -> v3.1: Sparkle Head Position Hash'),      (upgrade_hash, {'to': 'db79f5dc'})],

    '2ffc74a7': [('info', 'v3.1 -> v3.2: Sparkle Hair Draw Hash'), (upgrade_hash, {'to': '206f41aa'})],
    'b2bc717f': [('info', 'v3.1 -> v3.2: Sparkle Head Draw Hash'), (upgrade_hash, {'to': 'bd2f4472'})],
    'c22dc904': [('info', 'v3.1 -> v3.2: Sparkle Body Draw Hash'), (upgrade_hash, {'to': 'cdbefc09'})],
    '71da7564': [('info', 'v3.1 -> v3.2: Sparkle Body Position Hash'), (upgrade_hash, {'to': '9588097c'})],


    # MARK: SilverWolf
    '429574bd': [('info', 'v1.6 -> v2.0: SilverWolf Body Draw Hash'),      (upgrade_hash, {'to': '6bb20ea8'})],
    'f162c8dd': [('info', 'v1.6 -> v2.0: SilverWolf Body Position Hash'), (upgrade_hash, {'to': 'd845b2c8'})],
    '2e053525': [('info', 'v1.6 -> v2.0: SilverWolf Body Texcoord Hash'), (upgrade_hash, {'to': 'ab13f8b8'})],
     '729de5d2': [
        ('info', 'v1.6 -> v2.0: SilverWolf Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'SilverWolfBody',
            'hash': 'e8f10ab3',
            'trg_indices': ['0', '63549', '63663'],
            'src_indices': ['0', '64392',    '-1'],
        })
    ],
    'd28049f2': [
		(upgrade_shared_hash, {
			'to': 'dd137cff',
			'flag_hashes': ('876b2a8c', '689a54d8', '2de93d4b', '345c20f9'),
			'log_info': 'v3.1 -> v3.2: Serval Head Draw Hash',
		}),
		(upgrade_shared_hash, {
			'to': '293abc6c',
			'flag_hashes': ('b2d04673', '520314e4', '6f9922fe', 'b9254611'),
			'log_info': 'v2.2 -> v2.3: SilverWolf Hair Draw Hash',
		}),
	],
    'b2d04673': [('info', 'v2.2 -> v2.3: SilverWolf Hair Position Hash'), (upgrade_hash, {'to': '520314e4'})],
    '6f9922fe': [('info', 'v2.2 -> v2.3: SilverWolf Hair Texcoord Hash'), (upgrade_hash, {'to': 'b9254611'})],
    '3608ba80': [('info', 'v2.2 -> v2.3: SilverWolf Hair IB Hash'),       (upgrade_hash, {'to': '91db78c2'})],
    '56893677': [('info', 'v2.2 -> v2.3: SilverWolf Hair Diffuse Hash'),  (upgrade_hash, {'to': '7c7065ae'})],
    'dd608b21': [('info', 'v2.2 -> v2.3: SilverWolf Hair LightMap Hash'), (upgrade_hash, {'to': 'cf2cb5b7'})],
    
    'd99747d7': [('info', 'v2.2 -> v2.3: SilverWolf Head Diffuse Hash'),  (upgrade_hash, {'to': 'a05a9801'})],
 
    'ab13f8b8': [('info', 'v2.2 -> v2.3: SilverWolf Body Texcoord Hash'), (upgrade_hash, {'to': '6c945131'})],
     'e8f10ab3': [
        ('info', 'v2.2 -> v2.3: SilverWolf Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'SilverWolfBody',
            'hash': '891ecaae',
            'trg_indices': ['0', '63429', '63543'],
            'src_indices': ['0', '63549', '63663'],
        })
    ],
    '76d6dd31': [('info', 'v2.2 -> v2.3: SilverWolf Body Diffuse Hash'),  (upgrade_hash, {'to': 'b2f97e36'})],
    '84b3170b': [('info', 'v2.2 -> v2.3: SilverWolf Body LightMap Hash'), (upgrade_hash, {'to': '7b1eface'})],

    '17906457': [('info', 'v3.0 -> v3.1: SilverWolf Body Blend Hash'),      (upgrade_hash, {'to': 'f8611a03'})],
    '567d08be': [('info', 'v3.0 -> v3.1: SilverWolf Hair Blend Hash'),      (upgrade_hash, {'to': 'b98c76ea'})],
    '520314e4': [('info', 'v2.3 -> v3.1: SilverWolf Hair Position Hash'),   (upgrade_hash, {'to': '4bb60956'})],
    '2cf46858': [('info', 'v3.0 -> v3.1: SilverWolf Head Blend Hash'),      (upgrade_hash, {'to': 'c305160c'})],
    '314115a3': [('info', 'v3.0 -> v3.1: SilverWolf Head Position Hash'),   (upgrade_hash, {'to': '28f40811'})],

    '6bb20ea8': [('info', 'v2.0 -> v3.2: SilverWolf Body Draw Hash'), (upgrade_hash, {'to': '64213ba5'})],
    'd845b2c8': [('info', 'v2.0 -> v3.2: SilverWolf Body Position Hash'), (upgrade_hash, {'to': 'bd2443af'})],
    '293abc6c': [
        (upgrade_shared_hash, {
			'to': '26a98961',
			'flag_hashes': ('567d08be', '3608ba80', '91db78c2', 'b98c76ea'),
			'log_info': 'v2.3 -> v3.2: Silver Wolf Hair Draw Hash',
		}),    
    ],


    # MARK: Sunday
    # 'acc75a16': [
    #     ('info', 'v2.7: Sunday Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '2e207a71'}),
    #     (multiply_section, {
    #         'titles': ['SundayBodyPosition', 'SundayBodyPosition_Extra'],
    #         'hashes': ['acc75a16', '2e207a71']
    #     })
    # ],
    '7220563b': [('info', 'v2.7 -> v3.0: Sunday Body Diffuse Hash'),     (upgrade_hash, {'to': '5b056989'})],
    '9ec5fcc5': [('info', 'v2.7 -> v3.0: Sunday Body Diffuse Hash'),     (upgrade_hash, {'to': '09fdcc99'})],
    '2e207a71': [('info', 'v2.7 -> v3.1: Sunday Body Position Extra Hash'),          (comment_sections, {})],
    'acc75a16': [('info', 'v2.7 -> v3.1: Sunday Body Position Hash'),    (upgrade_hash, {'to': '379567c3'})],
    'c5c1150d': [('info', 'v3.0 -> v3.1: Sunday Body Blend Hash'),       (upgrade_hash, {'to': '2a306b59'})],
    'ca09a4f1': [('info', 'v3.0 -> v3.1: Sunday Hair Position Hash'),    (upgrade_hash, {'to': 'd3bcb943'})],
    'b03f76bb': [('info', 'v3.0 -> v3.1: Sunday Book Position Hash'),    (upgrade_hash, {'to': 'a98a6b09'})],
    'f74c7344': [('info', 'v3.0 -> v3.1: Sunday Hair Blend Hash'),       (upgrade_hash, {'to': '18bd0d10'})],
    '0fc6e4fe': [('info', 'v3.0 -> v3.1: Sunday Face Position Hash'),    (upgrade_hash, {'to': '1673f94c'})],

    'a147107a': [('info', 'v3.1 -> v3.2: Sunday Hair Draw Hash'),        (upgrade_hash, {'to': 'aed42577'})],
    '86890d04': [('info', 'v3.1 -> v3.2: Sunday Head Draw Hash'),        (upgrade_hash, {'to': '891a3809'})],
    '1f30e676': [('info', 'v3.1 -> v3.2: Sunday Body Draw Hash'),        (upgrade_hash, {'to': '10a3d37b'})],


    # MARK: Sushang
    '59a0b558': [('info', 'v1.6 -> v2.0: Sushang Body Texcoord Hash'), (upgrade_hash, {'to': '23dc010c'})],
     'd765c517': [
        ('info', 'v1.6 -> v2.0: Sushang Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'SushangBody',
            'hash': '4b22391b',
            'trg_indices': ['0', '3531', '30774', '44049'],
            'src_indices': ['0',   '-1', '30774',    '-1'],
        })
    ],

    '95e614e5': [('info', 'v2.2 -> v2.3: Sushang Hair Diffuse Hash'),   (upgrade_hash, {'to': '636dc89e'})],
    '728565ee': [('info', 'v2.2 -> v2.3: Sushang Hair LightMap Hash'),  (upgrade_hash, {'to': '0e484aa5'})],

    '9d7ea82f': [('info', 'v2.2 -> v2.3: Sushang Head Diffuse Hash'),   (upgrade_hash, {'to': '1897cfee'})],
 
    'e4ccda3f': [('info', 'v2.2 -> v2.3: Sushang BodyA Diffuse Hash'),  (upgrade_hash, {'to': '98507746'})],
    '653b35cd': [('info', 'v2.2 -> v2.3: Sushang BodyA LightMap Hash'), (upgrade_hash, {'to': '3134e1e4'})],
    '4724e9c1': [('info', 'v2.2 -> v2.3: Sushang BodyC Diffuse Hash'),  (upgrade_hash, {'to': '79354f80'})],
    'd2e9d4dc': [('info', 'v2.2 -> v2.3: Sushang BodyC LightMap Hash'), (upgrade_hash, {'to': '1e9893b3'})],

    'f30f2d7f': [('info', 'v3.0 -> v3.1: Sushang Body Blend Hash'),         (upgrade_hash, {'to': '1cfe532b'})],
    '38293906': [('info', 'v3.0 -> v3.1: Sushang Hair Blend Hash'),         (upgrade_hash, {'to': 'd7d84752'})],
    'c87cf153': [('info', 'v3.0 -> v3.1: Sushang Hair Position Hash'),      (upgrade_hash, {'to': 'd1c9ece1'})],
    'd0568383': [('info', 'v3.0 -> v3.1: Sushang Head Blend Hash'),         (upgrade_hash, {'to': '3fa7fdd7'})],
    'ad69421b': [('info', 'v3.0 -> v3.1: Sushang Head Position Hash'),      (upgrade_hash, {'to': 'b4dc5fa9'})],
 
    '86eff764': [('info', 'v3.1 -> v3.2: Sushang Hair Draw Hash'),          (upgrade_hash, {'to': '897cc269'})],
    'eccf68bc': [('info', 'v3.1 -> v3.2: Sushang Head Draw Hash'),          (upgrade_hash, {'to': 'e35c5db1'})],
    '7f1e869c': [('info', 'v3.1 -> v3.2: Sushang Body Draw Hash'),          (upgrade_hash, {'to': '708db391'})],
    'cce93afc': [('info', 'v3.1 -> v3.2: Sushang Body Position Hash'),      (upgrade_hash, {'to': 'df4128f2'})],


    # MARK: The Herta
    '2279c5a6': [('info', 'v3.1 -> v3.2: The Herta Hair Draw Hash'),        (upgrade_hash, {'to': '2deaf0ab'})],
    'f9199c35': [('info', 'v3.1 -> v3.2: The Herta Head Draw Hash'),        (upgrade_hash, {'to': 'f68aa938'})],
    '1a199989': [('info', 'v3.1 -> v3.2: The Herta Body Draw Hash'),        (upgrade_hash, {'to': '158aac84'})],


    # MARK: Tingyun
    '1870a9cb': [('info', 'v1.4 -> v1.6: Tingyun BodyA LightMap Hash'), (upgrade_hash, {'to': '547497fb'})],
    '6e205d4e': [('info', 'v1.4 -> v1.6: Tingyun BodyB LightMap Hash'), (upgrade_hash, {'to': '73fad5f5'})],
    '9bf82eaa': [('info', 'v1.6 -> v2.0: Tingyun Body Texcoord Hash'),  (upgrade_hash, {'to': 'f83ec867'})],
     '351d8570': [
        ('info', 'v1.6 -> v2.0: Tingyun Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'TingyunBody',
            'hash': 'da59600b',
            'trg_indices': ['0', '10905', '53229', '54588', '59736'],
            'src_indices': ['0', '16053',    '-1',    '-1', '59736'],
        })
    ],

    '02a81179': [('info', 'v2.2 -> v2.3: Tingyun Hair Diffuse Hash'),   (upgrade_hash, {'to': 'c4be701a'})],
    'fa9143b8': [('info', 'v2.2 -> v2.3: Tingyun Hair LightMap Hash'),  (upgrade_hash, {'to': 'f699e83b'})],

    'bdfd3d71': [('info', 'v2.2 -> v2.3: Tingyun Head Diffuse Hash'),   (upgrade_hash, {'to': 'fb95c111'})],
 
    '77ddf35c': [('info', 'v2.2 -> v2.3: Tingyun BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'ed473e73'})],
    '547497fb': [('info', 'v2.2 -> v2.3: Tingyun BodyA LightMap Hash'), (upgrade_hash, {'to': 'e0fa7d8e'})],
    '1cbf0500': [('info', 'v2.2 -> v2.3: Tingyun BodyC Diffuse Hash'),  (upgrade_hash, {'to': 'bf7501ab'})],
    '73fad5f5': [('info', 'v2.2 -> v2.3: Tingyun BodyC LightMap Hash'), (upgrade_hash, {'to': 'fa54a59b'})],

    '069ee84c': [('info', 'v3.0 -> v3.1: Tingyun Body Blend Hash'),         (upgrade_hash, {'to': 'e96f9618'})],
    '44cee658': [('info', 'v3.0 -> v3.1: Tingyun Hair Blend Hash'),         (upgrade_hash, {'to': 'ab3f980c'})],
    'be07554f': [('info', 'v3.0 -> v3.1: Tingyun Hair Position Hash'),      (upgrade_hash, {'to': 'a7b248fd'})],
    'ff6fdae4': [('info', 'v3.0 -> v3.1: Tingyun Head Blend Hash'),         (upgrade_hash, {'to': '109ea4b0'})],
    'f9fa713f': [('info', 'v3.0 -> v3.1: Tingyun Head Position Hash'),      (upgrade_hash, {'to': 'e04f6c8d'})],

    '0d41cc95': [('info', 'v3.1 -> v3.2: Tingyun Hair Draw Hash'), (upgrade_hash, {'to': '02d2f998'})],
    '7d4f8bae': [('info', 'v3.1 -> v3.2: Tingyun Head Draw Hash'), (upgrade_hash, {'to': '72dcbea3'})],
    '6a4333dc': [('info', 'v3.1 -> v3.2: Tingyun Body Draw Hash'), (upgrade_hash, {'to': '65d006d1'})],
    'd9b48fbc': [('info', 'v3.1 -> v3.2: Tingyun Body Position Hash'), (upgrade_hash, {'to': 'b061758a'})],


    # MARK: Topaz
    '6f354853': [('info', 'v1.6 -> v2.0: Topaz Body Position Extra Hash'), (upgrade_hash, {'to': '71d39d95'})],
    '24212bf6': [('info', 'v1.6 -> v2.0: Topaz Body Texcoord Hash'),        (upgrade_hash, {'to': '436288c9'})],
     'ae42518c': [
        ('info', 'v1.6 -> v2.0: Topaz Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'TopazBody',
            'hash': 'b52297bf',
            'trg_indices': ['0', '18327', '21645', '45078'],
            'src_indices': ['0',    '-1', '21645',    '-1'],
        })
    ],
    # '2eab6d2d': [
    #     ('info', 'v2.1: Topaz Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '71d39d95'}),
    #     (check_hash_not_in_ini, {'hash': '6f354853'}),
    #     (multiply_section, {
    #         'titles': ['TopazBodyPosition', 'TopazBodyPosition_Extra'],
    #         'hashes': ['2eab6d2d', '71d39d95']
    #     })
    # ],
    '71d39d95': [('info', 'v2.2 -> v3.1: Topaz Body Position Extra Hash'),              (comment_sections, {})],
    '0dd40a0b': [('info', 'v2.2 -> v2.3: Topaz Hair Draw Hash'),      (upgrade_hash, {'to': 'cc870789'})],
    '7fac28de': [('info', 'v2.2 -> v2.3: Topaz Hair Position Hash'),  (upgrade_hash, {'to': 'a413be23'})],
    'b8ec605d': [('info', 'v2.2 -> v2.3: Topaz Hair Texcoord Hash'),  (upgrade_hash, {'to': 'b131f866'})],
    'f1a4401b': [('info', 'v2.2 -> v2.3: Topaz Hair IB Hash'),        (upgrade_hash, {'to': '32ef4b75'})],
    '943bf9d3': [('info', 'v2.2 -> v2.3: Topaz Hair Diffuse Hash'),   (upgrade_hash, {'to': '78059f75'})],
    '67df29ec': [('info', 'v2.2 -> v2.3: Topaz Hair LightMap Hash'),  (upgrade_hash, {'to': '39fd4ba7'})],
 
    'fea9fff4': [('info', 'v2.2 -> v2.3: Topaz Head Diffuse Hash'),   (upgrade_hash, {'to': 'fc521095'})],
 
     '436288c9': [('info', 'v2.2 -> v2.3: Topaz Body Texcoord Hash'),  (upgrade_hash, {'to': '4be08333'})],
     '96f5e350': [('info', 'v2.2 -> v2.3: Topaz BodyA Diffuse Hash'),  (upgrade_hash, {'to': '3dfd62b8'})],
    '6a0ee180': [('info', 'v2.2 -> v2.3: Topaz BodyA LightMap Hash'), (upgrade_hash, {'to': 'b8c954ef'})],
     '68b887db': [('info', 'v2.2 -> v2.3: Topaz BodyC Diffuse Hash'),  (upgrade_hash, {'to': '13be2437'})],
    '924edd3e': [('info', 'v2.2 -> v2.3: Topaz BodyC LightMap Hash'), (upgrade_hash, {'to': '786f6565'})],

    '55ef95d4': [('info', 'v3.0 -> v3.1: Topaz Body Blend Hash'),           (upgrade_hash, {'to': 'ba1eeb80'})],
    'cbd71321': [('info', 'v3.0 -> v3.1: Topaz Hair Blend Hash'),           (upgrade_hash, {'to': '24266d75'})],
    'a413be23': [('info', 'v2.3 -> v3.1: Topaz Hair Position Hash'),        (upgrade_hash, {'to': 'bda6a391'})],
    '78012798': [('info', 'v3.0 -> v3.1: Topaz Head Blend Hash'),           (upgrade_hash, {'to': '97f059cc'})],
    'e0b28d05': [('info', 'v3.0 -> v3.1: Topaz Head Position Hash'),        (upgrade_hash, {'to': 'f90790b7'})],
    '2eab6d2d': [('info', 'v3.1 -> v3.2: Topaz Body Position Hash'),         (upgrade_hash, {'to': '68668027'})],

    'cc870789': [('info', 'v2.3 -> v3.2: Topaz Hair Draw Hash'), (upgrade_hash, {'to': 'c3143284'})],
    '7457372c': [('info', 'v3.1 -> v3.2: Topaz Head Draw Hash'), (upgrade_hash, {'to': '7bc40221'})],
    '9d5cd14d': [('info', 'v3.1 -> v3.2: Topaz Body Draw Hash'), (upgrade_hash, {'to': '92cfe440'})],

    # MARK: Tribbie
    'de857b6f': [('info', 'v3.1 -> v3.2: Tribbie Hair Draw Hash'), (upgrade_hash, {'to': 'd1164e62'})],
    '36f9ddcb': [('info', 'v3.1 -> v3.2: Tribbie Head Draw Hash'), (upgrade_hash, {'to': '396ae8c6'})],
    '90844efd': [('info', 'v3.1 -> v3.2: Tribbie Body Draw Hash'), (upgrade_hash, {'to': '9f177bf0'})],
    'cc339c92': [('info', 'v3.1 -> v3.2: Trianne Head Draw Hash'), (upgrade_hash, {'to': 'c3a0a99f'})],
    'f29b3fab': [('info', 'v3.1 -> v3.2: Trinnon Head Draw Hash'), (upgrade_hash, {'to': 'fd080aa6'})],

    # MARK: Welt
    'cb4839db': [('info', 'v1.6 -> v2.0: Welt HairA LightMap Hash'), (upgrade_hash, {'to': '2258cc03'})],
    'fef626ce': [('info', 'v1.6 -> v2.0: Welt Body Position Hash'),  (upgrade_hash, {'to': '31c9604b'})],
    '723e0365': [
        ('info', 'v1.6 -> v2.0: Welt Body Texcoord Hash + Buffer add Texcoord1'),
        (modify_buffer, {
            'operation': 'add_texcoord1',
            'payload': {
                'format': '<BBBBee',
                'value': 'copy'
            }
        }),
        (upgrade_hash, {'to': '0ab3a636'})
    ],
     '374ac8a9': [
        ('info', 'v1.6 -> v2.0: Welt Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'WeltBody',
            'hash': 'd15987b1',
            'trg_indices': ['0', '30588', '46620'],
            'src_indices': ['0', '30588',    '-1'],
        })
    ],
    '1dea5b29': [('info', 'v2.0 -> v2.1: Welt Body Draw Hash'),       (upgrade_hash, {'to': 'ce076065'})],
    '31c9604b': [('info', 'v2.0 -> v2.1: Welt Body Position Hash'),  (upgrade_hash, {'to': '7df0dc05'})],
    '0ab3a636': [
        ('info', 'v2.0 -> v2.1: Welt Body Texcoord Hash Upgrade + Buffer pad'),
        (modify_buffer, {
            'operation': 'convert_format',
            'payload': {
                'format_conversion': ('<BBBBeeee', '<BBBBffff')
            }
        }),
        (upgrade_hash, {'to': '381a994e'})
    ],
    'd15987b1': [
        ('info', 'v2.0 -> v2.1: Welt Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'WeltBody',
            'hash': 'e9f71838',
            'trg_indices': ['0', '30588', '48087'],
            'src_indices': ['0', '30588', '46620'],
        })
    ],
    # '7df0dc05': [
    #     ('info', 'v2.1: Welt Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '5c4ca7f9'}),
    #     (multiply_section, {
    #         'titles': ['WeltBodyPosition', 'WeltBodyPosition_Extra'],
    #         'hashes': ['7df0dc05', '5c4ca7f9']
    #     })
    # ],
    '5c4ca7f9': [('info', 'v2.2 -> v3.1: Welt Body Position Extra Hash'),                  (comment_sections, {})],
    '78ca8241': [('info', 'v2.2 -> v2.3: Welt Hair Texcoord Hash'),        (upgrade_hash, {'to': '8d2fdd4b'})],
    '6a8dcc20': [('info', 'v2.2 -> v2.3: Welt Hair Diffuse Hash'),         (upgrade_hash, {'to': '9dd3ae5d'})],
    '2258cc03': [('info', 'v2.2 -> v2.3: Welt Hair LightMap Hash'),        (upgrade_hash, {'to': 'c6f7c43c'})],
 
    '58db3a4d': [('info', 'v2.2 -> v2.3: Welt Head Diffuse Hash'),         (upgrade_hash, {'to': 'b4d6d5df'})],
 
    'c89a97aa': [('info', 'v2.2 -> v2.3: Welt BodyA Diffuse Hash'),        (upgrade_hash, {'to': 'd318fc3e'})],
    'b63f51eb': [('info', 'v2.2 -> v2.3: Welt BodyA LightMap Hash'),       (upgrade_hash, {'to': '8cd33bbc'})],
     '5c9711f2': [('info', 'v2.2 -> v2.3: Welt BodyB Diffuse Hash'),        (upgrade_hash, {'to': '948e03bd'})],
    '3dbb2ae6': [('info', 'v2.2 -> v2.3: Welt BodyB LightMap Hash'),       (upgrade_hash, {'to': 'd77a2807'})],

    'aa4229a3': [('info', 'v3.0 -> v3.1: Welt Body Blend Hash'),            (upgrade_hash, {'to': '45b357f7'})],
    '34e99315': [('info', 'v3.0 -> v3.1: Welt Hair Blend Hash'),            (upgrade_hash, {'to': 'db18ed41'})],
    'c13c202e': [('info', 'v3.0 -> v3.1: Welt Hair Position Hash'),         (upgrade_hash, {'to': 'd8893d9c'})],
    '0aafd819': [('info', 'v3.0 -> v3.1: Welt Head Blend Hash'),            (upgrade_hash, {'to': 'e55ea64d'})],
    '8cad004f': [('info', 'v3.0 -> v3.1: Welt Head Position Hash'),         (upgrade_hash, {'to': '95181dfd'})],
    '7df0dc05': [('info', 'v3.1 -> v3.2: Welt Body Position Hash'),         (upgrade_hash, {'to': '45f9ba4b'})],

    'ce076065': [('info', 'v2.1 -> v3.2: Welt Body Draw Hash'), (upgrade_hash, {'to': 'c1945568'})],
    '25f28b95': [('info', 'v3.1 -> v3.2: Welt Hair Draw Hash'), (upgrade_hash, {'to': '2a61be98'})],
    'a6cab8a7': [('info', 'v3.1 -> v3.2: Welt Head Draw Hash'), (upgrade_hash, {'to': 'a9598daa'})],


    # MARK: Xueyi
    '77b78d33': [('info', 'v1.6 -> v2.0: Xueyi Body Position Extra Hash'), (upgrade_hash, {'to': '8936451b'})],
    '2c096545': [('info', 'v1.6 -> v2.0: Xueyi Body Texcoord Hash'),        (upgrade_hash, {'to': '03ff3d10'})],
    '9f040cd3': [
        ('info', 'v1.6 -> v2.0: Xueyi Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'XueyiBody',
            'hash': 'af2983dd',
            'trg_indices': ['0', '31986', '39129', '54279'],
            'src_indices': ['0',    '-1', '39129',    '-1'],
        })
    ],
    # '206b86f0': [
    #     ('info', 'v2.1: Xueyi Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '8936451b'}),
    #     (check_hash_not_in_ini, {'hash': '77b78d33'}),
    #     (multiply_section, {
    #         'titles': ['XueyiBodyPosition', 'XueyiBodyPosition_Extra'],
    #         'hashes': ['206b86f0', '8936451b']
    #     })
    # ],

    '952c20b8': [('info', 'v2.2 -> v2.3: Xueyi Hair Diffuse Hash'),   (upgrade_hash, {'to': '360ebd7f'})],
    'dbb181aa': [('info', 'v2.2 -> v2.3: Xueyi Hair LightMap Hash'),  (upgrade_hash, {'to': '4d5812b5'})],

    '3c0e2e71': [('info', 'v2.2 -> v2.3: Xueyi Head Diffuse Hash'),   (upgrade_hash, {'to': 'f927a99b'})],

    'ad22f871': [('info', 'v2.2 -> v2.3: Xueyi BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'e2284397'})],
    '2e328427': [('info', 'v2.2 -> v2.3: Xueyi BodyA LightMap Hash'), (upgrade_hash, {'to': 'a694c7ef'})],
    '957cf6d9': [('info', 'v2.2 -> v2.3: Xueyi BodyC Diffuse Hash'),  (upgrade_hash, {'to': '89724253'})],
    '76f171f5': [('info', 'v2.2 -> v2.3: Xueyi BodyC LightMap Hash'), (upgrade_hash, {'to': '91c7faef'})],

    '8936451b': [('info', 'v2.0 -> v3.1: Xueyi Body Position Extra Hash'),              (comment_sections, {})],
    '9127a7b3': [('info', 'v3.0 -> v3.1: Xueyi Body Blend Hash'),           (upgrade_hash, {'to': '7ed6d9e7'})],
    'e0f8ce61': [('info', 'v3.0 -> v3.1: Xueyi Hair Blend Hash'),           (upgrade_hash, {'to': '0f09b035'})],
    '5ad7108a': [('info', 'v3.0 -> v3.1: Xueyi Hair Position Hash'),        (upgrade_hash, {'to': '43620d38'})],
    '4aab3325': [('info', 'v3.0 -> v3.1: Xueyi Head Blend Hash'),           (upgrade_hash, {'to': 'a55a4d71'})],
    'acec2843': [('info', 'v3.0 -> v3.1: Xueyi Head Position Hash'),        (upgrade_hash, {'to': 'b55935f1'})],
    '206b86f0': [('info', 'v3.1 -> v3.2: Xueyi Body Position Hash'),         (upgrade_hash, {'to': '908358a9'})],

    '4a753694': [('info', 'v3.1 -> v3.2: Xueyi Hair Draw Hash'), (upgrade_hash, {'to': '45e60399'})],
    '2e4a1f92': [('info', 'v3.1 -> v3.2: Xueyi Head Draw Hash'), (upgrade_hash, {'to': '21d92a9f'})],
    '939c3a90': [('info', 'v3.1 -> v3.2: Xueyi Body Draw Hash'), (upgrade_hash, {'to': '9c0f0f9d'})],


    # MARK: Yanqing
    'ef7a4f40': [('info', 'v1.6 -> v2.0: Yanqing Body Position Extra Hash'), (upgrade_hash, {'to': 'a09059a0'})],
    '6fc50cb8': [('info', 'v1.6 -> v2.0: Yanqing Texcoord Hash'),             (upgrade_hash, {'to': '9801327a'})],
    'a3fe2b8f': [('info', 'v1.6 -> v2.0: Yanqing BodyA Diffuse Hash'),          (upgrade_hash, {'to': '4e8f9778'})],
    'e7e004ca': [('info', 'v1.6 -> v2.0: Yanqing BodyA LightMap Hash'),      (upgrade_hash, {'to': '035f0719'})],
    'c20cd648': [
        ('info', 'v1.6 -> v2.0: Yanqing Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'YanqingBody',
            'hash': 'd03803e6',
            'trg_indices': ['0', '55983'],
            'src_indices': ['0',    '-1'],
        })
    ],
    # '5c21b25d': [
    #     ('info', 'v2.1: Yanqing Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': 'a09059a0'}),
    #     (check_hash_not_in_ini, {'hash': 'ef7a4f40'}),
    #     (multiply_section, {
    #         'titles': ['YanqingBodyPosition', 'YanqingBodyPosition_Extra'],
    #         'hashes': ['5c21b25d', 'a09059a0']
    #     })
    # ],
    
    'a09059a0': [('info', 'v2.2 -> v3.1: Yanqing Body Position Extra Hash'),              (comment_sections, {})],
    'ea81180d': [('info', 'v2.2 -> v2.3: Yanqing Hair Texcoord Hash'),  (upgrade_hash, {'to': 'e5457b98'})],
    '14629990': [('info', 'v2.2 -> v2.3: Yanqing Hair Diffuse Hash'),   (upgrade_hash, {'to': '541ba63d'})],
    '0519a715': [('info', 'v2.2 -> v2.3: Yanqing Hair LightMap Hash'),  (upgrade_hash, {'to': '9639c2cb'})],

    'af6f0aa8': [('info', 'v2.2 -> v2.3: Yanqing Head Diffuse Hash'),   (upgrade_hash, {'to': '80763bb9'})],

    '4e8f9778': [('info', 'v2.2 -> v2.3: Yanqing BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'a41345d3'})],
    '035f0719': [('info', 'v2.2 -> v2.3: Yanqing BodyA LightMap Hash'), (upgrade_hash, {'to': '2db9f1d6'})],

    '5b021ee9': [('info', 'v2.3 -> v2.4: Yanqing Hair Draw Hash'),      (upgrade_hash, {'to': '1534d13e'})],
    'e5457b98': [('info', 'v2.3 -> v2.4: Yanqing Hair Texcoord Hash'),  (upgrade_hash, {'to': '3ef427fd'})],
    'e0d7d970': [('info', 'v2.3 -> v2.4: Yanqing Hair Position Hash'),  (upgrade_hash, {'to': 'a2ee2b45'})],

    '994d55ab': [('info', 'v2.3 -> v2.4: Yanqing Head Position Hash'),  (upgrade_hash, {'to': '5bc1537b'})],
    'ed7ceec2': [('info', 'v2.3 -> v2.4: Yanqing Head Draw Hash'),      (upgrade_hash, {'to': '04782d92'})],
    '738ba58f': [('info', 'v2.3 -> v2.4: Yanqing Head Texcoord Hash'),  (upgrade_hash, {'to': '6d99c7e0'})],
    '6ae41f8f': [('info', 'v2.3 -> v2.4: Yanqing Head IB Hash'),        (upgrade_hash, {'to': '9e0449af'})],

    'a2ee2b45': [('info', 'v2.4 -> v3.1: Yanqing Hair Position Hash'),      (upgrade_hash, {'to': 'bb5b36f7'})],
    '5bc1537b': [('info', 'v2.4 -> v3.1: Yanqing Head Position Hash'),      (upgrade_hash, {'to': '42744ec9'})],
    '40828c6c': [('info', 'v3.0 -> v3.1: Yanqing Body Blend Hash'),         (upgrade_hash, {'to': 'af73f238'})],
    '628a3954': [('info', 'v3.0 -> v3.1: Yanqing Hair Blend Hash'),         (upgrade_hash, {'to': '8d7b4700'})],
    '34eb9f8c': [('info', 'v3.0 -> v3.1: Yanqing Head Blend Hash'),         (upgrade_hash, {'to': 'db1ae1d8'})],
    '5c21b25d': [('info', 'v3.1 -> v3.2: Yanqing Body Position Hash'),         (upgrade_hash, {'to': 'b9254412'})],

    '1534d13e': [('info', 'v2.4 -> v3.2: Yanqing Hair Draw Hash'), (upgrade_hash, {'to': '1aa7e433'})],
    '04782d92': [('info', 'v2.4 -> v3.2: Yanqing Head Draw Hash'), (upgrade_hash, {'to': '0beb189f'})],
    'efd60e3d': [('info', 'v3.1 -> v3.2: Yanqing Body Draw Hash'), (upgrade_hash, {'to': 'e0453b30'})],


    # MARK: Yukong
    '896a066e': [('info', 'v1.4 -> v1.6: Yukong BodyA LightMap Hash'),  (upgrade_hash, {'to': '052766cf'})],
    '1d185915': [('info', 'v1.6 -> v2.0: Yukong Body Texcoord Hash'),   (upgrade_hash, {'to': 'e5e376b8'})],
    '1df9540b': [
        ('info', 'v1.6 -> v2.0: Yukong Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'YukongBody',
            'hash': '28bbd4ae',
            'trg_indices': ['0', '55551', '60498'],
            'src_indices': ['0',    '-1', '60498'],
        })
    ],

    '08d184a7': [('info', 'v2.2 -> v2.3: Yukong Hair Diffuse Hash'),   (upgrade_hash, {'to': '6fa27e76'})],
    '11960703': [('info', 'v2.2 -> v2.3: Yukong Hair LightMap Hash'),  (upgrade_hash, {'to': '40baf876'})],

    'b111f58e': [('info', 'v2.2 -> v2.3: Yukong Head Diffuse Hash'),   (upgrade_hash, {'to': 'bbaa4fba'})],

    'b6457bdb': [('info', 'v2.2 -> v2.3: Yukong BodyA Diffuse Hash'),  (upgrade_hash, {'to': '9e0f6958'})],
    '052766cf': [('info', 'v2.2 -> v2.3: Yukong BodyA LightMap Hash'), (upgrade_hash, {'to': '220a5367'})],

    '0d24ec87': [('info', 'v3.0 -> v3.1: Yukong Body Blend Hash'),          (upgrade_hash, {'to': 'e2d592d3'})],
    '3219c61a': [('info', 'v3.0 -> v3.1: Yukong Hair Blend Hash'),          (upgrade_hash, {'to': 'dde8b84e'})],
    '96478ccb': [('info', 'v3.0 -> v3.1: Yukong Hair Position Hash'),       (upgrade_hash, {'to': '8ff29179'})],
    'e539f4ce': [('info', 'v3.0 -> v3.1: Yukong Head Blend Hash'),          (upgrade_hash, {'to': '0ac88a9a'})],
    '1c4be428': [('info', 'v3.0 -> v3.1: Yukong Head Position Hash'),       (upgrade_hash, {'to': '05fef99a'})],

    '0ea98fa3': [('info', 'v3.1 -> v3.2: Yukong Hair Draw Hash'), (upgrade_hash, {'to': '013abaae'})],
    'd8a2d73d': [('info', 'v3.1 -> v3.2: Yukong Head Draw Hash'), (upgrade_hash, {'to': 'd731e230'})],
    'eeb20473': [('info', 'v3.1 -> v3.2: Yukong Body Draw Hash'), (upgrade_hash, {'to': 'e121317e'})],
    '5d45b813': [('info', 'v3.1 -> v3.2: Yukong Body Position Hash'), (upgrade_hash, {'to': '59dca58e'})],


    # MARK: Yunli
    # 'afb1f48c': [
    #     ('info', 'v2.4: Yunli Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '8d5695b1'}),
    #     (multiply_section, {
    #         'titles': ['YunliBodyPosition', 'YunliBodyPosition_Extra'],
    #         'hashes': ['afb1f48c', '8d5695b1']
    #     })
    # ],

    '8d5695b1': [('info', 'v2.2 -> v3.1: Yunli Body Position Extra Hash'),              (comment_sections, {})],
    '2ab1d1bd': [('info', 'v3.0 -> v3.1: Yunli Body Blend Hash'),           (upgrade_hash, {'to': 'c540afe9'})],
    '22a4c645': [('info', 'v3.0 -> v3.1: Yunli Hair Blend Hash'),           (upgrade_hash, {'to': 'cd55b811'})],
    '6c60e749': [('info', 'v3.0 -> v3.1: Yunli Hair Position Hash'),        (upgrade_hash, {'to': '75d5fafb'})],
    'be092ccf': [('info', 'v3.0 -> v3.1: Yunli Head Blend Hash'),           (upgrade_hash, {'to': '51f8529b'})],
    '44a7e483': [('info', 'v3.0 -> v3.1: Yunli Head Position Hash'),        (upgrade_hash, {'to': '5d12f931'})],
    'afb1f48c': [('info', 'v3.1 -> v3.2: Yunli Body Position Hash'),         (upgrade_hash, {'to': '94e38803'})],

    '092a10a3': [('info', 'v3.1 -> v3.2: Yunli Hair Draw Hash'), (upgrade_hash, {'to': '06b925ae'})],
    '625e8b72': [('info', 'v3.1 -> v3.2: Yunli Head Draw Hash'), (upgrade_hash, {'to': '6dcdbe7f'})],
    '1c4648ec': [('info', 'v3.1 -> v3.2: Yunli Body Draw Hash'), (upgrade_hash, {'to': '13d57de1'})],


    # MARK: Caelus
    '0bbb3448': [('info', 'v1.5 -> v1.6: Caelus Body Texcoord Hash [Destruction]'),  (upgrade_hash, {'to': '97c34928'})],
    '97c34928': [('info', 'v2.7 -> v3.0: Caelus Body Texcoord Hash [Shared]'),       (upgrade_hash, {'to': '15be9519'})],
    '44da446d': [('info', 'v1.6: Caelus Body Texcoord Hash [Preservation]'),         (upgrade_else_comment, {'missing': ['0bbb3448', '97c34928', '15be9519'], 'hash': '0bbb3448'})],
    '77933d6e': [('info', 'v2.2: Caelus Body Texcoord Hash [Harmony]'),              (upgrade_else_comment, {'missing': ['0bbb3448', '97c34928', '15be9519'], 'hash': '0bbb3448'})],

    'f00b031a': [('info', 'v2.7 -> v3.0: Caelus Body Blend Hash'),                   (upgrade_hash, {'to': '2baba62a'})],
    '9e7ca423': [('info', 'v1.6: Caelus Body Blend Hash [Preservation]'),            (upgrade_else_comment, {'missing': ['f00b031a', '2baba62a'], 'hash': 'f00b031a'})],
    '560052ad': [('info', 'v2.2: Caelus Body Blend Hash [Harmony]'),                 (upgrade_else_comment, {'missing': ['f00b031a', '2baba62a'], 'hash': 'f00b031a'})],

    '91022b8f': [('info', 'v2.7 -> v3.0: Caelus Body Draw Hash'),                    (upgrade_hash, {'to': '33342be6'})],
    '22f597ef': [('info', 'v2.7 -> v3.0: Caelus Body Position Hash'),                (upgrade_hash, {'to': '80c39786'})],
    
    '80c39786': [('info', 'v3.0 -> v3.1: Caelus Body Position Hash'),                (upgrade_hash, {'to': 'aa2648d4'})],
    # '80c39786': [
    #     ('info', 'v3.0: Caelus Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': 'b3935566'}),
    #     (multiply_section, {
    #         'titles': ['CaelusBodyPosition', 'CaelusBodyPosition_Extra'],
    #         'hashes': ['80c39786', 'b3935566']
    #     })
    # ],
    'b3935566': [('info', 'v3.0 -> v3.1: Caelus Body Position Hash'),                (comment_sections, {})],


    'fd65164c': [
        ('info', 'v1.5 -> v1.6: Caelus Body IB Hash [Destruction]'),
        (multiply_indexed_section, {
            'title': 'CaelusBody',
            'hash': 'e3ffef9a',
            'trg_indices': [ '0', '38178'],
            'src_indices': ['-1', '0'],
        })
    ],
    'e3ffef9a': [
        ('info', 'v2.7 -> v3.0: Caelus Body IB Hash'),
        (multiply_indexed_section, {
            'title': 'CaelusBody',
            'hash': '825f79f5',
            'trg_indices': ['0', '37659'],
            'src_indices': ['0', '38178'],
        })
    ],
    'a270e292': [
        ('info', 'v1.6: Caelus Body IB Hash [Preservation]'),
        (upgrade_else_comment_indexed, {
            'missing': ['fd65164c', 'e3ffef9a', '825f79f5'],
            'title': 'CaelusBody',
            'hash': '825f79f5',
            'trg_indices': ['0', '37659'],
            'src_indices': ['0', '37674'],
        })
    ],
    '89fcb592': [
        ('info', 'v2.2: Caelus Body IB Hash [Harmony]'),
        (upgrade_else_comment_indexed, {
            'missing': ['fd65164c', 'e3ffef9a', '825f79f5'],
            'title': 'CaelusBody',
            'hash': '825f79f5',
            'trg_indices': ['0', '37659'],
            'src_indices': ['0', '39330'],
        })
    ],


    '3fc38f8a': [('info', 'v2.2 -> v2.3: Caelus Hair Texcoord Hash'), (upgrade_hash, {'to': 'f4f5c11d'})],
    '7de7f0c0': [('info', 'v2.2 -> v2.3: Caelus Hair Diffuse Hash'),  (upgrade_hash, {'to': 'fa0975b2'})],
    'c17e8830': [('info', 'v2.2 -> v2.3: Caelus Hair LightMap Hash'), (upgrade_hash, {'to': 'd75c3881'})],

    'd667a346': [('info', 'v2.7 -> v3.0: Caelus Head Position Hash'),   (upgrade_hash, {'to': '87f2f3ce'})],
    '7409246c': [('info', 'v2.3: Caelus Head Position Hash [Harmony]'), (upgrade_else_comment, {'missing': ['d667a346', '87f2f3ce'], 'hash': '87f2f3ce'})],

    '5df1352e': [('info', 'v2.7 -> v3.0: Caelus Head Draw Hash'),     (upgrade_hash, {'to': '1c71430d'})],
    'abdc67e6': [('info', 'v2.7 -> v3.0: Caelus Head Blend Hash'),    (upgrade_hash, {'to': '3576ec0a'})],
    '9108c1f1': [('info', 'v2.7 -> v3.0: Caelus Head Texcoord Hash'), (upgrade_hash, {'to': '714d71d0'})],
    'c1004613': [
        ('info', 'v2.7 -> v3.0: Caelus Head IB Hash'),
        (multiply_indexed_section, {
            'title': 'CaelusHead',
            'hash': '70f89eb8',
            'trg_indices': ['0', '13734'],
            'src_indices': ['0', '13716'],
        })
    ],


    'b193e6d8': [('info', 'v2.2 -> v2.3: Caelus Head Diffuse Hash'),             (upgrade_hash, {'to': '21b96557'})],

    '28d09106': [('info', 'v2.2 -> v2.3: Caelus Body Diffuse Hash'),             (upgrade_hash, {'to': '3e8e34d5'})],
    '0fe66c92': [('info', 'v2.2 -> v2.3: Caelus Body LightMap Hash'),            (upgrade_hash, {'to': '6194fa1b'})],

    '2baba62a': [('info', 'v3.0 -> v3.1: Caelus Body Blend Hash'),               (upgrade_hash, {'to': 'c45ad87e'})],
    '87f2f3ce': [('info', 'v3.0 -> v3.1: Caelus Head Position Hash'),            (upgrade_hash, {'to': '9e47ee7c'})],
    '6786de68': [('info', 'v3.0 -> v3.1: CaelusDestruction Hair Blend Hash'),    (upgrade_hash, {'to': '8877a03c'})],
    '870564f1': [('info', 'v3.0 -> v3.1: CaelusDestruction Hair Position Hash'), (upgrade_hash, {'to': '9eb07943'})],

    '3437de1d': [('info', 'v3.1 -> v3.2: CaelusRemembrance Hair Draw Hash'),     (upgrade_hash, {'to': '3ba4eb10'})],
    '1c71430d': [('info', 'v3.1 -> v3.2: CaelusRemembrance Head Draw Hash'),     (upgrade_hash, {'to': '13e27600'})],
    '33342be6': [('info', 'v3.1 -> v3.2: CaelusRemembrance Body Draw Hash'),     (upgrade_hash, {'to': '3ca71eeb'})],


    # MARK: Stelle
    #     Skip adding extra sections for v1.6, v2.0, v2.1 Preservation hashes
    #     because those extra sections are not needed in v2.2
    #     Comment out the extra sections later
    '01df48a6': [('info', 'v1.5 -> v1.6: Body Texcoord Hash (Stelle)'), (upgrade_hash, {'to': 'a68ffeb1'})],
    'a68ffeb1': [
        ('info', 'v2.1 -> v2.2: Body Texcoord Hash (Destruction Stelle)'),
        (upgrade_hash, {'to': 'f00b6ded'})
    ],

    '85ad43b3': [
        ('info', 'v1.5 -> v1.6: Body IB Hash (Stelle)'),
        (multiply_indexed_section, {
            'title': 'StelleBody',
            'hash': '174a08d4',
            'trg_indices': [ '0', '32967'],
            'src_indices': ['-1',     '0'],
        })
    ],
    '174a08d4': [
        ('info', 'v2.1 -> v2.2: Body IB Hash (Destruction Stelle)'),
        (multiply_indexed_section, {
            'title': 'StelleBody',
            'hash': 'fba309df',
            'trg_indices': ['0', '32946'],
            'src_indices': ['0', '32967'],
        })
    ],

    '1a415a73': [('info', 'v2.1 -> v2.2: Stelle Hair Draw Hash'),      (upgrade_hash, {'to': '00d0c31d'})],
    '938b9c8f': [('info', 'v2.1 -> v2.2: Stelle Hair Position Hash'), (upgrade_hash, {'to': '8c0c078f'})],
    '8680469b': [('info', 'v2.1 -> v2.2: Stelle Hair Texcoord Hash'), (upgrade_hash, {'to': 'fe9eaef0'})],
    '2d9adf2d': [('info', 'v2.1 -> v2.2: Stelle Hair IB Hash'),       (upgrade_hash, {'to': '1d62eafb'})],

    'fdb54553': [('info', 'v2.2 -> v2.3: Stelle Hair Diffuse Hash'),  (upgrade_hash, {'to': 'a04fcf6f'})],
    'ef5586c1': [('info', 'v2.2 -> v2.3: Stelle Hair LightMap Hash'), (upgrade_hash, {'to': '02a9b085'})],

    '1c0a8ff8': [('info', 'v2.2 -> v2.3: Stelle Head Diffuse Hash'),  (upgrade_hash, {'to': '4e98df53'})],

    'a19a8d2c': [('info', 'v2.2 -> v2.3: Stelle Body Diffuse Hash'),  (upgrade_hash, {'to': '78d10c03'})],
    '5d15eefe': [('info', 'v2.2 -> v2.3: Stelle Body LightMap Hash'), (upgrade_hash, {'to': '69014337'})],

    # '6949f854': [
    #     ('info', 'v3.0: Stelle Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': 'e9e81b6c'}),
    #     (multiply_section, {
    #         'titles': ['StelleBodyPosition', 'StelleBodyPosition_Extra'],
    #         'hashes': ['6949f854', 'e9e81b6c']
    #     })
    # ],
    
    'e9e81b6c': [('info', 'v2.2 -> v3.1: Stelle Body Position Extra Hash'),              (comment_sections, {})],
    
    # Comment out the sections with hashes no longer used in v2.2
    '2dcd5dc0': [('info', 'v2.1: Comment Body Texcoord Hash (Preservation Stelle)'), (comment_sections, {})],
    'e0d86dc8': [('info', 'v2.1: Comment Body IB Hash (Preservation Stelle)'),         (comment_sections, {})],

    '8c0c078f': [('info', 'v2.2 -> v3.1: Stelle Hair Position Hash'),       (upgrade_hash, {'to': '95b91a3d'})],
    '5aadfa65': [('info', 'v3.0 -> v3.1: Stelle Body Blend Hash'),          (upgrade_hash, {'to': 'b55c8431'})],
    '46ed784a': [('info', 'v3.0 -> v3.1: Stelle Hair Blend Hash'),          (upgrade_hash, {'to': 'a91c061e'})],
    '45a18e05': [('info', 'v3.0 -> v3.1: Stelle Head Blend Hash'),          (upgrade_hash, {'to': 'aa50f051'})],
    '00658faa': [('info', 'v3.0 -> v3.1: Stelle Head Position Hash'),       (upgrade_hash, {'to': '19d09218'})],


    '00d0c31d': [('info', 'v2.2 -> v3.2: Stelle Hair Draw Hash'), (upgrade_hash, {'to': '0f43f610'})],
    '9368f26c': [('info', 'v3.1 -> v3.2: Stelle Head Draw Hash'), (upgrade_hash, {'to': '9cfbc761'})],
    'dabe4434': [('info', 'v3.1 -> v3.2: Stelle Body Draw Hash'), (upgrade_hash, {'to': 'd52d7139'})],
    '6949f854': [('info', 'v3.1 -> v3.2: Stelle Body Position Hash'), (upgrade_hash, {'to': 'f05d06de'})],


    

    # MARK: Other Entity Fixes





    # MARK: Svarog
    'ae587fb2': [('info', 'v2.2 -> v2.3: Svarog BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'ae37a552'})],
    'a3acad6f': [('info', 'v2.2 -> v2.3: Svarog BodyA LightMap Hash'), (upgrade_hash, {'to': 'd653a999'})],
    '10beb640': [('info', 'v2.2 -> v2.3: Svarog BodyA Diffuse Hash'),  (upgrade_hash, {'to': 'e3a7f3fd'})],
    '69840f72': [('info', 'v2.2 -> v2.3: Svarog BodyA LightMap Hash'), (upgrade_hash, {'to': '4090cc01'})],



    # MARK: Numby
    '85d1b3ce': [('info', 'v2.2 -> v2.3: Numby Body DiffuseChScreen Hash'),        (upgrade_hash, {'to': 'e22b4c5e'})],
    'dab1477d': [('info', 'v2.2 -> v2.3: Numby Body DiffuseOverworldCombat Hash'), (upgrade_hash, {'to': '6cad0819'})],
    'a313ad5f': [('info', 'v2.2 -> v2.3: Numby Body LightMapChScreen Hash'),       (upgrade_hash, {'to': '07471bf5'})],
    '807fb688': [('info', 'v2.2 -> v2.3: Numby Body LightMapOverworld Hash'),      (upgrade_hash, {'to': '02644fcc'})],
    'ef40ac05': [('info', 'v2.2 -> v2.3: Numby Body LightMapCombat Hash'),         (upgrade_hash, {'to': 'cd7acd1a'})],

    # '9afaa7d9': [
    #     ('info', 'v2.1: Numby Body Position: Apply Vertex Explosion Fix'),
    #     (check_hash_not_in_ini, {'hash': '394111ad'}),
    #     (multiply_section, {
    #         'titles': ['NumbyBodyPosition', 'NumbyBodyPosition_Extra'],
    #         'hashes': ['9afaa7d9', '394111ad']
    #     })
    # ],
    '394111ad': [('info', 'v2.2 -> v3.1: Numby Body Position Extra Hash'),              (comment_sections, {})],


    # MARK: Weapons


    '7ae27f17': [('info', 'v2.2 -> v2.3: Jingliu Sword Diffuse Hash'),  (upgrade_hash, {'to': 'b71e3abe'})],
    '6acc5dd1': [('info', 'v2.2 -> v2.3: Jingliu Sword LightMap Hash'), (upgrade_hash, {'to': '12fde9bd'})],


    '52e8727a': [('info', 'v2.2 -> v2.3: March7th Bow Diffuse Hash'),  (upgrade_hash, {'to': '91804076'})],
    'f47e4ed8': [('info', 'v2.2 -> v2.3: March7th Bow LightMap Hash'), (upgrade_hash, {'to': 'e91ab48f'})],


    'c69a4a5f': [('info', 'v2.2 -> v2.3: Trailblazer Bat Diffuse Hash'),     (upgrade_hash, {'to': 'cac102b9'})],
    'bc86078f': [('info', 'v2.2 -> v2.3: Trailblazer Bat Diffuse Ult Hash'), (upgrade_hash, {'to': '4a638b94'})],
    'c7969478': [('info', 'v2.2 -> v2.3: Trailblazer Bat LightMap Hash'),    (upgrade_hash, {'to': 'ff6df1ec'})],

    '0a27a48e': [('info', 'v2.2 -> v2.3: Trailblazer Spear Diffuse Hash'),   (upgrade_hash, {'to': '4cd9ab1d'})],
    '7ce10d72': [('info', 'v2.2 -> v2.3: Trailblazer Spear LightMap Hash'),  (upgrade_hash, {'to': 'bdae2ad0'})],

    '685495d0': [('info', 'v2.2 -> v2.3: Seele Scythe Diffuse Hash'),        (upgrade_hash, {'to': 'ce802067'})],
    '910e8419': [('info', 'v2.2 -> v2.3: Seele Scythe LightMap Hash'),       (upgrade_hash, {'to': 'cb875574'})],


    # MARK: Unknown meshes that were added to Sora's 3.0 -> 3.1 hash update fix
    '253b0ea5': [('info', 'v3.0 -> v3.1: SilvermaneSoldier Body Blend Hash'),(upgrade_hash, {'to': 'caca70f1'})],
    '9e4fb633': [('info', 'v3.0 -> v3.1: SilvermaneSoldier Body Position Hash'),(upgrade_hash, {'to': '87faab81'})],
    '41b400fe': [('info', 'v3.0 -> v3.1: Siobhan Body Blend Hash'),         (upgrade_hash, {'to': 'ae457eaa'})],
    'e7b4d744': [('info', 'v3.0 -> v3.1: Siobhan Body Position Hash'),      (upgrade_hash, {'to': 'fe01caf6'})],
    '0f0feeb5': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e0fe90e1'})],
    '7c81efa9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6534f21b'})],
    'f79bf55c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ee2ee8ee'})],
    '88964833': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '67673667'})],
    'de1818d4': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c7ad0566'})],
    'c3912b58': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c7ad0566'})],
    '8124d93b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6ed5a76f'})],
    # 'e2fb7ce0': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'fb4e6152'})], # bailu extra hash 3.0 to 3.2
    # '10fb3cab': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '094e2119'})], # blackswan extra hash 3.0 to 3.2
    '90a94c09': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '4d61fb3a'})],
    'aa594182': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '45a83fd6'})],
    'fb3eae6f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e28bb3dd'})],
    '6b52f38e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '776a0dad'})],
    '40c9c4e2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e2ce4067'})],
    'f1e7fb1f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e852e6ad'})],
    '081b6cb4': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e7ea12e0'})],
    # '85d02e23': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9c653391'})], # feixiao pos hash 3.0 to 3.2
    '99c3e07e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '8076fdcc'})],
    '9525638d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '8c907e3f'})],
    '7d17af56': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '64a2b2e4'})],
    '869bd4b2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9f2ec900'})],
    '9963bd2c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '80d6a09e'})],
    'e0a23cff': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f917214d'})],
    # '04d0f9a0': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'eb2187f4'})],
    '11a90c69': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '081c11db'})],
    '7fb40d9c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3c4256b0'})],
    '3fe3d055': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'd012ae01'})],

    '472e6131': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a8df1f65'})],
    'caf79f9b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '2506e1cf'})],
    'aa0733d3': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'b3b22e61'})],
    '403a12dd': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'afcb6c89'})],
    'c0a7cb23': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5eab2525'})],
    '84eb69d9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6b307cf7'})],
    '7243533d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9db22d69'})],
    'f795f7c5': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ee20ea77'})],
    '425deed9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '01abb5f5'})],
    # '7e4f7890': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '67fa6522'})], # RUAN MEIN POS hash 3.0 to 3.2
    'b1be2710': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a80b3aa2'})],
    '0385188d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '407343a1'})],

    '54d8694d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'bb291719'})],
    '79daebcd': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '606ff67f'})],
    '9be881fe': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7419ffaa'})],
    'cdc9515a': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '22382f0e'})],
    '1663ad11': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f992d345'})],
    'fe4495a6': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e7f18814'})],
    '7dd3bc06': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9222c252'})],
    'caf6b434': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '2507ca60'})],
    'dda35578': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c41648ca'})],
    'e9d817e8': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '062969bc'})],
    '8287eb6e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9b32f6dc'})],
    'f8152c40': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '17e45214'})],
    '5e7a6aad': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '47cf771f'})],
    'bda9c73f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5258b96b'})],
    'af18050f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'b6ad18bd'})],
    'abd8978e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '4429e9da'})],
    'c487e3ef': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'dd32fe5d'})],
    '7bd8bb12': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9429c546'})],
    '667bbd6f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7fcea0dd'})],
    'e553e2c7': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '0aa29c93'})],
    '2af3a2df': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'd039e386'})],
    'd95a13b5': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5b958520'})],
    '3a57ca1e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'b0f43db2'})],
    '05bd6e65': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '473e01f2'})],
    'f7836426': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7b955957'})],
    '38186b93': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3af9021d'})],
    '527c39d7': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f1751019'})],
    'f942391e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7da1cd27'})],
    '3d12735a': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '94b37144'})],
    'da48c709': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '44e14830'})],
    '6205432d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3af9021d'})],
    '27bf8ebf': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f1751019'})],
    '7abd2d8f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7da1cd27'})],
    'b10b2e91': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '94b37144'})],
    'a23ddb70': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '44e14830'})],
    '4054a3fe': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7549a8b8'})],
    '960e77ad': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '2f74813a'})],
    '2c263e6c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ed4c8417'})],
    '46f3ff5f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7f862c3d'})],
    '938a531f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7f862c3d'})],
    'b2206637': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '2c760e0b'})],
    'c71aa0e9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'deafbd5b'})],
    '0d459ac9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e2b4e49d'})],
    'e752099b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'fee71429'})],
    '3747e5ed': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'd8b69bb9'})],
    'cdd6cd01': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'd463d0b3'})],
    '4846e3fa': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a7b79dae'})],
    'b263bc44': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'abd6a1f6'})],
    '34e69a64': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'db17e430'})],
    'd2d88f62': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'cb6d92d0'})],
    'f1f30cf3': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '1e0272a7'})],
    '7a26f186': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6393ec34'})],
    'a55c5aaf': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '4aad24fb'})],
    'b1f10cd5': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a8441167'})],
    '6de96e6e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '8218103a'})],
    '8898dbb9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '912dc60b'})],
    '512b60d1': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'beda1e85'})],
    '3f55afb2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '26e0b200'})],
    '75bec472': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9a4fba26'})],
    '1f5654c4': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '06e34976'})],
    'f61e2627': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '19ef5873'})],
    '93b253e7': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '8a074e55'})],
    '157d3961': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'fa8c4735'})],
    'ef07afd2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f6b2b260'})],
    'b06e7593': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5f9f0bc7'})],
    '80429718': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '99f78aaa'})],
    '89743b50': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '66854504'})],
    '49f9d1e5': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '504ccc57'})],
    '9cce1165': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '733f6f31'})],
    'e94f5824': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f0fa4596'})],
    'a3fdf5fe': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e00baed2'})],
    '4f07ac05': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '56b2b1b7'})],
    'a46c436b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e79a1847'})],
    '759fa196': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6c2abc24'})],
    '845a071f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c7ac5c33'})],
    '07814a7e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '1e3457cc'})],
    'ef66faaa': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ac90a186'})],
    'cc00c3a7': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'd5b5de15'})],
    'a0f13cc1': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e30767ed'})],
    '2e051c5d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '37b001ef'})],
    '9a134c5c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'd9e51770'})],
    'f0880cff': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e93d114d'})],
    'b15f1f0a': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f2a94426'})],
    '28365225': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '31834f97'})],
    '4ccac05b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '0f3c9b77'})],
    'f9f9c6d6': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e04cdb64'})],
    '1641072e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '55b75c02'})],
    '0e471e54': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '17f203e6'})],
    '2fbe1332': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6c48481e'})],
    '484b5014': [('info', 'v3.0 -> v3.1: Garment Maker Body Position Hash'),  (upgrade_hash, {'to': '51fe4da6'})],
    '31d815ee': [('info', 'v3.0 -> v3.1: Garment Maker Body Blend Hash'),     (upgrade_hash, {'to': 'de296bba'})],
    'df444c4c': [('info', 'v3.0 -> v3.1: Garment Maker Sword Position Hash'), (upgrade_hash, {'to': 'c6f151fe'})],
    '13483937': [('info', 'v3.0 -> v3.1: Garment Maker Sword Blend Hash'),    (upgrade_hash, {'to': 'fcb94763'})],
    '4e8967f8': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '573c7a4a'})],
    '8f549559': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '60a5eb0d'})],
    '181dc042': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '01a8ddf0'})],
    '24a44dd9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'cb55338d'})],
    'e5328f4c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'fc8792fe'})],
    '6e1dccfd': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '81ecb2a9'})],
    '96f5d1cf': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '8f40cc7d'})],
    'a080f5ba': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '4f718bee'})],
    '6a5b23b0': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '73ee3e02'})],
    'f3147d2f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '1ce5037b'})],
    '796716a5': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '60d20b17'})],
    'c5334397': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '2ac23dc3'})],
    'ba600701': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a3d51ab3'})],
    '303e84b6': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'dfcffae2'})],
    'fb858acf': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e230977d'})],
    'd7a04dcf': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3851339b'})],
    '22b0ae41': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3b05b3f3'})],
    '9b16dd34': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '74e7a360'})],
    '84e7c2ad': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9d52df1f'})],
    'a186a3f3': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '4e77dda7'})],
    '3cc75b26': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '25724694'})],
    '41ffe904': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ae0e9750'})],
    '5b76a8e4': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '42c3b556'})],
    '78e0e741': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '97119915'})],
    'dff98b92': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c64c9620'})],
    'c7d28178': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '2823ff2c'})],
    '4ec4ff4a': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5771e2f8'})],
    '469555d4': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a9642b80'})],
    '839fb43d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9a2aa98f'})],
    '03f7cc0c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ec06b258'})],
    '3a2a38ec': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '239f255e'})],
    '0dc8b8b1': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e239c6e5'})],
    '17b8acfd': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '0e0db14f'})],
    'dee2cb8f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3113b5db'})],
    'cb0e6b81': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'd2bb7633'})],
    'f61407ea': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '19e579be'})],
    'f391ee20': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '40737fdd'})],
    '267ee4a0': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3fcbf912'})],
    '2bef9f4d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c41ee119'})],
    '051dec78': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '1ca8f1ca'})],
    '18b574c0': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f7440a94'})],
    '5685e826': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '4f30f594'})],
    '4b791087': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a4886ed3'})],
    '9e2ed0a2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '879bcd10'})],
    '00f5d9a1': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ef04a7f5'})],
    '78d8b9e7': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '616da455'})],
    '05a7b795': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ea56c9c1'})],
    '0fe45c8c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '1651413e'})],
    '731e330f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9cef4d5b'})],
    '639b96a6': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7a2e8b14'})],
    '4a097720': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a5f80974'})],
    '3fc8d61e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '267dcbac'})],
    '0aef4192': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e51e3fc6'})],
    '0f37b1b2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '1682ac00'})],
    'b27ef4d9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5d8f8a8d'})],
    '2e3cadac': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3789b01e'})],
    'ee06a355': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '01f7dd01'})],
    '08f85552': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '114d48e0'})],
    '08600875': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e7917621'})],
    'dfac1dae': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c619001c'})],
    '38870c9d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'd77672c9'})],
    'ae3604aa': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'b7831918'})],
    '91122253': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '7ee35c07'})],
    '99c4cd87': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '8071d035'})],
    'd58cd44b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3a7daa1f'})],
    '23c4f7e1': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3a71ea53'})],
    '3bb80caf': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'd44972fb'})],
    'fa6f2140': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e3da3cf2'})],
    'a788062f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '4879787b'})],
    '888b8d61': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '913e90d3'})],
    '35d73a8d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'da2644d9'})],
    'f1a27cb3': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e8176101'})],
    '252d24d2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'cadc5a86'})],
    '56313ed8': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '4f84236a'})],
    '71504f62': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9ea13136'})],
    'bdd0dcec': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a465c15e'})],
    'eeb11ab9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f704070b'})],
    'a0da18b7': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '4f2b66e3'})],
    'f5066a2b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ecb37799'})],
    '661aa71e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '89ebd94a'})],
    '7e427e16': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '67f763a4'})],
    'eac4ead3': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '05359487'})],
    '8db73e2a': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '94022398'})],
    '258b5a81': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ca7a24d5'})],
    '6c61253f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '75d4388d'})],
    'b9c70ad2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '56367486'})],
    '588d2d50': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '413830e2'})],
    '0ac48257': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e535fc03'})],
    '4c350a3d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5580178f'})],
    'b6d18831': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5920f665'})],
    'd87f36f5': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c1ca2b47'})],
    '1a4e3624': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'f5bf4870'})],
    'df0fd15c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c6baccee'})],
    'd9f69a39': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3607e46d'})],
    '77505e42': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6ee543f0'})],
    '2614a98d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c9e5d7d9'})],
    '4362ba7e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5ad7a7cc'})],
    'e30281de': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '0cf3ff8a'})],
    'b62379c1': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'af966473'})],
    '5c1fdf60': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'b3eea134'})],
    '373d10bf': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '2e880d0d'})],
    'f6fe3359': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '190f4d0d'})],
    '8b209de2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '92958050'})],
    'b467336d': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '5b964d39'})],
    '8cd12bf9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9564364b'})],
    '61a07507': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '8e510b53'})],
    '39ca48a0': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '207f5512'})],
    '88a29256': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6753ec02'})],
    'da18ef05': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c3adf2b7'})],
    '323c8898': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ddcdf6cc'})],
    'bb844ba7': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e1446be0'})],
    '91aec744': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '334192b1'})],
    'f7e9b490': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6a4133f4'})],
    '0a345e81': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a55fda83'})],
    '74ed7efc': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '15313587'})],
    'e1c07b3c': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c0f69713'})],
    '812273c7': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '98b4fa51'})],
    '4e17629f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '8493de99'})],
    '3ac64e77': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6ad3a6f8'})],
    'f2362641': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ecaf7432'})],
    '00298224': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '6916750a'})],
    '2b8e11df': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '323b0c6d'})],
    '837da7fe': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c08bfcd2'})],
    'd3f9d51f': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'ca4cc8ad'})],
    'c365ae0b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '2c94d05f'})],
    'fb82ffbc': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'e237e20e'})],
    'd2d4f52a': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3d258b7e'})],
    'e7ed8a5a': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'fe5897e8'})],
    '88273782': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '67d649d6'})],
    '07c849d7': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '1e7d5465'})],
    '8b0fbf16': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '64fec142'})],
    'd4d3a4aa': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'cd66b918'})],
    'd7e8dab8': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3819a4ec'})],
    'db22c75e': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'c297daec'})],
    '6c9875d4': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '752d6866'})],
    '58637f0b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'b792015f'})],
    '7c5713d5': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '65e20e67'})],
    'ff9789b2': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '1066f7e6'})],
    '606fbb39': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '79daa68b'})],
    '40393e28': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'afc8407c'})],
    '9863bd15': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '81d6a0a7'})],
    'd21fd2f9': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '3deeacad'})],
    'c7827198': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'de376c2a'})],
    '2dbdd789': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '163ba24a'})],
    'ba5cb237': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '1a6fe208'})],
    '8ccd033a': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '9449348b'})],
    '782a2923': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': 'a5b56e16'})],
    'ceb80f3b': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '71296430'})],
    '26e02ee4': [('info', 'v3.0 -> v3.1: UNKNOWN UNKNOWN Unknown Hash'),    (upgrade_hash, {'to': '19759134'})],
}