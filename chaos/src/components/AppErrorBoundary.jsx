import React from 'react';

export default class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('CD-SET UI error:', error, info);
  }

  reset = () => {
    this.setState({ error: null });
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, background: '#07090e', color: '#fff' }}>
        <div className="glass-card" style={{ maxWidth: 720, width: '100%', padding: 28, border: '1px solid rgba(239,68,68,.25)' }}>
          <div style={{ color: '#f87171', fontWeight: 800, fontSize: 18, marginBottom: 8 }}>CD-SET could not display this page</div>
          <p style={{ color: '#94a3b8', lineHeight: 1.6, marginTop: 0 }}>
            A browser-side error occurred. Your imported project and test records are stored by the backend and are not deleted by this screen.
          </p>
          <details style={{ color: '#64748b', marginBottom: 18 }}>
            <summary style={{ cursor: 'pointer', color: '#cbd5e1' }}>Technical details</summary>
            <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 11 }}>{String(this.state.error?.stack || this.state.error?.message || this.state.error)}</pre>
          </details>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn-primary" onClick={this.reset}>Reload CD-SET</button>
            <button className="btn-secondary" onClick={() => window.location.href = '/'}>Go to start</button>
          </div>
        </div>
      </div>
    );
  }
}
