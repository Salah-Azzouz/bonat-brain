/**
 * Main Agent — Streaming orchestrator using Vercel AI SDK
 *
 * Uses streamText from the 'ai' package with OpenAI's gpt-4.1-mini model.
 * Yields SSE events: tool_start, tool_end, generating_start, token, done, error.
 *
 * Ported from Python's stream_main_agent in main_agent.py.
 */

import { streamText, type CoreMessage } from 'ai';
import { openai } from '@ai-sdk/openai';
import { buildSystemPrompt } from './prompts';
import { agentTools } from './tools';
import { getMerchantNow, formatDate, getDayName } from '../config';
import type { SSEEvent, CostData } from '@/types';

export interface StreamMainAgentParams {
  userQuery: string;
  merchantId: string;
  chatHistory: CoreMessage[];
  entityContext?: Record<string, unknown>;
  pastInsights?: Array<{ content: string; date?: string }>;
  language?: string;
}

/** Progress metadata for tool_start events */
const PROGRESS_MESSAGES: Record<string, { icon: string; title: string; description: string }> = {
  query_db: {
    icon: 'fa-database',
    title: 'Analyzing Data',
    description: 'Querying your database and processing metrics',
  },
  agentic_rag: {
    icon: 'fa-book-open',
    title: 'Searching Knowledge',
    description: 'Looking up best practices and recommendations',
  },
  validate: {
    icon: 'fa-shield-check',
    title: 'Validating Response',
    description: 'Ensuring accuracy and completeness',
  },
  respond_directly: {
    icon: 'fa-comment',
    title: 'Responding',
    description: 'Preparing your response',
  },
};

/**
 * Streams the main agent response as SSE events.
 *
 * Yields events matching the SSEEvent type:
 *  - tool_start / tool_end  — tool lifecycle
 *  - generating_start       — first token about to stream
 *  - token                  — individual text token
 *  - done                   — final event with full_response + cost_data
 *  - error                  — unrecoverable error
 */
export async function* streamMainAgent(
  params: StreamMainAgentParams
): AsyncGenerator<SSEEvent> {
  const {
    userQuery,
    merchantId,
    chatHistory,
    entityContext = {},
    pastInsights = [],
    language = 'ar',
  } = params;

  console.log(`[Main Agent Stream] Starting stream for query: ${userQuery}`);

  const now = getMerchantNow();
  const currentDate = formatDate(now);
  const currentDayName = getDayName(now);

  // Build system prompt
  const systemPrompt = buildSystemPrompt({
    merchantId,
    entityContext,
    pastInsights,
    language,
    currentDate,
    currentDayName,
    userQuery,
  });

  const fullResponse: string[] = [];
  let queriedTable: string | null = null;
  let streamingStarted = false;
  const startTime = Date.now();

  try {
    const result = streamText({
      model: openai('gpt-4.1-mini'),
      system: systemPrompt,
      messages: [
        ...chatHistory,
        { role: 'user' as const, content: userQuery },
      ],
      tools: agentTools,
      maxSteps: 5,
    });

    for await (const part of result.fullStream) {
      switch (part.type) {
        case 'tool-call': {
          const toolName = part.toolName;
          const progress = PROGRESS_MESSAGES[toolName] || {
            icon: 'fa-cog',
            title: `Running ${toolName}`,
            description: 'Processing your request',
          };

          console.log(`[Main Agent Stream] Tool started: ${toolName}`);

          yield {
            type: 'tool_start',
            tool: toolName,
            icon: progress.icon,
            title: progress.title,
            description: progress.description,
          };
          break;
        }

        case 'tool-result': {
          const toolName = part.toolName;
          console.log(`[Main Agent Stream] Tool completed: ${toolName}`);

          // Extract table name from query_db output for suggestions
          if (toolName === 'query_db' && typeof part.result === 'string') {
            const tableMatch = part.result.match(/Table:\s*(\w+)/);
            if (tableMatch) {
              queriedTable = tableMatch[1];
              console.log(`[Main Agent Stream] Captured queried table: ${queriedTable}`);
            }
          }

          yield {
            type: 'tool_end',
            tool: toolName,
          };
          break;
        }

        case 'text-delta': {
          const token = part.textDelta;
          if (token) {
            if (!streamingStarted) {
              streamingStarted = true;
              console.log('[Main Agent Stream] Started streaming final response');

              yield {
                type: 'generating_start',
                icon: 'fa-sparkles',
                title: 'Generating Response',
                description: 'Synthesizing your answer',
              };
            }

            fullResponse.push(token);

            yield {
              type: 'token',
              content: token,
            };
          }
          break;
        }

        // Ignore other part types (step-finish, finish, etc.)
        default:
          break;
      }
    }

    // Stream complete — gather cost data
    const completeResponse = fullResponse.join('');
    const latencyMs = Date.now() - startTime;

    console.log(`[Main Agent Stream] Stream completed. Total length: ${completeResponse.length}`);

    // Build cost data from usage (await the promise)
    let costData: CostData | null = null;
    try {
      const usage = await result.usage;
      costData = {
        input_tokens: usage.promptTokens,
        output_tokens: usage.completionTokens,
        total_tokens: usage.totalTokens,
        cost_usd: estimateCost(usage.promptTokens, usage.completionTokens),
        model: 'gpt-4.1-mini',
        latency_ms: latencyMs,
        llm_calls: 1,
        tools_used: [],
      };

      console.log(
        `[Main Agent Stream] Cost tracking: tokens=${costData.total_tokens}, cost=$${costData.cost_usd.toFixed(6)}`
      );
    } catch {
      // Usage info may not be available in all environments
    }

    yield {
      type: 'done',
      full_response: completeResponse,
      queried_table: queriedTable ?? undefined,
      cost_data: costData,
    };
  } catch (error) {
    console.error(`[Main Agent Stream] Error during streaming: ${error}`);

    yield {
      type: 'error',
      content:
        'I apologize, I encountered an unexpected error. Please try again or rephrase your question.',
    };
  }
}

/**
 * Rough cost estimation for gpt-4.1-mini.
 * Input: $0.40/1M tokens, Output: $1.60/1M tokens (approximate).
 */
function estimateCost(inputTokens: number, outputTokens: number): number {
  return (inputTokens * 0.4 + outputTokens * 1.6) / 1_000_000;
}
