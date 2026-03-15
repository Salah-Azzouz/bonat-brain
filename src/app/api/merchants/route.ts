import { NextResponse } from 'next/server';
import { authenticateRequest } from '@/server/auth';
import { ALLOWED_MERCHANTS, DEFAULT_MERCHANT } from '@/server/config';

/** Merchant ID to display name mapping */
const MERCHANT_NAMES: Record<string, string> = {
  '1032': 'Bonat Demo Merchant',
};

export async function GET(request: Request) {
  try {
    const user = await authenticateRequest(request);

    const merchants = ALLOWED_MERCHANTS.map((id) => ({
      id,
      name: MERCHANT_NAMES[id] || `Merchant ${id}`,
    }));

    return NextResponse.json({
      merchants,
      default: DEFAULT_MERCHANT,
      current: user.merchant_id,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unauthorized';

    if (message.includes('authorization') || message.includes('token')) {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    console.error('[Merchants] Error:', message);
    return NextResponse.json({ detail: 'An internal server error occurred.' }, { status: 500 });
  }
}
