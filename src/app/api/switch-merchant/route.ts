import { NextRequest, NextResponse } from 'next/server';
import { authenticateRequest, authService, SwitchMerchantSchema } from '@/server/auth';

export async function POST(request: NextRequest) {
  try {
    const user = await authenticateRequest(request);
    const body = await request.json();

    const parsed = SwitchMerchantSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json(
        { detail: parsed.error.errors[0]?.message || 'Invalid merchant ID' },
        { status: 400 }
      );
    }

    const { merchant_id } = parsed.data;
    const tokenResponse = await authService.switchMerchant(user, merchant_id);

    console.log(`[Switch Merchant] User ${user.email} switched to merchant: ${merchant_id}`);
    return NextResponse.json(tokenResponse);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Switch failed';

    if (message.includes('authorization') || message.includes('token')) {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    if (message.includes('Invalid merchant')) {
      return NextResponse.json({ detail: message }, { status: 400 });
    }

    console.error('[Switch Merchant] Error:', message);
    return NextResponse.json({ detail: 'An internal server error occurred.' }, { status: 500 });
  }
}
