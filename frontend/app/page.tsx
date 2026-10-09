import RepositoryAnalysisView from "@/components/analysis/RepositoryAnalysisView";

export default function Home() {
  return (
    <div className="app-container">
      {/* Header Application Shell */}
      <header className="app-header">
        <div className="brand-section">
          <div className="brand-logo">A</div>
          <div>
            <h1 className="brand-title">Atlas AI</h1>
          </div>
          <span className="brand-badge">Repository Analysis</span>
        </div>
        <div className="status-section">
          <div className="status-pill">
            <span className="status-dot" />
            <span>Frontend Ready</span>
          </div>
        </div>
      </header>

      {/* Main Analysis Workflow */}
      <RepositoryAnalysisView />

      {/* Footer Status Shell */}
      <footer className="app-footer">
        <span>Atlas AI P0-21 • Repository Analysis Workflow</span>
        <span>Connected API Mode</span>
      </footer>
    </div>
  );
}
