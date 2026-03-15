import { NextResponse } from 'next/server';
import { authenticateRequest } from '@/server/auth';

/**
 * POST /api/reset-insights
 *
 * Mock no-op endpoint. In the full implementation this would reset
 * the user's insight flags in MongoDB.
 */
export async function POST(request: Request) {
  try {
    const user = await authenticateRequest(request);

    console.log(`[Reset Insights] Mock reset for user: ${user.email}`);

    return NextResponse.json({
      message: 'Insights reset successfully',
      modified: 0,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unauthorized';

    if (message.includes('authorization') || message.includes('token')) {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    console.error('[Reset Insights] Error:', message);
    return NextResponse.json({ detail: 'An internal server error occurred.' }, { status: 500 });
  }
}
