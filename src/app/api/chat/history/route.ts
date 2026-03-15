import { NextRequest, NextResponse } from 'next/server';
import { authenticateRequest } from '@/server/auth';
import { getMongoCollections } from '@/server/db/mongodb';

export async function GET(request: NextRequest) {
  try {
    const user = await authenticateRequest(request);
    const merchantId = user.merchant_id || '1032';

    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get('limit') || '20', 10), 100);

    const collections = await getMongoCollections();
    if (!collections) {
      return NextResponse.json({ detail: 'Database connection failed' }, { status: 500 });
    }

    const historyDocs = await collections.history
      .find({
        user_id: user.user_id,
        merchant_id: merchantId,
      })
      .sort({ timestamp: -1 })
      .limit(limit)
      .toArray();

    // Reverse to chronological order (oldest first)
    historyDocs.reverse();

    const formattedMessages = historyDocs.map((doc) => {
      const d = doc as Record<string, unknown>;
      const ts = d.timestamp as Date | null;
      return {
        message_id: d.message_id,
        conversation_id: d.conversation_id,
        user_query: d.user_query,
        ai_response: d.ai_response,
        timestamp: ts ? ts.toISOString() : null,
      };
    });

    const latestConversationId =
      historyDocs.length > 0
        ? (historyDocs[historyDocs.length - 1] as Record<string, unknown>).conversation_id
        : null;

    console.log(
      `[Chat History] Returned ${formattedMessages.length} messages for user ${user.user_id}, merchant ${merchantId}`
    );

    return NextResponse.json({
      messages: formattedMessages,
      conversation_id: latestConversationId,
      count: formattedMessages.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unauthorized';

    if (message.includes('authorization') || message.includes('token')) {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    console.error('[Chat History GET] Error:', error);
    return NextResponse.json({ detail: 'Failed to fetch chat history' }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const user = await authenticateRequest(request);
    const merchantId = user.merchant_id || '1032';

    const collections = await getMongoCollections();
    if (!collections) {
      return NextResponse.json({ detail: 'Database connection failed' }, { status: 500 });
    }

    const result = await collections.history.deleteMany({
      user_id: user.user_id,
      merchant_id: merchantId,
    });

    console.log(
      `[Chat History] Cleared ${result.deletedCount} messages for user ${user.user_id}, merchant ${merchantId}`
    );

    return NextResponse.json({
      success: true,
      deleted_count: result.deletedCount,
      message: 'Chat history cleared successfully',
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unauthorized';

    if (message.includes('authorization') || message.includes('token')) {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    console.error('[Chat History DELETE] Error:', error);
    return NextResponse.json({ detail: 'Failed to clear chat history' }, { status: 500 });
  }
}
