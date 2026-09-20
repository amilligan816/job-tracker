import { Box, Tooltip, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";

import {
  ACTIVE_STATUSES,
  type ActiveStatus,
  type ApplicationStatus,
  type PipelineSummary,
} from "../api/types";
import { STATUS_META } from "../theme";

/**
 * Ordinal ramp for the five active pipeline stages: one hue, light -> dark as a
 * candidate advances. Validated for monotone lightness, adjacent-step gaps and
 * light-end contrast against a white surface.
 */
const STAGE_RAMP: Record<ActiveStatus, string> = {
  saved: "#86b6ef",
  applied: "#5598e7",
  screening: "#2a78d6",
  interviewing: "#1c5cab",
  offer: "#104281",
};

const CLOSED_STATUSES: ApplicationStatus[] = ["accepted", "rejected", "withdrawn"];

export default function PipelineBreakdown({ summary }: { summary: PipelineSummary }) {
  const counts = summary.by_status;
  const activeCounts = ACTIVE_STATUSES.map((s) => counts[s] ?? 0);
  // Bars are scaled to the busiest stage, not the total, so small stages stay visible.
  const scaleMax = Math.max(...activeCounts, 1);

  return (
    <Box>
      {ACTIVE_STATUSES.map((status, i) => {
        const count = activeCounts[i];
        const meta = STATUS_META[status];
        return (
          <Box
            key={status}
            component={RouterLink}
            to={`/applications?status=${status}`}
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "96px 1fr 32px", sm: "120px 1fr 40px" },
              alignItems: "center",
              gap: 1.5,
              py: 0.75,
              textDecoration: "none",
              color: "inherit",
              borderRadius: 1,
              "&:hover": { bgcolor: "action.hover" },
            }}
          >
            <Typography variant="body2" color="text.secondary" noWrap>
              {meta.label}
            </Typography>

            <Tooltip
              title={`${count} ${count === 1 ? "application" : "applications"} at ${meta.label.toLowerCase()}`}
              placement="top"
              arrow
            >
              {/* Full-width track gives the hover a hit target wider than the bar. */}
              <Box sx={{ position: "relative", height: 18, display: "flex", alignItems: "center" }}>
                <Box
                  sx={{
                    height: 10,
                    width: `${Math.max((count / scaleMax) * 100, count > 0 ? 2 : 0)}%`,
                    minWidth: count > 0 ? 6 : 0,
                    bgcolor: STAGE_RAMP[status],
                    // Rounded data-end only; the baseline end stays square.
                    borderRadius: "0 4px 4px 0",
                    transition: "width 240ms ease",
                  }}
                />
              </Box>
            </Tooltip>

            <Typography
              variant="body2"
              sx={{ fontVariantNumeric: "tabular-nums", fontWeight: 600, textAlign: "right" }}
              color={count ? "text.primary" : "text.disabled"}
            >
              {count}
            </Typography>
          </Box>
        );
      })}

      <Box sx={{ mt: 2, pt: 1.5, borderTop: "1px solid", borderColor: "divider" }}>
        <Typography variant="caption" color="text.secondary">
          Closed:{" "}
          {CLOSED_STATUSES.map((s, i) => (
            <Box component="span" key={s}>
              {i > 0 && " · "}
              {STATUS_META[s].label} {counts[s] ?? 0}
            </Box>
          ))}
        </Typography>
      </Box>
    </Box>
  );
}
