"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { getRepositoryImpact, ApiClientError } from "../../lib/api.ts";
import type {
  RepositoryImpactResponse,
  ImpactFetchStatus,
  ImpactedEntityModel,
} from "../../lib/types.ts";
import type { EntityNodeData } from "../../lib/graphMapper.ts";

export interface ImpactDetailsPanelProps {
  selectedEntity: EntityNodeData | null;
  repositoryId: string;
  onClose: () => void;
  onSelectEntity?: (entityId: string) => void;
  fetchImpactFn?: typeof getRepositoryImpact;
}

export default function ImpactDetailsPanel({
  selectedEntity,
  repositoryId,
  onClose,
  onSelectEntity,
  fetchImpactFn = getRepositoryImpact,
}: ImpactDetailsPanelProps) {
  const [status, setStatus] = useState<ImpactFetchStatus>("idle");
  const [impactData, setImpactData] = useState<RepositoryImpactResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const activeEntityIdRef = useRef<string | null>(null);

  const loadImpact = useCallback(
    async (entityId: string, repoId: string) => {
      // Cancel any ongoing in-flight request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;
      activeEntityIdRef.current = entityId;

      setStatus("loading");
      setErrorMessage(null);
      setImpactData(null); // Clear stale data immediately

      try {
        const response = await fetchImpactFn(repoId, entityId, {
          signal: controller.signal,
        });

        // Guard against race conditions: verify response matches current selection
        if (activeEntityIdRef.current === entityId && !controller.signal.aborted) {
          setImpactData(response);
          const hasDependents =
            (response.direct_dependents && response.direct_dependents.length > 0) ||
            (response.transitive_dependents && response.transitive_dependents.length > 0);

          setStatus(hasDependents ? "success" : "empty");
        }
      } catch (err: unknown) {
        // Ignore aborted requests caused by rapid selection changes
        if (controller.signal.aborted) {
          return;
        }

        if (activeEntityIdRef.current === entityId) {
          setStatus("error");
          if (err instanceof ApiClientError) {
            setErrorMessage(err.message);
          } else if (err instanceof Error) {
            setErrorMessage(err.message);
          } else {
            setErrorMessage("Failed to calculate impact analysis for the selected entity.");
          }
        }
      }
    },
    [fetchImpactFn]
  );

  useEffect(() => {
    let isMounted = true;
    if (selectedEntity && repositoryId) {
      const entityId = selectedEntity.id;
      void Promise.resolve().then(() => {
        if (isMounted) {
          loadImpact(entityId, repositoryId);
        }
      });
    }

    return () => {
      isMounted = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [selectedEntity, repositoryId, loadImpact]);


  if (!selectedEntity) {
    return null;
  }

  const directList = impactData?.direct_dependents || [];
  const transitiveList = impactData?.transitive_dependents || [];
  const filesList = impactData?.affected_files || [];
  const maxDepth = impactData?.max_depth;

  return (
    <aside
      className="impact-panel-container"
      data-testid="impact-details-panel"
      aria-label="Impact Analysis Details"
    >
      {/* Panel Header */}
      <div className="impact-panel-header">
        <div className="impact-header-title-group">
          <span className="impact-header-badge">Impact Analysis</span>
          <h2 className="impact-entity-title" title={selectedEntity.displayName}>
            {selectedEntity.displayName}
          </h2>
          <div className="impact-entity-meta">
            <span className="impact-type-pill">{selectedEntity.label || selectedEntity.type}</span>
            <code className="impact-id-code" title={selectedEntity.id}>
              {selectedEntity.id}
            </code>
          </div>
        </div>

        <button
          type="button"
          className="btn-impact-close"
          onClick={onClose}
          data-testid="btn-close-impact-panel"
          aria-label="Close impact analysis panel"
        >
          ✕
        </button>
      </div>

      {/* Main Content Area */}
      <div className="impact-panel-body">
        {/* Loading State */}
        {status === "loading" && (
          <div
            className="impact-loading-state"
            role="status"
            aria-live="polite"
            data-testid="impact-loading-indicator"
          >
            <div className="spinner-ring-sm" aria-hidden="true" />
            <div className="impact-loading-text">
              <span className="impact-loading-primary">Analyzing Blast Radius...</span>
              <span className="impact-loading-secondary">
                Traversing dependency graph to identify direct and transitive dependents.
              </span>
            </div>
          </div>
        )}

        {/* Error State */}
        {status === "error" && errorMessage && (
          <div className="impact-error-state" role="alert" data-testid="impact-error-banner">
            <div className="impact-error-title">Analysis Failed</div>
            <div className="impact-error-message">{errorMessage}</div>
            <button
              type="button"
              className="btn-retry-sm"
              onClick={() => loadImpact(selectedEntity.id, repositoryId)}
              data-testid="btn-retry-impact"
            >
              Retry Analysis
            </button>
          </div>
        )}

        {/* Valid Empty Impact State */}
        {status === "empty" && (
          <div className="impact-empty-state" data-testid="impact-empty-banner">
            <div className="impact-empty-icon">✓</div>
            <div className="impact-empty-title">Zero Downstream Blast Radius</div>
            <p className="impact-empty-message">
              No direct or transitive dependents rely on this entity. Modifying or removing it has
              no detected impact within repository &apos;{repositoryId}&apos;.
            </p>
            {filesList.length > 0 && (
              <div className="impact-section">
                <h3 className="impact-section-title">Contained Within</h3>
                <ul className="affected-files-list">
                  {filesList.map((file) => (
                    <li key={file} className="affected-file-item">
                      <span className="file-icon">📄</span>
                      <span className="file-path">{file}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Success State with Dependents */}
        {status === "success" && impactData && (
          <>
            {/* Quick Metrics Bar */}
            <div className="impact-metrics-bar" data-testid="impact-metrics-bar">
              <div className="impact-metric-pill">
                <span className="metric-num">{directList.length}</span>
                <span className="metric-tag">Direct</span>
              </div>
              <div className="impact-metric-pill">
                <span className="metric-num">{transitiveList.length}</span>
                <span className="metric-tag">Transitive</span>
              </div>
              <div className="impact-metric-pill">
                <span className="metric-num">{filesList.length}</span>
                <span className="metric-tag">Files</span>
              </div>
              {maxDepth !== undefined && (
                <div className="impact-metric-pill depth-pill">
                  <span className="metric-num">{maxDepth}</span>
                  <span className="metric-tag">Max Depth</span>
                </div>
              )}
            </div>

            {/* Direct Impact Section */}
            <div className="impact-section" data-testid="section-direct-dependents">
              <div className="impact-section-header">
                <h3 className="impact-section-title">Direct Dependents ({directList.length})</h3>
                <span className="impact-section-subtitle">Hop Distance 1</span>
              </div>

              {directList.length === 0 ? (
                <div className="empty-subtext">No direct dependents.</div>
              ) : (
                <ul className="dependents-list">
                  {directList.map((dep: ImpactedEntityModel) => (
                    <li
                      key={dep.id}
                      className={`dependent-card ${onSelectEntity ? "dependent-clickable" : ""}`}
                      onClick={() => onSelectEntity?.(dep.id)}
                      data-testid={`direct-dep-${dep.id}`}
                      role={onSelectEntity ? "button" : undefined}
                      tabIndex={onSelectEntity ? 0 : undefined}
                      title={onSelectEntity ? `Select ${dep.name} in graph` : undefined}
                    >
                      <div className="dependent-card-header">
                        <span className="dependent-type-tag">{dep.label || dep.type || "Entity"}</span>
                        <span className="dependent-name">{dep.name}</span>
                      </div>
                      {dep.file_path && (
                        <div className="dependent-file-path" title={dep.file_path}>
                          {dep.file_path}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Transitive Impact Section */}
            <div className="impact-section" data-testid="section-transitive-dependents">
              <div className="impact-section-header">
                <h3 className="impact-section-title">Transitive Dependents ({transitiveList.length})</h3>
                <span className="impact-section-subtitle">Hop Distance &gt; 1</span>
              </div>

              {transitiveList.length === 0 ? (
                <div className="empty-subtext">No transitive dependents.</div>
              ) : (
                <ul className="dependents-list">
                  {transitiveList.map((dep: ImpactedEntityModel) => (
                    <li
                      key={dep.id}
                      className={`dependent-card ${onSelectEntity ? "dependent-clickable" : ""}`}
                      onClick={() => onSelectEntity?.(dep.id)}
                      data-testid={`transitive-dep-${dep.id}`}
                      role={onSelectEntity ? "button" : undefined}
                      tabIndex={onSelectEntity ? 0 : undefined}
                      title={onSelectEntity ? `Select ${dep.name} in graph` : undefined}
                    >
                      <div className="dependent-card-header">
                        <span className="dependent-type-tag">{dep.label || dep.type || "Entity"}</span>
                        <span className="dependent-name">{dep.name}</span>
                        <span className="depth-badge">Depth {dep.depth}</span>
                      </div>
                      {dep.file_path && (
                        <div className="dependent-file-path" title={dep.file_path}>
                          {dep.file_path}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Affected Files Section */}
            <div className="impact-section" data-testid="section-affected-files">
              <div className="impact-section-header">
                <h3 className="impact-section-title">Affected Files ({filesList.length})</h3>
              </div>

              {filesList.length === 0 ? (
                <div className="empty-subtext">No files affected.</div>
              ) : (
                <ul className="affected-files-list">
                  {filesList.map((filePath: string) => (
                    <li key={filePath} className="affected-file-item" data-testid={`affected-file-${filePath}`}>
                      <span className="file-icon" aria-hidden="true">📄</span>
                      <span className="file-path">{filePath}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
