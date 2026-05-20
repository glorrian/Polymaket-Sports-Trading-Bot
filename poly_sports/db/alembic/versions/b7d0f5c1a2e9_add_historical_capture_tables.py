"""add historical capture tables

Revision ID: b7d0f5c1a2e9
Revises: 393f34e2dcc3
Create Date: 2026-05-20 04:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d0f5c1a2e9"
down_revision: Union[str, Sequence[str], None] = "393f34e2dcc3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_data_runs_run_type", "data_runs", ["run_type"])
    op.create_index("ix_data_runs_source", "data_runs", ["source"])
    op.create_index("ix_data_runs_status", "data_runs", ["status"])
    op.create_index("ix_data_runs_started_at", "data_runs", ["started_at"])

    op.create_table(
        "raw_payloads",
        sa.Column("payload_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("request_params_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_size_bytes", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["data_runs.run_id"]),
        sa.PrimaryKeyConstraint("payload_id"),
    )
    op.create_index("ix_raw_payloads_run_id", "raw_payloads", ["run_id"])
    op.create_index("ix_raw_payloads_source", "raw_payloads", ["source"])
    op.create_index("ix_raw_payloads_status", "raw_payloads", ["status"])
    op.create_index("ix_raw_payloads_payload_hash", "raw_payloads", ["payload_hash"])
    op.create_index("ix_raw_payloads_captured_at", "raw_payloads", ["captured_at"])
    op.create_index("ix_raw_payloads_source_captured", "raw_payloads", ["source", "captured_at"])

    op.create_table(
        "polymarket_market_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("raw_payload_id", sa.String(length=64), nullable=True),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("market_id", sa.String(length=64), nullable=True),
        sa.Column("condition_id", sa.String(length=128), nullable=True),
        sa.Column("outcome_index", sa.Integer(), nullable=True),
        sa.Column("outcome_name", sa.String(length=256), nullable=True),
        sa.Column("token_id", sa.String(length=128), nullable=True),
        sa.Column("outcome_price", sa.Float(), nullable=True),
        sa.Column("last_trade_price", sa.Float(), nullable=True),
        sa.Column("best_bid", sa.Float(), nullable=True),
        sa.Column("best_ask", sa.Float(), nullable=True),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("market_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.payload_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["data_runs.run_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index("ix_polymarket_market_snapshots_run_id", "polymarket_market_snapshots", ["run_id"])
    op.create_index("ix_polymarket_market_snapshots_raw_payload_id", "polymarket_market_snapshots", ["raw_payload_id"])
    op.create_index("ix_polymarket_market_snapshots_event_id", "polymarket_market_snapshots", ["event_id"])
    op.create_index("ix_polymarket_market_snapshots_market_id", "polymarket_market_snapshots", ["market_id"])
    op.create_index("ix_polymarket_market_snapshots_token_id", "polymarket_market_snapshots", ["token_id"])
    op.create_index("ix_polymarket_market_snapshots_captured_at", "polymarket_market_snapshots", ["captured_at"])
    op.create_index("ix_pm_market_snapshots_market_time", "polymarket_market_snapshots", ["market_id", "captured_at"])
    op.create_index("ix_pm_market_snapshots_event_time", "polymarket_market_snapshots", ["event_id", "captured_at"])

    op.create_table(
        "sportsbook_event_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("raw_payload_id", sa.String(length=64), nullable=True),
        sa.Column("odds_event_id", sa.String(length=64), nullable=True),
        sa.Column("sport_key", sa.String(length=64), nullable=True),
        sa.Column("home_team", sa.String(length=256), nullable=True),
        sa.Column("away_team", sa.String(length=256), nullable=True),
        sa.Column("commence_time", sa.DateTime(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("event_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.payload_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["data_runs.run_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index("ix_sportsbook_event_snapshots_run_id", "sportsbook_event_snapshots", ["run_id"])
    op.create_index("ix_sportsbook_event_snapshots_raw_payload_id", "sportsbook_event_snapshots", ["raw_payload_id"])
    op.create_index("ix_sportsbook_event_snapshots_odds_event_id", "sportsbook_event_snapshots", ["odds_event_id"])
    op.create_index("ix_sportsbook_event_snapshots_sport_key", "sportsbook_event_snapshots", ["sport_key"])
    op.create_index("ix_sportsbook_event_snapshots_commence_time", "sportsbook_event_snapshots", ["commence_time"])
    op.create_index("ix_sportsbook_event_snapshots_captured_at", "sportsbook_event_snapshots", ["captured_at"])
    op.create_index("ix_sb_event_snapshots_event_time", "sportsbook_event_snapshots", ["odds_event_id", "captured_at"])

    op.create_table(
        "sportsbook_odds_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("raw_payload_id", sa.String(length=64), nullable=True),
        sa.Column("odds_event_id", sa.String(length=64), nullable=True),
        sa.Column("sport_key", sa.String(length=64), nullable=True),
        sa.Column("bookmaker_key", sa.String(length=128), nullable=True),
        sa.Column("bookmaker_title", sa.String(length=256), nullable=True),
        sa.Column("market_key", sa.String(length=64), nullable=True),
        sa.Column("outcome_name", sa.String(length=256), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("point", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("odds_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.payload_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["data_runs.run_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index("ix_sportsbook_odds_snapshots_run_id", "sportsbook_odds_snapshots", ["run_id"])
    op.create_index("ix_sportsbook_odds_snapshots_raw_payload_id", "sportsbook_odds_snapshots", ["raw_payload_id"])
    op.create_index("ix_sportsbook_odds_snapshots_odds_event_id", "sportsbook_odds_snapshots", ["odds_event_id"])
    op.create_index("ix_sportsbook_odds_snapshots_sport_key", "sportsbook_odds_snapshots", ["sport_key"])
    op.create_index("ix_sportsbook_odds_snapshots_bookmaker_key", "sportsbook_odds_snapshots", ["bookmaker_key"])
    op.create_index("ix_sportsbook_odds_snapshots_market_key", "sportsbook_odds_snapshots", ["market_key"])
    op.create_index("ix_sportsbook_odds_snapshots_outcome_name", "sportsbook_odds_snapshots", ["outcome_name"])
    op.create_index("ix_sportsbook_odds_snapshots_captured_at", "sportsbook_odds_snapshots", ["captured_at"])
    op.create_index("ix_sb_odds_snapshots_event_time", "sportsbook_odds_snapshots", ["odds_event_id", "captured_at"])
    op.create_index("ix_sb_odds_snapshots_outcome_time", "sportsbook_odds_snapshots", ["outcome_name", "captured_at"])

    op.create_table(
        "event_match_snapshots",
        sa.Column("match_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("pm_event_id", sa.String(length=64), nullable=True),
        sa.Column("pm_market_id", sa.String(length=64), nullable=True),
        sa.Column("odds_event_id", sa.String(length=64), nullable=True),
        sa.Column("sport_key", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("pm_home_team", sa.String(length=256), nullable=True),
        sa.Column("pm_away_team", sa.String(length=256), nullable=True),
        sa.Column("odds_home_team", sa.String(length=256), nullable=True),
        sa.Column("odds_away_team", sa.String(length=256), nullable=True),
        sa.Column("matched_at", sa.DateTime(), nullable=False),
        sa.Column("match_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["data_runs.run_id"]),
        sa.PrimaryKeyConstraint("match_id"),
    )
    op.create_index("ix_event_match_snapshots_run_id", "event_match_snapshots", ["run_id"])
    op.create_index("ix_event_match_snapshots_pm_event_id", "event_match_snapshots", ["pm_event_id"])
    op.create_index("ix_event_match_snapshots_pm_market_id", "event_match_snapshots", ["pm_market_id"])
    op.create_index("ix_event_match_snapshots_odds_event_id", "event_match_snapshots", ["odds_event_id"])
    op.create_index("ix_event_match_snapshots_sport_key", "event_match_snapshots", ["sport_key"])
    op.create_index("ix_event_match_snapshots_matched_at", "event_match_snapshots", ["matched_at"])
    op.create_index("ix_event_match_snapshots_pm_odds", "event_match_snapshots", ["pm_event_id", "odds_event_id"])

    op.create_table(
        "comparison_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("pm_event_id", sa.String(length=64), nullable=True),
        sa.Column("pm_market_id", sa.String(length=64), nullable=True),
        sa.Column("odds_event_id", sa.String(length=64), nullable=True),
        sa.Column("sport_key", sa.String(length=64), nullable=True),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("sportsbook_count", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("comparison_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["data_runs.run_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index("ix_comparison_snapshots_run_id", "comparison_snapshots", ["run_id"])
    op.create_index("ix_comparison_snapshots_pm_event_id", "comparison_snapshots", ["pm_event_id"])
    op.create_index("ix_comparison_snapshots_pm_market_id", "comparison_snapshots", ["pm_market_id"])
    op.create_index("ix_comparison_snapshots_odds_event_id", "comparison_snapshots", ["odds_event_id"])
    op.create_index("ix_comparison_snapshots_sport_key", "comparison_snapshots", ["sport_key"])
    op.create_index("ix_comparison_snapshots_captured_at", "comparison_snapshots", ["captured_at"])
    op.create_index("ix_comparison_snapshots_market_time", "comparison_snapshots", ["pm_market_id", "captured_at"])
    op.create_index("ix_comparison_snapshots_sport_time", "comparison_snapshots", ["sport_key", "captured_at"])

    op.create_table(
        "opportunity_snapshots",
        sa.Column("opportunity_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("signal_id", sa.String(length=64), nullable=True),
        sa.Column("pm_event_id", sa.String(length=64), nullable=True),
        sa.Column("pm_market_id", sa.String(length=64), nullable=True),
        sa.Column("odds_event_id", sa.String(length=64), nullable=True),
        sa.Column("outcome_name", sa.String(length=256), nullable=True),
        sa.Column("opportunity_type", sa.String(length=64), nullable=True),
        sa.Column("profit_margin", sa.Float(), nullable=True),
        sa.Column("delta_difference", sa.Float(), nullable=True),
        sa.Column("pm_price", sa.Float(), nullable=True),
        sa.Column("target_probability", sa.Float(), nullable=True),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("opportunity_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["data_runs.run_id"]),
        sa.PrimaryKeyConstraint("opportunity_id"),
    )
    op.create_index("ix_opportunity_snapshots_run_id", "opportunity_snapshots", ["run_id"])
    op.create_index("ix_opportunity_snapshots_signal_id", "opportunity_snapshots", ["signal_id"])
    op.create_index("ix_opportunity_snapshots_pm_event_id", "opportunity_snapshots", ["pm_event_id"])
    op.create_index("ix_opportunity_snapshots_pm_market_id", "opportunity_snapshots", ["pm_market_id"])
    op.create_index("ix_opportunity_snapshots_odds_event_id", "opportunity_snapshots", ["odds_event_id"])
    op.create_index("ix_opportunity_snapshots_outcome_name", "opportunity_snapshots", ["outcome_name"])
    op.create_index("ix_opportunity_snapshots_created_at", "opportunity_snapshots", ["created_at"])
    op.create_index("ix_opportunity_snapshots_market_time", "opportunity_snapshots", ["pm_market_id", "created_at"])

    op.create_table(
        "live_price_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("position_id", sa.String(length=64), nullable=True),
        sa.Column("market_id", sa.String(length=64), nullable=True),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("outcome_name", sa.String(length=256), nullable=True),
        sa.Column("token_id", sa.String(length=128), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["data_runs.run_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index("ix_live_price_snapshots_run_id", "live_price_snapshots", ["run_id"])
    op.create_index("ix_live_price_snapshots_position_id", "live_price_snapshots", ["position_id"])
    op.create_index("ix_live_price_snapshots_market_id", "live_price_snapshots", ["market_id"])
    op.create_index("ix_live_price_snapshots_event_id", "live_price_snapshots", ["event_id"])
    op.create_index("ix_live_price_snapshots_outcome_name", "live_price_snapshots", ["outcome_name"])
    op.create_index("ix_live_price_snapshots_token_id", "live_price_snapshots", ["token_id"])
    op.create_index("ix_live_price_snapshots_source", "live_price_snapshots", ["source"])
    op.create_index("ix_live_price_snapshots_captured_at", "live_price_snapshots", ["captured_at"])
    op.create_index("ix_live_price_snapshots_market_time", "live_price_snapshots", ["market_id", "captured_at"])
    op.create_index("ix_live_price_snapshots_outcome_time", "live_price_snapshots", ["outcome_name", "captured_at"])


def downgrade() -> None:
    op.drop_table("live_price_snapshots")
    op.drop_table("opportunity_snapshots")
    op.drop_table("comparison_snapshots")
    op.drop_table("event_match_snapshots")
    op.drop_table("sportsbook_odds_snapshots")
    op.drop_table("sportsbook_event_snapshots")
    op.drop_table("polymarket_market_snapshots")
    op.drop_table("raw_payloads")
    op.drop_table("data_runs")
