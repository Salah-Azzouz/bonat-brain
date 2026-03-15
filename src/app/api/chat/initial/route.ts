import { NextResponse } from 'next/server';
import { authenticateRequest } from '@/server/auth';

/**
 * GET /api/chat/initial
 *
 * Mock endpoint that returns { type: 'none' } — no real insights check.
 * In the full implementation, this would check for proactive insights
 * and monthly reports.
 */
export async function GET(request: Request) {
  try {
    await authenticateRequest(request);

    return NextResponse.json({ type: 'none' });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unauthorized';

    if (message.includes('authorization') || message.includes('token')) {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    console.error('[Chat Initial] Error:', message);
    return NextResponse.json({ detail: 'An internal server error occurred.' }, { status: 500 });
  }
}
