import React from "react";

// Catches render failures because each major panel should fail independently with a calm fallback UI.
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
    };
  }

  static getDerivedStateFromError() {
    return {
      hasError: true,
    };
  }

  componentDidCatch(error, errorInfo) {
    console.error("Panel render failed.", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <section style={fallbackStyles.panelShell}>
          <div style={fallbackStyles.content}>
            <div style={fallbackStyles.eyebrow}>Something went wrong</div>
            <h2 style={fallbackStyles.title}>This panel could not be rendered</h2>
            <div style={fallbackStyles.text}>
              Refresh the page to try again. The rest of the workspace is still
              available.
            </div>
          </div>
        </section>
      );
    }

    return this.props.children;
  }
}

const fallbackStyles = {
  panelShell: {
    display: "flex",
    flexDirection: "column",
    minHeight: 0,
    height: "100%",
    borderRadius: 28,
    border: "1px solid rgba(53, 45, 34, 0.12)",
    background: "#FFF8EF",
    boxShadow: "0 28px 80px rgba(45, 36, 24, 0.12)",
    overflow: "hidden",
    position: "relative",
    zIndex: 0,
  },
  content: {
    margin: "auto",
    maxWidth: 420,
    padding: 28,
    textAlign: "center",
  },
  eyebrow: {
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: "0.14em",
    textTransform: "uppercase",
    color: "#8A6B3D",
  },
  title: {
    margin: "10px 0 0 0",
    fontSize: 24,
    lineHeight: 1.15,
    color: "#231C14",
    fontFamily: '"Avenir Next", "Helvetica Neue", sans-serif',
  },
  text: {
    marginTop: 12,
    fontSize: 14,
    lineHeight: 1.6,
    color: "#5A4B3C",
  },
};
