import { NextRequest, NextResponse } from 'next/server';
import { authenticateRequest, authService, UserPreferencesSchema } from '@/server/auth';

export async function GET(request: Request) {
  try {
    const user = await authenticateRequest(request);
    const preferences = await authService.getUserPreferences(user.user_id);

    return NextResponse.json(preferences);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unauthorized';

    if (message.includes('authorization') || message.includes('token')) {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    console.error('[Preferences GET] Error:', message);
    return NextResponse.json({ detail: 'An internal server error occurred.' }, { status: 500 });
  }
}

export async function PATCH(request: NextRequest) {
  try {
    const user = await authenticateRequest(request);
    const body = await request.json();

    const parsed = UserPreferencesSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json(
        { detail: parsed.error.errors[0]?.message || 'Invalid preferences' },
        { status: 400 }
      );
    }

    await authService.updateUserPreferences(user.user_id, parsed.data);

    console.log(`[Preferences] User ${user.email} updated preferences: language=${parsed.data.preferred_language}`);

    return NextResponse.json({
      message: 'Preferences updated',
      preferred_language: parsed.data.preferred_language,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Update failed';

    if (message.includes('authorization') || message.includes('token')) {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    console.error('[Preferences PATCH] Error:', message);
    return NextResponse.json({ detail: 'An internal server error occurred.' }, { status: 500 });
  }
}
