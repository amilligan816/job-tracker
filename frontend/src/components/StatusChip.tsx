import { Chip } from "@mui/material";

import type { ApplicationStatus } from "../api/types";
import { STATUS_META } from "../theme";

export default function StatusChip({
  status,
  size = "small",
}: {
  status: ApplicationStatus;
  size?: "small" | "medium";
}) {
  const meta = STATUS_META[status];
  return <Chip label={meta.label} color={meta.color} size={size} variant="filled" />;
}
