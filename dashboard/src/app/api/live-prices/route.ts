import { NextResponse } from "next/server";
import { getOpenPositions, getClosedPositions } from "@/lib/db";

const GAMMA_API = "https://gamma-api.polymarket.com";

export async function GET() {
  try {
    const openPositions = getOpenPositions();
    const closedPositions = getClosedPositions();

    if (openPositions.length === 0 && closedPositions.length === 0) {
      return NextResponse.json({});
    }

    const marketIds = [...new Set([
      ...openPositions.map((p) => p.market_id as string),
      ...closedPositions.map((p) => p.market_id as string),
    ])];

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
      const md = marketData[pos.market_id as string];
      if (!md) continue;

      const match = md.prices.find(
        (p) =>
          p.outcome_name.toLowerCase().includes((pos.outcome_name as string).toLowerCase()) ||
          (pos.outcome_name as string).toLowerCase().includes(p.outcome_name.toLowerCase())
      );
      if (!match || match.price <= 0) continue;

      const entry_price = pos.entry_price as number;
      const size_usd = pos.size_usd as number;
      const livePnl = size_usd * (match.price / entry_price - 1);
      const livePnlPct = (match.price / entry_price - 1) * 100;

      result[pos.position_id as string] = {
        current_price: match.price,
        bid: 0,
        ask: 0,
        live_pnl: Math.round(livePnl * 100) / 100,
        live_pnl_pct: Math.round(livePnlPct * 100) / 100,
        polymarket_url: md.slug ? `https://polymarket.com/event/${md.slug}` : null,
      };
    }

    for (const pos of closedPositions) {
      const md = marketData[pos.market_id as string];
      if (!md || !md.slug) continue;
      if (result[pos.position_id as string]) continue;
      result[pos.position_id as string] = {
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