import { NavLink, Route, Routes } from "react-router-dom";
import AssetDetail from "./pages/AssetDetail";
import Connectors from "./pages/Connectors";
import Dashboard from "./pages/Dashboard";
import Inventory from "./pages/Inventory";
import Links from "./pages/Links";
import NetworkMap from "./pages/NetworkMap";
import { ConnectorsIcon, DashboardIcon, InventoryIcon, LinksIcon, MoonIcon, NetworkMapIcon, SunIcon } from "./icons";
import { ThemeProvider, useTheme } from "./theme";

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button className="theme-toggle" onClick={toggleTheme} title="Toggle light / dark theme">
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      {theme === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <div className="layout">
        <nav className="sidebar">
          <div className="brand">
            <img src="/favicon.svg" width={20} height={20} alt="" />
            netdoc
          </div>
          <NavLink to="/" end>
            <DashboardIcon /> Dashboard
          </NavLink>
          <NavLink to="/inventory">
            <InventoryIcon /> Inventory
          </NavLink>
          <NavLink to="/network-map">
            <NetworkMapIcon /> Network map
          </NavLink>
          <NavLink to="/links">
            <LinksIcon /> Link suggestions
          </NavLink>
          <NavLink to="/connectors">
            <ConnectorsIcon /> Connectors
          </NavLink>
          <div className="sidebar-spacer" />
          <ThemeToggle />
        </nav>
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/inventory" element={<Inventory />} />
            <Route path="/assets/:id" element={<AssetDetail />} />
            <Route path="/network-map" element={<NetworkMap />} />
            <Route path="/links" element={<Links />} />
            <Route path="/connectors" element={<Connectors />} />
          </Routes>
        </main>
      </div>
    </ThemeProvider>
  );
}
