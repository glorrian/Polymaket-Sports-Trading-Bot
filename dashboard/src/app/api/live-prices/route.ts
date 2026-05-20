import { NextResponse } from "next/server";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

const GAMMA_API = "https://gamma-api.polymarket.com";
const DATA_DIR = join(process.cwd(), "..", "data", "trading");

interface Position {
  position_id: string;
  market_id: string;
  outcome_name: string;
  entry_price: number;
  size_usd: number;
  status: string;
}

interface State {
  positions: Position[];
}

export async function GET() {
  try {
    const statePath = join(DATA_DIR, "state.json");
    if (!existsSync(statePath)) return NextResponse.json({});

    const state: State = JSON.parse(readFileSync(statePath, "utf-8"));
    const openPositions = state.positions.filter((p) => p.status === "OPEN");
    const closedPositions = state.positions.filter((p) => p.status !== "OPEN");
    const allPositions = state.positions;
    if (allPositions.length === 0) return NextResponse.json({});

    const marketIds = [...new Set(allPositions.map((p) => p.market_id))];
    const marketData: Record<string, { prices: { price: number; outcome_name: string }[]; slug: string | null }> = {};

    await Promise.all(
      marketIds.map(async (mid) => {
        try {
          const res = await fetch(`${GAMMA_API}/markets/${mid}`, {
            headers: {
              Accept: "application/json",
              "User-Agent": "Mozilla/5.0",
            },
            signal: AbortSignal.timeout(5000),
          });
          if (!res.ok) return;
          const m = await res.json();

          let outcomePrices: number[] = [];
          try {
            outcomePrices = JSON.parse(m.outcomePrices || "[]").map(Number);
          } catch { /* */ }
          let outcomes: string[] = [];
          try {
            outcomes = JSON.parse(m.outcomes || "[]");
          } catch {
            outcomes = (m.outcomes || "").split(",").map((s: string) => s.trim());
          }

          marketData[mid] = {
            prices: outcomes.map((name, i) => ({ price: outcomePrices[i] ?? 0, outcome_name: name })),
            slug: m.slug || null,
          };
        } catch { /* skip */ }
      })
    );

    const result: Record<
      string,
      {
        current_price: number;
        bid: number;
        ask: number;
        live_pnl: number;
        live_pnl_pct: number;
        polymarket_url: string | null;
      }
    > = {};

    for (const pos of openPositions) {
      const md = marketData[pos.market_id];
      if (!md) continue;

      const match = md.prices.find(
        (p) =>
          p.outcome_name.toLowerCase().includes(pos.outcome_name.toLowerCase()) ||
          pos.outcome_name.toLowerCase().includes(p.outcome_name.toLowerCase())
      );
      if (!match || match.price <= 0) continue;

      const livePnl = pos.size_usd * (match.price / pos.entry_price - 1);
      const livePnlPct = (match.price / pos.entry_price - 1) * 100;

      result[pos.position_id] = {
        current_price: match.price,
        bid: 0,
        ask: 0,
        live_pnl: Math.round(livePnl * 100) / 100,
        live_pnl_pct: Math.round(livePnlPct * 100) / 100,
        polymarket_url: md.slug ? `https://polymarket.com/event/${md.slug}` : null,
      };
    }

    for (const pos of closedPositions) {
      const md = marketData[pos.market_id];
      if (!md || !md.slug) continue;
      if (result[pos.position_id]) continue;
      result[pos.position_id] = {
        current_price: 0,
        bid: 0,
        ask: 0,
        live_pnl: 0,
        live_pnl_pct: 0,
        polymarket_url: `https://polymarket.com/event/${md.slug}`,
      };
    }

    return NextResponse.json(result);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
