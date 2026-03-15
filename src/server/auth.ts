import bcrypt from 'bcryptjs';
import { SignJWT, jwtVerify } from 'jose';
import { v4 as uuidv4 } from 'uuid';
import { z } from 'zod';
import {
  SECRET_KEY,
  ALGORITHM,
  ACCESS_TOKEN_EXPIRE_MINUTES,
  DEFAULT_MERCHANT,
  ALLOWED_MERCHANTS,
} from './config';
import { getMongoCollections } from './db/mongodb';
import type { User, TokenResponse } from '@/types';

// Zod schemas
export const UserRegistrationSchema = z.object({
  email: z.string().email().refine(e => e.endsWith('@bonat.io'), {
    message: 'Email must be a valid @bonat.io address',
  }),
  password: z.string().min(6),
});

export const UserLoginSchema = z.object({
  email: z.string().email(),
  password: z.string(),
});

export const SwitchMerchantSchema = z.object({
  merchant_id: z.string().refine(id => ALLOWED_MERCHANTS.includes(id), {
    message: `Invalid merchant ID. Allowed: ${ALLOWED_MERCHANTS.join(', ')}`,
  }),
});

export const ChatRequestSchema = z.object({
  user_query: z.string(),
  conversation_id: z.string().optional(),
  language: z.string().default('ar'),
});

export const UserPreferencesSchema = z.object({
  preferred_language: z.string().default('ar'),
});

const secretKey = new TextEncoder().encode(SECRET_KEY);

class AuthService {
  async verifyPassword(plainPassword: string, hashedPassword: string): Promise<boolean> {
    return bcrypt.compare(plainPassword, hashedPassword);
  }

  async hashPassword(password: string): Promise<string> {
    return bcrypt.hash(password, 10);
  }

  async createAccessToken(data: Record<string, string>, expiresInMinutes?: number): Promise<string> {
    const expMinutes = expiresInMinutes || ACCESS_TOKEN_EXPIRE_MINUTES;
    const jwt = new SignJWT(data)
      .setProtectedHeader({ alg: ALGORITHM === 'HS256' ? 'HS256' : 'HS256' })
      .setExpirationTime(`${expMinutes}m`)
      .setIssuedAt();
    return jwt.sign(secretKey);
  }

  async registerUser(email: string, password: string): Promise<User> {
    const collections = await getMongoCollections();
    if (!collections) throw new Error('Database connection failed');

    const existing = await collections.users.findOne({ email });
    if (existing) throw new Error('Email already registered');

    const userId = uuidv4();
    const hashedPassword = await this.hashPassword(password);

    await collections.users.insertOne({
      user_id: userId,
      email,
      hashed_password: hashedPassword,
      created_at: new Date(),
      last_login: null,
      last_insight_date: null,
      insight_shown_count: 0,
    });

    console.log(`[Auth] New user registered: ${email}`);
    return { user_id: userId, email, merchant_id: DEFAULT_MERCHANT };
  }

  async loginUser(email: string, password: string): Promise<TokenResponse> {
    const collections = await getMongoCollections();
    if (!collections) throw new Error('Database connection failed');

    const userDoc = await collections.users.findOne({ email });
    if (!userDoc) throw new Error('Invalid email or password');

    const valid = await this.verifyPassword(password, userDoc.hashed_password as string);
    if (!valid) throw new Error('Invalid email or password');

    const user: User = {
      user_id: userDoc.user_id as string,
      email: userDoc.email as string,
      merchant_id: DEFAULT_MERCHANT,
    };

    // Update login timestamps
    const now = new Date();
    await collections.users.updateOne(
      { user_id: user.user_id },
      {
        $set: {
          previous_login: userDoc.last_login,
          last_login: now,
        },
      }
    );

    const accessToken = await this.createAccessToken({
      sub: user.email,
      user_id: user.user_id,
      merchant_id: user.merchant_id!,
    });

    return {
      access_token: accessToken,
      token_type: 'bearer',
      user,
    };
  }

  async switchMerchant(currentUser: User, newMerchantId: string): Promise<TokenResponse> {
    if (!ALLOWED_MERCHANTS.includes(newMerchantId)) {
      throw new Error(`Invalid merchant ID. Allowed: ${ALLOWED_MERCHANTS.join(', ')}`);
    }

    const updatedUser: User = {
      ...currentUser,
      merchant_id: newMerchantId,
    };

    const accessToken = await this.createAccessToken({
      sub: updatedUser.email,
      user_id: updatedUser.user_id,
      merchant_id: updatedUser.merchant_id!,
    });

    console.log(`[Auth] User ${currentUser.email} switched to merchant: ${newMerchantId}`);
    return {
      access_token: accessToken,
      token_type: 'bearer',
      user: updatedUser,
    };
  }

  async getCurrentUser(token: string): Promise<User | null> {
    try {
      const { payload } = await jwtVerify(token, secretKey);
      const email = payload.sub as string;
      const userId = payload.user_id as string;

      if (!email || !userId) return null;

      return {
        user_id: userId,
        email,
        merchant_id: DEFAULT_MERCHANT,
      };
    } catch {
      return null;
    }
  }

  async getUserPreferences(userId: string): Promise<{ preferred_language: string }> {
    const collections = await getMongoCollections();
    if (!collections) return { preferred_language: 'ar' };

    const userDoc = await collections.users.findOne({ user_id: userId });
    if (!userDoc) return { preferred_language: 'ar' };

    return {
      preferred_language: (userDoc.preferred_language as string) || 'ar',
    };
  }

  async updateUserPreferences(userId: string, prefs: { preferred_language: string }): Promise<boolean> {
    const collections = await getMongoCollections();
    if (!collections) throw new Error('Database connection failed');

    const result = await collections.users.updateOne(
      { user_id: userId },
      { $set: { preferred_language: prefs.preferred_language } }
    );
    return result.modifiedCount > 0;
  }
}

export const authService = new AuthService();

// Helper to extract user from request
export async function authenticateRequest(req: Request): Promise<User> {
  const authHeader = req.headers.get('Authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    throw new Error('Missing or invalid authorization header');
  }

  const token = authHeader.slice(7);
  const user = await authService.getCurrentUser(token);
  if (!user) {
    throw new Error('Invalid or expired token');
  }

  return user;
}
