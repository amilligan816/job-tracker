import { Box, Container } from "@mui/material";
import { Navigate, Route, Routes } from "react-router-dom";

import NavBar from "./components/NavBar";
import ApplicationDetailPage from "./pages/ApplicationDetailPage";
import ApplicationsPage from "./pages/ApplicationsPage";
import CapturePage from "./pages/CapturePage";
import CompaniesPage from "./pages/CompaniesPage";
import DashboardPage from "./pages/DashboardPage";
import ExperiencePage from "./pages/ExperiencePage";

export default function App() {
  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <NavBar />
      <Container maxWidth="lg" sx={{ py: { xs: 2, sm: 4 } }}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/applications" element={<ApplicationsPage />} />
          <Route path="/applications/:id" element={<ApplicationDetailPage />} />
          <Route path="/capture" element={<CapturePage />} />
          <Route path="/companies" element={<CompaniesPage />} />
          <Route path="/experience" element={<ExperiencePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Container>
    </Box>
  );
}
