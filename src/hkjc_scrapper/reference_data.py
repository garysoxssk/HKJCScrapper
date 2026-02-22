"""Reference data for odds types and tournaments."""

from hkjc_scrapper.models import OddsTypeReference, TournamentReference


# Odds types reference data
ODDS_TYPES_DATA = [
    OddsTypeReference(
        code="HAD",
        name_en="Home/Away/Draw",
        name_ch="主客和",
        description="Standard 1X2 betting",
        example="Home win, Draw, or Away win"
    ),
    OddsTypeReference(
        code="EHA",
        name_en="Early Home/Away/Draw",
        name_ch="早場主客和",
        description="Early market HAD",
        example="Pre-match HAD odds offered early"
    ),
    OddsTypeReference(
        code="HHA",
        name_en="Handicap",
        name_ch="讓球",
        description="Handicap betting",
        example="Home -2.0 goals handicap"
    ),
    OddsTypeReference(
        code="HDC",
        name_en="Asian Handicap",
        name_ch="亞洲讓球",
        description="Asian handicap with split lines",
        example="Home -1.5/-2.0"
    ),
    OddsTypeReference(
        code="HIL",
        name_en="Hi-Lo",
        name_ch="大細",
        description="Total goals over/under",
        example="Over/Under 2.5 goals"
    ),
    OddsTypeReference(
        code="CHL",
        name_en="Corner Hi-Lo",
        name_ch="角球大細",
        description="Total corners over/under",
        example="Over/Under 9.5 corners"
    ),
    OddsTypeReference(
        code="CRS",
        name_en="Correct Score",
        name_ch="波膽",
        description="Exact final score",
        example="2-1, 3-0, etc."
    ),
    OddsTypeReference(
        code="TTG",
        name_en="Total Goals",
        name_ch="總入球",
        description="Exact number of total goals",
        example="0-1, 2-3, 4-6, 7+"
    ),
    OddsTypeReference(
        code="NTS",
        name_en="Next Team to Score",
        name_ch="下一隊入球",
        description="Which team scores next",
        example="Home, Away, or No Goal"
    ),
    OddsTypeReference(
        code="CHD",
        name_en="Corner HAD",
        name_ch="角球主客和",
        description="Which team gets more corners",
        example="Home, Draw, Away"
    ),
    OddsTypeReference(
        code="FHA",
        name_en="First Half HAD",
        name_ch="半場主客和",
        description="First half 1X2",
        example="First half: Home, Draw, Away"
    ),
    OddsTypeReference(
        code="FHL",
        name_en="First Half Hi-Lo",
        name_ch="半場大細",
        description="First half total goals",
        example="First half Over/Under 1.5"
    ),
    OddsTypeReference(
        code="FHH",
        name_en="First Half Handicap",
        name_ch="半場讓球",
        description="First half handicap",
        example="First half Home -1.0"
    ),
    OddsTypeReference(
        code="FCS",
        name_en="First Correct Score",
        name_ch="半場波膽",
        description="First half exact score",
        example="First half 1-0, 0-0, etc."
    ),
    OddsTypeReference(
        code="OOE",
        name_en="Odd/Even",
        name_ch="單雙",
        description="Total goals odd or even",
        example="Odd (1,3,5...) or Even (0,2,4...)"
    ),
    OddsTypeReference(
        code="FTS",
        name_en="First Team to Score",
        name_ch="首先入球",
        description="Which team scores first",
        example="Home, Away, or No Goal"
    ),
    OddsTypeReference(
        code="FGS",
        name_en="First Goal Scorer",
        name_ch="首名入球球員",
        description="Which player scores first",
        example="Player name selection"
    ),
    OddsTypeReference(
        code="AGS",
        name_en="Anytime Goal Scorer",
        name_ch="任何時間入球",
        description="Player to score anytime",
        example="Player name selection"
    ),
]


# Tournament reference data
TOURNAMENTS_DATA = [
    TournamentReference(
        code="EPL",
        name_en="English Premier League",
        name_ch="英格蘭超級聯賽",
        country="England",
        tier=1
    ),
    TournamentReference(
        code="LLG",
        name_en="Spanish La Liga",
        name_ch="西班牙甲組聯賽",
        country="Spain",
        tier=1
    ),
    TournamentReference(
        code="ITA",
        name_en="Italian Serie A",
        name_ch="意大利甲組聯賽",
        country="Italy",
        tier=1
    ),
    TournamentReference(
        code="BUN",
        name_en="German Bundesliga",
        name_ch="德國甲組聯賽",
        country="Germany",
        tier=1
    ),
    TournamentReference(
        code="FRA",
        name_en="French Ligue 1",
        name_ch="法國甲組聯賽",
        country="France",
        tier=1
    ),
    TournamentReference(
        code="UCL",
        name_en="UEFA Champions League",
        name_ch="歐洲聯賽冠軍盃",
        country="Europe",
        tier=1
    ),
    TournamentReference(
        code="UEL",
        name_en="UEFA Europa League",
        name_ch="歐霸盃",
        country="Europe",
        tier=2
    ),
    TournamentReference(
        code="MLS",
        name_en="US Major League Soccer",
        name_ch="美國職業聯賽",
        country="USA",
        tier=1
    ),
]


def get_odds_type_name(code: str) -> str:
    """Get the English name for an odds type code."""
    for odds_type in ODDS_TYPES_DATA:
        if odds_type.code == code:
            return odds_type.name_en
    return code  # Return code if not found


def get_tournament_name(code: str) -> str:
    """Get the English name for a tournament code."""
    for tournament in TOURNAMENTS_DATA:
        if tournament.code == code:
            return tournament.name_en
    return code  # Return code if not found
