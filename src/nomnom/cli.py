import argparse
import json
import os
from pathlib import Path
from .detection.simulated import SimulatedDetector
from .engine.ingestion import ingest

def main():
    parser = argparse.ArgumentParser(description="NomNom® v0.1 local SD-card simulation")
    parser.add_argument("source", type=Path)
    parser.add_argument("--card-id", required=True, help="Stable identity for this simulated card")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "nomnom")
    args = parser.parse_args()
    try:
        result = ingest(SimulatedDetector(args.source, args.card_id).inserted(), args.destination, args.state_dir)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + "\n")
    print(json.dumps(vars(result), indent=2))
    return 1 if result.failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
