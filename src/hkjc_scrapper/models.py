"""Pydantic data models for HKJC API responses and watch rules."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Enums for validation and reference
# ============================================================================

class OddsType(str, Enum):
    """HKJC odds type codes."""
    HAD = "HAD"  # Home/Away/Draw
    EHA = "EHA"  # Early HAD
    HHA = "HHA"  # Handicap
    HDC = "HDC"  # Asian Handicap
    HIL = "HIL"  # Hi-Lo (total goals)
    CHL = "CHL"  # Corner Hi-Lo
    CRS = "CRS"  # Correct Score
    TTG = "TTG"  # Total Goals
    NTS = "NTS"  # Next Team to Score
    CHD = "CHD"  # Corner HAD
    FHA = "FHA"  # First Half HAD
    FHL = "FHL"  # First Half Hi-Lo
    FHH = "FHH"  # First Half Handicap
    FCS = "FCS"  # First Correct Score
    OOE = "OOE"  # Odd/Even
    FTS = "FTS"  # First Team to Score
    FGS = "FGS"  # First Goal Scorer
    AGS = "AGS"  # Anytime Goal Scorer


class TournamentCode(str, Enum):
    """Common HKJC tournament codes."""
    EPL = "EPL"  # English Premier League
    LLG = "LLG"  # Spanish La Liga
    ITA = "ITA"  # Italian Serie A
    BUN = "BUN"  # German Bundesliga
    FRA = "FRA"  # French Ligue 1
    UCL = "UCL"  # UEFA Champions League
    UEL = "UEL"  # UEFA Europa League
    MLS = "MLS"  # US Major League
    # Add more as needed


class MatchStatus(str, Enum):
    """Match status values."""
    SCHEDULED = "SCHEDULED"
    FIRSTHALF = "FIRSTHALF"
    SECONDHALF = "SECONDHALF"
    HALFTIME = "HALFTIME"
    FULLTIME = "FULLTIME"


class PoolStatus(str, Enum):
    """Pool/Line status values."""
    SELLINGSTARTED = "SELLINGSTARTED"
    SUSPENDED = "SUSPENDED"
    PAYOUTSTARTED = "PAYOUTSTARTED"


class CombinationStatus(str, Enum):
    """Combination status values."""
    AVAILABLE = "AVAILABLE"
    WIN = "WIN"
    LOSE = "LOSE"


# ============================================================================
# API Response Models (nested from innermost to outermost)
# ============================================================================

class Team(BaseModel):
    """Team information."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name_en: str
    name_ch: str


class Tournament(BaseModel):
    """Tournament information."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    frontEndId: str = ""
    nameProfileId: Optional[str] = None
    isInteractiveServiceAvailable: bool = False
    code: str
    name_en: str
    name_ch: str


class TvChannel(BaseModel):
    """TV channel information."""
    model_config = ConfigDict(populate_by_name=True)

    code: str
    name_en: str
    name_ch: str


class RunningResult(BaseModel):
    """Live match running result."""
    model_config = ConfigDict(populate_by_name=True)

    homeScore: Optional[int] = None
    awayScore: Optional[int] = None
    corner: Optional[int] = None
    homeCorner: Optional[int] = None
    awayCorner: Optional[int] = None


class Selection(BaseModel):
    """A single selection within a combination."""
    model_config = ConfigDict(populate_by_name=True)

    selId: str
    str: str  # Selection string identifier (e.g., "H", "A", "D")
    name_ch: str
    name_en: str


class Combination(BaseModel):
    """A betting combination with odds."""
    model_config = ConfigDict(populate_by_name=True)

    combId: str
    str: str  # Combination string identifier
    status: str
    offerEarlySettlement: str
    currentOdds: str
    selections: list[Selection]


class Line(BaseModel):
    """A betting line with multiple combinations."""
    model_config = ConfigDict(populate_by_name=True)

    lineId: str
    status: str
    condition: Optional[str] = None  # e.g., "-2.0" for handicap
    main: bool = False
    combinations: list[Combination]


class FoPool(BaseModel):
    """Fixed Odds Pool - a complete betting market."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: str
    oddsType: str  # Will validate against OddsType enum in parser
    instNo: int = 0
    inplay: bool = False
    name_ch: str = ""
    name_en: str = ""
    updateAt: str
    expectedSuspendDateTime: str = ""
    lines: list[Line] = []


class PoolInfo(BaseModel):
    """Pool availability information."""
    model_config = ConfigDict(populate_by_name=True)

    normalPools: list[str] = []
    inplayPools: list[str] = []
    sellingPools: list[str] = []
    definedPools: list[str] = []
    # ntsInfo and agsInfo are complex nested structures, add if needed


class Match(BaseModel):
    """Complete match information with odds."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    frontEndId: str
    matchDate: str
    kickOffTime: str
    status: str
    updateAt: str
    sequence: Optional[str] = None
    esIndicatorEnabled: bool = False
    isInteractiveServiceAvailable: bool = False
    inplayDelay: bool = False

    homeTeam: Team
    awayTeam: Team
    tournament: Tournament

    venue: Optional[str] = None
    tvChannels: list[TvChannel] = []
    poolInfo: Optional[PoolInfo] = None
    runningResult: Optional[RunningResult] = None
    foPools: list[FoPool] = []


# ============================================================================
# Watch Rule Models
# ============================================================================

class MatchFilter(BaseModel):
    """Filter criteria for matching matches."""
    model_config = ConfigDict(populate_by_name=True)

    teams: list[str] = []  # Team names to match
    tournaments: list[str] = []  # Tournament codes to match
    match_ids: list[str] = []  # Specific match IDs


class ScheduleTrigger(BaseModel):
    """A single schedule trigger event."""
    model_config = ConfigDict(populate_by_name=True)

    event: str  # "before_kickoff", "at_kickoff", "at_halftime", "after_kickoff"
    minutes: Optional[int] = None  # For before_kickoff/after_kickoff


class Schedule(BaseModel):
    """Schedule configuration for an observation."""
    model_config = ConfigDict(populate_by_name=True)

    mode: str  # "event" or "continuous"
    triggers: list[ScheduleTrigger] = []  # For event mode
    interval_seconds: Optional[int] = None  # For continuous mode
    start_event: Optional[str] = None  # For continuous mode: "kickoff", etc.
    end_event: Optional[str] = None  # For continuous mode: "fulltime", etc.


class Observation(BaseModel):
    """What odds types to observe and when."""
    model_config = ConfigDict(populate_by_name=True)

    odds_types: list[str]  # List of OddsType values
    schedule: Schedule


class WatchRule(BaseModel):
    """A complete watch rule definition."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    enabled: bool = True
    match_filter: MatchFilter
    observations: list[Observation]


# ============================================================================
# Reference Data Models (for MongoDB collections)
# ============================================================================

class OddsTypeReference(BaseModel):
    """Reference data for odds types."""
    model_config = ConfigDict(populate_by_name=True)

    code: str  # e.g., "HAD"
    name_en: str  # e.g., "Home/Away/Draw"
    name_ch: str  # Chinese name
    description: str = ""  # Optional description
    example: str = ""  # Example of how it works


class TournamentReference(BaseModel):
    """Reference data for tournaments."""
    model_config = ConfigDict(populate_by_name=True)

    code: str  # e.g., "EPL"
    name_en: str  # e.g., "English Premier League"
    name_ch: str  # Chinese name
    country: str = ""
    tier: int = 1  # League tier (1 = top tier)
