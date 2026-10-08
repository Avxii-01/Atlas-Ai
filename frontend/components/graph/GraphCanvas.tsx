"use client";

import React, { useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Node,
  type Edge,
  type Connection,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

const defaultInitialNodes: Node[] = [];
const defaultInitialEdges: Edge[] = [];

export interface GraphCanvasProps {
  initialNodes?: Node[];
  initialEdges?: Edge[];
  className?: string;
}

/**
 * Reusable GraphCanvas component wrapping React Flow for Atlas AI graph visualization.
 * Establishes the interactive node-link canvas foundation for P0.
 */
export default function GraphCanvas({
  initialNodes = defaultInitialNodes,
  initialEdges = defaultInitialEdges,
  className = "graph-canvas-container",
}: GraphCanvasProps) {
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge(connection, eds)),
    [setEdges]
  );

  return (
    <div className={className} data-testid="graph-canvas-container">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#334155" />
        <Controls />
        <MiniMap
          nodeColor="#6366f1"
          maskColor="rgba(15, 23, 42, 0.7)"
          zoomable
          pannable
        />
      </ReactFlow>
    </div>
  );
}
