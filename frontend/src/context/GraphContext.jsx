import { createContext, useContext, useMemo, useReducer } from "react";

const GraphContext = createContext(null);

function graphReducer(state, action) {
  switch (action.type) {
    case "SET_CYPHER":
      return {
        ...state,
        lastCypher: action.payload,
      };
    default:
      return state;
  }
}

// Provides shared graph-query state because chat results and graph highlighting should coordinate without prop drilling.
export function GraphProvider({ children }) {
  const [state, dispatch] = useReducer(graphReducer, {
    lastCypher: "",
  });

  // Stores the latest Cypher because the graph view uses it to highlight the entities referenced by the last answer.
  function handleQueryResult(cypher) {
    dispatch({
      type: "SET_CYPHER",
      payload: cypher,
    });
  }

  const value = useMemo(
    function buildContextValue() {
      return {
        lastCypher: state.lastCypher,
        handleQueryResult,
      };
    },
    [state.lastCypher],
  );

  return (
    <GraphContext.Provider value={value}>{children}</GraphContext.Provider>
  );
}

// Reads the graph context because shared Cypher state should be consumed through one dedicated hook.
export function useGraphContext() {
  const context = useContext(GraphContext);

  if (!context) {
    throw new Error("useGraphContext must be used within a GraphProvider.");
  }

  return context;
}
