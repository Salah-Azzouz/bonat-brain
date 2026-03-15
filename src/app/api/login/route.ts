import { NextRequest, NextResponse } from 'next/server';
import { authService, UserLoginSchema } from '@/server/auth';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const parsed = UserLoginSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json(
        { detail: parsed.error.errors[0]?.message || 'Invalid input' },
        { status: 400 }
      );
    }

    const { email, password } = parsed.data;
    const tokenResponse = await authService.loginUser(email, password);

    return NextResponse.json(tokenResponse);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Login failed';

    if (message === 'Invalid email or password') {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    console.error('[Login] Error:', message);
    return NextResponse.json({ detail: 'An internal server error occurred.' }, { status: 500 });
  }
}
