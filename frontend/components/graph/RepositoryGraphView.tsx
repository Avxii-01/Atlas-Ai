"use client";

import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Panel,
  useNodesState,
  useEdgesState,
  type ReactFlowInstance,
  type Node,
  type Edge,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { getRepositoryGraph, getRepositoryImpact, ApiClientError } from "../../lib/api.ts";
import {
  mapGraphResponseToReactFlow,
  type EntityNodeData,
} from "../../lib/graphMapper.ts";
import type { GraphFetchStatus, RepositoryGraphResponse } from "../../lib/types.ts";
import {
  mockFetchNodeChildren,
  mergeGraphData,
  collapseNodeDescendants,
  isKnownLeafType,
  type FetchNodeChildrenFn,
} from "../../lib/progressiveExploration.ts";
import EntityNode from "./EntityNode.tsx";
import ImpactDetailsPanel from "./ImpactDetailsPanel.tsx";
import GraphLegend from "./GraphLegend.tsx";
import GraphSearch from "./GraphSearch.tsx";

export interface RepositoryGraphViewProps {
  initialRepositoryId?: string;
  onBackToAnalysis?: () => void;
  fetchGraphFn?: (
    repositoryId: string,
    options?: { limit?: number; signal?: AbortSignal }
  ) => Promise<RepositoryGraphResponse>;
  fetchImpactFn?: typeof getRepositoryImpact;
  fetchNodeChildrenFn?: FetchNodeChildrenFn;
}

export default function RepositoryGraphView({
  initialRepositoryId = "",
  onBackToAnalysis,
  fetchGraphFn = getRepositoryGraph,
  fetchImpactFn = getRepositoryImpact,
  fetchNodeChildrenFn = mockFetchNodeChildren,
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

  // Progressive exploration tracking state (Checkpoint 4)
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(new Set());
  const [loadingNodeIds, setLoadingNodeIds] = useState<Set<string>>(new Set());
  const [nodeErrors, setNodeErrors] = useState<Map<string, string>>(new Map());

  // Race condition & cancellation guards
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeRepoIdRef = useRef<string | null>(null);
  const requestIdRef = useRef<number>(0);
  const rfInstanceRef = useRef<ReactFlowInstance | null>(null);

  // Progressive exploration refs for stable async synchronization
  const expandedNodeIdsRef = useRef<Set<string>>(new Set());
  const loadingNodeIdsRef = useRef<Set<string>>(new Set());
  const parentToChildrenMapRef = useRef<Map<string, Set<string>>>(new Map());
  const baseNodesRef = useRef<Node<EntityNodeData>[]>([]);
  const baseEdgesRef = useRef<Edge[]>([]);
  const handleToggleExpandRef = useRef<(id: string) => Promise<void>>(() => Promise.resolve());
  const nodesRef = useRef<Node[]>([]);
  const edgesRef = useRef<Edge[]>([]);

  // Synchronize nodes and edges refs for stable access in async callbacks
  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  // Adjust state during render if prop changes (React 19 pattern)
  if (initialRepositoryId !== prevInitialId) {
    setPrevInitialId(initialRepositoryId);
    setRepositoryIdInput(initialRepositoryId);
  }

  const nodeTypes = useMemo(() => ({ entityNode: EntityNode }), []);

  const handleInit = useCallback((instance: ReactFlowInstance) => {
    setRfInstance(instance);
    rfInstanceRef.current = instance;
  }, []);

  const handleFitView = useCallback(() => {
    (rfInstanceRef.current || rfInstance)?.fitView({ padding: 0.15, duration: 400 });
  }, [rfInstance]);

  // Progressive exploration expand/collapse handler
  const handleToggleExpand = useCallback(
    async (nodeId: string) => {
      // 1. Guard against duplicate calls while in-flight
      if (loadingNodeIdsRef.current.has(nodeId)) {
        return;
      }

      // 2. Collapse if currently expanded
      if (expandedNodeIdsRef.current.has(nodeId)) {
        const currentNodes = (nodesRef.current.length > 0 ? nodesRef.current : nodes) as Node<EntityNodeData>[];
        const currentEdges = edgesRef.current.length > 0 ? edgesRef.current : edges;

        const { updatedNodes, updatedEdges, removedNodeIds } = collapseNodeDescendants(
          nodeId,
          parentToChildrenMapRef.current,
          currentNodes,
          currentEdges
        );

        parentToChildrenMapRef.current.delete(nodeId);

        const nextExpanded = new Set(expandedNodeIdsRef.current);
        nextExpanded.delete(nodeId);
        for (const rId of removedNodeIds) {
          nextExpanded.delete(rId);
          parentToChildrenMapRef.current.delete(rId);
        }
        expandedNodeIdsRef.current = nextExpanded;
        setExpandedNodeIds(nextExpanded);

        setSelectedEntity((currentSelected) => {
          if (currentSelected && removedNodeIds.has(currentSelected.id)) {
            return null;
          }
          return currentSelected;
        });

        nodesRef.current = updatedNodes as Node[];
        edgesRef.current = updatedEdges;
        setNodes(updatedNodes as Node[]);
        setEdges(updatedEdges);
        return;
      }

      // 3. Expand if not yet expanded
      const currentNodes = (nodesRef.current.length > 0 ? nodesRef.current : nodes) as Node<EntityNodeData>[];
      const targetParent = currentNodes.find((n) => n.id === nodeId);
      if (!targetParent) return;

      const nextLoading = new Set(loadingNodeIdsRef.current);
      nextLoading.add(nodeId);
      loadingNodeIdsRef.current = nextLoading;
      setLoadingNodeIds(nextLoading);

      setNodes((prevNodes) =>
        prevNodes.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, isLoadingChildren: true } } : n
        )
      );

      try {
        const response = await fetchNodeChildrenFn(activeRepositoryId, nodeId);

        // Always clear loading state upon response arrival
        const nextLoad = new Set(loadingNodeIdsRef.current);
        nextLoad.delete(nodeId);
        loadingNodeIdsRef.current = nextLoad;
        setLoadingNodeIds(nextLoad);

        // Handle empty child response
        if (!response.nodes || response.nodes.length === 0) {
          setNodes((prevNodes) =>
            prevNodes.map((n) =>
              n.id === nodeId
                ? { ...n, data: { ...n.data, isLoadingChildren: false, hasNoChildren: true } }
                : n
            )
          );
          return;
        }

        // Add to expanded set
        const nextExp = new Set(expandedNodeIdsRef.current);
        nextExp.add(nodeId);
        expandedNodeIdsRef.current = nextExp;
        setExpandedNodeIds(nextExp);

        // Merge children and relationships
        const latestNodes = (nodesRef.current.length > 0 ? nodesRef.current : nodes) as Node<EntityNodeData>[];
        const latestEdges = edgesRef.current.length > 0 ? edgesRef.current : edges;
        const parentNodeToExpand =
          latestNodes.find((n) => n.id === nodeId) || targetParent;

        const { mergedNodes, mergedEdges, addedNodeIds } = mergeGraphData(
          latestNodes,
          latestEdges,
          parentNodeToExpand,
          response.nodes,
          response.relationships,
          {
            onToggleExpand: (id: string) => {
              void handleToggleExpandRef.current(id);
            },
            expandedNodeIds: nextExp,
            loadingNodeIds: nextLoad,
          }
        );

        parentToChildrenMapRef.current.set(nodeId, new Set(addedNodeIds));
        nodesRef.current = mergedNodes as Node[];
        edgesRef.current = mergedEdges;
        setNodes(mergedNodes as Node[]);
        setEdges(mergedEdges);
      } catch (err: unknown) {
        const nextLoad = new Set(loadingNodeIdsRef.current);
        nextLoad.delete(nodeId);
        loadingNodeIdsRef.current = nextLoad;
        setLoadingNodeIds(nextLoad);

        setNodes((prevNodes) =>
          prevNodes.map((n) =>
            n.id === nodeId ? { ...n, data: { ...n.data, isLoadingChildren: false } } : n
          )
        );

        const msg = err instanceof Error ? err.message : "Failed to expand node";
        setNodeErrors((prev) => {
          const next = new Map(prev);
          next.set(nodeId, msg);
          return next;
        });
      }
    },
    [activeRepositoryId, fetchNodeChildrenFn, nodes, edges, setNodes, setEdges]
  );

  // Synchronize expand handler ref for child node callbacks
  useEffect(() => {
    handleToggleExpandRef.current = handleToggleExpand;
  }, [handleToggleExpand]);

  const loadGraph = useCallback(
    async (repoId: string) => {
      const cleanId = repoId.trim();
      if (!cleanId) {
        setErrorMessage("Please enter a valid repository identifier.");
        setStatus("error");
        return;
      }

      // Abort prior in-flight request if active
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;
      activeRepoIdRef.current = cleanId;
      const currentRequestId = ++requestIdRef.current;

      setStatus("loading");
      setErrorMessage(null);
      setSelectedEntity(null);

      try {
        const response = await fetchGraphFn(cleanId, { signal: controller.signal });

        // Stale response guard: ensure response matches active request and was not aborted
        if (
          requestIdRef.current !== currentRequestId ||
          activeRepoIdRef.current !== cleanId ||
          controller.signal.aborted
        ) {
          return;
        }

        setActiveRepositoryId(response.repository_id || cleanId);

        if (!response.nodes || response.nodes.length === 0) {
          setNodes([]);
          setEdges([]);
          setStatus("empty");
          return;
        }

        const { nodes: rfNodes, edges: rfEdges } = mapGraphResponseToReactFlow(response);

        // Bind progressive exploration handlers and flags
        const mappedWithHandlers = rfNodes.map((n) => ({
          ...n,
          data: {
            ...n.data,
            isExpandable: !isKnownLeafType(n.data.type || n.data.label),
            isExpanded: false,
            isLoadingChildren: false,
            onToggleExpand: (id: string) => {
              void handleToggleExpandRef.current(id);
            },
          },
        }));

        setNodes(mappedWithHandlers as Node[]);
        setEdges(rfEdges);
        nodesRef.current = mappedWithHandlers as Node[];
        edgesRef.current = rfEdges;
        setExpandedNodeIds(new Set());
        setLoadingNodeIds(new Set());
        setNodeErrors(new Map());

        expandedNodeIdsRef.current = new Set();
        loadingNodeIdsRef.current = new Set();
        parentToChildrenMapRef.current = new Map();
        baseNodesRef.current = mappedWithHandlers as Node<EntityNodeData>[];
        baseEdgesRef.current = rfEdges;

        setStatus("success");

        // Fit view after nodes render
        setTimeout(() => {
          (rfInstanceRef.current || rfInstance)?.fitView({ padding: 0.15, duration: 300 });
        }, 50);
      } catch (err: unknown) {
        // Silently ignore aborted requests to prevent misleading error displays
        if (
          controller.signal.aborted ||
          (err instanceof ApiClientError && err.code === "ABORTED") ||
          (err instanceof Error && err.name === "AbortError")
        ) {
          return;
        }

        // Only commit error if this request is still the active request
        if (
          requestIdRef.current === currentRequestId &&
          activeRepoIdRef.current === cleanId
        ) {
          setStatus("error");
          if (err instanceof ApiClientError) {
            setErrorMessage(err.message);
          } else if (err instanceof Error) {
            setErrorMessage(err.message);
          } else {
            setErrorMessage("Failed to retrieve repository graph. Please check service connectivity.");
          }
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
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [initialRepositoryId, loadGraph]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (repositoryIdInput.trim()) {
      loadGraph(repositoryIdInput.trim());
    }
  };

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const entityData = (node.data as unknown as EntityNodeData) || null;
      setSelectedEntity(entityData);
      setNodes((prevNodes) =>
        prevNodes.map((n) => ({
          ...n,
          selected: n.id === node.id,
        }))
      );
    },
    [setNodes]
  );

  const handlePaneClick = useCallback(() => {
    setSelectedEntity(null);
    setNodes((prevNodes) =>
      prevNodes.map((n) => ({
        ...n,
        selected: false,
      }))
    );
  }, [setNodes]);

  const handleSelectEntityById = useCallback(
    (entityId: string) => {
      const targetNode = nodes.find((n) => n.id === entityId);
      if (targetNode) {
        setSelectedEntity(targetNode.data as unknown as EntityNodeData);
        setNodes((prevNodes) =>
          prevNodes.map((n) => ({
            ...n,
            selected: n.id === entityId,
          }))
        );
        const inst = rfInstanceRef.current || rfInstance;
        inst?.setCenter(
          targetNode.position.x + 100,
          targetNode.position.y + 40,
          { duration: 400, zoom: Math.max(inst.getZoom(), 0.8) }
        );
      }
    },
    [nodes, rfInstance, setNodes]
  );

  const handleCloseImpactPanel = useCallback(() => {
    setSelectedEntity(null);
    setNodes((prevNodes) =>
      prevNodes.map((n) => ({
        ...n,
        selected: false,
      }))
    );
  }, [setNodes]);

  const handleResetExploration = useCallback(() => {
    if (baseNodesRef.current.length > 0) {
      setNodes(baseNodesRef.current as Node[]);
      setEdges(baseEdgesRef.current);
      nodesRef.current = baseNodesRef.current as Node[];
      edgesRef.current = baseEdgesRef.current;
      setExpandedNodeIds(new Set());
      setLoadingNodeIds(new Set());
      setNodeErrors(new Map());
      expandedNodeIdsRef.current = new Set();
      loadingNodeIdsRef.current = new Set();
      parentToChildrenMapRef.current = new Map();
      handleFitView();
    }
  }, [setNodes, setEdges, handleFitView]);

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
              {/* Local In-Memory Graph Search (Checkpoint 3) */}
              <GraphSearch
                nodes={nodes as Node<EntityNodeData>[]}
                onSelectNode={handleSelectEntityById}
              />

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
                {expandedNodeIds.size > 0 && (
                  <span className="stat-pill-item" data-testid="graph-stat-expanded">
                    Expanded: <strong>{expandedNodeIds.size}</strong>
                  </span>
                )}
                {loadingNodeIds.size > 0 && (
                  <span className="stat-pill-item" data-testid="graph-stat-loading">
                    Expanding...
                  </span>
                )}
              </div>

              {expandedNodeIds.size > 0 && (
                <button
                  type="button"
                  className="btn-toolbar-action"
                  onClick={handleResetExploration}
                  data-testid="btn-reset-exploration"
                  title="Collapse all expanded nodes back to initial graph"
                >
                  Reset Exploration
                </button>
              )}

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

      {/* Main Canvas & Impact Layout Area */}
      <div className="graph-layout-body">
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

          {/* Node Expansion Error Toast / Banner */}
          {nodeErrors.size > 0 && (
            <div
              className="graph-expansion-error-banner"
              role="alert"
              data-testid="graph-expansion-error"
            >
              <div className="expansion-error-message">
                {Array.from(nodeErrors.entries()).map(([nId, err]) => (
                  <span key={nId}>
                    Error expanding <strong>{nId}</strong>: {err}
                  </span>
                ))}
              </div>
              <button
                type="button"
                className="btn-close-toast"
                onClick={() => setNodeErrors(new Map())}
                aria-label="Dismiss error"
              >
                ✕
              </button>
            </div>
          )}

          {/* Interactive React Flow Canvas */}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            onInit={handleInit}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            fitView
            minZoom={0.05}
            maxZoom={2.5}
          >
            <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#334155" />
            <Controls showInteractive={false} />
            {status === "success" && (
              <Panel position="bottom-right">
                <GraphLegend />
              </Panel>
            )}
          </ReactFlow>
        </div>

        {/* Impact Analysis Details Panel */}
        <ImpactDetailsPanel
          selectedEntity={selectedEntity}
          repositoryId={activeRepositoryId}
          onClose={handleCloseImpactPanel}
          onSelectEntity={handleSelectEntityById}
          fetchImpactFn={fetchImpactFn}
        />
      </div>
    </div>
  );
}
