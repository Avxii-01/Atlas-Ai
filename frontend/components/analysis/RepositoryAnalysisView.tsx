"use client";

import React, { useState, useCallback } from "react";
import {
  RepositoryAnalysisRequest,
  RepositoryAnalysisResponse,
  AnalysisStatus,
} from "../../lib/types";
import { analyzeRepository } from "../../lib/api";
import RepositoryAnalysisForm from "./RepositoryAnalysisForm";
import AnalysisResultCard from "./AnalysisResultCard";
import AnalysisErrorAlert from "./AnalysisErrorAlert";

export interface RepositoryAnalysisViewProps {
  initialPath?: string;
  onAnalyze?: (request: RepositoryAnalysisRequest) => Promise<RepositoryAnalysisResponse>;
}

export default function RepositoryAnalysisView({
  initialPath = "",
  onAnalyze = analyzeRepository,
}: RepositoryAnalysisViewProps) {
  const [path, setPath] = useState<string>(initialPath);
  const [name, setName] = useState<string>("");
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [result, setResult] = useState<RepositoryAnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const handlePathChange = useCallback((newPath: string) => {
    setPath(newPath);
    // Clear validation error when user begins typing
    if (validationError) {
      setValidationError(null);
    }
  }, [validationError]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      // Prevent duplicate submission if already in progress
      if (status === "loading") {
        return;
      }

      const trimmedPath = path.trim();

      if (!trimmedPath) {
        setValidationError("Repository path is required. Please enter a valid filesystem path.");
        return;
      }

      setValidationError(null);
      setErrorMessage(null);
      // Clear previous result so stale data is not mistaken for current request
      setResult(null);
      setStatus("loading");

      try {
        const payload: RepositoryAnalysisRequest = {
          path: trimmedPath,
          ...(name.trim() ? { name: name.trim() } : {}),
        };

        const response = await onAnalyze(payload);
        setResult(response);
        setStatus("success");
      } catch (err: unknown) {
        const msg =
          err instanceof Error
            ? err.message
            : "An unexpected error occurred during repository analysis.";
        setErrorMessage(msg);
        setStatus("error");
      }
    },
    [path, name, status, onAnalyze]
  );

  const handleReset = useCallback(() => {
    setResult(null);
    setErrorMessage(null);
    setValidationError(null);
    setStatus("idle");
  }, []);

  const handleRetry = useCallback(() => {
    // Re-trigger submit with current path
    const fakeEvent = { preventDefault: () => {} } as React.FormEvent;
    handleSubmit(fakeEvent);
  }, [handleSubmit]);

  return (
    <div className="analysis-view-wrapper" data-testid="repository-analysis-view">
      <div className="analysis-view-card">
        <div className="view-header">
          <div className="view-title-group">
            <h2 className="view-title">Analyze Repository</h2>
            <p className="view-description">
              Scan, parse, and resolve Python code entities and relationships to build a repository knowledge graph.
            </p>
          </div>
        </div>

        {/* Repository Input Form */}
        <RepositoryAnalysisForm
          path={path}
          onPathChange={handlePathChange}
          name={name}
          onNameChange={setName}
          onSubmit={handleSubmit}
          isLoading={status === "loading"}
          validationError={validationError}
        />

        {/* Loading In-Progress State */}
        {status === "loading" && (
          <div
            className="analysis-loading-banner"
            role="status"
            aria-live="polite"
            data-testid="analysis-loading-indicator"
          >
            <div className="spinner-ring" aria-hidden="true" />
            <div className="loading-text-group">
              <span className="loading-primary-text">Analyzing repository...</span>
              <span className="loading-secondary-text">
                Parsing syntax tree, resolving imports, and storing knowledge graph in Neo4j.
              </span>
            </div>
          </div>
        )}

        {/* Error State */}
        {status === "error" && errorMessage && (
          <div className="view-alert-slot">
            <AnalysisErrorAlert
              message={errorMessage}
              onDismiss={() => setErrorMessage(null)}
              onRetry={handleRetry}
            />
          </div>
        )}

        {/* Success State */}
        {status === "success" && result && (
          <div className="view-result-slot">
            <AnalysisResultCard result={result} onReset={handleReset} />
          </div>
        )}
      </div>
    </div>
  );
}
