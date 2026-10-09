"use client";

import React from "react";

export interface RepositoryAnalysisFormProps {
  path: string;
  onPathChange: (value: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  isLoading: boolean;
  validationError?: string | null;
  name?: string;
  onNameChange?: (value: string) => void;
}

export default function RepositoryAnalysisForm({
  path,
  onPathChange,
  onSubmit,
  isLoading,
  validationError,
  name = "",
  onNameChange,
}: RepositoryAnalysisFormProps) {
  return (
    <form
      onSubmit={onSubmit}
      className="analysis-form"
      data-testid="repository-analysis-form"
      noValidate
    >
      <div className="form-group">
        <label htmlFor="repo-path-input" className="form-label">
          Repository Path <span className="required-indicator">*</span>
        </label>
        <p id="repo-path-help" className="form-instructions">
          Enter the local filesystem path to the Python repository for static analysis and graph construction.
        </p>
        <div className="input-wrapper">
          <input
            id="repo-path-input"
            name="path"
            type="text"
            className={`form-input ${validationError ? "input-invalid" : ""}`}
            placeholder="e.g. tests/fixtures/atlas_fixture or /workspace/my-python-project"
            value={path}
            onChange={(e) => onPathChange(e.target.value)}
            disabled={isLoading}
            aria-describedby={`repo-path-help ${validationError ? "repo-path-error" : ""}`}
            aria-invalid={Boolean(validationError)}
            aria-required="true"
            data-testid="repository-path-input"
            autoComplete="off"
            spellCheck="false"
          />
        </div>
        {validationError && (
          <p
            id="repo-path-error"
            className="validation-error-message"
            role="alert"
            data-testid="path-validation-error"
          >
            {validationError}
          </p>
        )}
      </div>

      {onNameChange && (
        <div className="form-group">
          <label htmlFor="repo-name-input" className="form-label">
            Repository Name <span className="optional-tag">(Optional)</span>
          </label>
          <input
            id="repo-name-input"
            name="name"
            type="text"
            className="form-input"
            placeholder="e.g. atlas_fixture (defaults to directory name)"
            value={name}
            onChange={(e) => onNameChange(e.target.value)}
            disabled={isLoading}
            data-testid="repository-name-input"
            autoComplete="off"
          />
        </div>
      )}

      <div className="form-action-row">
        <button
          type="submit"
          className="btn-primary"
          disabled={isLoading}
          aria-busy={isLoading}
          data-testid="analyze-submit-btn"
        >
          {isLoading ? (
            <>
              <span className="button-spinner" aria-hidden="true" />
              <span>Analyzing Repository...</span>
            </>
          ) : (
            <span>Analyze Repository</span>
          )}
        </button>
      </div>
    </form>
  );
}
