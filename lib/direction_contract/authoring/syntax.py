"""Strict parser for the human Director authoring document (director-authoring-guide.md section 2).

Markdown is only the shell: ``# PROJECT`` and ``## <SCENE_ID>`` open blocks, ``[SECTION]`` lines open
sections, ``>`` lines are Director memos. Every section body is YAML, read by a strict loader: YAML 1.2
booleans only (``on``/``yes`` stay strings), no duplicate keys, no anchors/aliases/merge keys/custom
tags, no implicit timestamps. Nothing unknown is skipped: it becomes an AuthoringIssue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionStartEvent, ScalarEvent

from lib.direction_contract.authoring.errors import AuthoringIssue
from lib.direction_contract.authoring.grammar import PROJECT_SECTIONS, SCENE_SECTIONS

PROJECT_HEADER = "# PROJECT"
SCENE_HEADER = re.compile(r"^## ([A-Z][A-Z0-9_-]*)$")
SECTION_HEADER = re.compile(r"^\[([A-Z][A-Z ]*)\]$")


@dataclass
class Section:
    name: str
    line: int                 # line of the [SECTION] header (1-based)
    body: Any                 # parsed YAML


@dataclass
class Block:
    kind: str                 # "project" | "scene"
    id: str | None
    line: int
    sections: dict[str, Section] = field(default_factory=dict)   # document order


@dataclass
class AuthoringDoc:
    project: Block | None
    scenes: list[Block]


# --- strict YAML ------------------------------------------------------------------------------------

class _StrictLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans, no timestamps, no merge keys and duplicate-key detection."""

    def construct_mapping(self, node, deep=False):  # noqa: D401 - PyYAML hook
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise _DuplicateKey(key, key_node.start_mark.line)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


_StrictLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag not in ("tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:merge")]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_StrictLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))


class _DuplicateKey(Exception):
    def __init__(self, key: Any, line: int):
        super().__init__(key)
        self.key, self.line = key, line


def _load_yaml(text: str, first_line: int, where: dict[str, Any], issues: list[AuthoringIssue]) -> Any:
    try:
        for event in yaml.parse(text, Loader=_StrictLoader):
            line = first_line + event.start_mark.line
            if isinstance(event, AliasEvent):
                issues.append(AuthoringIssue("PARSE_YAML_FEATURE", f"alias *{event.anchor}", line=line, **where))
                return None
            if isinstance(event, (ScalarEvent, CollectionStartEvent)):
                if event.anchor is not None:
                    issues.append(AuthoringIssue("PARSE_YAML_FEATURE", f"anchor &{event.anchor}", line=line, **where))
                    return None
                explicit = event.tag is not None and not (isinstance(event, ScalarEvent) and event.implicit[0]) \
                    and not (isinstance(event, CollectionStartEvent) and event.implicit)
                if explicit and event.tag != "!":
                    issues.append(AuthoringIssue("PARSE_YAML_FEATURE", f"tag {event.tag}", line=line, **where))
                    return None
        data = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - strict SafeLoader subclass
    except _DuplicateKey as dup:
        issues.append(AuthoringIssue("PARSE_YAML_KEY_DUPLICATE", f"key {dup.key!r} appears twice", line=first_line + dup.line, **where))
        return None
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        issues.append(AuthoringIssue("PARSE_YAML", str(getattr(exc, "problem", exc)), line=first_line + mark.line if mark else None, **where))
        return None
    if _has_merge_key(data):
        issues.append(AuthoringIssue("PARSE_YAML_FEATURE", "merge key <<", line=first_line, **where))
        return None
    return data


def _has_merge_key(data: Any) -> bool:
    if isinstance(data, dict):
        return "<<" in data or any(_has_merge_key(v) for v in data.values())
    if isinstance(data, list):
        return any(_has_merge_key(v) for v in data)
    return False


# --- document ---------------------------------------------------------------------------------------

def parse_authoring(text: str) -> tuple[AuthoringDoc, list[AuthoringIssue]]:
    """Split the document into blocks and sections and load every section body as strict YAML."""
    issues: list[AuthoringIssue] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    project: Block | None = None
    scenes: list[Block] = []
    block: Block | None = None
    open_section: tuple[str, int, list[str], bool] | None = None   # name, header line, body lines, known

    def scene_id() -> str | None:
        return block.id if block and block.kind == "scene" else None

    def close_section() -> None:
        nonlocal open_section
        if open_section is None:
            return
        name, header_line, body, known = open_section
        open_section = None
        if not known:
            return  # already reported; its body is not parsed
        where = {"scene": scene_id(), "section": name}
        # trailing > memos (and blank lines) belong between sections, not to the body
        while body and (not body[-1].strip() or body[-1].startswith(">")):
            body.pop()
        for offset, raw in enumerate(body):
            if raw.startswith(">"):
                issues.append(AuthoringIssue("PARSE_MEMO", "memo inside a YAML body", line=header_line + 1 + offset, **where))
                return
        if not "".join(body).strip():
            issues.append(AuthoringIssue("PARSE_SECTION_EMPTY", f"[{name}] has no body", line=header_line, **where))
            return
        before = len(issues)
        data = _load_yaml("\n".join(body), header_line + 1, where, issues)
        if len(issues) == before:
            block.sections[name] = Section(name, header_line, data)

    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        scene_match = SCENE_HEADER.match(line)
        section_match = SECTION_HEADER.match(line)
        if line == PROJECT_HEADER or scene_match or (line.startswith("#") and line.split(" ", 1)[0] in ("#", "##") and open_section is None):
            close_section()
            if line == PROJECT_HEADER:
                if project is not None or scenes:
                    issues.append(AuthoringIssue("PARSE_HEADER", "# PROJECT must appear once, before every scene", line=number))
                block = Block("project", None, number)
                project = project or block
            elif scene_match:
                if project is None:
                    issues.append(AuthoringIssue("PARSE_HEADER", "scenes come after the # PROJECT block", line=number))
                block = Block("scene", scene_match.group(1), number)
                if any(b.id == block.id for b in scenes):
                    issues.append(AuthoringIssue("ID_DUPLICATE", f"scene {block.id} is written twice", scene=block.id, line=number))
                scenes.append(block)
            else:
                issues.append(AuthoringIssue("PARSE_HEADER", f"unknown header {line!r}", line=number))
            continue
        if section_match:
            close_section()
            name = section_match.group(1)
            if block is None:
                issues.append(AuthoringIssue("PARSE_TEXT_OUTSIDE", f"[{name}] before any block header", line=number))
                continue
            allowed = PROJECT_SECTIONS if block.kind == "project" else SCENE_SECTIONS
            if name not in allowed:
                issues.append(AuthoringIssue("PARSE_SECTION_UNKNOWN", f"[{name}]", scene=scene_id(), section=name, line=number))
                open_section = (name, number, [], False)
                continue
            if name in block.sections:
                issues.append(AuthoringIssue("PARSE_SECTION_DUPLICATE", f"[{name}] appears twice", scene=scene_id(), section=name, line=number))
            open_section = (name, number, [], True)
            continue
        if open_section is not None:
            open_section[2].append(raw)
            continue
        if not line.strip() or line.startswith(">"):
            continue  # blank line or memo between headers
        issues.append(AuthoringIssue("PARSE_TEXT_OUTSIDE", line.strip()[:60], scene=scene_id(), line=number))
    close_section()

    if project is None:
        issues.append(AuthoringIssue("PARSE_HEADER", "the document has no # PROJECT block"))
    return AuthoringDoc(project, scenes), issues
