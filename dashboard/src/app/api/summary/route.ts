import { NextResponse } from "next/server";
import { getSummary } from "@/lib/db";

export async function GET() {
  return NextResponse.json(getSummary());
}