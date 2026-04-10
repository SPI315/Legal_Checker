from __future__ import annotations

import json
from pathlib import Path

from app.services.storage.crypto import DpapiCipher


class ArtifactStore:
    def __init__(self, base_dir: Path, cipher: DpapiCipher) -> None:
        self.base_dir = base_dir
        self.cipher = cipher
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_encrypted_json(self, session_id: str, name: str, payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return self.save_encrypted_bytes(session_id, name, raw)

    def save_encrypted_bytes(self, session_id: str, name: str, payload: bytes) -> str:
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        target = session_dir / f"{name}.bin"
        target.write_bytes(self.cipher.encrypt(payload))
        return str(target)

    def save_plain_bytes(self, session_id: str, name: str, payload: bytes, extension: str) -> str:
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        target = session_dir / f"{name}.{extension.lstrip('.')}"
        target.write_bytes(payload)
        return str(target)

    def save_plain_json(self, session_id: str, name: str, payload: dict | list) -> str:
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        target = session_dir / f"{name}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(target)

    def append_jsonl(self, session_id: str, name: str, payload: dict) -> str:
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        target = session_dir / f"{name}.jsonl"
        with target.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return str(target)

    def load_encrypted_json(self, path: str) -> dict:
        raw = Path(path).read_bytes()
        return json.loads(self.cipher.decrypt(raw).decode("utf-8"))
