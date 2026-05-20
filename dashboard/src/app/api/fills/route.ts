import { NextResponse } from "next/server";
import { getFills } from "@/lib/db";

export async function GET() {
  return NextResponse.json(getFills(100));
}