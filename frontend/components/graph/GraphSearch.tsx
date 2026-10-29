"use client";

import React, { useState, useRef, useEffect, useCallback, useMemo } from "react";
import type { Node } from "@xyflow/react";
import type { EntityNodeData } from "../../lib/graphMapper.ts";
import { searchGraphNodes, type GraphSearchResult } from "../../lib/graphSearch.ts";
import { getEntityBadgeStyle } from "../../lib/graphTokens.ts";

export interface GraphSearchProps {
  nodes: Node<EntityNodeData>[];
  onSelectNode: (nodeId: string) => void;
  placeholder?: string;
  className?: string;
}

/**
 * Accessible, keyboard-navigable in-memory search combobox for loaded graph nodes (Checkpoint 3).
 * Operates strictly on already-loaded nodes in the React Flow canvas.
 */
export default function GraphSearch({
  nodes,
  onSelectNode,
  placeholder = "Search loaded entities...",
  className = "",
}: GraphSearchProps) {
  const [query, setQuery] = useState<string>("");
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [highlightedIndex, setHighlightedIndex] = useState<number>(-1);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxRef = useRef<HTMLUListElement>(null);

  const cleanQuery = query.trim();
  const hasQuery = cleanQuery.length > 0;

  // Memoized search execution over loaded nodes only
  const results = useMemo<GraphSearchResult[]>(() => {
    if (!hasQuery) return [];
    return searchGraphNodes(nodes, cleanQuery, { limit: 15 });
  }, [nodes, cleanQuery, hasQuery]);

  // Derived effective highlight index without state-synchronizing effects
  const effectiveHighlightIndex =
    results.length > 0
      ? highlightedIndex >= 0 && highlightedIndex < results.length
        ? highlightedIndex
        : 0
      : -1;

  // Click outside listener to dismiss search dropdown
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as HTMLElement)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  // Scroll highlighted item into view if necessary
  useEffect(() => {
    if (isOpen && effectiveHighlightIndex >= 0 && listboxRef.current) {
      const activeElement = listboxRef.current.children[effectiveHighlightIndex] as HTMLElement;
      if (activeElement && activeElement.scrollIntoView) {
        activeElement.scrollIntoView({ block: "nearest" });
      }
    }
  }, [isOpen, effectiveHighlightIndex]);

  const handleSelectResult = useCallback(
    (item: GraphSearchResult) => {
      onSelectNode(item.id);
      setIsOpen(false);
      setHighlightedIndex(-1);
    },
    [onSelectNode]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!isOpen && (e.key === "ArrowDown" || e.key === "ArrowUp") && hasQuery) {
      setIsOpen(true);
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (results.length === 0) return;
      const current = effectiveHighlightIndex >= 0 ? effectiveHighlightIndex : -1;
      setHighlightedIndex((current + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (results.length === 0) return;
      const current = effectiveHighlightIndex >= 0 ? effectiveHighlightIndex : 0;
      setHighlightedIndex((current - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (isOpen && results.length > 0) {
        const targetIndex = effectiveHighlightIndex >= 0 ? effectiveHighlightIndex : 0;
        const targetItem = results[targetIndex];
        if (targetItem) {
          handleSelectResult(targetItem);
        }
      }
    } else if (e.key === "Escape") {
      if (isOpen) {
        setIsOpen(false);
      } else {
        setQuery("");
      }
    }
  };

  const handleClear = () => {
    setQuery("");
    setIsOpen(false);
    setHighlightedIndex(-1);
    inputRef.current?.focus();
  };

  return (
    <div
      ref={containerRef}
      className={`graph-search-container ${className}`.trim()}
      role="search"
      data-testid="graph-search-container"
    >
      <div className="graph-search-input-wrapper">
        <span className="search-icon" aria-hidden="true">
          🔍
        </span>

        <input
          ref={inputRef}
          type="text"
          className="graph-search-input"
          placeholder={placeholder}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => {
            if (hasQuery) setIsOpen(true);
          }}
          onKeyDown={handleKeyDown}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={isOpen && hasQuery}
          aria-controls="graph-search-listbox"
          aria-activedescendant={
            isOpen && effectiveHighlightIndex >= 0
              ? `graph-search-item-${effectiveHighlightIndex}`
              : undefined
          }
          aria-label="Search loaded graph entities"
          data-testid="input-graph-search"
        />

        {query && (
          <button
            type="button"
            className="btn-search-clear"
            onClick={handleClear}
            aria-label="Clear search input"
            data-testid="btn-clear-search"
          >
            ✕
          </button>
        )}
      </div>

      {isOpen && hasQuery && (
        <div className="graph-search-dropdown" data-testid="graph-search-dropdown">
          {results.length > 0 ? (
            <ul
              ref={listboxRef}
              id="graph-search-listbox"
              role="listbox"
              aria-label="Graph search results"
              className="graph-search-results-list"
            >
              {results.map((item, index) => {
                const badgeStyle = getEntityBadgeStyle(item.type);
                const isHighlighted = effectiveHighlightIndex === index;

                return (
                  <li
                    key={item.id}
                    id={`graph-search-item-${index}`}
                    role="option"
                    aria-selected={isHighlighted}
                    className={`graph-search-item ${isHighlighted ? "highlighted" : ""}`}
                    onClick={() => handleSelectResult(item)}
                    onMouseEnter={() => setHighlightedIndex(index)}
                    data-testid={`search-result-item-${index}`}
                  >
                    <div className="search-item-left">
                      <span
                        className="entity-type-badge-sm"
                        style={{
                          backgroundColor: badgeStyle.bg,
                          color: badgeStyle.text,
                          borderColor: badgeStyle.border,
                        }}
                      >
                        {item.type}
                      </span>
                      <span className="search-item-name" title={item.displayName}>
                        {item.displayName}
                      </span>
                    </div>

                    <div className="search-item-meta">
                      {item.filePath ? (
                        <span className="search-item-path" title={item.filePath}>
                          {item.filePath}
                        </span>
                      ) : (
                        <span className="search-item-id" title={item.id}>
                          {item.id}
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="graph-search-empty-state" data-testid="search-no-results">
              <div className="empty-state-title">No entities found</div>
              <div className="empty-state-desc">
                No loaded entity matched &quot;<strong>{cleanQuery}</strong>&quot;.
              </div>
              <div className="empty-state-hint">
                Local search is restricted to the {nodes.length} entities currently loaded in the graph.
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
