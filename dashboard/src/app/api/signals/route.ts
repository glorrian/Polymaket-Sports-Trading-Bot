import { NextResponse } from "next/server";
import { getSignals } from "@/lib/db";

export async function GET() {
  const signals = getSignals(100);
  return NextResponse.json(signals);
}