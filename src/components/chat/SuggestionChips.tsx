'use client';

import React from 'react';

interface SuggestionChipsProps {
  suggestions: string[];
  onClick: (text: string) => void;
}

export default function SuggestionChips({ suggestions, onClick }: SuggestionChipsProps) {
  if (!suggestions.length) return null;

  return (
    <div className="suggestion-chips">
      {suggestions.map((s, i) => (
        <button
          key={i}
          className="suggestion-chip"
          onClick={() => onClick(s)}
          type="button"
        >
          {s}
        </button>
      ))}
    </div>
  );
}
