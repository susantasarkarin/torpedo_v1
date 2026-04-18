// v3 - force cache bust
const _b = 3;
import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "./App.jsx"
import { PanelAuthProvider } from "./panel/context/PanelAuthContext"
import "./styles/index.css"

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <PanelAuthProvider>
        <App />
      </PanelAuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
