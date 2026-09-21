import { Card, CardContent, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";
import { Link as RouterLink } from "react-router-dom";

/**
 * A headline number. Deliberately not a one-bar chart: a single current value
 * reads faster as a figure than as a plotted mark.
 */
export default function StatTile({
  label,
  value,
  caption,
  icon,
  accent,
  to,
}: {
  label: string;
  value: number | string;
  caption?: string;
  icon?: ReactNode;
  /** Status colour. Always paired with the icon + label, never colour alone. */
  accent?: string;
  to?: string;
}) {
  return (
    <Card
      {...(to ? { component: RouterLink, to } : {})}
      sx={{
        // An <a> is inline by default, which collapses the card box.
        display: "block",
        height: "100%",
        textDecoration: "none",
        ...(to ? { "&:hover": { borderColor: "primary.main" } } : {}),
      }}
    >
      <CardContent>
        <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.5 }}>
          {icon}
          <Typography variant="body2" color="text.secondary">
            {label}
          </Typography>
        </Stack>
        <Typography
          sx={{
            fontSize: 40,
            lineHeight: 1.1,
            fontWeight: 700,
            fontVariantNumeric: "tabular-nums",
            color: accent ?? "text.primary",
          }}
        >
          {value}
        </Typography>
        {caption && (
          <Typography variant="caption" color="text.secondary">
            {caption}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}
