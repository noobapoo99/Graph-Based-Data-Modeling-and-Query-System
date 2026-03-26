import { useEffect, useState } from "react";

import { apiFetch } from "../api/client";

// Converts a snake_case flow key into readable text because the badge and drawer should communicate in operator-friendly language.
function formatFlowName(flowName) {
  return flowName
    .split("_")
    .map(function capitalizeWord(word) {
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(" ");
}

// Formats a record field value because broken-flow details can contain mixed strings, numbers, and nulls.
function formatRecordValue(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }

  return String(value);
}

// Renders the broken-flow status badge because the header should surface incomplete business flows at a glance.
export default function BrokenFlowBadge({ isPanelOpen, onOpenPanel, onClosePanel }) {
  const [brokenFlowData, setBrokenFlowData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(function loadBrokenFlowsOnMount() {
    let isActive = true;

    async function loadBrokenFlows() {
      setIsLoading(true);
      setErrorMessage("");

      try {
        const payload = await apiFetch("/api/broken-flows");

        if (!isActive) {
          return;
        }

        setBrokenFlowData(payload);
      } catch (error) {
        if (!isActive) {
          return;
        }

        setErrorMessage(error instanceof Error ? error.message : "Unable to load broken flows.");
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    loadBrokenFlows();

    return function cleanupBrokenFlowRequest() {
      isActive = false;
    };
  }, []);

  function handleTogglePanel() {
    if (!brokenFlowData || brokenFlowData.broken_flow_count === 0) {
      return;
    }

    if (isPanelOpen) {
      onClosePanel();
      return;
    }

    onOpenPanel(brokenFlowData);
  }

  const brokenFlowCount = brokenFlowData?.broken_flow_count ?? 0;

  return (
    <div style={styles.badgeShell}>
      {isLoading ? <div style={styles.loadingText}>Checking flows...</div> : null}

      {!isLoading && errorMessage ? <div style={styles.errorText}>Broken flow status unavailable</div> : null}

      {!isLoading && !errorMessage && brokenFlowCount === 0 ? <div style={styles.completeText}>All flows complete</div> : null}

      {!isLoading && !errorMessage && brokenFlowCount > 0 ? (
        <button
          type="button"
          onClick={handleTogglePanel}
          style={{
            ...styles.warningButton,
            ...(isPanelOpen ? styles.warningButtonActive : null),
          }}
        >
          {isPanelOpen ? "Hide broken flows" : `${brokenFlowCount} broken flow(s) detected`}
        </button>
      ) : null}
    </div>
  );
}

// Renders the docked details panel because the workspace should reflow around it instead of being covered by an overlay.
export function BrokenFlowDrawer({ brokenFlowData, onClose }) {
  const brokenFlowCount = brokenFlowData?.broken_flow_count ?? 0;
  const detailEntries = Object.entries(brokenFlowData?.details || {});

  if (!brokenFlowData) {
    return null;
  }

  return (
    <aside style={styles.drawerCard} role="complementary" aria-label="Broken flow details">
      <div style={styles.drawerHeader}>
        <div>
          <div style={styles.eyebrow}>Broken Flow Details</div>
          <h3 style={styles.drawerTitle}>{brokenFlowCount} incomplete flow(s) found</h3>
          <div style={styles.drawerSubtitle}>Review affected records in a dedicated side panel.</div>
        </div>
        <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close broken flow details">
          ×
        </button>
      </div>

      <div style={styles.drawerBody}>
        {detailEntries.map(function renderFlowGroup([flowName, records]) {
          return (
            <section key={flowName} style={styles.flowSection}>
              <div style={styles.flowSectionHeader}>
                <div style={styles.flowName}>{formatFlowName(flowName)}</div>
                <div style={styles.flowCount}>{records.length}</div>
              </div>

              {records.length === 0 ? (
                <div style={styles.emptyGroupText}>No broken records in this category.</div>
              ) : (
                <div style={styles.recordList}>
                  {records.map(function renderRecord(record, index) {
                    return (
                      <div key={`${flowName}-${index}`} style={styles.recordCard}>
                        {Object.entries(record).map(function renderField([key, value]) {
                          return (
                            <div key={key} style={styles.recordField}>
                              <div style={styles.recordFieldKey}>{key}</div>
                              <div style={styles.recordFieldValue}>{formatRecordValue(value)}</div>
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </aside>
  );
}

const styles = {
  badgeShell: {
    position: "relative",
    zIndex: 2,
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    minWidth: 0,
    flexShrink: 0,
    maxWidth: "100%",
  },
  loadingText: {
    color: "#D9CFBF",
    fontSize: 13,
    fontWeight: 600,
    textAlign: "right",
  },
  errorText: {
    color: "#F2B7A3",
    fontSize: 13,
    fontWeight: 600,
    textAlign: "right",
  },
  completeText: {
    color: "#8AE5B4",
    fontSize: 13,
    fontWeight: 700,
    textAlign: "right",
  },
  warningButton: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    border: "1px solid rgba(239, 159, 39, 0.4)",
    borderRadius: 999,
    padding: "10px 14px",
    backgroundColor: "rgba(239, 159, 39, 0.14)",
    color: "#FFD08A",
    fontSize: 13,
    fontWeight: 800,
    lineHeight: 1.3,
    textAlign: "center",
    cursor: "pointer",
  },
  warningButtonActive: {
    backgroundColor: "rgba(239, 159, 39, 0.24)",
    boxShadow: "0 12px 28px rgba(239, 159, 39, 0.18)",
  },
  drawerCard: {
    minWidth: 0,
    minHeight: 0,
    height: "100%",
    display: "flex",
    flexDirection: "column",
    borderRadius: 28,
    overflow: "hidden",
    border: "1px solid rgba(88, 67, 44, 0.14)",
    background: "linear-gradient(180deg, #FFFBF5 0%, #F5EADA 100%)",
    boxShadow: "0 28px 80px rgba(45, 36, 24, 0.12)",
  },
  drawerHeader: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
    padding: "24px 22px 18px 22px",
    borderBottom: "1px solid rgba(58, 48, 37, 0.08)",
    background: "linear-gradient(180deg, rgba(255,255,255,0.94) 0%, rgba(255,255,255,0.8) 100%)",
  },
  eyebrow: {
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: "0.14em",
    textTransform: "uppercase",
    color: "#8A6B3D",
  },
  drawerTitle: {
    margin: "6px 0 0 0",
    fontSize: 22,
    lineHeight: 1.2,
    color: "#231C14",
    fontFamily: '"Avenir Next", "Helvetica Neue", sans-serif',
  },
  drawerSubtitle: {
    marginTop: 10,
    fontSize: 13,
    lineHeight: 1.55,
    color: "#6E5E4E",
  },
  closeButton: {
    border: "none",
    background: "rgba(77, 62, 43, 0.10)",
    color: "#4A3A2A",
    width: 40,
    height: 40,
    borderRadius: "50%",
    fontSize: 22,
    lineHeight: 1,
    cursor: "pointer",
    flexShrink: 0,
  },
  drawerBody: {
    overflowY: "auto",
    padding: "18px 22px 24px 22px",
    display: "flex",
    flexDirection: "column",
    gap: 18,
    backgroundColor: "#F9F1E5",
  },
  flowSection: {
    borderRadius: 22,
    border: "1px solid rgba(58, 48, 37, 0.09)",
    backgroundColor: "rgba(255, 255, 255, 0.62)",
    overflow: "hidden",
  },
  flowSectionHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    padding: "16px 18px",
    borderBottom: "1px solid rgba(58, 48, 37, 0.07)",
  },
  flowName: {
    fontSize: 16,
    fontWeight: 800,
    color: "#31261A",
  },
  flowCount: {
    minWidth: 34,
    padding: "6px 10px",
    borderRadius: 999,
    backgroundColor: "rgba(239, 159, 39, 0.16)",
    color: "#8B5700",
    fontSize: 12,
    fontWeight: 800,
    textAlign: "center",
  },
  emptyGroupText: {
    padding: 18,
    fontSize: 14,
    color: "#736453",
  },
  recordList: {
    display: "grid",
    gridTemplateColumns: "1fr",
    gap: 14,
    padding: 18,
  },
  recordCard: {
    borderRadius: 18,
    padding: 14,
    backgroundColor: "#FFF9F1",
    border: "1px solid rgba(67, 53, 37, 0.08)",
  },
  recordField: {
    padding: "8px 0",
    borderBottom: "1px solid rgba(67, 53, 37, 0.08)",
  },
  recordFieldKey: {
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    color: "#8A6B3D",
  },
  recordFieldValue: {
    marginTop: 5,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    fontSize: 13,
    lineHeight: 1.55,
    color: "#33291D",
  },
};
