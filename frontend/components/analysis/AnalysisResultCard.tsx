"use client";

import { RepositoryAnalysisResponse } from "../../lib/types";

export interface AnalysisResultCardProps {
  result: RepositoryAnalysisResponse;
  onReset?: () => void;
  onViewGraph?: (repositoryId: string) => void;
}

export default function AnalysisResultCard({
  result,
  onReset,
  onViewGraph,
}: AnalysisResultCardProps) {
  const { summary } = result;

  const statItems = [
    { label: "Files", value: summary.files, testId: "stat-files" },
    { label: "Classes", value: summary.classes, testId: "stat-classes" },
    { label: "Functions", value: summary.functions, testId: "stat-functions" },
    { label: "Relationships", value: summary.relationships, testId: "stat-relationships" },
    ...(summary.modules !== undefined && summary.modules !== null
      ? [{ label: "Modules", value: summary.modules, testId: "stat-modules" }]
      : []),
    ...(summary.methods !== undefined && summary.methods !== null
      ? [{ label: "Methods", value: summary.methods, testId: "stat-methods" }]
      : []),
    ...(summary.imports !== undefined && summary.imports !== null
      ? [{ label: "Imports", value: summary.imports, testId: "stat-imports" }]
      : []),
  ];

  return (
    <div
      className="analysis-result-container"
      data-testid="analysis-result-card"
      role="region"
      aria-label="Analysis Results"
    >
      <div className="result-header">
        <div className="result-status-badge">
          <span className="status-dot-success" />
          <span>Analysis Completed</span>
        </div>
        <div className="result-header-actions">
          {onViewGraph && (
            <button
              type="button"
              onClick={() => onViewGraph(result.repository_id)}
              className="btn-primary-sm"
              data-testid="view-graph-btn"
            >
              View Knowledge Graph →
            </button>
          )}
          {onReset && (
            <button
              type="button"
              onClick={onReset}
              className="btn-secondary-sm"
              data-testid="analyze-another-btn"
            >
              Analyze Another
            </button>
          )}
        </div>
      </div>

      <div className="repo-meta-row">
        <div className="repo-id-group">
          <span className="meta-label">Repository ID:</span>
          <code className="repo-id-badge" data-testid="result-repo-id">
            {result.repository_id}
          </code>
        </div>
        <div className="repo-status-group">
          <span className="meta-label">Status:</span>
          <span className="meta-value-status" data-testid="result-status">
            {result.status}
          </span>
        </div>
      </div>

      <div className="metrics-section">
        <h3 className="metrics-title">Analysis Summary</h3>
        <div className="metrics-grid" data-testid="metrics-grid">
          {statItems.map((item) => (
            <div key={item.label} className="metric-card" data-testid={item.testId}>
              <span className="metric-number">{item.value}</span>
              <span className="metric-label">{item.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
