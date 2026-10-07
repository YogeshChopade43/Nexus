import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Keeps a crash in one page from blanking the whole app. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page crashed:', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="max-w-lg mx-auto mt-16 p-6 rounded-xl border border-nexus-danger/30 bg-nexus-bg-secondary text-center space-y-3">
        <h2 className="text-lg font-semibold text-nexus-text">Something went wrong on this page</h2>
        <p className="text-sm text-nexus-text-secondary break-words">{this.state.error.message}</p>
        <button
          onClick={() => this.setState({ error: null })}
          className="px-4 py-2 rounded-lg bg-nexus-accent text-nexus-bg text-sm font-medium"
        >
          Try again
        </button>
      </div>
    );
  }
}
