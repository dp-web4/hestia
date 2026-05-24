import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { Vault } from "./pages/Vault";
import { Chain } from "./pages/Chain";
import { Policy } from "./pages/Policy";
import { Fleet } from "./pages/Fleet";
import { Settings } from "./pages/Settings";
import "./styles/global.css";

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <nav className="sidebar">
          <div className="sidebar-brand">
            <span className="flame">&#x1F525;</span>
            <span className="brand-text">Hestia</span>
          </div>
          <div className="nav-links">
            <NavLink to="/" end>Dashboard</NavLink>
            <NavLink to="/vault">Vault</NavLink>
            <NavLink to="/chain">Chain</NavLink>
            <NavLink to="/policy">Policy</NavLink>
            <NavLink to="/fleet">Fleet</NavLink>
            <NavLink to="/settings">Settings</NavLink>
          </div>
          <div className="sidebar-footer">
            <span className="version">v0.1.0</span>
          </div>
        </nav>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/vault" element={<Vault />} />
            <Route path="/chain" element={<Chain />} />
            <Route path="/policy" element={<Policy />} />
            <Route path="/fleet" element={<Fleet />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
