"use client";

import React, { useState } from "react";
import RepositoryAnalysisView from "@/components/analysis/RepositoryAnalysisView";
import RepositoryGraphView from "@/components/graph/RepositoryGraphView";

type ActiveTab = "analysis" | "graph";

export default function Home() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("analysis");
  const [currentRepositoryId, setCurrentRepositoryId] = useState<string>("");

  const handleViewGraph = (repositoryId: string) => {
    setCurrentRepositoryId(repositoryId);
    setActiveTab("graph");
  };

  const handleBackToAnalysis = () => {
    setActiveTab("analysis");
  };

  return (
    <div className="app-container">
      {/* Header Application Shell */}
      <header className="app-header">
        <div className="brand-section">
          <div className="brand-logo">A</div>
          <div>
            <h1 className="brand-title">Atlas AI</h1>
          </div>
          <span className="brand-badge">P0 Code Intelligence</span>
        </div>

        {/* View Mode Navigation Tabs */}
        <div className="app-nav-tabs" role="tablist" aria-label="Application Views">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "analysis"}
            className={`nav-tab-btn ${activeTab === "analysis" ? "nav-tab-active" : ""}`}
            onClick={() => setActiveTab("analysis")}
            data-testid="tab-nav-analysis"
          >
            Repository Analysis
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "graph"}
            className={`nav-tab-btn ${activeTab === "graph" ? "nav-tab-active" : ""}`}
            onClick={() => setActiveTab("graph")}
            data-testid="tab-nav-graph"
          >
            Graph Visualization
            {currentRepositoryId && (
              <span className="nav-repo-badge">{currentRepositoryId}</span>
            )}
          </button>
        </div>

        <div className="status-section">
          <div className="status-pill">
            <span className="status-dot" />
            <span>Frontend Ready</span>
          </div>
        </div>
      </header>

      {/* Main Workflow View Area */}
      <main className="app-main-viewport">
        {activeTab === "analysis" ? (
          <RepositoryAnalysisView onViewGraph={handleViewGraph} />
        ) : (
          <RepositoryGraphView
            initialRepositoryId={currentRepositoryId}
            onBackToAnalysis={handleBackToAnalysis}
          />
        )}
      </main>

      {/* Footer Status Shell */}
      <footer className="app-footer">
        <span>Atlas AI P0-22 • Repository Graph Visualization</span>
        <span>
          {activeTab === "analysis"
            ? "Analysis Workflow Mode"
            : `Graph Visualizer Mode${currentRepositoryId ? ` • ${currentRepositoryId}` : ""}`}
        </span>
      </footer>
    </div>
  );
}
