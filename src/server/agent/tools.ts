/**
 * Tool Definitions for Vercel AI SDK
 *
 * Defines the 4 tools available to the main agent:
 * - query_db: Query merchant business data
 * - agentic_rag: Search knowledge base
 * - validate: Quality check on responses
 * - respond_directly: Greetings and social messages
 */

import { tool } from 'ai';
import { z } from 'zod';

/**
 * query_db — Query the merchant's business database.
 * Call this for any question about revenue, visits, customers, segments,
 * loyalty, orders, campaigns, or payments.
 */
export const queryDbTool = tool({
  description:
    'Query the merchant\'s business database. Call this for any question about revenue, visits, customers, segments, loyalty, orders, campaigns, or payments — including Arabic questions.',
  parameters: z.object({
    user_question: z.string().describe("The user's question about their business data"),
    merchant_id: z
      .union([z.string(), z.number()])
      .describe("The merchant's unique identifier (automatically provided)"),
    intent_category: z
      .string()
      .optional()
      .describe(
        'Data category to route the query to the correct table. ALWAYS set this.'
      ),
  }),
  execute: async ({ user_question, merchant_id, intent_category }) => {
    const mid = String(merchant_id);
    console.log(
      `[query_db] START - Question: ${user_question.slice(0, 100)}..., merchant: ${mid}, intent: ${intent_category}`
    );

    try {
      // TODO: Replace with real executeDataPipeline when available
      // import { executeDataPipeline } from '../pipelines/data-pipeline';
      // const result = await executeDataPipeline({ userQuestion: user_question, merchantId: mid, intentCategory: intent_category });

      // Mock response
      return `[Mock] Data pipeline result for "${user_question}" (merchant: ${mid}, intent: ${intent_category || 'auto'}). Table: MockTable. No real data — pipeline not yet wired.`;
    } catch (error) {
      console.error(`[query_db] ERROR - ${error}`);
      return "I'm sorry, I encountered an unexpected error while processing your request. Please try again.";
    }
  },
});

/**
 * agentic_rag — Search Bonat knowledge base for feature guides,
 * best practices, and troubleshooting.
 */
export const agenticRagTool = tool({
  description:
    'Search Bonat knowledge base for feature guides, best practices, and troubleshooting. Not for business data — use query_db for that.',
  parameters: z.object({
    question: z.string().describe('The knowledge question to search for'),
    merchant_context: z
      .record(z.unknown())
      .optional()
      .describe('Optional merchant context for scoped answers'),
  }),
  execute: async ({ question }) => {
    console.log(`[agentic_rag] Called with question: ${question}`);

    try {
      // TODO: Replace with real executeAgenticRag when available
      // import { executeAgenticRag } from '../pipelines/rag-pipeline';
      // return await executeAgenticRag({ question, merchantContext, maxRetries: 2 });

      // Mock response
      return `[Mock] RAG result for "${question}". No real knowledge base connected yet.`;
    } catch (error) {
      console.error(`[agentic_rag] Error: ${error}`);
      return "I'm sorry, I encountered an error accessing the knowledge base. Please try rephrasing your question or contact support.";
    }
  },
});

/**
 * validate — Quality check after query_db returns data.
 */
export const validateTool = tool({
  description:
    'Quality check after query_db returns data. Returns VALIDATION PASSED, insights needed, or VALIDATION FAILED. If insights needed, call agentic_rag with the suggested query and combine results.',
  parameters: z.object({
    draft_response: z.string().describe('The draft response to validate'),
    user_query: z.string().describe('The original user query'),
    source_tool: z.string().describe('Which tool generated the draft (e.g. query_db)'),
    source_data: z
      .string()
      .optional()
      .describe('Optional JSON string of the raw source data'),
  }),
  execute: async ({ draft_response, user_query, source_tool }) => {
    console.log(`[validate] Validating ${source_tool} response for: ${user_query}`);

    try {
      // TODO: Replace with real executeValidationPipeline when available
      // import { executeValidationPipeline } from '../pipelines/validation-pipeline';

      // Mock: always pass validation
      return `VALIDATION PASSED\n\nThe response is accurate and complete. No additional insights needed.\n\nACTION: Return the original response to the user as-is.`;
    } catch (error) {
      console.error(`[validate] Validation failed with error: ${error}`);
      return `VALIDATION ERROR\n\nAn error occurred during validation. Proceed with caution.\n\nACTION: Return the original response with a disclaimer, or ask the user to rephrase.`;
    }
  },
});

/**
 * respond_directly — Respond to greetings, thanks, and social messages.
 */
export const respondDirectlyTool = tool({
  description:
    'Respond to greetings, thanks, and social messages. Pass the full response text as the message parameter.',
  parameters: z.object({
    message: z.string().describe('The full response text to send to the user'),
  }),
  execute: async ({ message }) => {
    return message;
  },
});

/** All tools bundled for the agent */
export const agentTools = {
  query_db: queryDbTool,
  agentic_rag: agenticRagTool,
  validate: validateTool,
  respond_directly: respondDirectlyTool,
};
