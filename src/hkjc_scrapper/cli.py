"""CLI for managing HKJC watch rules and ad-hoc data retrieval.

Usage:
    # Watch rules management
    uv run python -m hkjc_scrapper.cli add-rule --name "..." --tournaments "EPL" --observation "HAD,HHA:event:before_kickoff:30"
    uv run python -m hkjc_scrapper.cli list-rules
    uv run python -m hkjc_scrapper.cli show-rule --name "..."
    uv run python -m hkjc_scrapper.cli enable-rule --name "..."
    uv run python -m hkjc_scrapper.cli disable-rule --name "..."
    uv run python -m hkjc_scrapper.cli delete-rule --name "..."

    # Ad-hoc data retrieval
    uv run python -m hkjc_scrapper.cli list-matches
    uv run python -m hkjc_scrapper.cli list-matches --tournament EPL --status SCHEDULED
    uv run python -m hkjc_scrapper.cli fetch-match --id 50062141 --odds HAD,HHA
    uv run python -m hkjc_scrapper.cli fetch-match --front-end-id FB4233 --odds HAD
"""

import argparse
import sys

from pymongo.errors import DuplicateKeyError

from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.config import Settings
from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.models import (
    MatchFilter,
    Observation,
    Schedule,
    ScheduleTrigger,
    WatchRule,
)
from hkjc_scrapper.parser import parse_matches_response


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


# ============================================================================
# Ad-hoc data retrieval commands
# ============================================================================

def cmd_list_matches(args, db: MongoDBClient, client: HKJCGraphQLClient) -> int:
    """Handle list-matches command: fetch and display current match list."""
    print("Fetching match list from HKJC API...")
    try:
        raw = client.send_basic_match_list_request()
        matches = parse_matches_response(raw)
    except Exception as e:
        print(f"Error fetching matches: {e}")
        return 1

    if not matches:
        print("No matches found.")
        return 0

    # Apply filters
    filtered = matches
    if args.tournament:
        code = args.tournament.upper()
        filtered = [m for m in filtered if m.tournament.code == code]
    if args.status:
        status = args.status.upper()
        filtered = [m for m in filtered if m.status == status]
    if args.team:
        term = args.team.lower()
        filtered = [
            m for m in filtered
            if term in m.homeTeam.name_en.lower()
            or term in m.awayTeam.name_en.lower()
        ]

    if not filtered:
        print("No matches found matching filters.")
        return 0

    # Print header
    print(
        f"\n{'ID':<12} {'FrontEndId':<12} {'Tournament':<8} "
        f"{'Home':<22} {'Away':<22} {'Kickoff':<18} {'Status'}"
    )
    print("-" * 110)

    for m in filtered:
        kickoff_display = m.kickOffTime[:16].replace("T", " ")
        print(
            f"{m.id:<12} {m.frontEndId:<12} {m.tournament.code:<8} "
            f"{m.homeTeam.name_en:<22} {m.awayTeam.name_en:<22} "
            f"{kickoff_display:<18} {m.status}"
        )

    print(f"\n{len(filtered)} matches displayed (of {len(matches)} total)")
    return 0


def cmd_fetch_match(args, db: MongoDBClient, client: HKJCGraphQLClient) -> int:
    """Handle fetch-match command: fetch odds for a specific match and save."""
    # Parse odds types
    if not args.odds:
        print("Error: --odds is required (e.g., --odds HAD,HHA,HDC)")
        return 1
    odds_types = [o.strip().upper() for o in args.odds.split(",")]

    # Determine which match to look for
    target_id = args.id
    target_feid = args.front_end_id

    if not target_id and not target_feid:
        print("Error: provide --id or --front-end-id")
        return 1

    print(f"Fetching odds [{','.join(odds_types)}] from HKJC API...")
    try:
        raw = client.fetch_matches_for_odds(
            odds_types=odds_types,
            with_preflight=True,
        )
        matches = parse_matches_response(raw)
    except Exception as e:
        print(f"Error fetching matches: {e}")
        return 1

    # Find the target match
    target = None
    for m in matches:
        if target_id and m.id == target_id:
            target = m
            break
        if target_feid and m.frontEndId == target_feid:
            target = m
            break

    if target is None:
        identifier = target_id or target_feid
        print(f"Match '{identifier}' not found in API response ({len(matches)} matches returned).")
        print("Use 'list-matches' to see available matches and their IDs.")
        return 1

    # Display match info
    print(f"\nMatch: {target.frontEndId} ({target.id})")
    print(f"  {target.homeTeam.name_en} vs {target.awayTeam.name_en}")
    print(f"  Tournament: {target.tournament.name_en} ({target.tournament.code})")
    print(f"  Kickoff: {target.kickOffTime[:16].replace('T', ' ')}")
    print(f"  Status: {target.status}")

    # Show odds summary
    if target.foPools:
        print(f"  Odds pools: {len(target.foPools)}")
        for pool in target.foPools:
            line_count = len(pool.lines)
            comb_count = sum(len(ln.combinations) for ln in pool.lines)
            print(f"    {pool.oddsType}: {line_count} lines, {comb_count} combinations ({pool.status})")
            # Show main line odds for common types
            for ln in pool.lines:
                if ln.main:
                    odds_str = " | ".join(
                        f"{c.str}={c.currentOdds}" for c in ln.combinations
                    )
                    condition = f" [{ln.condition}]" if ln.condition else ""
                    print(f"      Main{condition}: {odds_str}")
                    break
    else:
        print("  Odds pools: 0 (no odds returned for requested types)")

    # Save to DB
    if args.no_save:
        print("\n(--no-save: skipping database save)")
        return 0

    result = db.save_matches([target])
    print(
        f"\nSaved to DB: {result['matches_upserted']} match, "
        f"{result['odds_snapshots']} odds snapshots"
    )
    return 0


# ============================================================================
# Database query commands
# ============================================================================

def cmd_get_match(args, db: MongoDBClient) -> int:
    """Handle get-match command: look up a stored match from DB."""
    # Find the match
    doc = None
    if args.id:
        doc = db.get_match(args.id)
    elif args.front_end_id:
        doc = db.get_match_by_front_end_id(args.front_end_id)
    elif args.team or args.tournament:
        results = db.search_matches(
            team=args.team or None,
            tournament=args.tournament or None,
        )
        if not results:
            print("No stored matches found matching filters.")
            return 1
        # Print summary table for multiple results
        print(
            f"\n{'ID':<12} {'FrontEndId':<12} {'Tournament':<8} "
            f"{'Home':<22} {'Away':<22} {'Kickoff':<18} {'Status'}"
        )
        print("-" * 110)
        for m in results:
            ko = m.get("kickOffTime", "")[:16].replace("T", " ")
            print(
                f"{m.get('id',''):<12} {m.get('frontEndId',''):<12} "
                f"{m.get('tournament',{}).get('code',''):<8} "
                f"{m.get('homeTeam',{}).get('name_en',''):<22} "
                f"{m.get('awayTeam',{}).get('name_en',''):<22} "
                f"{ko:<18} {m.get('status','')}"
            )
        print(f"\n{len(results)} matches found in DB")
        return 0
    else:
        print("Error: provide --id, --front-end-id, --team, or --tournament")
        return 1

    if doc is None:
        identifier = args.id or args.front_end_id
        print(f"Match '{identifier}' not found in database.")
        return 1

    _print_match_detail(doc)
    return 0


def cmd_get_odds(args, db: MongoDBClient) -> int:
    """Handle get-odds command: query stored odds history from DB."""
    # Resolve match ID
    match_id = args.id
    if not match_id and args.front_end_id:
        doc = db.get_match_by_front_end_id(args.front_end_id)
        if doc:
            match_id = doc["_id"]
        else:
            print(f"Match '{args.front_end_id}' not found in database.")
            return 1
    if not match_id:
        print("Error: provide --id or --front-end-id")
        return 1

    # Get match info for header
    match_doc = db.get_match(match_id)
    if match_doc:
        home = match_doc.get("homeTeam", {}).get("name_en", "?")
        away = match_doc.get("awayTeam", {}).get("name_en", "?")
        kickoff = match_doc.get("kickOffTime", "")[:16].replace("T", " ")
        feid = match_doc.get("frontEndId", "?")
        print(f"\nMatch: {feid} ({match_id})")
        print(f"  {home} vs {away}")
        print(f"  Kickoff: {kickoff}")
    else:
        print(f"\nMatch ID: {match_id} (not in matches_current)")

    # Parse odds type filter
    odds_type_filter = args.odds.upper() if args.odds else None

    # Show available odds types if none recorded
    available_types = db.get_odds_distinct_types(match_id)
    if not available_types:
        print("\n  No odds history recorded for this match.")
        return 0

    print(f"  Recorded odds types: {', '.join(sorted(available_types))}")

    # Determine time filter
    if args.all:
        # All snapshots
        history = db.get_odds_history(match_id, odds_type=odds_type_filter)
        if not history:
            print(f"\n  No odds history found" + (f" for {odds_type_filter}" if odds_type_filter else "") + ".")
            return 0
        print(f"\n  All snapshots ({len(history)} records):")
        print(f"  {'Time (UTC)':<22} {'Type':<6} {'Inplay':<8} Main Line Odds")
        print("  " + "-" * 80)
        for snap in history:
            _print_odds_snapshot_row(snap)

    elif args.before_kickoff:
        # Last snapshot before kickoff
        if not match_doc:
            print("  Cannot determine kickoff time (match not in DB).")
            return 1
        from hkjc_scrapper.scheduler import parse_kickoff_time
        try:
            kickoff_dt = parse_kickoff_time(match_doc["kickOffTime"])
        except (ValueError, KeyError):
            print("  Cannot parse kickoff time.")
            return 1

        history = db.get_odds_history(
            match_id, odds_type=odds_type_filter, end_time=kickoff_dt
        )
        if not history:
            print(f"\n  No pre-kickoff odds found" + (f" for {odds_type_filter}" if odds_type_filter else "") + ".")
            return 0

        # Group by odds type and take last per type
        by_type: dict[str, dict] = {}
        for snap in history:
            by_type[snap["oddsType"]] = snap  # last one wins (sorted asc)

        print(f"\n  Last snapshot before kickoff:")
        print(f"  {'Time (UTC)':<22} {'Type':<6} {'Inplay':<8} Main Line Odds")
        print("  " + "-" * 80)
        for snap in sorted(by_type.values(), key=lambda s: s["oddsType"]):
            _print_odds_snapshot_row(snap)

    elif args.last:
        # Last N snapshots
        n = args.last
        history = db.get_odds_history(match_id, odds_type=odds_type_filter)
        if not history:
            print(f"\n  No odds history found.")
            return 0
        history = history[-n:]
        print(f"\n  Last {len(history)} snapshot(s):")
        print(f"  {'Time (UTC)':<22} {'Type':<6} {'Inplay':<8} Main Line Odds")
        print("  " + "-" * 80)
        for snap in history:
            _print_odds_snapshot_row(snap)

    else:
        # Default: latest per odds type
        snapshots = db.get_latest_odds(match_id, odds_type=odds_type_filter)
        if not snapshots:
            print(f"\n  No odds history found" + (f" for {odds_type_filter}" if odds_type_filter else "") + ".")
            return 0
        print(f"\n  Latest snapshot per odds type:")
        print(f"  {'Time (UTC)':<22} {'Type':<6} {'Inplay':<8} Main Line Odds")
        print("  " + "-" * 80)
        for snap in snapshots:
            _print_odds_snapshot_row(snap)

    return 0


def _print_odds_snapshot_row(snap: dict) -> None:
    """Print a single odds snapshot as a table row."""
    fetched = snap.get("fetchedAt")
    time_str = fetched.strftime("%Y-%m-%d %H:%M:%S") if fetched else "?"
    odds_type = snap.get("oddsType", "?")
    inplay = "Yes" if snap.get("inplay") else "No"

    # Extract main line odds
    main_odds = ""
    for line in snap.get("lines", []):
        if line.get("main"):
            parts = []
            condition = line.get("condition")
            if condition:
                parts.append(f"[{condition}]")
            for comb in line.get("combinations", []):
                parts.append(f"{comb.get('str', '?')}={comb.get('currentOdds', '?')}")
            main_odds = " ".join(parts)
            break

    if not main_odds and snap.get("lines"):
        # No main line, show first line
        first_line = snap["lines"][0]
        parts = []
        condition = first_line.get("condition")
        if condition:
            parts.append(f"[{condition}]")
        for comb in first_line.get("combinations", []):
            parts.append(f"{comb.get('str', '?')}={comb.get('currentOdds', '?')}")
        main_odds = " ".join(parts)

    print(f"  {time_str:<22} {odds_type:<6} {inplay:<8} {main_odds}")


def _print_match_detail(doc: dict) -> None:
    """Print detailed stored match information."""
    print(f"\nMatch: {doc.get('frontEndId', '?')} ({doc.get('_id', doc.get('id', '?'))})")
    print(f"  {doc.get('homeTeam', {}).get('name_en', '?')} vs {doc.get('awayTeam', {}).get('name_en', '?')}")
    t = doc.get("tournament", {})
    print(f"  Tournament: {t.get('name_en', '?')} ({t.get('code', '?')})")
    print(f"  Kickoff: {doc.get('kickOffTime', '?')[:16].replace('T', ' ')}")
    print(f"  Status: {doc.get('status', '?')}")

    rr = doc.get("runningResult")
    if rr and rr.get("homeScore") is not None:
        print(f"  Score: {rr.get('homeScore', '?')}-{rr.get('awayScore', '?')}")
        if rr.get("corner") is not None:
            print(f"  Corners: {rr.get('corner')} (H:{rr.get('homeCorner', '?')} A:{rr.get('awayCorner', '?')})")

    pi = doc.get("poolInfo")
    if pi:
        selling = pi.get("sellingPools", [])
        if selling:
            print(f"  Selling pools: {', '.join(selling)}")

    pools = doc.get("foPools", [])
    if pools:
        print(f"  Stored odds ({len(pools)} pools):")
        for pool in pools:
            line_count = len(pool.get("lines", []))
            print(f"    {pool.get('oddsType', '?')}: {line_count} lines ({pool.get('status', '?')})")
            for ln in pool.get("lines", []):
                if ln.get("main"):
                    parts = []
                    cond = ln.get("condition")
                    if cond:
                        parts.append(f"[{cond}]")
                    for c in ln.get("combinations", []):
                        parts.append(f"{c.get('str', '?')}={c.get('currentOdds', '?')}")
                    print(f"      Main: {' '.join(parts)}")
                    break

    fetched = doc.get("fetchedAt")
    if fetched:
        print(f"  Last fetched: {fetched.strftime('%Y-%m-%d %H:%M:%S') if hasattr(fetched, 'strftime') else fetched}")


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

    # list-matches (ad-hoc)
    lm_parser = subparsers.add_parser(
        "list-matches", help="List matches from HKJC API"
    )
    lm_parser.add_argument("--tournament", default="", help="Filter by tournament code (e.g., EPL)")
    lm_parser.add_argument("--status", default="", help="Filter by status (SCHEDULED, FIRSTHALF, etc.)")
    lm_parser.add_argument("--team", default="", help="Filter by team name (partial match)")

    # fetch-match (ad-hoc)
    fm_parser = subparsers.add_parser(
        "fetch-match", help="Fetch odds for a specific match and save to DB"
    )
    fm_parser.add_argument("--id", default="", help="Match ID (e.g., 50062141)")
    fm_parser.add_argument("--front-end-id", default="", help="Front-end match ID (e.g., FB4233)")
    fm_parser.add_argument("--odds", default="", help="Comma-separated odds types (e.g., HAD,HHA,HDC)")
    fm_parser.add_argument("--no-save", action="store_true", help="Display only, don't save to DB")

    # get-match (DB query)
    gm_parser = subparsers.add_parser(
        "get-match", help="Look up a stored match from DB"
    )
    gm_parser.add_argument("--id", default="", help="Match ID")
    gm_parser.add_argument("--front-end-id", default="", help="Front-end match ID (e.g., FB4233)")
    gm_parser.add_argument("--team", default="", help="Search by team name (partial)")
    gm_parser.add_argument("--tournament", default="", help="Filter by tournament code")

    # get-odds (DB query)
    go_parser = subparsers.add_parser(
        "get-odds", help="Query stored odds history from DB"
    )
    go_parser.add_argument("--id", default="", help="Match ID")
    go_parser.add_argument("--front-end-id", default="", help="Front-end match ID")
    go_parser.add_argument("--odds", default="", help="Filter by odds type (e.g., HAD)")
    go_parser.add_argument("--latest", action="store_true", default=True, help="Latest snapshot per type (default)")
    go_parser.add_argument("--before-kickoff", action="store_true", help="Last snapshot before kickoff")
    go_parser.add_argument("--all", action="store_true", help="Show all snapshots (time series)")
    go_parser.add_argument("--last", type=int, default=0, help="Show last N snapshots")

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

    # Commands that only need db
    db_commands = {
        "add-rule": cmd_add_rule,
        "list-rules": cmd_list_rules,
        "show-rule": cmd_show_rule,
        "enable-rule": cmd_enable_rule,
        "disable-rule": cmd_disable_rule,
        "delete-rule": cmd_delete_rule,
        "get-match": cmd_get_match,
        "get-odds": cmd_get_odds,
    }

    # Commands that need both db and client (ad-hoc API calls)
    api_commands = {
        "list-matches": cmd_list_matches,
        "fetch-match": cmd_fetch_match,
    }

    try:
        if args.command in db_commands:
            return db_commands[args.command](args, db)
        elif args.command in api_commands:
            client = HKJCGraphQLClient(settings)
            return api_commands[args.command](args, db, client)
        else:
            parser.print_help()
            return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
