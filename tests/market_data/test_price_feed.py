"""Unit tests for Polymarket WS price feed parsing."""

from datetime import timedelta

import pytest

from poly_sports.market_data.price_feed import PolymarketWsPriceFeed, PriceQuote, parse_clob_token_ids, utc_now


def test_parse_clob_token_ids_accepts_json_string_and_list():
    assert parse_clob_token_ids('["tok-a", "tok-b"]') == ["tok-a", "tok-b"]
    assert parse_clob_token_ids(["tok-a", 123]) == ["tok-a", "123"]
    assert parse_clob_token_ids("tok-a,tok-b") == ["tok-a", "tok-b"]


def test_book_message_sets_best_bid_ask_and_midpoint():
    feed = PolymarketWsPriceFeed()
    feed.asset_metadata["tok-a"] = {"market_id": "m1", "outcome_name": "Team A"}

    quote = feed.apply_message(
        {
            "event_type": "book",
            "asset_id": "tok-a",
            "bids": [{"price": "0.48", "size": "10"}, {"price": "0.50", "size": "5"}],
            "asks": [{"price": "0.54", "size": "9"}, {"price": "0.52", "size": "4"}],
            "timestamp": "123",
        }
    )

    assert quote is not None
    assert quote.market_id == "m1"
    assert quote.best_bid == 0.50
    assert quote.best_ask == 0.52
    assert quote.midpoint == 0.51
    assert quote.executable_price("BUY") == 0.52
    assert quote.executable_price("SELL") == 0.50


def test_price_change_updates_top_of_book():
    feed = PolymarketWsPriceFeed()
    feed.apply_message(
        {
            "event_type": "price_change",
            "price_changes": [
                {
                    "asset_id": "tok-a",
                    "best_bid": "0.41",
                    "best_ask": "0.44",
                    "price": "0.42",
                    "side": "BUY",
                }
            ],
        }
    )

    quote = feed.get_quote_by_asset("tok-a")
    assert quote is not None
    assert quote.best_bid == 0.41
    assert quote.best_ask == 0.44
    assert quote.spread == pytest.approx(0.03)


def test_best_bid_ask_and_last_trade_messages():
    feed = PolymarketWsPriceFeed()
    feed.apply_message(
        {
            "event_type": "best_bid_ask",
            "asset_id": "tok-a",
            "best_bid": "0.73",
            "best_ask": "0.77",
            "spread": "0.04",
        }
    )
    feed.apply_message(
        {
            "event_type": "last_trade_price",
            "asset_id": "tok-a",
            "price": "0.75",
            "side": "BUY",
        }
    )

    quote = feed.get_quote_by_asset("tok-a")
    assert quote is not None
    assert quote.best_bid == 0.73
    assert quote.best_ask == 0.77
    assert quote.last_trade_price == 0.75
    assert quote.last_trade_side == "BUY"


def test_quote_staleness():
    quote = PriceQuote(asset_id="tok-a", best_bid=0.4, best_ask=0.5)
    quote.received_at = utc_now() - timedelta(seconds=10)

    assert quote.is_stale(5000)


def test_executable_price_preserves_zero_bid_or_ask():
    quote = PriceQuote(asset_id="tok-a", best_bid=0.0, best_ask=0.02)

    assert quote.executable_price("SELL") == 0.0
    assert quote.executable_price("BUY") == 0.02
