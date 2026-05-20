"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";

interface Summary {
  updated_at: string;
  open_count: number;
  closed_count: number;
  total_unrealized_pnl: number;
  total_realized_pnl: number;
  total_fees: number;
  total_invested: number;
  net_pnl: number;
  realized_pnl_today: number;
  closed_pnl: {
    total_realized: number;
    total_fees: number;
    net_realized: number;
    wins: number;
    losses: number;
    win_rate: number;
    avg_win: number;
    avg_loss: number;
    avg_pnl: number;
    total_volume: number;
    roi_pct: number;
    best_trade: number;
    worst_trade: number;
  };
}

interface Position {
  position_id: string;
  signal_id: string;
  market_id: string;
  event_id: string;
  outcome_name: string;
  side: string;
  status: string;
  size_usd: number;
  entry_price: number;
  entry_time: string;
  target_price: number;
  stop_loss_price: number;
  take_profit_price: number;
  max_holding_minutes: number;
  entry_fees_usd: number;
  exit_price: number | null;
  exit_time: string | null;
  exit_reason: string | null;
  exit_fees_usd: number;
  realized_pnl_usd: number;
  unrealized_pnl_usd: number;
  metadata: { signal_confidence: number };
}

interface LivePrice {
  current_price: number;
  bid: number;
  ask: number;
  live_pnl: number;
  live_pnl_pct: number;
  polymarket_url: string | null;
}

interface CheckEntry {
  timestamp: string;
  position_id: string;
  market_id: string;
  outcome_name: string;
  entry_price: number;
  current_price: number | null;
  target_price: number;
  stop_loss_price: number;
  take_profit_price: number;
  unrealized_pnl_usd: number;
  should_exit: boolean;
  reason: string;
  size_usd: number;
  entry_context?: {
    signal_confidence: number;
    expected_profit_pct: number;
    spread: number;
    liquidity: number;
    suggested_price: number;
    side: string;
    sportsbook_count: number;
    opportunity_type: string;
    matched_outcomes: { pm_outcome: string; sb_outcome: string; pm_price: number; sb_implied_prob: number }[];
    sell_points: { description: string; target_price: number; profit_percentage: number; confidence: string }[];
  };
  realized_pnl_usd?: number;
  exit_price?: number;
}

interface RiskEvent {
  timestamp: string;
  signal_id: string;
  market_id: string;
  allow: boolean;
  reason_code: string;
  message: string;
}

function fmt(v: number, decimals = 2) {
  return v.toFixed(decimals);
}

function pnlColor(v: number) {
  return v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-muted-foreground";
}

function pnlSign(v: number) {
  return v > 0 ? "+" : "";
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString("ru-RU");
}

function HoldingTimer({ entryTime, maxMinutes }: { entryTime: string; maxMinutes: number }) {
  const [label, setLabel] = useState("");

  useEffect(() => {
    const update = () => {
      const diffMin = Math.floor((Date.now() - new Date(entryTime).getTime()) / 60000);
      const remaining = Math.max(0, maxMinutes - diffMin);
      const h = Math.floor(remaining / 60);
      const m = remaining % 60;
      setLabel(remaining === 0 ? "ИСТЕКЛО" : `${h}ч ${m}м`);
    };
    update();
    const iv = setInterval(update, 30000);
    return () => clearInterval(iv);
  }, [entryTime, maxMinutes]);

  const remaining = maxMinutes - Math.floor((Date.now() - new Date(entryTime).getTime()) / 60000);
  const pct = Math.min(100, Math.max(0, ((maxMinutes - remaining) / maxMinutes) * 100));

  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${remaining <= 30 ? "bg-red-500" : remaining <= 60 ? "bg-yellow-500" : "bg-green-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

function PositionDetail({
  position,
  checks,
  livePrice,
  onClose,
}: {
  position: Position;
  checks: CheckEntry[];
  livePrice: LivePrice | undefined;
  onClose: () => void;
}) {
  const entryCheck = checks.find((c) => c.reason === "entry");
  const ctx = entryCheck?.entry_context;
  const monitorChecks = checks.filter((c) => c.reason !== "entry");

  const currentPrice = livePrice?.current_price ?? (position.status === "OPEN" ? null : position.exit_price);
  const livePnl = livePrice?.live_pnl;
  const livePnlPct = livePrice?.live_pnl_pct;

  const priceMin = position.stop_loss_price;
  const priceMax = position.take_profit_price;
  const priceRange = priceMax - priceMin || 1;

  const priceBarPct = (p: number) => Math.min(100, Math.max(0, ((p - priceMin) / priceRange) * 100));

  return (
    <div className="fixed inset-0 bg-black/80 z-50 flex items-start justify-center px-4 overflow-y-auto" onClick={onClose}>
      <div className="w-full max-w-3xl my-8 animate-in fade-in-0 slide-in-from-bottom-4" onClick={(e) => e.stopPropagation()}>
        <div className="bg-card border border-border rounded-xl overflow-hidden shadow-2xl">
          {/* Header */}
          <div className="px-6 py-5 border-b border-border flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3">
                <h2 className="text-xl font-semibold">{position.outcome_name}</h2>
                <Badge variant={position.status === "OPEN" ? "default" : "secondary"}>
                  {position.status === "OPEN" ? "Открыта" : "Закрыта"}
                </Badge>
                {livePrice?.polymarket_url && (
                  <a
                    href={livePrice.polymarket_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2"
                  >
                    Polymarket ↗
                  </a>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-1.5 font-mono">{position.position_id}</p>
            </div>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-2xl leading-none p-1">&times;</button>
          </div>

          <div className="p-6 space-y-8">
            {/* Price overview */}
            <div className="flex items-end justify-between gap-6">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Живой PnL</p>
                {livePnl != null ? (
                  <div className={`text-3xl font-bold tracking-tight ${pnlColor(livePnl)}`}>
                    {pnlSign(livePnl)}${fmt(livePnl)}
                    <span className="text-lg ml-1.5 opacity-70">{pnlSign(livePnlPct!)}{fmt(livePnlPct!)}%</span>
                  </div>
                ) : (
                  <div className="text-3xl font-bold text-muted-foreground">—</div>
                )}
              </div>
              <div className="text-right">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">
                  {position.status === "OPEN" ? "Текущая цена" : "Цена выхода"}
                </p>
                <div className="text-2xl font-bold font-mono">
                  {currentPrice ? `${fmt(currentPrice * 100, 1)}c` : "—"}
                </div>
              </div>
            </div>

            {/* Price bar */}
            <div>
              <div className="relative h-2 bg-muted rounded-full">
                {/* SL zone */}
                <div className="absolute left-0 top-0 h-full w-[15%] bg-red-900/30 rounded-l-full" />
                {/* TP zone */}
                <div className="absolute right-0 top-0 h-full w-[15%] bg-green-900/30 rounded-r-full" />

                {/* Entry marker */}
                <div
                  className="absolute top-1/2 -translate-y-1/2 w-0.5 h-5 bg-foreground/50"
                  style={{ left: `${priceBarPct(position.entry_price)}%` }}
                />

                {/* Current price marker */}
                {currentPrice && (
                  <div
                    className={`absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border-2 border-card ${currentPrice >= position.entry_price ? "bg-green-400" : "bg-red-400"}`}
                    style={{ left: `${priceBarPct(currentPrice)}%`, transform: "translate(-50%, -50%)" }}
                  />
                )}

                {/* Target marker */}
                <div
                  className="absolute top-1/2 -translate-y-1/2 w-0.5 h-3 bg-green-400"
                  style={{ left: `${priceBarPct(position.target_price)}%` }}
                />
              </div>
              <div className="flex justify-between mt-1.5 text-xs font-mono text-muted-foreground">
                <span className="text-red-400">СЛ {fmt(priceMin * 100, 1)}c</span>
                <span>Вход {fmt(position.entry_price * 100, 1)}c</span>
                <span className="text-green-400">Цель {fmt(position.target_price * 100, 1)}c</span>
                <span className="text-green-400">ТП {fmt(priceMax * 100, 1)}c</span>
              </div>
            </div>

            {/* Key metrics row */}
            <div className="grid grid-cols-4 gap-px bg-border rounded-lg overflow-hidden">
              {[
                { label: "Размер", value: `$${fmt(position.size_usd)}` },
                { label: "Комиссии", value: `$${fmt(position.entry_fees_usd + position.exit_fees_usd, 4)}` },
                { label: "Bid", value: livePrice ? `${fmt(livePrice.bid * 100, 1)}c` : "—" },
                { label: "Ask", value: livePrice ? `${fmt(livePrice.ask * 100, 1)}c` : "—" },
              ].map((item) => (
                <div key={item.label} className="bg-card px-4 py-3">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{item.label}</p>
                  <p className="text-sm font-mono mt-0.5">{item.value}</p>
                </div>
              ))}
            </div>

            {/* Entry context */}
            {ctx && (
              <div className="bg-muted/30 rounded-lg p-5 space-y-4">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Вводные данные входа</h3>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Ожидаемая прибыль</p>
                    <p className="text-sm font-mono text-green-400 mt-0.5">+{(ctx.expected_profit_pct * 100).toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Спред на входе</p>
                    <p className="text-sm font-mono mt-0.5">{(ctx.spread * 100).toFixed(1)}c</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Ликвидность</p>
                    <p className="text-sm font-mono mt-0.5">${(ctx.liquidity / 1000).toFixed(0)}K</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Букмекеров</p>
                    <p className="text-sm font-mono mt-0.5">{ctx.sportsbook_count ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Тип</p>
                    <p className="text-sm font-mono mt-0.5">{ctx.opportunity_type ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Уверенность</p>
                    <p className="text-sm font-mono mt-0.5">{(ctx.signal_confidence * 100).toFixed(0)}%</p>
                  </div>
                </div>

                {ctx.matched_outcomes && ctx.matched_outcomes.length > 0 && (
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">Совпадения исходов</p>
                    <div className="space-y-1">
                      {ctx.matched_outcomes.map((mo, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs font-mono">
                          <span className="px-1.5 py-0.5 bg-primary/10 rounded text-primary">{mo.pm_outcome}</span>
                          <span className="text-muted-foreground">@ {mo.pm_price}</span>
                          <span className="text-muted-foreground">&larr;</span>
                          <span className="px-1.5 py-0.5 bg-green-900/30 rounded text-green-400">{mo.sb_outcome}</span>
                          <span className="text-muted-foreground">@ {(mo.sb_implied_prob * 100).toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {ctx.sell_points && ctx.sell_points.length > 0 && (
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">Точки выхода</p>
                    <div className="flex gap-2 flex-wrap">
                      {ctx.sell_points.map((sp, i) => (
                        <span key={i} className="inline-flex items-center gap-1.5 text-xs font-mono px-2.5 py-1 bg-border/50 rounded-full">
                          <span className="text-muted-foreground">{sp.description}</span>
                          <span className="text-green-400">+{(sp.profit_percentage * 100).toFixed(1)}%</span>
                          <span className="text-muted-foreground">@ {fmt(sp.target_price * 100, 1)}c</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Check history */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  История проверок
                </h3>
                <span className="text-xs text-muted-foreground font-mono">{monitorChecks.length}</span>
              </div>
              {monitorChecks.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">Пока нет проверок</p>
              ) : (
                <div className="max-h-72 overflow-y-auto rounded-lg border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-[10px] uppercase tracking-wider">Время</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider text-right">Цена</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider text-right">PnL</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">Решение</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">Причина</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {[...monitorChecks].reverse().map((c, i) => (
                        <TableRow key={i}>
                          <TableCell className="text-xs text-muted-foreground whitespace-nowrap py-2">
                            {formatTime(c.timestamp)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-2">
                            {c.current_price != null ? `${fmt(c.current_price * 100, 1)}c` : "—"}
                          </TableCell>
                          <TableCell className={`text-right font-mono text-xs py-2 ${pnlColor(c.unrealized_pnl_usd)}`}>
                            {pnlSign(c.unrealized_pnl_usd)}${fmt(c.unrealized_pnl_usd)}
                          </TableCell>
                          <TableCell className="py-2">
                            {c.should_exit ? (
                              <span className="inline-flex items-center gap-1 text-xs text-red-400">
                                <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                                Выход
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50" />
                                Держим
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground py-2 font-mono">
                            {c.reason}
                            {c.realized_pnl_usd != null && (
                              <span className={`ml-1.5 ${pnlColor(c.realized_pnl_usd)}`}>
                                {pnlSign(c.realized_pnl_usd)}${fmt(c.realized_pnl_usd)}
                              </span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [openPositions, setOpenPositions] = useState<Position[]>([]);
  const [closedPositions, setClosedPositions] = useState<Position[]>([]);
  const [riskEvents, setRiskEvents] = useState<RiskEvent[]>([]);
  const [livePrices, setLivePrices] = useState<Record<string, LivePrice>>({});
  const [checksByPos, setChecksByPos] = useState<Record<string, CheckEntry[]>>({});
  const [selectedPosition, setSelectedPosition] = useState<Position | null>(null);
  const [sortKey, setSortKey] = useState<string>("unrealized_pnl");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const refresh = useCallback(async () => {
    const [sumRes, openRes, closedRes, riskRes, liveRes, checksRes] = await Promise.all([
      fetch("/api/summary"),
      fetch("/api/positions?status=open"),
      fetch("/api/positions?status=closed"),
      fetch("/api/risk-events"),
      fetch("/api/live-prices"),
      fetch("/api/checks"),
    ]);
    if (sumRes.ok) setSummary(await sumRes.json());
    if (openRes.ok) setOpenPositions(await openRes.json());
    if (closedRes.ok) setClosedPositions(await closedRes.json());
    if (riskRes.ok) setRiskEvents(await riskRes.json());
    if (liveRes.ok) setLivePrices(await liveRes.json());
    if (checksRes.ok) setChecksByPos(await checksRes.json());
  }, []);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 15000);
    return () => clearInterval(iv);
  }, [refresh]);

  const deniedCount = riskEvents.filter((r) => !r.allow).length;
  const approvedCount = riskEvents.filter((r) => r.allow).length;

  const totalLivePnl = openPositions.reduce((s, p) => {
    const lp = livePrices[p.position_id];
    return s + (lp?.live_pnl ?? p.unrealized_pnl_usd);
  }, 0);

  type SortVal = number | string;
  function getSortVal(pos: Position, key: string): SortVal {
    const lp = livePrices[pos.position_id];
    switch (key) {
      case "outcome_name": return pos.outcome_name;
      case "size_usd": return pos.size_usd;
      case "entry_price": return pos.entry_price;
      case "current_price": return lp?.current_price ?? 0;
      case "target_price": return pos.target_price;
      case "stop_loss_price": return pos.stop_loss_price;
      case "unrealized_pnl": return lp?.live_pnl ?? pos.unrealized_pnl_usd;
      case "pnl_pct": return lp?.live_pnl_pct ?? 0;
      case "entry_time": return pos.entry_time;
      case "exit_price": return pos.exit_price ?? 0;
      case "exit_time": return pos.exit_time ?? "";
      case "exit_reason": return pos.exit_reason ?? "";
      case "realized_pnl": return pos.realized_pnl_usd;
      case "realized_pnl_pct": return pos.size_usd > 0 ? (pos.realized_pnl_usd / pos.size_usd) * 100 : 0;
      default: return 0;
    }
  }

  function sortPositions(positions: Position[]): Position[] {
    return [...positions].sort((a, b) => {
      const va = getSortVal(a, sortKey);
      const vb = getSortVal(b, sortKey);
      const cmp = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }

  function SortHead({ label, colKey, className }: { label: string; colKey: string; className?: string }) {
    const active = sortKey === colKey;
    return (
      <TableHead className={`cursor-pointer select-none hover:text-foreground ${className || ""}`}
        onClick={() => {
          if (active) setSortDir((d) => d === "asc" ? "desc" : "asc");
          else { setSortKey(colKey); setSortDir("desc"); }
        }}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          {active && <span className="text-xs opacity-60">{sortDir === "asc" ? "↑" : "↓"}</span>}
        </span>
      </TableHead>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Торговый дашборд Polymarket</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {summary ? `Обновлено: ${formatTime(summary.updated_at)}` : "Загрузка..."}
            </p>
          </div>
          <Badge variant="outline" className="text-sm px-3 py-1">
            Бумажная торговля
          </Badge>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Живой PnL
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold ${pnlColor(totalLivePnl)}`}>
                {pnlSign(totalLivePnl)}${fmt(totalLivePnl)}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Нереализованный PnL
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold ${summary ? pnlColor(summary.total_unrealized_pnl) : ""}`}>
                {summary ? `${pnlSign(summary.total_unrealized_pnl)}$${fmt(summary.total_unrealized_pnl)}` : "—"}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Открытые / Закрытые
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {summary ? (
                  <>
                    <span className="text-blue-400">{summary.open_count}</span>
                    <span className="text-muted-foreground mx-1">/</span>
                    <span className="text-green-400">{summary.closed_count}</span>
                  </>
                ) : "—"}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Вложено всего
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {summary ? `$${fmt(summary.total_invested)}` : "—"}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Комиссии: {summary ? `$${fmt(summary.total_fees)}` : "—"}
              </p>
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-2 gap-4 mb-8">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Сигналы одобрены
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-400">{approvedCount}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Сигналы отклонены
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-400">{deniedCount}</div>
            </CardContent>
          </Card>
        </div>

        {summary?.closed_pnl && summary.closed_count > 0 && (
          <Card className="mb-8">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Статистика закрытых сделок
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-7 gap-px bg-border rounded-lg overflow-hidden">
                {[
                  { label: "Реализ. PnL", value: `${pnlSign(summary.closed_pnl.total_realized)}$${fmt(summary.closed_pnl.total_realized)}`, color: pnlColor(summary.closed_pnl.total_realized) },
                  { label: "Комиссии", value: `$${fmt(summary.closed_pnl.total_fees)}` },
                  { label: "Чистый PnL", value: `${pnlSign(summary.closed_pnl.net_realized)}$${fmt(summary.closed_pnl.net_realized)}`, color: pnlColor(summary.closed_pnl.net_realized) },
                  { label: "Винрейт", value: `${summary.closed_pnl.wins}/${summary.closed_pnl.losses + summary.closed_pnl.wins} (${fmt(summary.closed_pnl.win_rate, 0)}%)` },
                  { label: "Средний PnL", value: `${pnlSign(summary.closed_pnl.avg_pnl)}$${fmt(summary.closed_pnl.avg_pnl)}`, color: pnlColor(summary.closed_pnl.avg_pnl) },
                  { label: "Лучшая", value: `${pnlSign(summary.closed_pnl.best_trade)}$${fmt(summary.closed_pnl.best_trade)}`, color: "text-green-400" },
                  { label: "Худшая", value: `${pnlSign(summary.closed_pnl.worst_trade)}$${fmt(summary.closed_pnl.worst_trade)}`, color: "text-red-400" },
                ].map((item) => (
                  <div key={item.label} className="bg-card px-3 py-2.5">
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{item.label}</p>
                    <p className={`text-sm font-mono mt-0.5 ${item.color || ""}`}>{item.value}</p>
                  </div>
                ))}
              </div>
              <div className="flex gap-6 mt-3 text-xs text-muted-foreground">
                <span>Объём: ${fmt(summary.closed_pnl.total_volume)}</span>
                <span>ROI: <span className={pnlColor(summary.closed_pnl.roi_pct)}>{pnlSign(summary.closed_pnl.roi_pct)}{fmt(summary.closed_pnl.roi_pct, 1)}%</span></span>
                <span>Ср. прибыль: <span className="text-green-400">+${fmt(summary.closed_pnl.avg_win)}</span></span>
                <span>Ср. убыток: <span className="text-red-400">${fmt(summary.closed_pnl.avg_loss)}</span></span>
              </div>
            </CardContent>
          </Card>
        )}

        <Tabs defaultValue="open" className="space-y-4">
          <TabsList>
            <TabsTrigger value="open">
              Открытые ({openPositions.length})
            </TabsTrigger>
            <TabsTrigger value="closed">
              Закрытые ({closedPositions.length})
            </TabsTrigger>
          </TabsList>

          <TabsContent value="open">
            <Card>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortHead label="Исход" colKey="outcome_name" />
                      <SortHead label="Размер" colKey="size_usd" className="text-right" />
                      <SortHead label="Вход" colKey="entry_price" className="text-right" />
                      <SortHead label="Текущая" colKey="current_price" className="text-right" />
                      <SortHead label="Цель" colKey="target_price" className="text-right" />
                      <SortHead label="Стоп" colKey="stop_loss_price" className="text-right" />
                      <SortHead label="Живой PnL" colKey="unrealized_pnl" className="text-right" />
                      <SortHead label="PnL %" colKey="pnl_pct" className="text-right" />
                      <SortHead label="Осталось" colKey="entry_time" />
                      <TableHead>Проверок</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {openPositions.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                          Нет открытых позиций
                        </TableCell>
                      </TableRow>
                    ) : (
                      sortPositions(openPositions).map((p) => {
                        const lp = livePrices[p.position_id];
                        const pnl = lp?.live_pnl ?? p.unrealized_pnl_usd;
                        const pnlPct = lp?.live_pnl_pct ?? ((p.unrealized_pnl_usd / p.size_usd) * 100);
                        const checkCount = (checksByPos[p.position_id] || []).filter((c) => c.reason !== "entry").length;
                        return (
                          <TableRow
                            key={p.position_id}
                            className="cursor-pointer hover:bg-muted/50"
                            onClick={() => setSelectedPosition(p)}
                          >
                            <TableCell className="font-medium">{p.outcome_name}</TableCell>
                            <TableCell className="text-right">${fmt(p.size_usd)}</TableCell>
                            <TableCell className="text-right">{fmt(p.entry_price * 100, 1)}c</TableCell>
                            <TableCell className="text-right font-mono">
                              {lp ? (
                                <span className={lp.current_price >= p.entry_price ? "text-green-400" : "text-red-400"}>
                                  {fmt(lp.current_price * 100, 1)}c
                                </span>
                              ) : (
                                <span className="text-muted-foreground">...</span>
                              )}
                            </TableCell>
                            <TableCell className="text-right">{fmt(p.target_price * 100, 1)}c</TableCell>
                            <TableCell className="text-right text-red-400">{fmt(p.stop_loss_price * 100, 1)}c</TableCell>
                            <TableCell className={`text-right font-mono ${pnlColor(pnl)}`}>
                              {pnlSign(pnl)}${fmt(pnl)}
                            </TableCell>
                            <TableCell className={`text-right font-mono ${pnlColor(pnlPct)}`}>
                              {pnlSign(pnlPct)}{fmt(pnlPct)}%
                            </TableCell>
                            <TableCell>
                              <HoldingTimer entryTime={p.entry_time} maxMinutes={p.max_holding_minutes} />
                            </TableCell>
                            <TableCell className="text-center">
                              <Badge variant="secondary" className="text-xs">{checkCount}</Badge>
                            </TableCell>
                          </TableRow>
                        );
                      })
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="closed">
            <Card>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortHead label="Исход" colKey="outcome_name" />
                      <SortHead label="Размер" colKey="size_usd" className="text-right" />
                      <SortHead label="Вход" colKey="entry_price" className="text-right" />
                      <SortHead label="Выход" colKey="exit_price" className="text-right" />
                      <SortHead label="Причина" colKey="exit_reason" />
                      <SortHead label="Реализ. PnL" colKey="realized_pnl" className="text-right" />
                      <SortHead label="PnL %" colKey="realized_pnl_pct" className="text-right" />
                      <SortHead label="Время входа" colKey="entry_time" />
                      <SortHead label="Время выхода" colKey="exit_time" />
                      <TableHead>Проверок</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {closedPositions.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                          Пока нет закрытых позиций
                        </TableCell>
                      </TableRow>
                    ) : (
                      sortPositions(closedPositions).map((p) => {
                        const pnlPct = (p.realized_pnl_usd / p.size_usd) * 100;
                        const checkCount = (checksByPos[p.position_id] || []).length;
                        return (
                          <TableRow
                            key={p.position_id}
                            className="cursor-pointer hover:bg-muted/50"
                            onClick={() => setSelectedPosition(p)}
                          >
                            <TableCell className="font-medium">{p.outcome_name}</TableCell>
                            <TableCell className="text-right">${fmt(p.size_usd)}</TableCell>
                            <TableCell className="text-right">{fmt(p.entry_price * 100, 1)}c</TableCell>
                            <TableCell className="text-right">
                              {p.exit_price ? `${fmt(p.exit_price * 100, 1)}c` : "—"}
                            </TableCell>
                            <TableCell>
                              <Badge variant={p.exit_reason === "take_profit" || p.exit_reason === "target_reached" ? "default" : "destructive"}>
                                {p.exit_reason || "—"}
                              </Badge>
                            </TableCell>
                            <TableCell className={`text-right font-mono ${pnlColor(p.realized_pnl_usd)}`}>
                              {pnlSign(p.realized_pnl_usd)}${fmt(p.realized_pnl_usd)}
                            </TableCell>
                            <TableCell className={`text-right font-mono ${pnlColor(pnlPct)}`}>
                              {pnlSign(pnlPct)}{fmt(pnlPct)}%
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {formatTime(p.entry_time)}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {p.exit_time ? formatTime(p.exit_time) : "—"}
                            </TableCell>
                            <TableCell className="text-center">
                              <Badge variant="secondary" className="text-xs">{checkCount}</Badge>
                            </TableCell>
                          </TableRow>
                        );
                      })
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {selectedPosition && (
          <PositionDetail
            position={selectedPosition}
            checks={checksByPos[selectedPosition.position_id] || []}
            livePrice={livePrices[selectedPosition.position_id]}
            onClose={() => setSelectedPosition(null)}
          />
        )}
      </div>
    </div>
  );
}
