import React from 'react';

export default function ErrorBudgetBar({ remaining }) {
  // Do not render if Pyrra has not produced enough data yet
  if (remaining === null || remaining === undefined) return null;

  const pct = Math.round(remaining);
  // Colour thresholds: green > 50%, amber > 20%, red <= 20%
  const color = pct > 50 ? '#22c55e' : pct > 20 ? '#f59e0b' : '#ef4444';

  return (
    <div className="error-budget">
      <div className="budget-label">
        <span>Error budget</span>
        <span style={{ color }}>{pct}%</span>
      </div>
      <div className="budget-track">
        <div className="budget-fill" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}
