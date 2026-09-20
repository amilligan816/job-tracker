import { createTheme } from "@mui/material/styles";
import type { ApplicationStatus } from "./api/types";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#2f5d8f" },
    secondary: { main: "#6d5f8a" },
    background: { default: "#f6f7f9", paper: "#ffffff" },
  },
  typography: {
    fontFamily: '"Inter", system-ui, -apple-system, "Segoe UI", sans-serif',
    h4: { fontWeight: 700, letterSpacing: "-0.02em" },
    h5: { fontWeight: 650, letterSpacing: "-0.01em" },
    h6: { fontWeight: 600 },
  },
  shape: { borderRadius: 10 },
  components: {
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { backgroundImage: "none" } } },
    MuiCard: {
      defaultProps: { elevation: 0 },
      styleOverrides: { root: { border: "1px solid rgba(0,0,0,0.08)" } },
    },
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { textTransform: "none" } } },
    MuiChip: { styleOverrides: { root: { fontWeight: 500 } } },
  },
});

type ChipColor = "default" | "primary" | "secondary" | "success" | "error" | "warning" | "info";

/** One place deciding what each pipeline stage looks like. */
export const STATUS_META: Record<ApplicationStatus, { label: string; color: ChipColor }> = {
  saved: { label: "Saved", color: "default" },
  applied: { label: "Applied", color: "info" },
  screening: { label: "Screening", color: "secondary" },
  interviewing: { label: "Interviewing", color: "primary" },
  offer: { label: "Offer", color: "success" },
  accepted: { label: "Accepted", color: "success" },
  rejected: { label: "Rejected", color: "error" },
  withdrawn: { label: "Withdrawn", color: "default" },
};
