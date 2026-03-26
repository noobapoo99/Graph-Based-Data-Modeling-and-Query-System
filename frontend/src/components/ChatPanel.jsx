import { useEffect, useRef, useState } from "react";

import useChatSession from "../hooks/useChatSession";
import styles from "./ChatPanel.module.css";

// Renders the conversational query panel because users need a text-first workflow alongside the graph visualization.
export default function ChatPanel() {
  const {
    sessionId,
    messages,
    isLoading,
    errorMessage,
    lastAttemptedQuery,
    submitQuery,
  } = useChatSession();
  const [draft, setDraft] = useState("");
  const [expandedMessageIds, setExpandedMessageIds] = useState({});
  const messagesEndRef = useRef(null);

  useEffect(
    function scrollToBottomOnNewMessages() {
      if (!messagesEndRef.current) {
        return;
      }

      // Scrolls smoothly because chat conversations should feel anchored at the latest answer without a jarring jump.
      messagesEndRef.current.scrollIntoView({
        behavior: "smooth",
        block: "end",
      });
    },
    [messages, isLoading],
  );

  // Updates the text input because controlled inputs keep the submit and retry flows predictable.
  function handleDraftChange(event) {
    setDraft(event.target.value);
  }

  // Toggles Cypher visibility because users sometimes want provenance details without overwhelming the default chat view.
  function handleToggleCypher(messageId) {
    setExpandedMessageIds(function updateExpandedState(previousState) {
      return {
        ...previousState,
        [messageId]: !previousState[messageId],
      };
    });
  }

  // Handles the Send action because user-submitted chat input should immediately flow into the backend query pipeline.
  async function handleSend() {
    const didSucceed = await submitQuery(draft, true);

    if (didSucceed) {
      setDraft("");
    }
  }

  // Retries the last failed request because transient API errors should be recoverable without retyping the same question.
  async function handleRetry() {
    if (!lastAttemptedQuery) {
      return;
    }

    await submitQuery(lastAttemptedQuery, false);
  }

  // Submits on Enter because the panel is designed as a fast single-line query box rather than a multi-line composer.
  async function handleInputKeyDown(event) {
    if (event.key !== "Enter") {
      return;
    }

    event.preventDefault();
    await handleSend();
  }

  return (
    <section className={styles.panelShell}>
      <div className={styles.panelHeader}>
        <div>
          <div className={styles.eyebrow}>Query Console</div>
          <h2 className={styles.panelTitle}>Ask the graph</h2>
        </div>
        <div className={styles.sessionPill}>Session {sessionId.slice(0, 8)}</div>
      </div>

      <div className={styles.messagesContainer}>
        {messages.length === 0 ? (
          <div className={styles.emptyState}>
            <div className={styles.emptyStateTitle}>
              Ask about orders, invoices, payments, deliveries, or customers.
            </div>
            <div className={styles.emptyStateText}>
              Every answer is generated from live Neo4j query results returned
              by the backend.
            </div>
          </div>
        ) : null}

        {messages.map(function renderMessage(message) {
          const isAssistant = message.role === "assistant";
          const isExpanded = !!expandedMessageIds[message.id];

          return (
            <div
              key={message.id}
              className={`${styles.messageRow} ${
                isAssistant ? styles.assistantRow : styles.userRow
              }`}
            >
              <div
                className={`${styles.messageBubble} ${
                  isAssistant ? styles.assistantBubble : styles.userBubble
                }`}
              >
                <div className={styles.messageText}>{message.text}</div>

                {isAssistant && message.cypher ? (
                  <div className={styles.detailsSection}>
                    <button
                      type="button"
                      onClick={function handleToggleClick() {
                        handleToggleCypher(message.id);
                      }}
                      className={styles.toggleButton}
                    >
                      {isExpanded ? "Hide query" : "Show query"}
                    </button>

                    {isExpanded ? (
                      <pre className={styles.cypherBlock}>{message.cypher}</pre>
                    ) : null}
                  </div>
                ) : null}

                {isAssistant && message.explanation ? (
                  <div className={styles.explanationText}>
                    {message.explanation}
                  </div>
                ) : null}

                {isAssistant && message.latencyMs !== null ? (
                  <div className={styles.metaText}>
                    Latency: {message.latencyMs} ms
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}

        {isLoading ? <div className={styles.loadingText}>Thinking...</div> : null}
        <div ref={messagesEndRef} />
      </div>

      {errorMessage ? (
        <div className={styles.errorBanner}>
          <div className={styles.errorText}>{errorMessage}</div>
          <button
            type="button"
            onClick={handleRetry}
            className={styles.retryButton}
          >
            Retry
          </button>
        </div>
      ) : null}

      <div className={styles.inputBar}>
        <input
          type="text"
          value={draft}
          onChange={handleDraftChange}
          onKeyDown={handleInputKeyDown}
          placeholder="Ask a question about the business graph..."
          className={styles.input}
          disabled={isLoading}
        />
        <button
          type="button"
          onClick={handleSend}
          className={styles.sendButton}
          disabled={isLoading || !draft.trim()}
        >
          Send
        </button>
      </div>
    </section>
  );
}
