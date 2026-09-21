import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Grid2 as Grid,
  Stack,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import EventBusyIcon from "@mui/icons-material/EventBusy";
import ForumIcon from "@mui/icons-material/Forum";
import LocalOfferIcon from "@mui/icons-material/LocalOffer";
import MarkEmailUnreadIcon from "@mui/icons-material/MarkEmailUnread";
import WorkHistoryIcon from "@mui/icons-material/WorkHistory";
import { useQuery } from "@tanstack/react-query";
import { Link as RouterLink } from "react-router-dom";

import { api } from "../api/client";
import { ACTIVE_STATUSES } from "../api/types";
import PipelineBreakdown from "../components/PipelineBreakdown";
import QueryState from "../components/QueryState";
import StatTile from "../components/StatTile";
import UpcomingActions from "../components/UpcomingActions";

export default function DashboardPage() {
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.applications.summary });
  const assistant = useQuery({ queryKey: ["assistant-status"], queryFn: api.assistant.status });
  const mail = useQuery({ queryKey: ["mail-status"], queryFn: api.mail.status });

  const counts = summary.data?.by_status ?? {};
  const active = ACTIVE_STATUSES.reduce((sum, s) => sum + (counts[s] ?? 0), 0);
  const needsAction = summary.data?.needs_action ?? 0;
  const inboxUpdates = mail.data?.pending_suggestions ?? 0;

  return (
    <Stack spacing={3}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ sm: "center" }}
        spacing={2}
      >
        <Box>
          <Typography variant="h4">Dashboard</Typography>
          <Typography color="text.secondary">Where every application stands today.</Typography>
        </Box>
        <Button component={RouterLink} to="/capture" variant="contained" startIcon={<AddIcon />}>
          Capture a posting
        </Button>
      </Stack>

      {inboxUpdates > 0 && (
        <Alert
          severity="info"
          icon={<MarkEmailUnreadIcon fontSize="inherit" />}
          action={
            <Button component={RouterLink} to="/email" size="small" color="inherit">
              Review
            </Button>
          }
        >
          {inboxUpdates === 1
            ? "1 update from your inbox is waiting to be reviewed."
            : `${inboxUpdates} updates from your inbox are waiting to be reviewed.`}
        </Alert>
      )}

      {assistant.data && !assistant.data.enabled && (
        <Alert severity="info">
          Assistant features are off. Set <code>ANTHROPIC_API_KEY</code> in <code>.env</code> and
          restart the backend to enable match analysis, cover letters and interview prep.
        </Alert>
      )}

      <QueryState isLoading={summary.isLoading} error={summary.error}>
        <Grid container spacing={2}>
          <Grid size={{ xs: 6, md: 3 }}>
            <StatTile
              label="Active"
              value={active}
              caption="still in play"
              icon={<WorkHistoryIcon fontSize="small" color="action" />}
              to="/applications"
            />
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <StatTile
              label="Needs action"
              value={needsAction}
              caption="due today or overdue"
              icon={<EventBusyIcon fontSize="small" sx={{ color: needsAction ? "#d03b3b" : undefined }} />}
              accent={needsAction ? "#d03b3b" : undefined}
            />
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <StatTile
              label="Interviewing"
              value={counts.interviewing ?? 0}
              icon={<ForumIcon fontSize="small" color="action" />}
              to="/applications?status=interviewing"
            />
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <StatTile
              label="Offers"
              value={counts.offer ?? 0}
              icon={<LocalOfferIcon fontSize="small" color="action" />}
              to="/applications?status=offer"
            />
          </Grid>
        </Grid>

        <Grid container spacing={2} sx={{ mt: 0 }}>
          <Grid size={{ xs: 12, md: 7 }}>
            <Card sx={{ height: "100%" }}>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  Applications by stage
                </Typography>
                {summary.data && summary.data.total === 0 ? (
                  <Typography color="text.secondary" sx={{ py: 3 }}>
                    Nothing tracked yet. Capture a posting to get started.
                  </Typography>
                ) : (
                  summary.data && <PipelineBreakdown summary={summary.data} />
                )}
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 5 }}>
            <UpcomingActions />
          </Grid>
        </Grid>
      </QueryState>
    </Stack>
  );
}
