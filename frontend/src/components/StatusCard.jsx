import React, { useState } from 'react';
import ErrorBudgetBar from './ErrorBudgetBar';

export default function StatusCard({ data, type, onDelete }) {
  const isOk      = data.status === 'ok';
  const isLoading = data.current === null || data.current === undefined;
  // confirming: shows the inline "Delete? Yes/No" prompt
  const [confirming, setConfirming] = useState(false);
  // deleting: disables the confirm button while the DELETE request is in flight
  const [deleting, setDeleting]     = useState(false);

  // Sends DELETE /api/slo/{name} and notifies the parent to refresh the card list
  async function handleDelete() {
    setDeleting(true);
    try {
      await fetch(`/api/slo/${data.slo}`, { method: 'DELETE' });
      onDelete(data.slo);
    } finally {
      setDeleting(false);
      setConfirming(false);
    }
  }

  return (
    <div className={`status-card ${isOk ? '' : 'breach'} ${type}`}>
      <div className="card-header">
        <span className="card-name">{data.name}</span>
        <div className="card-header-right">
          {/* Hide the status badge while the delete confirmation is shown */}
          {!confirming && (
            <span className={`status-badge ${isOk ? 'ok' : 'breach'}`}>
              {isLoading ? '...' : isOk ? 'OK' : 'BREACH'}
            </span>
          )}
          {confirming ? (
            <div className="delete-confirm">
              <span className="delete-confirm-text">Delete?</span>
              <button className="btn-confirm-yes" onClick={handleDelete} disabled={deleting}>
                {deleting ? '…' : 'Yes'}
              </button>
              <button className="btn-confirm-no" onClick={() => setConfirming(false)}>No</button>
            </div>
          ) : (
            // The ✕ button is hidden by CSS (opacity 0) and only appears on card hover
            <button className="btn-delete" onClick={() => setConfirming(true)} title="Delete SLO">
              ✕
            </button>
          )}
        </div>
      </div>
      <div className="card-body">
        <div className="metric">
          <span className="label">Current</span>
          <span className="value">{isLoading ? '–' : `${data.current?.toFixed(2)}%`}</span>
        </div>
        <div className="metric">
          <span className="label">Target</span>
          <span className="value target">{data.target}%</span>
        </div>
        <div className="metric">
          <span className="label">Window</span>
          <span className="value">{data.window}</span>
        </div>
      </div>
      <ErrorBudgetBar remaining={data.error_budget_remaining} />
    </div>
  );
}
