"""Authoring Bridge errors: every problem is collected, located and reported at once."""

from __future__ import annotations

from dataclasses import dataclass

# code -> what the Director should do about it
CODES = {
    "PARSE_HEADER": "only '# PROJECT', '## <SCENE_ID>' and known '[SECTION]' lines are headers",
    "PARSE_SECTION_UNKNOWN": "use a section defined in director-authoring-guide.md",
    "PARSE_SECTION_DUPLICATE": "write each section once per block",
    "PARSE_SECTION_NOT_APPLICABLE": "this section does not apply to the scene's importance (guide section 5)",
    "PARSE_SECTION_EMPTY": "leave the section out instead of writing it empty",
    "PARSE_TEXT_OUTSIDE": "text must be inside a section body, a header or a > memo",
    "PARSE_MEMO": "> memos are allowed only between sections, never inside a YAML body",
    "PARSE_YAML": "fix the YAML syntax",
    "PARSE_YAML_KEY_DUPLICATE": "write each YAML key once",
    "PARSE_YAML_FEATURE": "YAML anchors, aliases, merge keys and custom tags are not allowed",
    "KEY_UNKNOWN": "use only the keys documented for this section",
    "KEY_REQUIRED": "add the required key",
    "KEY_TYPE": "use the documented value type",
    "SYSTEM_FIELD": "this value is produced by the Bridge or the runtime; remove it",
    "UNSUPPORTED_FIELD": "not supported in v1.2; remove it",
    "ID_INVALID": "ids start with a letter and use letters, digits, _ or -",
    "ID_DUPLICATE": "every id must be unique within its scene",
    "REF_UNRESOLVED": "refer to an id defined in this scene (or SCxxx/ID in another scene) of the right kind",
    "ANCHOR_NOT_FOUND": "copy the phrase verbatim from the approved script",
    "ANCHOR_AMBIGUOUS": "the phrase occurs more than once in the script; write a longer exact_text",
    "INITIAL_STATE": "mark exactly one state with initial: true",
    "DURING_NOT_STATE": "invariant during takes state ids (or 'scene'), never action ids",
    "ROUTING_LAYER_MISSING": "declare the runtime layer in [RUNTIME]",
    "ROUTING_UNKNOWN": "a non-model action needs layers: [...]",
    "GRAPH_CYCLE": "beats, states, actions and events must not form a cycle",
    "INPUT": "fix the Bridge input (script, models, narration)",
    "CONTRACT_SCHEMA": "the generated 40 does not validate against visual_direction_contract",
    "CONTRACT_SEMANTIC": "validate_contract rejected the generated 40",
}


@dataclass(frozen=True)
class AuthoringIssue:
    code: str
    message: str
    scene: str | None = None
    section: str | None = None
    line: int | None = None

    def __str__(self) -> str:
        where = ":".join(str(x) for x in (self.scene, f"[{self.section}]" if self.section else None, f"L{self.line}" if self.line else None) if x)
        return f"{self.code}{' ' + where if where else ''}: {self.message}"


class AuthoringError(ValueError):
    """The authoring document cannot be compiled; ``issues`` lists every problem found."""

    def __init__(self, issues: list[AuthoringIssue]):
        self.issues = list(issues)
        super().__init__("Director authoring document rejected:\n" + "\n".join(f"  - {i}" for i in self.issues))

    @property
    def codes(self) -> list[str]:
        return [i.code for i in self.issues]
