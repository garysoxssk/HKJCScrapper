"""CLI for managing HKJC watch rules.

Usage:
    uv run python -m hkjc_scrapper.cli add-rule --name "..." --tournaments "EPL" --observation "HAD,HHA:event:before_kickoff:30"
    uv run python -m hkjc_scrapper.cli list-rules
    uv run python -m hkjc_scrapper.cli show-rule --name "..."
    uv run python -m hkjc_scrapper.cli enable-rule --name "..."
    uv run python -m hkjc_scrapper.cli disable-rule --name "..."
    uv run python -m hkjc_scrapper.cli delete-rule --name "..."
"""

import argparse
import sys

from pymongo.errors import DuplicateKeyError

from hkjc_scrapper.config import Settings
from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.models import (
    MatchFilter,
    Observation,
    Schedule,
    ScheduleTrigger,
    WatchRule,
)


def parse_observation(obs_str: str) -> Observation:
    """
    Parse an observation string into an Observation object.

    Format: "ODDS_TYPES:MODE:DETAILS"

    Event mode examples:
        "HAD,HHA,HDC:event:before_kickoff:30"
        "CHL:event:at_kickoff"
        "HAD:event:at_halftime"

    Continuous mode examples:
        "CHL:continuous:300:kickoff:fulltime"

    Args:
        obs_str: Observation string

    Returns:
        Observation object

    Raises:
        ValueError: If format is invalid
    """
    parts = obs_str.split(":")
    if len(parts) < 2:
        raise ValueError(
            f"Invalid observation format: '{obs_str}'. "
            "Expected 'ODDS_TYPES:MODE:...' "
            "(e.g., 'HAD,HHA:event:before_kickoff:30' or 'CHL:continuous:300:kickoff:fulltime')"
        )

    odds_types = [ot.strip() for ot in parts[0].split(",")]
    mode = parts[1]

    if mode == "event":
        if len(parts) < 3:
            raise ValueError(
                f"Event mode requires trigger: '{obs_str}'. "
                "Expected 'ODDS:event:TRIGGER[:MINUTES]'"
            )
        trigger_event = parts[2]
        minutes = int(parts[3]) if len(parts) > 3 else None

        return Observation(
            odds_types=odds_types,
            schedule=Schedule(
                mode="event",
                triggers=[ScheduleTrigger(event=trigger_event, minutes=minutes)],
            ),
        )
    elif mode == "continuous":
        if len(parts) < 5:
            raise ValueError(
                f"Continuous mode requires interval, start, end: '{obs_str}'. "
                "Expected 'ODDS:continuous:INTERVAL_SEC:START_EVENT:END_EVENT'"
            )
        interval = int(parts[2])
        start_event = parts[3]
        end_event = parts[4]

        return Observation(
            odds_types=odds_types,
            schedule=Schedule(
                mode="continuous",
                interval_seconds=interval,
                start_event=start_event,
                end_event=end_event,
            ),
        )
    else:
        raise ValueError(
            f"Unknown mode '{mode}'. Must be 'event' or 'continuous'."
        )


def cmd_add_rule(args, db: MongoDBClient) -> int:
    """Handle add-rule command."""
    teams = [t.strip() for t in args.teams.split(",")] if args.teams else []
    tournaments = [t.strip() for t in args.tournaments.split(",")] if args.tournaments else []
    match_ids = [m.strip() for m in args.match_ids.split(",")] if args.match_ids else []

    # Parse observations
    observations = []
    for obs_str in args.observation:
        try:
            observations.append(parse_observation(obs_str))
        except ValueError as e:
            print(f"Error: {e}")
            return 1

    if not observations:
        print("Error: at least one --observation is required")
        return 1

    rule = WatchRule(
        name=args.name,
        enabled=True,
        match_filter=MatchFilter(
            teams=teams,
            tournaments=tournaments,
            match_ids=match_ids,
        ),
        observations=observations,
    )

    try:
        db.add_watch_rule(rule)
        print(f"Added rule: {args.name}")
        _print_rule_detail(rule.model_dump())
        return 0
    except DuplicateKeyError:
        print(f"Error: rule '{args.name}' already exists")
        return 1


def cmd_list_rules(args, db: MongoDBClient) -> int:
    """Handle list-rules command."""
    rules = db.get_all_watch_rules()

    if not rules:
        print("No watch rules found.")
        return 0

    print(f"{'Name':<25} {'Status':<10} {'Filters':<30} {'Observations'}")
    print("-" * 90)

    for rule in rules:
        status = "ENABLED" if rule.get("enabled", True) else "DISABLED"
        filters = []
        mf = rule.get("match_filter", {})
        if mf.get("teams"):
            filters.append(f"teams={mf['teams']}")
        if mf.get("tournaments"):
            filters.append(f"tourn={mf['tournaments']}")
        if mf.get("match_ids"):
            filters.append(f"ids={mf['match_ids']}")
        if not filters:
            filters.append("(all matches)")

        obs_parts = []
        for obs in rule.get("observations", []):
            odds = ",".join(obs.get("odds_types", []))
            mode = obs.get("schedule", {}).get("mode", "?")
            obs_parts.append(f"{odds}({mode})")

        print(f"{rule['name']:<25} {status:<10} {'; '.join(filters):<30} {'; '.join(obs_parts)}")

    return 0


def cmd_show_rule(args, db: MongoDBClient) -> int:
    """Handle show-rule command."""
    doc = db.get_watch_rule(args.name)
    if not doc:
        print(f"Rule '{args.name}' not found.")
        return 1

    _print_rule_detail(doc)
    return 0


def cmd_enable_rule(args, db: MongoDBClient) -> int:
    """Handle enable-rule command."""
    if db.enable_watch_rule(args.name):
        print(f"Enabled rule: {args.name}")
        return 0
    print(f"Rule '{args.name}' not found.")
    return 1


def cmd_disable_rule(args, db: MongoDBClient) -> int:
    """Handle disable-rule command."""
    if db.disable_watch_rule(args.name):
        print(f"Disabled rule: {args.name}")
        return 0
    print(f"Rule '{args.name}' not found.")
    return 1


def cmd_delete_rule(args, db: MongoDBClient) -> int:
    """Handle delete-rule command."""
    if db.delete_watch_rule(args.name):
        print(f"Deleted rule: {args.name}")
        return 0
    print(f"Rule '{args.name}' not found.")
    return 1


def _print_rule_detail(doc: dict) -> None:
    """Print detailed rule information."""
    print(f"\n  Rule: {doc['name']}")
    print(f"  Status: {'ENABLED' if doc.get('enabled', True) else 'DISABLED'}")

    mf = doc.get("match_filter", {})
    if mf.get("teams"):
        print(f"  Teams: {', '.join(mf['teams'])}")
    if mf.get("tournaments"):
        print(f"  Tournaments: {', '.join(mf['tournaments'])}")
    if mf.get("match_ids"):
        print(f"  Match IDs: {', '.join(mf['match_ids'])}")
    if not mf.get("teams") and not mf.get("tournaments") and not mf.get("match_ids"):
        print("  Filter: (all matches)")

    for i, obs in enumerate(doc.get("observations", []), 1):
        odds = ", ".join(obs.get("odds_types", []))
        sched = obs.get("schedule", {})
        mode = sched.get("mode", "?")

        print(f"  Observation {i}: [{odds}]")
        if mode == "event":
            for trigger in sched.get("triggers", []):
                event = trigger.get("event", "?")
                minutes = trigger.get("minutes")
                if minutes:
                    print(f"    Schedule: {event} ({minutes} min)")
                else:
                    print(f"    Schedule: {event}")
        elif mode == "continuous":
            interval = sched.get("interval_seconds", "?")
            start = sched.get("start_event", "?")
            end = sched.get("end_event", "?")
            print(f"    Schedule: continuous every {interval}s from {start} to {end}")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="hkjc_scrapper.cli",
        description="Manage HKJC watch rules",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # add-rule
    add_parser = subparsers.add_parser("add-rule", help="Add a new watch rule")
    add_parser.add_argument("--name", required=True, help="Rule name (must be unique)")
    add_parser.add_argument("--teams", default="", help="Comma-separated team names")
    add_parser.add_argument("--tournaments", default="", help="Comma-separated tournament codes")
    add_parser.add_argument("--match-ids", default="", help="Comma-separated match IDs")
    add_parser.add_argument(
        "--observation",
        action="append",
        default=[],
        help="Observation spec (e.g., 'HAD,HHA:event:before_kickoff:30'). Can be repeated.",
    )

    # list-rules
    subparsers.add_parser("list-rules", help="List all watch rules")

    # show-rule
    show_parser = subparsers.add_parser("show-rule", help="Show rule details")
    show_parser.add_argument("--name", required=True, help="Rule name")

    # enable-rule
    enable_parser = subparsers.add_parser("enable-rule", help="Enable a watch rule")
    enable_parser.add_argument("--name", required=True, help="Rule name")

    # disable-rule
    disable_parser = subparsers.add_parser("disable-rule", help="Disable a watch rule")
    disable_parser.add_argument("--name", required=True, help="Rule name")

    # delete-rule
    delete_parser = subparsers.add_parser("delete-rule", help="Delete a watch rule")
    delete_parser.add_argument("--name", required=True, help="Rule name")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    settings = Settings()
    db = MongoDBClient(settings.MONGODB_URI, settings.MONGODB_DATABASE)
    db.ensure_collections()

    commands = {
        "add-rule": cmd_add_rule,
        "list-rules": cmd_list_rules,
        "show-rule": cmd_show_rule,
        "enable-rule": cmd_enable_rule,
        "disable-rule": cmd_disable_rule,
        "delete-rule": cmd_delete_rule,
    }

    handler = commands.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    try:
        return handler(args, db)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
