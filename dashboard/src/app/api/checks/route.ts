import { NextResponse } from "next/server";
import { getAllPositionChecks } from "@/lib/db";

export async function GET() {
  const checks = getAllPositionChecks();

  const byPosition: Record<string, typeof checks> = {};
  for (const row of checks) {
    const pid = row.position_id as string;
    if (!byPosition[pid]) byPosition[pid] = [];
    byPosition[pid].push(row);
  }

  return NextResponse.json(byPosition);
}