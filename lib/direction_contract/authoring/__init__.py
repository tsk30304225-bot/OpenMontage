"""Director Authoring Bridge: the authoring-side compiler from the human Director document to canonical 40.

Not a runtime stage: it only produces the 40 that the existing Phase 1 pipeline consumes.
"""

from lib.direction_contract.authoring.compile import compile_authoring, write_contract
from lib.direction_contract.authoring.errors import AuthoringError, AuthoringIssue

__all__ = ["AuthoringError", "AuthoringIssue", "compile_authoring", "write_contract"]
