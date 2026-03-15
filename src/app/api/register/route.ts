import { NextRequest, NextResponse } from 'next/server';
import { authService, UserRegistrationSchema } from '@/server/auth';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const parsed = UserRegistrationSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json(
        { detail: parsed.error.errors[0]?.message || 'Invalid input' },
        { status: 400 }
      );
    }

    const { email, password } = parsed.data;

    const user = await authService.registerUser(email, password);
    const accessToken = await authService.createAccessToken({
      sub: user.email,
      user_id: user.user_id,
      merchant_id: user.merchant_id!,
    });

    return NextResponse.json({
      access_token: accessToken,
      token_type: 'bearer',
      user,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Registration failed';

    if (message === 'Email already registered') {
      return NextResponse.json({ detail: message }, { status: 400 });
    }

    console.error('[Register] Error:', message);
    return NextResponse.json({ detail: 'An internal server error occurred.' }, { status: 500 });
  }
}
