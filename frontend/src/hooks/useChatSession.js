import { useState } from "react";
import { v4 as uuidv4 } from "uuid";

import { graphRepository } from "../api/repository";
import { useGraphContext } from "../context/GraphContext";

const SESSION_STORAGE_KEY = "graph-query-system-session-id";

// Returns one session ID per browser tab because the backend uses it to preserve follow-up context for that tab only.
function getOrCreateSessionId() {
  const existingSessionId = window.sessionStorage.getItem(SESSION_STORAGE_KEY);

  if (existingSessionId) {
    return existingSessionId;
  }

  const newSessionId = uuidv4();
  window.sessionStorage.setItem(SESSION_STORAGE_KEY, newSessionId);
  return newSessionId;
}

// Builds a stable message model because the chat list needs one shape for user, assistant, and system-visible content.
function createMessage({
  role,
  text,
  cypher = "",
  explanation = "",
  latencyMs = null,
}) {
  return {
    id: uuidv4(),
    role,
    text,
    cypher,
    explanation,
    latencyMs,
  };
}

// Creates a friendly error string because network failures should be recoverable without exposing raw exception objects to the user.
function getErrorText(error) {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "The request could not be completed.";
}

// Owns chat session state because request orchestration and message updates should stay outside the presentational panel.
export default function useChatSession() {
  const [sessionId] = useState(getOrCreateSessionId);
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [lastAttemptedQuery, setLastAttemptedQuery] = useState("");
  const { handleQueryResult } = useGraphContext();

  // Sends one query because both the main send action and the retry action should reuse identical request logic.
  async function submitQuery(queryText, shouldAppendUserMessage) {
    const normalizedQuery = queryText.trim();

    if (!normalizedQuery || isLoading) {
      return false;
    }

    setIsLoading(true);
    setErrorMessage("");
    setLastAttemptedQuery(normalizedQuery);

    if (shouldAppendUserMessage) {
      setMessages(function appendUserMessage(previousMessages) {
        return [
          ...previousMessages,
          createMessage({
            role: "user",
            text: normalizedQuery,
          }),
        ];
      });
    }

    try {
      const response = await graphRepository.query(normalizedQuery, sessionId);

      if (response.cypher) {
        handleQueryResult(response.cypher);
      }

      setMessages(function appendAssistantMessage(previousMessages) {
        return [
          ...previousMessages,
          createMessage({
            role: "assistant",
            text: response.answer,
            cypher: response.cypher || "",
            explanation: response.explanation || "",
            latencyMs: response.latency_ms ?? null,
          }),
        ];
      });

      return true;
    } catch (error) {
      setErrorMessage(getErrorText(error));
      return false;
    } finally {
      setIsLoading(false);
    }
  }

  return {
    sessionId,
    messages,
    isLoading,
    errorMessage,
    lastAttemptedQuery,
    submitQuery,
  };
}
