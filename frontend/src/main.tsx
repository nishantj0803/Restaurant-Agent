import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { IconContext } from "@phosphor-icons/react";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <IconContext.Provider value={{ size: 20, weight: "regular" }}>
      <App />
    </IconContext.Provider>
  </StrictMode>,
);
