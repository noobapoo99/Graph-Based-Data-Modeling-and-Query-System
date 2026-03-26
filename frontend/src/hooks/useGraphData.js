import { useEffect, useState } from "react";

import { graphRepository } from "../api/repository";

// Normalizes the backend graph payload because the current API returns Neo4j-shaped fields rather than the simplified frontend shape.
function normalizeGraphPayload(payload) {
  const nodes = Array.isArray(payload?.nodes)
    ? payload.nodes.map(function mapNode(node) {
        const label =
          Array.isArray(node?.labels) && node.labels.length > 0
            ? node.labels[0]
            : "Unknown";
        const properties =
          node?.properties && typeof node.properties === "object"
            ? node.properties
            : {};

        return {
          id: String(node?.id ?? ""),
          label,
          props: {
            id: String(node?.id ?? ""),
            ...properties,
          },
        };
      })
    : [];

  const links = Array.isArray(payload?.edges)
    ? payload.edges.map(function mapEdge(edge) {
        return {
          id: String(
            edge?.id ?? `${edge?.source}-${edge?.target}-${edge?.type}`,
          ),
          source: String(edge?.source ?? ""),
          target: String(edge?.target ?? ""),
          label: String(edge?.type ?? "RELATED_TO"),
        };
      })
    : [];

  return { nodes, links };
}

// Loads and reloads graph data because the graph panel should keep fetch state outside the presentation component.
export default function useGraphData() {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  async function reloadGraph() {
    setIsLoading(true);
    setErrorMessage("");

    try {
      const payload = await graphRepository.getGraph();
      setGraphData(normalizeGraphPayload(payload));
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Unable to load graph data.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(function loadGraphOnMount() {
    let isActive = true;

    // Fetches graph data once because the graph view is a read-mostly visualization surface for the current business dataset.
    async function loadGraph() {
      setIsLoading(true);
      setErrorMessage("");

      try {
        const payload = await graphRepository.getGraph();

        if (!isActive) {
          return;
        }

        setGraphData(normalizeGraphPayload(payload));
      } catch (error) {
        if (!isActive) {
          return;
        }

        setErrorMessage(
          error instanceof Error ? error.message : "Unable to load graph data.",
        );
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    loadGraph();

    return function cleanupLoadGraph() {
      isActive = false;
    };
  }, []);

  return {
    graphData,
    isLoading,
    errorMessage,
    reloadGraph,
  };
}
