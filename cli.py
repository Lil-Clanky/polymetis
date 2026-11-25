"""``hermes polymetis``: the report on what Polymetis decided and what the models used."""

import argparse
import sys

from . import hooks, log, report


def days(text: str) -> int:  # named for argparse's message: "invalid days value"
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("expected 1 or more days")
    return value


def setup_parser(parser: argparse.ArgumentParser) -> None:
    # The dest must differ from Hermes's own `command`, which names `polymetis` itself.
    sub = parser.add_subparsers(dest="polymetis_command", required=True, metavar="<command>")
    p = sub.add_parser("report", help="show what Polymetis decided and which skills the models used")
    p.add_argument("--days", type=days, default=30, help="look at the last N days, 1 or more (default 30)")


def handle(args: argparse.Namespace, out=None) -> int:
    out = out or sys.stdout
    if args.polymetis_command == "report":
        try:
            records = log.read(hooks.log_path())
        except OSError as e:
            out.write(f"Polymetis cannot read its log ({type(e).__name__}): {hooks.log_path()}\n")
            return 1
        out.write(report.render(records, days=args.days, catalogs=hooks.catalogs()) + "\n")
        out.write(f"Log: {hooks.log_path()}\n")
    return 0
