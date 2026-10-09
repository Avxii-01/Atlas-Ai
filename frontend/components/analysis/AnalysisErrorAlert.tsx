"use client";

import React from "react";

export interface AnalysisErrorAlertProps {
  message: string;
  onDismiss?: () => void;
  onRetry?: () => void;
}

export default function AnalysisErrorAlert({
  message,
  onDismiss,
  onRetry,
}: AnalysisErrorAlertProps) {
  return (
    <div
      className="error-alert-container"
      role="alert"
      aria-live="assertive"
      data-testid="analysis-error-alert"
    >
      <div className="error-icon-box" aria-hidden="true">
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>

      <div className="error-content">
        <h4 className="error-title">Analysis Failed</h4>
        <p className="error-message" data-testid="error-message-text">
          {message}
        </p>
      </div>

      <div className="error-actions">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="btn-retry-sm"
            data-testid="error-retry-btn"
          >
            Retry
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="btn-dismiss-sm"
            data-testid="error-dismiss-btn"
            aria-label="Dismiss error"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}
