"use client";

import React, { useState, useCallback } from "react";
import {
  SUPPORTED_ENTITY_TYPES,
  SUPPORTED_RELATIONSHIP_TYPES,
  getEntityBadgeStyle,
  getRelationshipEdgeStyle,
} from "../../lib/graphTokens.ts";

export interface GraphLegendProps {
  initialOpen?: boolean;
  className?: string;
  onToggle?: (isOpen: boolean) => void;
}

/**
 * Compact, accessible floating legend for Atlas AI graph entities and relationships.
 * Renders visual tokens identical to the canvas EntityNode and edge styles.
 */
export default function GraphLegend({
  initialOpen = false,
  className = "",
  onToggle,
}: GraphLegendProps) {
  const [isOpen, setIsOpen] = useState<boolean>(initialOpen);

  const handleToggle = useCallback(() => {
    setIsOpen((prev) => {
      const next = !prev;
      onToggle?.(next);
      return next;
    });
  }, [onToggle]);

  return (
    <div
      className={`graph-legend-container ${className}`.trim()}
      data-testid="graph-legend-container"
    >
      <button
        type="button"
        className={`btn-legend-toggle ${isOpen ? "legend-toggle-open" : ""}`}
        onClick={handleToggle}
        aria-expanded={isOpen}
        aria-controls="graph-legend-card"
        aria-label={isOpen ? "Collapse Graph Legend" : "Expand Graph Legend"}
        data-testid="btn-toggle-legend"
      >
        <span className="legend-toggle-text">Legend</span>
        <span className="legend-toggle-icon" aria-hidden="true">
          {isOpen ? "▾" : "▴"}
        </span>
      </button>

      {isOpen && (
        <aside
          id="graph-legend-card"
          className="graph-legend-card"
          role="region"
          aria-label="Graph Visual Legend"
          data-testid="graph-legend-card"
        >
          <div className="legend-header">
            <span className="legend-title">Graph Legend</span>
            <button
              type="button"
              className="legend-close-btn"
              onClick={handleToggle}
              aria-label="Close graph legend"
              data-testid="btn-close-legend"
            >
              ✕
            </button>
          </div>

          <div className="legend-section" data-testid="legend-section-entities">
            <div className="legend-section-title">Entity Nodes</div>
            <div className="legend-items-grid">
              {SUPPORTED_ENTITY_TYPES.map((item) => {
                const style = getEntityBadgeStyle(item.type);
                return (
                  <div
                    key={item.type}
                    className="legend-item-row"
                    data-testid={`legend-entity-${item.type}`}
                  >
                    <div className="legend-item-left">
                      <span
                        className="entity-type-badge"
                        style={{
                          backgroundColor: style.bg,
                          color: style.text,
                          borderColor: style.border,
                        }}
                      >
                        {item.label}
                      </span>
                    </div>
                    <span className="legend-item-desc" title={item.description}>
                      {item.description}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="legend-section" data-testid="legend-section-relationships">
            <div className="legend-section-title">Relationships</div>
            <div className="legend-items-grid">
              {SUPPORTED_RELATIONSHIP_TYPES.map((item) => {
                const style = getRelationshipEdgeStyle(item.type);
                return (
                  <div
                    key={item.type}
                    className="legend-item-row"
                    data-testid={`legend-rel-${item.type}`}
                  >
                    <div className="legend-item-left">
                      <div className="legend-edge-sample" aria-hidden="true">
                        <span
                          className="legend-edge-line"
                          style={{ backgroundColor: style.stroke }}
                        />
                        <span
                          className="legend-edge-arrow"
                          style={{ borderLeftColor: style.stroke }}
                        />
                      </div>
                      <code className="legend-edge-name" style={{ color: style.stroke }}>
                        {item.label}
                      </code>
                    </div>
                    <span className="legend-item-desc" title={item.description}>
                      {item.description}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}

