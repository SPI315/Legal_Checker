from __future__ import annotations

import json


class JsonReportExporter:
    def export(self, payload: dict) -> bytes:
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
