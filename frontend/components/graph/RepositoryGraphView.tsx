"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  type ReactFlowInstance,
  type Node,
  type Edge,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { getRepositoryGraph, ApiClientError } from "../../lib/api.ts";
import {
  mapGraphResponseToReactFlow,
  type EntityNodeData,
} from "../../lib/graphMapper.ts";
import type { GraphFetchStatus, RepositoryGraphResponse } from "../../lib/types.ts";
import EntityNode from "./EntityNode.tsx";

export interface RepositoryGraphViewProps {
  initialRepositoryId?: string;
  onBackToAnalysis?: () => void;
  fetchGraphFn?: (repositoryId: string) => Promise<RepositoryGraphResponse>;
}

export default function RepositoryGraphView({
  initialRepositoryId = "",
  onBackToAnalysis,
  fetchGraphFn = getRepositoryGraph,
}: RepositoryGraphViewProps) {
  const [repositoryIdInput, setRepositoryIdInput] = useState<string>(initialRepositoryId);
  const [prevInitialId, setPrevInitialId] = useState<string>(initialRepositoryId);
  const [activeRepositoryId, setActiveRepositoryId] = useState<string>(initialRepositoryId);
  const [status, setStatus] = useState<GraphFetchStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<EntityNodeData | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // Adjust state during render if prop changes (React 19 pattern)
  if (initialRepositoryId !== prevInitialId) {
    setPrevInitialId(initialRepositoryId);
    setRepositoryIdInput(initialRepositoryId);
  }

  const nodeTypes = useMemo(() => ({ entityNode: EntityNode }), []);

  const loadGraph = useCallback(
    async (repoId: string) => {
      const cleanId = repoId.trim();
      if (!cleanId) {
        setErrorMessage("Please enter a valid repository identifier.");
        setStatus("error");
        return;
      }

      setStatus("loading");
      setErrorMessage(null);
      setSelectedEntity(null);

      try {
        const response = await fetchGraphFn(cleanId);
        setActiveRepositoryId(response.repository_id || cleanId);

        if (!response.nodes || response.nodes.length === 0) {
          setNodes([]);
          setEdges([]);
          setStatus("empty");
          return;
        }

        const { nodes: rfNodes, edges: rfEdges } = mapGraphResponseToReactFlow(response);
        setNodes(rfNodes as Node[]);
        setEdges(rfEdges);
        setStatus("success");

        // Fit view after nodes render
        setTimeout(() => {
          rfInstance?.fitView({ padding: 0.15, duration: 300 });
        }, 50);
      } catch (err: unknown) {
        setStatus("error");
        if (err instanceof ApiClientError) {
          setErrorMessage(err.message);
        } else if (err instanceof Error) {
          setErrorMessage(err.message);
        } else {
          setErrorMessage("Failed to retrieve repository graph. Please check service connectivity.");
        }
      }
    },
    [fetchGraphFn, rfInstance, setNodes, setEdges]
  );

  // Automatically load graph on mount if initialRepositoryId is provided
  useEffect(() => {
    let isMounted = true;
    if (initialRepositoryId && initialRepositoryId.trim()) {
      const cleanId = initialRepositoryId.trim();
      void Promise.resolve().then(() => {
        if (isMounted) {
          loadGraph(cleanId);
        }
      });
    }
    return () => {
      isMounted = false;
    };
  }, [initialRepositoryId, loadGraph]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (repositoryIdInput.trim()) {
      loadGraph(repositoryIdInput.trim());
    }
  };

  const handleFitView = useCallback(() => {
    rfInstance?.fitView({ padding: 0.15, duration: 400 });
  }, [rfInstance]);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedEntity((node.data as unknown as EntityNodeData) || null);
    },
    []
  );

  const handlePaneClick = useCallback(() => {
    setSelectedEntity(null);
  }, []);

  return (
    <div className="graph-view-wrapper" data-testid="repository-graph-view">
      {/* Top Header & Navigation Bar */}
      <div className="graph-toolbar">
        <div className="toolbar-left">
          {onBackToAnalysis && (
            <button
              type="button"
              className="btn-toolbar-nav"
              onClick={onBackToAnalysis}
              data-testid="btn-back-to-analysis"
              title="Return to repository analysis view"
            >
              ← Back to Analysis
            </button>
          )}

          <form onSubmit={handleSubmit} className="toolbar-repo-form">
            <label htmlFor="graph-repo-id-input" className="sr-only">
              Repository ID
            </label>
            <input
              id="graph-repo-id-input"
              type="text"
              className="toolbar-input"
              placeholder="Repository ID (e.g. atlas_fixture)"
              value={repositoryIdInput}
              onChange={(e) => setRepositoryIdInput(e.target.value)}
              disabled={status === "loading"}
              data-testid="graph-repo-id-input"
            />
            <button
              type="submit"
              className="btn-toolbar-submit"
              disabled={status === "loading" || !repositoryIdInput.trim()}
              data-testid="btn-load-graph"
            >
              {status === "loading" ? "Loading..." : "Load Graph"}
            </button>
          </form>
        </div>

        <div className="toolbar-right">
          {status === "success" && (
            <>
              <div className="graph-stat-pills">
                <span className="stat-pill-item" data-testid="graph-stat-repo">
                  Repo: <strong>{activeRepositoryId}</strong>
                </span>
                <span className="stat-pill-item" data-testid="graph-stat-nodes">
                  Nodes: <strong>{nodes.length}</strong>
                </span>
                <span className="stat-pill-item" data-testid="graph-stat-edges">
                  Edges: <strong>{edges.length}</strong>
                </span>
              </div>

              <button
                type="button"
                className="btn-toolbar-action"
                onClick={handleFitView}
                data-testid="btn-fit-view"
                title="Fit graph into viewport"
              >
                Fit View
              </button>

              <button
                type="button"
                className="btn-toolbar-action"
                onClick={() => loadGraph(activeRepositoryId)}
                data-testid="btn-refresh-graph"
                title="Reload graph from backend"
              >
                ↻ Refresh
              </button>
            </>
          )}
        </div>
      </div>

      {/* Main Canvas Area */}
      <div className="graph-canvas-container" data-testid="graph-canvas-container">
        {/* Loading Overlay */}
        {status === "loading" && (
          <div
            className="graph-state-overlay"
            role="status"
            aria-live="polite"
            data-testid="graph-loading-indicator"
          >
            <div className="spinner-ring" aria-hidden="true" />
            <div className="graph-state-text-group">
              <span className="state-primary-text">Retrieving Knowledge Graph...</span>
              <span className="state-secondary-text">
                Fetching code entities and relationships for &apos;{repositoryIdInput}&apos;
              </span>
            </div>
          </div>
        )}

        {/* Error Overlay */}
        {status === "error" && errorMessage && (
          <div className="graph-state-overlay" role="alert" data-testid="graph-error-banner">
            <div className="state-alert-box">
              <div className="state-alert-title">Failed to Load Graph</div>
              <div className="state-alert-message">{errorMessage}</div>
              <div className="state-alert-actions">
                <button
                  type="button"
                  className="btn-primary-sm"
                  onClick={() => loadGraph(repositoryIdInput)}
                  data-testid="btn-retry-graph"
                >
                  Retry
                </button>
                {onBackToAnalysis && (
                  <button
                    type="button"
                    className="btn-secondary-sm"
                    onClick={onBackToAnalysis}
                  >
                    Go to Analysis
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Empty State Overlay */}
        {status === "empty" && (
          <div className="graph-state-overlay" data-testid="graph-empty-banner">
            <div className="state-empty-box">
              <div className="state-empty-title">Empty Repository Graph</div>
              <div className="state-empty-message">
                No entities or relationships were found for repository &apos;{activeRepositoryId}&apos;.
                Please ensure the repository has been analyzed.
              </div>
              <div className="state-alert-actions">
                {onBackToAnalysis && (
                  <button
                    type="button"
                    className="btn-primary-sm"
                    onClick={onBackToAnalysis}
                  >
                    Analyze Repository
                  </button>
                )}
                <button
                  type="button"
                  className="btn-secondary-sm"
                  onClick={() => loadGraph(activeRepositoryId)}
                >
                  Reload
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Idle Prompt State Overlay */}
        {status === "idle" && (
          <div className="graph-state-overlay" data-testid="graph-idle-banner">
            <div className="state-idle-box">
              <div className="state-idle-title">Repository Knowledge Graph</div>
              <div className="state-idle-message">
                Enter a repository identifier above or analyze a repository to view its interactive code graph.
              </div>
              {onBackToAnalysis && (
                <button
                  type="button"
                  className="btn-primary-sm"
                  onClick={onBackToAnalysis}
                >
                  Go to Repository Analysis
                </button>
              )}
            </div>
          </div>
        )}

        {/* Interactive React Flow Canvas */}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          onInit={setRfInstance}
          onNodeClick={handleNodeClick}
          onPaneClick={handlePaneClick}
          fitView
          minZoom={0.05}
          maxZoom={2.5}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#334155" />
          <Controls showInteractive={false} />
        </ReactFlow>

        {/* Selected Node Inspector Pill */}
        {selectedEntity && (
          <div className="graph-inspector-panel" data-testid="graph-inspector-panel">
            <div className="inspector-header">
              <span className="inspector-type">{selectedEntity.label || selectedEntity.type}</span>
              <button
                type="button"
                className="btn-inspector-close"
                onClick={() => setSelectedEntity(null)}
                aria-label="Close entity inspection"
              >
                ✕
              </button>
            </div>
            <div className="inspector-name" title={selectedEntity.displayName}>
              {selectedEntity.displayName}
            </div>
            <div className="inspector-id" title={selectedEntity.id}>
              {selectedEntity.id}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
