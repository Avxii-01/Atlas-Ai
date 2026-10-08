import GraphCanvas from "@/components/graph/GraphCanvas";

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
          <span className="brand-badge">P0 Foundation</span>
        </div>
        <div className="status-section">
          <div className="status-pill">
            <span className="status-dot" />
            <span>Standalone Frontend</span>
          </div>
        </div>
      </header>

      {/* Main Graph Visualization View */}
      <main className="canvas-main">
        <div className="canvas-info-overlay">
          <div className="canvas-info-title">Repository Knowledge Graph Canvas</div>
          <div className="canvas-info-desc">React Flow Foundation • Interactive pan, zoom, and node canvas</div>
        </div>
        <GraphCanvas />
      </main>

      {/* Footer Status Shell */}
      <footer className="app-footer">
        <span>Atlas AI P0-04 • Frontend Foundation</span>
        <span>Independent Runtime Mode</span>
      </footer>
    </div>
  );
}
