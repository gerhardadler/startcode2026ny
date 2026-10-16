import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import PhoneFrame from "./components/PhoneFrame";
import { inPhone, showPhone } from "./frame";
import "./tokens.css";
import "./styles.css";

if (inPhone) document.documentElement.classList.add("in-phone");

createRoot(document.getElementById("root")!).render(<StrictMode>{showPhone ? <PhoneFrame /> : <App />}</StrictMode>);
