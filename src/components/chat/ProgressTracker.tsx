'use client';

import React from 'react';
import { ToolProgress } from '@/hooks/useChat';
import { TOOL_DISPLAY_MAP } from '@/lib/constants';

interface ProgressTrackerProps {
  tools: ToolProgress[];
}

export default function ProgressTracker({ tools }: ProgressTrackerProps) {
  // Only show the currently active tool
  const activeTool = tools.filter((t) => t.status === 'active').pop();
  if (!activeTool) return null;

  const display = TOOL_DISPLAY_MAP[activeTool.tool] || {
    icon: activeTool.icon,
    description: activeTool.description,
  };

  return (
    <div className="progress-tracker">
      <div className="loading-dots">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
      </div>
      <span>
        {display.icon} {activeTool.title || display.description}
      </span>
    </div>
  );
}
