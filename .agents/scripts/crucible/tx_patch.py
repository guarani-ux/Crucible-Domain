"""In-RAM Copy-on-Write Transaction Buffer for atomic multi-file edits (ACID + AST/TQ validation)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

try:
    import test_quality_gate as tqg
except Exception:
    tqg = None


class TransactionValidationError(ValueError):
    """Raised when in-RAM pre-commit validation fails; guarantees zero disk mutations."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _sha256_bytes(data: bytes | None) -> str | None:
    if data is None:
        return None
    return hashlib.sha256(data).hexdigest()


class TransactionBuffer:
    """In-RAM Copy-on-Write overlay supporting atomic multi-file commit via os.replace()."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self._overlay: dict[Path, bytes | None] = {}

    def _resolve(self, path: Path | str) -> Path:
        p = Path(path)
        resolved = p.resolve() if p.is_absolute() else (self.root / p).resolve()
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise ValueError(f"Path '{path}' escapes transaction root '{self.root}'")
        return resolved

    def read_bytes(self, path: Path | str) -> bytes:
        p = self._resolve(path)
        if p in self._overlay:
            data = self._overlay[p]
            if data is None:
                raise FileNotFoundError(f"Staged for deletion: {p}")
            return data
        return p.read_bytes()

    def read_text(self, path: Path | str, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding)

    def stage_write(self, path: Path | str, content: str | bytes, encoding: str = "utf-8") -> None:
        p = self._resolve(path)
        data = content.encode(encoding) if isinstance(content, str) else bytes(content)
        self._overlay[p] = data

    def stage_delete(self, path: Path | str) -> None:
        p = self._resolve(path)
        self._overlay[p] = None

    def stage_replace(self, path: Path | str, target: str, replacement: str) -> None:
        text = self.read_text(path)
        if target not in text:
            raise ValueError(f"Target string not found in {path}")
        self.stage_write(path, text.replace(target, replacement, 1))

    def stage_json_transform(self, path: Path | str, transform: Callable[[Any], Any], indent: int = 2) -> None:
        obj = json.loads(self.read_text(path))
        updated = transform(obj)
        self.stage_write(path, json.dumps(updated, indent=indent, ensure_ascii=False) + "\n")

    def validate(self) -> list[str]:
        errors: list[str] = []
        for path, data in sorted(self._overlay.items()):
            if data is None:
                continue
            rel = str(path.relative_to(self.root)).replace("\\", "/")
            suffix = path.suffix.lower()
            if suffix == ".py":
                try:
                    text = data.decode("utf-8")
                    compile(text, rel, "exec")
                except (UnicodeDecodeError, SyntaxError) as exc:
                    errors.append(f"python syntax error in {rel}: {exc}")
                    continue
                if tqg is not None and tqg.is_test_file(path):
                    findings = tqg.check_test_source(text, rel)
                    for f in findings:
                        errors.append(f"{f.rule_id} in {f.file}:{f.line}: {f.message}")
            elif suffix == ".json":
                try:
                    json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"invalid json in {rel}: {exc}")
        return errors

    def commit(self) -> dict[str, Any]:
        errors = self.validate()
        if errors:
            raise TransactionValidationError(errors)

        receipt_files: list[dict[str, Any]] = []
        applied_undo: list[tuple[Path, bytes | None]] = []
        try:
            for path, data in sorted(self._overlay.items()):
                before_bytes = path.read_bytes() if path.is_file() else None
                rel = str(path.relative_to(self.root)).replace("\\", "/")
                if data is None:
                    if path.exists():
                        path.unlink()
                    action = "deleted"
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    fd, tmp_name = tempfile.mkstemp(prefix=".tx_", dir=str(path.parent))
                    try:
                        with os.fdopen(fd, "wb") as fh:
                            fh.write(data)
                        os.replace(tmp_name, path)
                    except Exception:
                        if os.path.exists(tmp_name):
                            os.unlink(tmp_name)
                        raise
                    action = "updated" if before_bytes is not None else "created"

                applied_undo.append((path, before_bytes))
                receipt_files.append(
                    {
                        "path": rel,
                        "action": action,
                        "before_sha256": _sha256_bytes(before_bytes),
                        "after_sha256": _sha256_bytes(data),
                    }
                )
        except Exception:
            for undo_path, prev_bytes in reversed(applied_undo):
                if prev_bytes is None:
                    if undo_path.exists():
                        undo_path.unlink()
                else:
                    undo_path.write_bytes(prev_bytes)
            raise

        self._overlay.clear()
        return {"status": "committed", "file_count": len(receipt_files), "files": receipt_files}
