"""Reference data for odds types and tournaments.

Odds type translations sourced from HKJC API description files:
  - resources/description-en-res.json (LB_FB_TITLE_{code})
  - resources/description-ch-res.json (LB_FB_TITLE_{code})

Tournament data sourced from HKJC GraphQL tournamentList query:
  - resources/match-list-res-1.json
"""

from hkjc_scrapper.models import OddsTypeReference, TournamentReference


# ============================================================================
# Odds types - sourced from HKJC LB_FB_TITLE_ labels
# ============================================================================

ODDS_TYPES_DATA = [
    # --- Standard match odds ---
    OddsTypeReference(
        code="HAD", name_en="Home/Away/Draw", name_ch="主客和",
        description="Standard 1X2 betting",
    ),
    OddsTypeReference(
        code="FHA", name_en="First Half HAD", name_ch="半場主客和",
        description="First half 1X2",
    ),
    OddsTypeReference(
        code="HHA", name_en="Handicap HAD", name_ch="讓球主客和",
        description="Handicap home/away/draw",
    ),
    OddsTypeReference(
        code="FHH", name_en="First Half Handicap", name_ch="半場讓球",
        description="First half handicap",
    ),
    OddsTypeReference(
        code="HDC", name_en="Handicap", name_ch="讓球",
        description="Asian handicap",
    ),
    OddsTypeReference(
        code="HIL", name_en="HiLo", name_ch="入球大細",
        description="Total goals over/under",
    ),
    OddsTypeReference(
        code="FHL", name_en="First Half HiLo", name_ch="半場入球大細",
        description="First half total goals over/under",
    ),
    OddsTypeReference(
        code="CRS", name_en="Correct Score", name_ch="波膽",
        description="Exact final score",
    ),
    OddsTypeReference(
        code="FCS", name_en="First Half Correct Score", name_ch="半場波膽",
        description="First half exact score",
    ),
    OddsTypeReference(
        code="TTG", name_en="Total Goals", name_ch="總入球",
        description="Exact number of total goals",
    ),
    OddsTypeReference(
        code="OOE", name_en="Odd/Even", name_ch="入球單雙",
        description="Total goals odd or even",
    ),
    OddsTypeReference(
        code="HFT", name_en="HaFu", name_ch="半全場",
        description="Half-time/full-time result",
    ),
    OddsTypeReference(
        code="FTS", name_en="First Team to Score", name_ch="第一隊入球",
        description="Which team scores first",
    ),
    OddsTypeReference(
        code="NTS", name_en="Next Team To Score", name_ch="下一隊入球",
        description="Which team scores next",
    ),
    OddsTypeReference(
        code="TQL", name_en="To Qualify", name_ch="晉級隊伍",
        description="Which team qualifies",
    ),
    # --- Corner odds ---
    OddsTypeReference(
        code="CHL", name_en="Corner Taken HiLo", name_ch="開出角球大細",
        description="Total corners over/under",
    ),
    OddsTypeReference(
        code="FCH", name_en="First Half Corner Taken HiLo", name_ch="半場開出角球大細",
        description="First half total corners over/under",
    ),
    OddsTypeReference(
        code="CHD", name_en="Corner Taken Handicap", name_ch="開出角球讓球",
        description="Corner handicap",
    ),
    OddsTypeReference(
        code="FHC", name_en="First Half Corner Taken Handicap", name_ch="半場開出角球讓球",
        description="First half corner handicap",
    ),
    # --- Goal scorer odds ---
    OddsTypeReference(
        code="FGS", name_en="First Scorer", name_ch="首名入球",
        description="First goal scorer",
    ),
    OddsTypeReference(
        code="LGS", name_en="Last Scorer", name_ch="最後入球球員",
        description="Last goal scorer",
    ),
    OddsTypeReference(
        code="NGS", name_en="Next Scorer", name_ch="下一名入球球員",
        description="Next goal scorer",
    ),
    OddsTypeReference(
        code="AGS", name_en="Anytime Scorer", name_ch="任何時間入球球員",
        description="Anytime goal scorer",
    ),
    # --- Extra time odds ---
    OddsTypeReference(
        code="EHA", name_en="Home/Away/Draw (Extra Time)", name_ch="主客和 (加時)",
        description="Extra time HAD",
    ),
    OddsTypeReference(
        code="EDC", name_en="Handicap (Extra Time)", name_ch="讓球 (加時)",
        description="Extra time Asian handicap",
    ),
    OddsTypeReference(
        code="EHH", name_en="Handicap HAD (Extra Time)", name_ch="讓球主客和 (加時)",
        description="Extra time handicap HAD",
    ),
    OddsTypeReference(
        code="EHL", name_en="HiLo (Extra Time)", name_ch="入球大細 (加時)",
        description="Extra time over/under",
    ),
    OddsTypeReference(
        code="ECH", name_en="Corner Taken HiLo (Extra Time)", name_ch="開出角球大細 (加時)",
        description="Extra time corner over/under",
    ),
    OddsTypeReference(
        code="ECD", name_en="Corner Taken Handicap (Extra Time)", name_ch="開出角球讓球 (加時)",
        description="Extra time corner handicap",
    ),
    OddsTypeReference(
        code="ECS", name_en="Correct Score (Extra Time)", name_ch="波膽 (加時)",
        description="Extra time correct score",
    ),
    OddsTypeReference(
        code="ETG", name_en="Total Goals (Extra Time)", name_ch="總入球 (加時)",
        description="Extra time total goals",
    ),
    OddsTypeReference(
        code="ENT", name_en="Next Team To Score (Extra Time)", name_ch="下一隊入球 (加時)",
        description="Extra time next team to score",
    ),
    # --- Special / tournament odds ---
    OddsTypeReference(
        code="SGA", name_en="Same Game All Up", name_ch="同場過關",
        description="Same game all-up (parlay within single match)",
    ),
    OddsTypeReference(
        code="MSP", name_en="Specials", name_ch="特別項目",
        description="Match specials",
    ),
    OddsTypeReference(
        code="CHP", name_en="Champion", name_ch="冠軍",
        description="Outright tournament winner",
    ),
    OddsTypeReference(
        code="GPW", name_en="Group Winner", name_ch="小組首名",
        description="Group stage winner",
    ),
    OddsTypeReference(
        code="GPF", name_en="Group Forecast", name_ch="小組一二名",
        description="Group stage 1st and 2nd",
    ),
    OddsTypeReference(
        code="TPS", name_en="Top Scorer", name_ch="神射手",
        description="Tournament top scorer",
    ),
]


# ============================================================================
# Tournaments - initial set (will be auto-updated from API)
# ============================================================================

TOURNAMENTS_DATA = [
    TournamentReference(
        code="EPL", name_en="English Premier League", name_ch="英格蘭超級聯賽",
        country="England", tier=1,
    ),
    TournamentReference(
        code="SFL", name_en="Spanish Division 1", name_ch="西班牙甲組聯賽",
        country="Spain", tier=1,
    ),
    TournamentReference(
        code="ISA", name_en="Italian Division 1", name_ch="意大利甲組聯賽",
        country="Italy", tier=1,
    ),
    TournamentReference(
        code="GSL", name_en="German Division 1", name_ch="德國甲組聯賽",
        country="Germany", tier=1,
    ),
    TournamentReference(
        code="FFL", name_en="French Division 1", name_ch="法國甲組聯賽",
        country="France", tier=1,
    ),
    TournamentReference(
        code="UCL", name_en="UE Champions", name_ch="歐洲聯賽冠軍盃",
        country="Europe", tier=1,
    ),
    TournamentReference(
        code="UEC", name_en="UE Cup", name_ch="歐霸盃",
        country="Europe", tier=2,
    ),
    TournamentReference(
        code="MLS", name_en="US Major League", name_ch="美國職業聯賽",
        country="USA", tier=1,
    ),
]


# ============================================================================
# Helper functions
# ============================================================================

def get_odds_type_name(code: str, lang: str = "en") -> str:
    """Get the display name for an odds type code.

    Args:
        code: Odds type code (e.g., "HAD")
        lang: Language ("en" or "ch")

    Returns:
        Display name, or the code itself if not found
    """
    for ot in ODDS_TYPES_DATA:
        if ot.code == code:
            return ot.name_en if lang == "en" else ot.name_ch
    return code


def get_tournament_name(code: str, lang: str = "en") -> str:
    """Get the display name for a tournament code.

    Args:
        code: Tournament code (e.g., "EPL")
        lang: Language ("en" or "ch")

    Returns:
        Display name, or the code itself if not found
    """
    for t in TOURNAMENTS_DATA:
        if t.code == code:
            return t.name_en if lang == "en" else t.name_ch
    return code
