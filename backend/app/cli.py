"""Command line entry points.

  python -m app.cli seed                     load CSVs and run the engine
  python -m app.cli run [--as-of YYYY-MM-DD] re-run the engine on loaded data
  python -m app.cli openapi                  print the OpenAPI schema (for frontend types)
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from app.db import init_db, make_engine, make_session_factory
from app.engine.rules import load_catalog
from app.engine.runner import run_engine
from app.ingest import load_csvs
from app.settings import get_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("seed", "run"):
        p = sub.add_parser(name)
        p.add_argument("--as-of", type=date.fromisoformat, help="evaluation date (default: AS_OF_DATE)")
    sub.add_parser("openapi")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()

    if args.command == "openapi":
        from app.api.main import create_app

        print(json.dumps(create_app(run_on_startup=False).openapi(), indent=2))
        return

    engine = make_engine(settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    catalog = load_catalog(settings.rules_dir)
    as_of = args.as_of or settings.as_of
    with factory() as session:
        if args.command == "seed":
            report = load_csvs(session, settings.data_dir)
            print(f"Loaded: {report.summary()}")
        run = run_engine(session, catalog, as_of)
        print(
            f"Run {run.id} as of {run.as_of}: {run.patients_evaluated} patients, {run.enrollments} enrollments, "
            f"{run.needs} needs, {run.tasks_open} open tasks (+{run.tasks_created} new, {run.tasks_resolved} resolved)"
        )


if __name__ == "__main__":
    main()
