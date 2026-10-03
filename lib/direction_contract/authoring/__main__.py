"""python -m lib.direction_contract.authoring <authoring.md> --pvm 41.json --script script.json --out 40.json"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib.direction_contract.authoring import AuthoringError, compile_authoring, write_contract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile a Director authoring document into canonical 40.")
    parser.add_argument("authoring", type=Path)
    parser.add_argument("--pvm", type=Path, required=True, help="41 persistent_visual_models.json")
    parser.add_argument("--script", type=Path, required=True, help="approved script artifact (sections[].text)")
    parser.add_argument("--out", type=Path, required=True, help="where to write 40")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--generated-at", help="lifecycle.generated_at (default: now, UTC)")
    parser.add_argument("--narration", type=Path, help="TTS narration audio, when PROJECT.narration is set")
    parser.add_argument("--lock-by", help="lock the contract: who approved it")
    parser.add_argument("--locked-at", help="lock time (default: now, UTC)")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lock = {"by": args.lock_by, "at": args.locked_at or now} if args.lock_by else None
    try:
        contract = compile_authoring(
            args.authoring.read_text(encoding="utf-8"),
            json.loads(args.pvm.read_text(encoding="utf-8")),
            json.loads(args.script.read_text(encoding="utf-8")),
            revision=args.revision, generated_at=args.generated_at or now, lock=lock,
            narration_audio=args.narration.read_bytes() if args.narration else None,
        )
    except AuthoringError as exc:
        print(exc, file=sys.stderr)
        return 1
    write_contract(contract, args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
