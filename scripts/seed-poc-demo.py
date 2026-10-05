"""Seed only this desk's owned synthetic database; never read dotenv files."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from poc_demo_support import offline_boundary, local_database, seed_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin')
    args = parser.parse_args()
    offline_boundary()
    with local_database(args.postgres_bin) as (engine, owner):
        scope = seed_catalog(engine)
        print(f"Seed ready: {scope['product_count']} fictional products, stable catalog IDs; zero provider calls")


if __name__ == '__main__':
    main()
