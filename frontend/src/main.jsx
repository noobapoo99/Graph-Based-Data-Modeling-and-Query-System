import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";

// Mounts the React application because Vite hands us a static root element that needs one client entry point.
function renderApp() {
  ReactDOM.createRoot(document.getElementById("root")).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

renderApp();
