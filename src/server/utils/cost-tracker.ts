/**
 * Cost Tracker — Tracks LLM token usage and costs.
 * Supports per-model and per-node breakdown.
 */

// Approximate pricing per 1M tokens (USD)
const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  'gpt-4.1-mini': { input: 0.15, output: 0.60 },
  'gpt-4.1': { input: 2.00, output: 8.00 },
  'gpt-4o-mini': { input: 0.15, output: 0.60 },
  'gpt-4o': { input: 2.50, output: 10.00 },
  'gpt-3.5-turbo': { input: 0.50, output: 1.50 },
  'text-embedding-3-large': { input: 0.13, output: 0.0 },
  'text-embedding-3-small': { input: 0.02, output: 0.0 },
};

const DEFAULT_PRICING = { input: 1.00, output: 3.00 };

interface LLMCall {
  model: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  cost: number;
  latencyMs: number;
  timestamp: string;
  node: string;
}

export interface CostSummary {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  model: string;
  latency_ms: number;
  llm_calls: number;
  tools_used: string[];
  byModel: Record<
    string,
    {
      calls: number;
      inputTokens: number;
      outputTokens: number;
      estimatedCost: number;
    }
  >;
  byNode: Record<
    string,
    {
      calls: number;
      inputTokens: number;
      outputTokens: number;
      estimatedCost: number;
    }
  >;
}

export class CostTracker {
  private calls: LLMCall[] = [];
  private toolsUsed: string[] = [];

  trackLLMCall(
    model: string,
    inputTokens: number,
    outputTokens: number,
    latencyMs: number = 0,
    node: string = 'unknown'
  ): void {
    const pricing = MODEL_PRICING[model] || DEFAULT_PRICING;
    const inputCost = (inputTokens * pricing.input) / 1_000_000;
    const outputCost = (outputTokens * pricing.output) / 1_000_000;

    this.calls.push({
      model,
      inputTokens,
      outputTokens,
      totalTokens: inputTokens + outputTokens,
      cost: inputCost + outputCost,
      latencyMs,
      timestamp: new Date().toISOString(),
      node,
    });

    console.log(
      `[CostTracker] ${node}: ${model} — ${inputTokens} in / ${outputTokens} out — $${(inputCost + outputCost).toFixed(6)}`
    );
  }

  trackToolUse(toolName: string): void {
    if (!this.toolsUsed.includes(toolName)) {
      this.toolsUsed.push(toolName);
    }
  }

  getSummary(): CostSummary {
    const totalInputTokens = this.calls.reduce((s, c) => s + c.inputTokens, 0);
    const totalOutputTokens = this.calls.reduce((s, c) => s + c.outputTokens, 0);
    const totalCost = this.calls.reduce((s, c) => s + c.cost, 0);
    const totalLatency = this.calls.reduce((s, c) => s + c.latencyMs, 0);
    const models = this.calls.map((c) => c.model).filter((m) => m !== 'unknown');
    const primaryModel =
      models.length > 0
        ? models.sort(
            (a, b) =>
              models.filter((v) => v === b).length - models.filter((v) => v === a).length
          )[0]
        : 'unknown';

    // Per-model breakdown
    const byModel: CostSummary['byModel'] = {};
    for (const call of this.calls) {
      if (!byModel[call.model]) {
        byModel[call.model] = { calls: 0, inputTokens: 0, outputTokens: 0, estimatedCost: 0 };
      }
      byModel[call.model].calls++;
      byModel[call.model].inputTokens += call.inputTokens;
      byModel[call.model].outputTokens += call.outputTokens;
      byModel[call.model].estimatedCost += call.cost;
    }

    // Per-node breakdown
    const byNode: CostSummary['byNode'] = {};
    for (const call of this.calls) {
      if (!byNode[call.node]) {
        byNode[call.node] = { calls: 0, inputTokens: 0, outputTokens: 0, estimatedCost: 0 };
      }
      byNode[call.node].calls++;
      byNode[call.node].inputTokens += call.inputTokens;
      byNode[call.node].outputTokens += call.outputTokens;
      byNode[call.node].estimatedCost += call.cost;
    }

    return {
      input_tokens: totalInputTokens,
      output_tokens: totalOutputTokens,
      total_tokens: totalInputTokens + totalOutputTokens,
      cost_usd: Math.round(totalCost * 100000000) / 100000000,
      model: primaryModel,
      latency_ms: totalLatency,
      llm_calls: this.calls.length,
      tools_used: [...this.toolsUsed],
      byModel,
      byNode,
    };
  }

  reset(): void {
    this.calls = [];
    this.toolsUsed = [];
  }

  getCallCount(): number {
    return this.calls.length;
  }

  getTotalCost(): number {
    return this.calls.reduce((sum, c) => sum + c.cost, 0);
  }
}

// Singleton per request (or global for simple usage)
let _tracker: CostTracker | null = null;

export function getCostTracker(): CostTracker {
  if (!_tracker) {
    _tracker = new CostTracker();
  }
  return _tracker;
}

export function createCostTracker(): CostTracker {
  return new CostTracker();
}
