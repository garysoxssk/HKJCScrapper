"""Pytest configuration and shared fixtures."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def sample_response_data():
    """Load the sample API response JSON."""
    sample_path = Path(__file__).parent.parent / "docs" / "api" / "base_api_sample_response.json"
    with open(sample_path) as f:
        return json.load(f)


@pytest.fixture
def sample_matches(sample_response_data):
    """Parse sample response into Match objects."""
    from hkjc_scrapper.parser import parse_matches_response
    return parse_matches_response(sample_response_data)
