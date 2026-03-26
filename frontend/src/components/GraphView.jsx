import { useEffect, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";

import { useGraphContext } from "../context/GraphContext";
import useGraphData from "../hooks/useGraphData";
import styles from "./GraphView.module.css";

const LABEL_COLORS = {
  Customer: "#7F77DD",
  Order: "#1D9E75",
  Invoice: "#D85A30",
  Payment: "#378ADD",
  Delivery: "#BA7517",
  Product: "#D4537E",
  JournalEntry: "#888780",
};

const HIGHLIGHT_COLOR = "#EF9F27";

// Extracts quoted literals because the graph should highlight the concrete entity values referenced by the last Cypher query.
function extractQuotedValues(cypher) {
  if (!cypher) {
    return [];
  }

  const matches = [...cypher.matchAll(/'([^']+)'/g)];
  return matches.map(function mapMatch(match) {
    return match[1];
  });
}

// Determines highlight state because exact entity matches are easier to trust than broad fuzzy matching in a graph UI.
function matchesQuotedValue(node, quotedValuesSet) {
  if (quotedValuesSet.size === 0) {
    return false;
  }

  if (quotedValuesSet.has(String(node.id))) {
    return true;
  }

  return Object.values(node.props || {}).some(
    function somePropertyValue(value) {
      return quotedValuesSet.has(String(value));
    },
  );
}

// Chooses the display color because the graph needs both schema-level coloring and last-query highlighting.
function getNodeColor(node, quotedValuesSet) {
  if (matchesQuotedValue(node, quotedValuesSet)) {
    return HIGHLIGHT_COLOR;
  }

  return LABEL_COLORS[node.label] || "#5E6472";
}

// Formats property values because the sidebar should stay readable even when a value is an object or array.
function formatPropertyValue(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }

  return String(value);
}

// Tracks the graph container size because ForceGraph2D needs explicit width and height to fill the panel cleanly.
function useContainerSize(containerRef) {
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(
    function observeContainerSize() {
      const element = containerRef.current;

      if (!element) {
        return undefined;
      }

      // Measures immediately so the graph paints on the first render after mount instead of waiting for a resize event.
      function updateSize() {
        setSize({
          width: element.clientWidth,
          height: element.clientHeight,
        });
      }

      updateSize();

      // Uses ResizeObserver because the panel can change size with layout changes, not just window resizes.
      const observer = new ResizeObserver(function handleResize() {
        updateSize();
      });

      observer.observe(element);

      return function cleanupResizeObserver() {
        observer.disconnect();
      };
    },
    [containerRef],
  );

  return size;
}

// Draws a graph node because canvas rendering gives us custom colors and clearer highlight treatment than the default circle renderer.
function drawNode(node, ctx, globalScale, highlightedValuesSet) {
  const fontSize = Math.max(11 / globalScale, 3.5);
  const radius = matchesQuotedValue(node, highlightedValuesSet) ? 9 : 6;
  const nodeColor = getNodeColor(node, highlightedValuesSet);

  ctx.beginPath();
  ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
  ctx.fillStyle = nodeColor;
  ctx.fill();

  // Draws a thin white ring because it helps colored nodes stand out against the textured panel background.
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "#F8F3EA";
  ctx.stroke();

  // Only draws labels when zoomed in enough because always-on labels make dense graphs unreadable.
  if (globalScale > 1.15) {
    ctx.font = `${fontSize}px "Avenir Next", "Helvetica Neue", sans-serif`;
    ctx.fillStyle = "#2F2A24";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(String(node.id), node.x, node.y + radius + 3);
  }
}

// Humanizes the node label because the sidebar header should read like domain language rather than raw graph metadata.
function buildNodeTitle(node) {
  const preferredName =
    node?.props?.name || node?.props?.id || node?.id || "Unknown";
  return `${node?.label || "Node"}: ${preferredName}`;
}

// Renders the graph panel because users need a visual map of the business entities alongside chat answers.
export default function GraphView() {
  const containerRef = useRef(null);
  const graphRef = useRef(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [highlightedValues, setHighlightedValues] = useState([]);
  const { lastCypher } = useGraphContext();
  const { graphData, isLoading, errorMessage, reloadGraph } = useGraphData();
  const { width, height } = useContainerSize(containerRef);

  useEffect(
    function syncHighlightedValues() {
      setHighlightedValues(extractQuotedValues(lastCypher));
    },
    [lastCypher],
  );

  useEffect(
    function zoomGraphToFit() {
      if (
        !graphRef.current ||
        graphData.nodes.length === 0 ||
        width === 0 ||
        height === 0
      ) {
        return;
      }

      // Waits a moment because the force layout needs a few ticks before a fit call produces a useful viewport.
      const timeoutId = window.setTimeout(function handleFit() {
        graphRef.current.zoomToFit(350, 60);
      }, 450);

      return function cleanupFitTimer() {
        window.clearTimeout(timeoutId);
      };
    },
    [graphData, width, height],
  );

  // Re-fetches the graph because the user may want to recover from a temporary API failure without reloading the page.
  async function handleReloadGraph() {
    await reloadGraph();
  }

  // Opens the sidebar because clicking a node should reveal the full business record behind that graph point.
  function handleNodeClick(node) {
    setSelectedNode(node);
  }

  // Closes the sidebar because the selected-node panel is transient inspection UI rather than a persistent layout column.
  function handleCloseSidebar() {
    setSelectedNode(null);
  }

  const highlightedValuesSet = new Set(highlightedValues);

  return (
    <section className={styles.panelShell}>
      <div className={styles.panelHeader}>
        <div>
          <div className={styles.eyebrow}>Business Graph</div>
          <h2 className={styles.panelTitle}>Live entity map</h2>
        </div>
        <div className={styles.legend}>
          {Object.entries(LABEL_COLORS).map(function renderLegendItem([
            label,
            color,
          ]) {
            return (
              <div key={label} className={styles.legendItem}>
                <span
                  className={styles.legendSwatch}
                  style={{ backgroundColor: color }}
                />
                <span>{label}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div ref={containerRef} className={styles.graphStage}>
        {width > 0 && height > 0 ? (
          <ForceGraph2D
            ref={graphRef}
            width={width}
            height={height}
            graphData={graphData}
            backgroundColor="rgba(0, 0, 0, 0)"
            linkColor={function linkColor() {
              return "rgba(71, 66, 56, 0.24)";
            }}
            linkDirectionalParticles={0}
            linkWidth={function linkWidth(link) {
              return selectedNode &&
                (link.source?.id === selectedNode.id ||
                  link.target?.id === selectedNode.id)
                ? 2.4
                : 1.2;
            }}
            nodeCanvasObject={function nodeCanvasObject(
              node,
              ctx,
              globalScale,
            ) {
              drawNode(node, ctx, globalScale, highlightedValuesSet);
            }}
            nodePointerAreaPaint={function paintNodePointerArea(
              node,
              color,
              ctx,
            ) {
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(node.x, node.y, 10, 0, 2 * Math.PI, false);
              ctx.fill();
            }}
            nodeLabel={function nodeLabel(node) {
              return buildNodeTitle(node);
            }}
            onNodeClick={handleNodeClick}
            cooldownTicks={120}
          />
        ) : null}

        {isLoading ? (
          <div className={styles.overlayCard}>
            <div className={styles.overlayTitle}>Loading graph...</div>
            <div className={styles.overlayText}>
              Fetching nodes and edges from the backend.
            </div>
          </div>
        ) : null}

        {!isLoading && errorMessage ? (
          <div className={styles.overlayCard}>
            <div className={styles.overlayTitle}>Graph unavailable</div>
            <div className={styles.overlayText}>{errorMessage}</div>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={handleReloadGraph}
            >
              Reload graph
            </button>
          </div>
        ) : null}

        {highlightedValues.length > 0 ? (
          <div className={styles.queryHint}>
            Highlighting values from the latest Cypher:{" "}
            {highlightedValues.join(", ")}
          </div>
        ) : null}

        {selectedNode ? (
          <aside className={styles.sidebar}>
            <div className={styles.sidebarHeader}>
              <div>
                <div className={styles.eyebrow}>Selected node</div>
                <div className={styles.sidebarTitle}>
                  {buildNodeTitle(selectedNode)}
                </div>
              </div>
              <button
                className={styles.closeButton}
                type="button"
                onClick={handleCloseSidebar}
                aria-label="Close node details"
              >
                ×
              </button>
            </div>

            <div className={styles.sidebarBody}>
              {Object.entries(selectedNode.props || {}).map(
                function renderProperty([key, value]) {
                  return (
                    <div key={key} className={styles.propertyRow}>
                      <div className={styles.propertyKey}>{key}</div>
                      <div className={styles.propertyValue}>
                        {formatPropertyValue(value)}
                      </div>
                    </div>
                  );
                },
              )}
            </div>
          </aside>
        ) : null}
      </div>
    </section>
  );
}
