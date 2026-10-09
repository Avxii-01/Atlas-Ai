"use client";

import React, { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { EntityNodeData } from "../../lib/graphMapper.ts";

/**
 * Returns a theme badge color class or background based on entity kind.
 */
function getBadgeStyle(label: string): { bg: string; text: string; border: string } {
  const kind = (label || "").toLowerCase();
  switch (kind) {
    case "repository":
      return { bg: "rgba(168, 85, 247, 0.15)", text: "#c084fc", border: "rgba(168, 85, 247, 0.35)" };
    case "file":
      return { bg: "rgba(59, 130, 246, 0.15)", text: "#60a5fa", border: "rgba(59, 130, 246, 0.35)" };
    case "module":
      return { bg: "rgba(6, 182, 212, 0.15)", text: "#22d3ee", border: "rgba(6, 182, 212, 0.35)" };
    case "class":
      return { bg: "rgba(99, 102, 241, 0.15)", text: "#a5b4fc", border: "rgba(99, 102, 241, 0.35)" };
    case "function":
      return { bg: "rgba(16, 185, 129, 0.15)", text: "#34d399", border: "rgba(16, 185, 129, 0.35)" };
    case "method":
      return { bg: "rgba(20, 184, 166, 0.15)", text: "#2dd4bf", border: "rgba(20, 184, 166, 0.35)" };
    case "import":
      return { bg: "rgba(245, 158, 11, 0.15)", text: "#fbbf24", border: "rgba(245, 158, 11, 0.35)" };
    default:
      return { bg: "rgba(148, 163, 184, 0.15)", text: "#cbd5e1", border: "rgba(148, 163, 184, 0.3)" };
  }
}

/**
 * Custom React Flow node component for Atlas AI code entities.
 * Displays the entity type badge, readable display label, and connection handles.
 */
function EntityNodeComponent({
  id,
  data,
  selected,
}: NodeProps & { data: EntityNodeData }) {
  const badgeStyle = getBadgeStyle(data.label || data.type);

  return (
    <div
      className={`entity-node-container ${selected ? "entity-node-selected" : ""}`}
      data-testid={`graph-node-${id}`}
      data-entity-type={data.type}
      title={`${data.label}: ${data.displayName} (${id})`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="entity-handle entity-handle-target"
      />

      <div className="entity-node-content">
        <div className="entity-node-header">
          <span
            className="entity-type-badge"
            style={{
              backgroundColor: badgeStyle.bg,
              color: badgeStyle.text,
              borderColor: badgeStyle.border,
            }}
          >
            {data.label || data.type}
          </span>
        </div>

        <div className="entity-node-label" title={data.displayName}>
          {data.displayName}
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="entity-handle entity-handle-source"
      />
    </div>
  );
}

export default memo(EntityNodeComponent);
