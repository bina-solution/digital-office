import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

/**
 * ROUTE-LEVEL ERROR BOUNDARY. A render error inside one screen used to unmount the whole app to
 * a blank white page — no message, no navigation, no way back but a reload. This keeps the header
 * and the tab strip alive, says what broke in words, and offers the two honest exits: try the
 * screen again, or go somewhere that works.
 *
 * Keyed by the route (App.tsx passes `key={pathname}`), so navigating away resets it; a boundary
 * that stayed tripped on the next screen would blame that screen for the previous one's failure.
 * Rendered INSIDE the router, so the exit is a real route link under whichever basename the app
 * is mounted at (standalone or `/a/incoming/` in the console).
 */
export default class ErrorBoundary extends Component<
  { children: ReactNode; homeTo: string },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // the console is the only trail a blank screen used to leave; keep it, with the component stack
    console.error('INDOX screen crashed', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="callout bad" role="alert" style={{ marginTop: 18 }}>
        <b>המסך נכשל בהצגה.</b>{' '}
        <span style={{ wordBreak: 'break-word' }}>{error.message || String(error)}</span>
        <div className="muted small" style={{ marginTop: 8, color: 'var(--ink)' }}>
          הנתונים לא נפגעו — זו שגיאת תצוגה. אפשר לנסות שוב, או לעבור ללוח הבקרה.
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button className="btn sm" onClick={() => this.setState({ error: null })} title="מרנדר את המסך מחדש בלי לטעון את הדף">
            נסו שוב
          </button>
          <Link className="btn sm ghost" to={this.props.homeTo} title="מעבר ללוח הבקרה של המופע">
            ללוח הבקרה
          </Link>
        </div>
      </div>
    );
  }
}
