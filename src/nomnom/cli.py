import argparse
import json
import os
from pathlib import Path
from .detection.simulated import SimulatedDetector
from .engine.ingestion import ingest

def main():
    parser = argparse.ArgumentParser(description="NomNom® — choose what it eats and where it puts it")
    parser.add_argument("source", type=Path)
    parser.add_argument("--card-id", required=True, help="Stable identity for this simulated card")
    parser.add_argument("--destination", type=Path, required=False)
    parser.add_argument("--config", type=Path, help="Portable JSON settings for v0.2")
    parser.add_argument("--resume", help="Explicit backup session ID")
    parser.add_argument("--preview", action="store_true", help="Plan only; create no directories")
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "nomnom")
    args = parser.parse_args()
    try:
        card = SimulatedDetector(args.source, args.card_id).inserted()
        if args.config:
            from .config import Config
            from .engine.configured import run, inventory
            from .planning import preview
            config = Config.load(args.config)
            if args.destination:
                config.destination = str(args.destination.resolve())
            config.validate(True)
            if args.preview:
                files, directories, failures = inventory(card.root)
                paths = [preview(config, p, card.root)[0] for p in files]
                print(json.dumps({'paths': [str(p) for p in paths if p is not None], 'failures': failures}, indent=2))
                return 1 if failures else 0
            result = run(card, config, args.state_dir, args.resume)
        else:
            if not args.destination or args.resume or args.preview:
                raise ValueError('Legacy ingestion requires --destination; preview/resume require --config')
            result = ingest(card, args.destination, args.state_dir)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, str(error) + "\n")
    print(json.dumps(vars(result), indent=2))
    return 1 if result.failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
