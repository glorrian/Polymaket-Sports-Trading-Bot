"""Opt-in smoke checks for live Polymarket API contracts."""

import os

import pytest

from poly_sports.data_fetching.fetch_sports_markets import fetch_sports_markets
from poly_sports.market_data.price_feed import PolymarketWsPriceFeed, parse_clob_token_ids


pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv("RUN_POLYMARKET_SMOKE") != "1",
        reason="set RUN_POLYMARKET_SMOKE=1 to hit live Polymarket APIs",
    ),
]


def _market_with_token():
    markets = fetch_sports_markets("https://gamma-api.polymarket.com", limit=25)
    assert markets, "Gamma sports markets response should include at least one market"

    for market in markets:
        token_ids = parse_clob_token_ids(market.get("clobTokenIds"))
        outcomes = market.get("outcomes") or market.get("market_outcomes")
        outcome_prices = market.get("outcomePrices") or market.get("market_outcomePrices")
        if token_ids and outcomes and outcome_prices:
            return market, token_ids[0]

    raise AssertionError("Expected at least one active sports market with clobTokenIds")


def test_gamma_sports_markets_include_valid_clob_tokens():
    market, token_id = _market_with_token()

    assert market.get("id") or market.get("market_id")
    assert str(token_id).isdigit()
    assert 20 <= len(str(token_id)) <= 90
    assert market.get("outcomes") or market.get("market_outcomes")
    assert market.get("outcomePrices") or market.get("market_outcomePrices")


@pytest.mark.asyncio
async def test_polymarket_market_websocket_returns_valid_quote():
    market, token_id = _market_with_token()
    feed = PolymarketWsPriceFeed(quote_stale_ms=15000)
    try:
        await feed.subscribe_assets({
            token_id: {
                "market_id": market.get("id") or market.get("market_id"),
                "event_id": market.get("event_id"),
                "outcome_name": "smoke",
            }
        })
        assert await feed.wait_for_assets([token_id], timeout_ms=15000)
        quote = feed.get_quote_by_asset(token_id)
        assert quote is not None

        observed = [
            value
            for value in [quote.best_bid, quote.best_ask, quote.midpoint, quote.last_trade_price]
            if value is not None
        ]
        assert observed, "WS quote should include bid/ask, midpoint, or last trade"
        assert all(0 <= value <= 1 for value in observed)
    finally:
        await feed.stop()
