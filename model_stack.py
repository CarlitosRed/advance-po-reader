"""Inspect the self-hosted stack without loading/training model weights."""
import argparse
import json
from pathlib import Path

from po_reader.infrastructure import CONFIG, readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--output', type=Path, default=Path('output/infrastructure-readiness.json'))
    args = parser.parse_args()
    result = readiness(args.config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(report=str(args.output), ollama=result['ollama'],
                         components={k:dict(model=v['model'],status=v['status']) for k,v in result['components'].items()}), indent=2))


if __name__ == '__main__':
    main()
