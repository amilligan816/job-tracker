import { Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { Link as RouterLink } from "react-router-dom";

import { api } from "../api/client";
import QueryState from "./QueryState";

/** Next 30 days of scheduled follow-ups, soonest first. */
export default function UpcomingActions() {
  const horizon = new Date();
  horizon.setDate(horizon.getDate() + 30);
  const dueBefore = horizon.toISOString().slice(0, 10);

  const { data, isLoading, error } = useQuery({
    queryKey: ["applications", "due", dueBefore],
    queryFn: () => api.applications.list({ due_before: dueBefore }),
  });

  const today = new Date().toISOString().slice(0, 10);

  return (
    <Card sx={{ height: "100%" }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Next actions
        </Typography>
        <QueryState
          isLoading={isLoading}
          error={error}
          isEmpty={!data?.length}
          emptyMessage="No follow-ups scheduled in the next 30 days."
        >
          <Stack divider={<span />} spacing={1}>
            {data?.slice(0, 8).map((app) => {
              const overdue = !!app.next_action_on && app.next_action_on <= today;
              return (
                <Stack
                  key={app.id}
                  component={RouterLink}
                  to={`/applications/${app.id}`}
                  direction="row"
                  justifyContent="space-between"
                  alignItems="center"
                  spacing={1}
                  sx={{
                    textDecoration: "none",
                    color: "inherit",
                    p: 1,
                    borderRadius: 1,
                    "&:hover": { bgcolor: "action.hover" },
                  }}
                >
                  <div>
                    <Typography variant="body2" fontWeight={600} noWrap>
                      {app.posting?.title ?? "Untitled role"}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {app.posting?.company?.name ?? "Unknown company"}
                      {app.next_action ? ` — ${app.next_action}` : ""}
                    </Typography>
                  </div>
                  <Chip
                    size="small"
                    label={app.next_action_on}
                    // Overdue carries an explicit colour AND the date text.
                    color={overdue ? "error" : "default"}
                    variant={overdue ? "filled" : "outlined"}
                  />
                </Stack>
              );
            })}
          </Stack>
        </QueryState>
      </CardContent>
    </Card>
  );
}
