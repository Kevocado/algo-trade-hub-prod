import React, { Component, ErrorInfo, ReactNode } from "react";
import { AlertCircle } from "lucide-react";

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false
  };

  public static getDerivedStateFromError(_: Error): State {
    return { hasError: true };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="p-4 m-2 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center text-red-500 text-sm">
          <AlertCircle className="w-4 h-4 mr-2" />
          Data format error: Unable to parse the expected statistical payload.
        </div>
      );
    }
    return this.props.children;
  }
}
