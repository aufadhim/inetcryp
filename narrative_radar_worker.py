"""Continuous public-source narrative radar."""
import os
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from engine.narrative_radar import NarrativeRadar


def atomic(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def main():
    radar = NarrativeRadar()
    while True:
        try:
            atomic("data/narrative_radar_status.json", {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})
            result = radar.scan()
            atomic("data/research/narrative-latest.json", result)
            atomic("data/narrative_radar_status.json", {"status": "sleeping", "last_completed": result["generated_at"],
                "matches": len(result["matches"]), "next_run_minutes": 15})
        except Exception as exc:
            atomic("data/narrative_radar_status.json", {"status": "error", "error_type": type(exc).__name__})
        time.sleep(15*60)


if __name__ == "__main__": main()
