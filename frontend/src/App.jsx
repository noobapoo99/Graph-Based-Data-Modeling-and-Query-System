// import BrokenFlowBadge, { BrokenFlowDrawer } from "./components/BrokenFlowBadge";
import ChatPanel from "./components/ChatPanel";
import ErrorBoundary from "./components/ErrorBoundary";
import GraphView from "./components/GraphView";
import { GraphProvider } from "./context/GraphContext";
import useCompactLayout from "./hooks/useCompactLayout";
import styles from "./App.module.css";

// Renders the Stage 2 application shell because the frontend needs one shared place to coordinate graph and chat state.
export default function App() {
  const isCompactLayout = useCompactLayout();

  return (
    <GraphProvider>
      <div className={styles.appShell}>
        <div className={styles.backgroundOrbOne} />
        <div className={styles.backgroundOrbTwo} />

        <header className={styles.header}>
          <div>
            {/* <div className={styles.headerEyebrow}>Stage 2 Frontend</div> */}
            <h1 className={styles.headerTitle}>Graph Query System</h1>
          </div>
          {/* <BrokenFlowBadge
            isPanelOpen={isBrokenFlowPanelOpen}
            onOpenPanel={handleOpenBrokenFlowPanel}
            onClosePanel={handleCloseBrokenFlowPanel}
          /> */}
        </header>

        <main
          className={`${styles.mainGrid} ${
            isCompactLayout ? styles.mainGridCompact : styles.mainGridExpanded
          }`}
        >
          <ErrorBoundary>
            <GraphView />
          </ErrorBoundary>
          <ErrorBoundary>
            <ChatPanel />
          </ErrorBoundary>
        </main>
      </div>
    </GraphProvider>
  );
}
