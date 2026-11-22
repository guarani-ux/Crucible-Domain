"""Record only host lifecycle evidence in the host's own artifact directory."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def observe(event, payload):
    required = ("conversationId", "artifactDirectoryPath")
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
        return
    directory = Path(payload["artifactDirectoryPath"])
    if not directory.is_absolute() or not directory.is_dir():
        return

    entry = {
        "schema": "inner-gravity-lifecycle/v1",
        "event": event,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "session": payload["conversationId"],
        "model": payload.get("modelName"),
    }
    if event == "stop":
        entry["attempt"] = payload.get("executionNum")
        entry["termination_reason"] = payload.get("terminationReason")
        entry["idle"] = payload.get("fullyIdle")

    receipts = directory / "inner-gravity-observations"
    receipts.mkdir(exist_ok=True)
    token = uuid4().hex
    provisional = receipts / f".{token}.tmp"
    target = receipts / f"{token}.json"
    try:
        provisional.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
        os.replace(provisional, target)
    finally:
        provisional.unlink(missing_ok=True)


def main():
    try:
        event, = sys.argv[1:]
        payload = json.load(sys.stdin)
        if event in {"session-start", "stop"} and isinstance(payload, dict):
            observe(event, payload)
    except (ValueError, OSError) as failure:
        print(f"Inner Gravity observation unavailable: {type(failure).__name__}", file=sys.stderr)
    print("{}")


if __name__ == "__main__":
    main()
