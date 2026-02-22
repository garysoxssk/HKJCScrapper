"""HKJC GraphQL API client with browser simulation."""

import time
from typing import Optional

import requests

from hkjc_scrapper.config import Settings


# GraphQL query templates
# Note: HKJC API uses query whitelisting - query structure must exactly match approved format
# This is the exact query format from the real API, with all parameters defined
MATCH_LIST_QUERY = """
query matchList($startIndex: Int, $endIndex: Int,$startDate: String, $endDate: String, $matchIds: [String], $tournIds: [String], $fbOddsTypes: [FBOddsType]!, $fbOddsTypesM: [FBOddsType]!, $inplayOnly: Boolean, $featuredMatchesOnly: Boolean, $frontEndIds: [String], $earlySettlementOnly: Boolean, $showAllMatch: Boolean) {
  matches(startIndex: $startIndex,endIndex: $endIndex, startDate: $startDate, endDate: $endDate, matchIds: $matchIds, tournIds: $tournIds, fbOddsTypes: $fbOddsTypesM, inplayOnly: $inplayOnly, featuredMatchesOnly: $featuredMatchesOnly, frontEndIds: $frontEndIds, earlySettlementOnly: $earlySettlementOnly, showAllMatch: $showAllMatch) {
    id
    frontEndId
    matchDate
    kickOffTime
    status
    updateAt
    sequence
    esIndicatorEnabled
    homeTeam {
      id
      name_en
      name_ch
    }
    awayTeam {
      id
      name_en
      name_ch
    }
    tournament {
      id
      frontEndId
      nameProfileId
      isInteractiveServiceAvailable
      code
      name_en
      name_ch
    }
    isInteractiveServiceAvailable
    inplayDelay
    venue {
      code
      name_en
      name_ch
    }
    tvChannels {
      code
      name_en
      name_ch
    }
    liveEvents {
      id
      code
    }
    featureStartTime
    featureMatchSequence
    poolInfo {
      normalPools
      inplayPools
      sellingPools
      ntsInfo
      entInfo
      definedPools
      ngsInfo {
        str
        name_en
        name_ch
        instNo
      }
      agsInfo {
        str
        name_en
        name_ch
      }
    }
    runningResult {
      homeScore
      awayScore
      corner
      homeCorner
      awayCorner
    }
    runningResultExtra {
      homeScore
      awayScore
      corner
      homeCorner
      awayCorner
    }
    adminOperation {
      remark {
        typ
      }
    }
    foPools(fbOddsTypes: $fbOddsTypes) {
      id
      status
      oddsType
      instNo
      inplay
      name_ch
      name_en
      updateAt
      expectedSuspendDateTime
      lines {
        lineId
        status
        condition
        main
        combinations {
          combId
          str
          status
          offerEarlySettlement
          currentOdds
          selections {
            selId
            str
            name_ch
            name_en
          }
        }
      }
    }
  }
}
"""


class HKJCGraphQLClient:
    """Client for HKJC GraphQL API with browser simulation."""

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize the client with settings."""
        self.settings = settings or Settings()
        self.endpoint = self.settings.GRAPHQL_ENDPOINT
        self.session = requests.Session()

        # Set browser-like headers
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "Referer": "https://bet.hkjc.com/",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Origin": "https://bet.hkjc.com",
            "sec-fetch-site": "same-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "sec-ch-ua": '"Chromium";v="140", "Google Chrome";v="140", "Not A Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        })

    def send_options_preflight(self) -> requests.Response:
        """Send OPTIONS preflight request for CORS."""
        response = self.session.options(
            self.endpoint,
            headers={
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            }
        )
        response.raise_for_status()
        return response

    def send_basic_match_list_request(
        self,
        start_index: Optional[int] = None,
        end_index: Optional[int] = None
    ) -> dict:
        """
        Fetch basic match list without odds.

        Args:
            start_index: Starting index for pagination (default from settings)
            end_index: Ending index for pagination (default from settings)

        Returns:
            JSON response as dict

        Raises:
            requests.HTTPError: If request fails
        """
        # Use whitelisted query with all parameters (set unused to null)
        variables = {
            "fbOddsTypes": [],  # Required - pass empty to fetch no odds
            "fbOddsTypesM": [],  # Required - pass empty for basic query
            "inplayOnly": False,
            "featuredMatchesOnly": False,
            "startDate": None,
            "endDate": None,
            "tournIds": None,
            "matchIds": None,
            "tournId": None,
            "tournProfileId": None,
            "subType": None,
            "startIndex": start_index,
            "endIndex": end_index,
            "frontEndIds": None,
            "earlySettlementOnly": False,
            "showAllMatch": False,
            "tday": None,
            "tIdList": None,
        }

        payload = {
            "query": MATCH_LIST_QUERY,
            "variables": variables,
        }

        response = self.session.post(self.endpoint, json=payload, timeout=30)

        # Log error response body for debugging
        if response.status_code >= 400:
            print(f"ERROR {response.status_code}: {response.text[:500]}")

        response.raise_for_status()
        return response.json()

    def send_detailed_match_list_request(
        self,
        odds_types: list[str],
        start_index: Optional[int] = None,
        end_index: Optional[int] = None
    ) -> dict:
        """
        Fetch detailed match list with odds.

        Args:
            odds_types: List of odds type codes to fetch (e.g., ["HAD", "HHA"])
            start_index: Starting index for pagination
            end_index: Ending index for pagination

        Returns:
            JSON response as dict

        Raises:
            requests.HTTPError: If request fails
        """
        # Use whitelisted query with all parameters
        variables = {
            "fbOddsTypes": odds_types,
            "fbOddsTypesM": odds_types,  # Same odds types for both
            "inplayOnly": False,
            "featuredMatchesOnly": False,
            "startDate": None,
            "endDate": None,
            "tournIds": None,
            "matchIds": None,
            "tournId": None,
            "tournProfileId": None,
            "subType": None,
            "startIndex": start_index,
            "endIndex": end_index,
            "frontEndIds": None,
            "earlySettlementOnly": False,
            "showAllMatch": False,
            "tday": None,
            "tIdList": None,
        }

        payload = {
            "query": MATCH_LIST_QUERY,
            "variables": variables,
        }

        response = self.session.post(self.endpoint, json=payload, timeout=30)

        # Log error response body for debugging
        if response.status_code >= 400:
            print(f"ERROR {response.status_code}: {response.text[:500]}")

        response.raise_for_status()
        return response.json()

    def fetch_matches_for_odds(
        self,
        odds_types: list[str],
        start_index: Optional[int] = None,
        end_index: Optional[int] = None,
        with_preflight: bool = True,
        delay_ms: int = 500
    ) -> dict:
        """
        Full sequence: preflight + detailed query with odds.

        Args:
            odds_types: List of odds type codes
            start_index: Starting index
            end_index: Ending index
            with_preflight: Whether to send OPTIONS preflight (default True)
            delay_ms: Delay in milliseconds between preflight and request

        Returns:
            JSON response as dict
        """
        if with_preflight:
            self.send_options_preflight()
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

        return self.send_detailed_match_list_request(
            odds_types=odds_types,
            start_index=start_index,
            end_index=end_index
        )
