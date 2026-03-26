import { apiFetch, sendQuery } from "./client";

// Centralizes frontend API access because components and hooks should depend on one repository interface.
export const graphRepository = {
  getGraph: function getGraph() {
    return apiFetch("/api/graph");
  },

  getBrokenFlows: function getBrokenFlows() {
    return apiFetch("/api/broken-flows");
  },

  query: function query(text, sessionId) {
    return sendQuery(text, sessionId);
  },
};
