import { NextResponse } from "next/server";
import { getRiskEvents } from "@/lib/db";

export async function GET() {
  return NextResponse.json(getRiskEvents(100));
}