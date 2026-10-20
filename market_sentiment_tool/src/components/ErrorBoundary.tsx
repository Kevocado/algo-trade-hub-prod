import { Component, type ReactNode } from "react";

/** One broken panel must not blank the whole app: show what failed and keep the nav usable.
 *  `resetKey` (the route path) clears the error when the visitor navigates elsewhere. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { failed: Error | null }> {
  state = { failed: null as Error | null };

  static getDerivedStateFromError(failed: Error) {
    return { failed };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.failed && prev.resetKey !== this.props.resetKey) this.setState({ failed: null });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="m-8 rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
        <p className="font-semibold">This page failed to draw</p>
        <p className="mt-1 text-rose-300/80">{this.state.failed.message}</p>
      </div>
    );
  }
}
