import { NavLink, Route, Routes } from "react-router-dom";
import AssetDetail from "./pages/AssetDetail";
import Connectors from "./pages/Connectors";
import Dashboard from "./pages/Dashboard";
import Inventory from "./pages/Inventory";
import Links from "./pages/Links";
import NetworkMap from "./pages/NetworkMap";

export default function App() {
  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand">netdoc</div>
        <NavLink to="/" end>
          Dashboard
        </NavLink>
        <NavLink to="/inventory">Inventory</NavLink>
        <NavLink to="/network-map">Network map</NavLink>
        <NavLink to="/links">Link suggestions</NavLink>
        <NavLink to="/connectors">Connectors</NavLink>
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
  );
}
