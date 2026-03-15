import { NextRequest, NextResponse } from 'next/server';
import { authenticateRequest, ChatRequestSchema } from '@/server/auth';
import { getMongoCollections } from '@/server/db/mongodb';
import { streamMainAgent } from '@/server/agent/main-agent';
import type { CoreMessage } from 'ai';
import { v4 as uuidv4 } from 'uuid';

/**
 * POST /api/chat/agent/stream
 *
 * Main SSE streaming endpoint for the chat agent.
 * Authenticates the user, streams tool progress and tokens via SSE,
 * and saves the conversation to mock MongoDB.
 *
 * Ported from Python app.py's /api/chat/agent/stream endpoint.
 */
export async function POST(request: NextRequest) {
  try {
    // 1. Authenticate
    const user = await authenticateRequest(request);

    // 2. Parse body
    const body = await request.json();
    const parsed = ChatRequestSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json(
        { detail: parsed.error.errors[0]?.message || 'Invalid request body' },
        { status: 400 }
      );
    }

    const { user_query, language } = parsed.data;
    const conversationId = parsed.data.conversation_id || uuidv4();
    const messageId = uuidv4();
    const merchantId = user.merchant_id || '1032';

    // 3. Fetch conversation history from mock MongoDB
    const collections = await getMongoCollections();
    if (!collections) {
      return NextResponse.json({ detail: 'Database connection failed' }, { status: 500 });
    }

    const chatHistory: CoreMessage[] = [];
    if (parsed.data.conversation_id) {
      const historyDocs = await collections.history
        .find({
          conversation_id: parsed.data.conversation_id,
        })
        .sort({ timestamp: -1 })
        .limit(10)
        .toArray();

      // Reverse to chronological order
      historyDocs.reverse();

      for (const doc of historyDocs) {
        const d = doc as Record<string, unknown>;
        chatHistory.push({ role: 'user', content: d.user_query as string });
        chatHistory.push({ role: 'assistant', content: d.ai_response as string });
      }
    }

    // 4. Create ReadableStream for SSE
    const encoder = new TextEncoder();
    let fullResponseForSave = '';

    const stream = new ReadableStream({
      async start(controller) {
        // Keepalive interval — sends SSE comment every 15s to prevent proxy timeouts
        const keepaliveInterval = setInterval(() => {
          try {
            controller.enqueue(encoder.encode(': keepalive\n\n'));
          } catch {
            // Controller may be closed
            clearInterval(keepaliveInterval);
          }
        }, 15_000);

        try {
          const agentStream = streamMainAgent({
            userQuery: user_query,
            merchantId,
            chatHistory,
            entityContext: {},
            pastInsights: [],
            language,
          });

          for await (const event of agentStream) {
            const eventType = event.type;

            if (eventType === 'token') {
              fullResponseForSave += event.content || '';
            }

            if (eventType === 'done') {
              // Use the full_response from the done event if available
              fullResponseForSave = event.full_response || fullResponseForSave;

              // Augment done event with conversation metadata
              const doneEvent = {
                ...event,
                conversation_id: conversationId,
                message_id: messageId,
                suggestions: [],
              };
              controller.enqueue(encoder.encode(`data: ${JSON.stringify(doneEvent)}\n\n`));

              // Save to mock history
              try {
                await collections.history.insertOne({
                  message_id: messageId,
                  conversation_id: conversationId,
                  user_id: user.user_id,
                  merchant_id: merchantId,
                  user_query,
                  ai_response: fullResponseForSave,
                  timestamp: new Date(),
                } as unknown as Record<string, unknown>);

                console.log(`[API Stream] Response saved for conversation: ${conversationId}`);
              } catch (saveError) {
                console.error('[API Stream] Failed to save history:', saveError);
              }
            } else {
              // Send all other events as SSE
              controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
            }

            if (eventType === 'done' || eventType === 'error') {
              break;
            }
          }
        } catch (error) {
          console.error('[API Stream] Stream error:', error);
          const errorEvent = {
            type: 'error',
            content: 'An unexpected error occurred. Please try again.',
          };
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(errorEvent)}\n\n`));
        } finally {
          clearInterval(keepaliveInterval);
          controller.close();
        }
      },
    });

    // 5. Return SSE response
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unauthorized';

    if (message.includes('authorization') || message.includes('token')) {
      return NextResponse.json({ detail: message }, { status: 401 });
    }

    console.error('[API Stream] Error:', error);
    return NextResponse.json({ detail: 'An internal server error occurred.' }, { status: 500 });
  }
}
