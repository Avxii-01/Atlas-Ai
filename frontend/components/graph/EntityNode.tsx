"use client";

import React, { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { EntityNodeData } from "../../lib/graphMapper.ts";
import { getEntityBadgeStyle, type EntityBadgeStyle } from "../../lib/graphTokens.ts";

/**
 * Returns a theme badge color class or background based on entity kind.
 * Delegates to centralized graphTokens definition.
 */
export function getBadgeStyle(label: string): EntityBadgeStyle {
  return getEntityBadgeStyle(label);
}

/**
 * Custom React Flow node component for Atlas AI code entities.
 * Displays the entity type badge, readable display label, connection handles,
 * and progressive exploration expand/collapse toggle button (Checkpoint 4).
 */
function EntityNodeComponent({
  id,
  data,
  selected,
}: NodeProps & { data: EntityNodeData }) {
  const badgeStyle = getBadgeStyle(data.label || data.type);
  const canExpand = data.isExpandable !== false && typeof data.onToggleExpand === "function";

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (data.isLoadingChildren || data.hasNoChildren) return;
    data.onToggleExpand?.(id);
  };

  return (
    <div
      className={`entity-node-container ${selected ? "entity-node-selected" : ""} ${
        data.isExpanded ? "entity-node-expanded" : ""
      }`}
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

          {canExpand && (
            <button
              type="button"
              className={`btn-node-expand ${data.isExpanded ? "expanded" : ""} ${
                data.hasNoChildren ? "empty" : ""
              }`}
              onClick={handleToggle}
              onPointerDown={(e) => e.stopPropagation()}
              onMouseDown={(e) => e.stopPropagation()}
              disabled={data.isLoadingChildren || data.hasNoChildren}
              aria-expanded={data.isExpanded || false}
              aria-label={
                data.hasNoChildren
                  ? `No children for ${data.displayName}`
                  : data.isExpanded
                  ? `Collapse children of ${data.displayName}`
                  : `Expand children of ${data.displayName}`
              }
              title={
                data.hasNoChildren
                  ? "No child entities found"
                  : data.isExpanded
                  ? "Collapse children"
                  : "Expand direct children"
              }
              data-testid={`btn-toggle-expand-${id}`}
            >
              {data.isLoadingChildren ? (
                <span className="expand-spinner" aria-hidden="true" />
              ) : data.hasNoChildren ? (
                "•"
              ) : data.isExpanded ? (
                "−"
              ) : (
                "+"
              )}
            </button>
          )}
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
