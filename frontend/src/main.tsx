import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ApolloProvider } from "@apollo/client";
import { apolloClient } from "./apollo";
import App from "./App";
import { LabAuthProvider } from "./lab/auth";
import "./styles.css";
import "./lab/lab.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ApolloProvider client={apolloClient}>
      <LabAuthProvider>
        <App />
      </LabAuthProvider>
    </ApolloProvider>
  </StrictMode>,
);
