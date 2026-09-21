import { AppBar, Box, Button, Container, Toolbar, Typography } from "@mui/material";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import { NavLink, useLocation } from "react-router-dom";

const LINKS = [
  { to: "/", label: "Dashboard" },
  { to: "/applications", label: "Applications" },
  { to: "/capture", label: "Capture" },
  { to: "/experience", label: "Experience" },
  { to: "/email", label: "Email" },
  { to: "/companies", label: "Companies" },
];

export default function NavBar() {
  const { pathname } = useLocation();

  return (
    <AppBar position="sticky" color="inherit" sx={{ borderBottom: "1px solid rgba(0,0,0,0.08)" }}>
      <Container maxWidth="lg" disableGutters>
        <Toolbar sx={{ gap: 1, flexWrap: "wrap" }}>
          <WorkOutlineIcon color="primary" />
          <Typography variant="h6" sx={{ mr: 2 }}>
            Job Tracker
          </Typography>
          <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap" }}>
            {LINKS.map((link) => {
              const active =
                link.to === "/" ? pathname === "/" : pathname.startsWith(link.to);
              return (
                <Button
                  key={link.to}
                  component={NavLink}
                  to={link.to}
                  size="small"
                  color={active ? "primary" : "inherit"}
                  sx={{ fontWeight: active ? 600 : 500 }}
                >
                  {link.label}
                </Button>
              );
            })}
          </Box>
        </Toolbar>
      </Container>
    </AppBar>
  );
}
