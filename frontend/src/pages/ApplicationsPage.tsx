import {
  Box,
  Button,
  Card,
  Chip,
  Link,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { useQuery } from "@tanstack/react-query";
import { Link as RouterLink, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { APPLICATION_STATUSES, type ApplicationStatus } from "../api/types";
import QueryState from "../components/QueryState";
import { MatchScoreCell } from "../components/MatchScore";
import StatusChip from "../components/StatusChip";
import { STATUS_META } from "../theme";

export default function ApplicationsPage() {
  // The status filter lives in the URL so dashboard tiles can deep-link into it.
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const status = (params.get("status") as ApplicationStatus | null) ?? "";

  const { data, isLoading, error } = useQuery({
    queryKey: ["applications", status],
    queryFn: () =>
      api.applications.list({
        ...(status ? { status: [status as ApplicationStatus] } : {}),
        with_match: true,
      }),
  });

  return (
    <Stack spacing={3}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ sm: "center" }}
        spacing={2}
      >
        <Typography variant="h4">Applications</Typography>
        <Button component={RouterLink} to="/capture" variant="contained" startIcon={<AddIcon />}>
          Capture a posting
        </Button>
      </Stack>

      <TextField
        select
        size="small"
        label="Stage"
        value={status}
        onChange={(e) => {
          const next = e.target.value;
          setParams(next ? { status: next } : {});
        }}
        sx={{ maxWidth: 220 }}
      >
        <MenuItem value="">All stages</MenuItem>
        {APPLICATION_STATUSES.map((s) => (
          <MenuItem key={s} value={s}>
            {STATUS_META[s].label}
          </MenuItem>
        ))}
      </TextField>

      <QueryState
        isLoading={isLoading}
        error={error}
        isEmpty={!data?.length}
        emptyMessage="No applications match this filter."
      >
        <Card>
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Role</TableCell>
                  <TableCell>Company</TableCell>
                  <TableCell>Stage</TableCell>
                  <TableCell>Applied</TableCell>
                  <TableCell>Next action</TableCell>
                  <TableCell align="right">Match</TableCell>
                  <TableCell align="right">Interest</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data?.map((app) => (
                  <TableRow
                    key={app.id}
                    hover
                    onClick={() => navigate(`/applications/${app.id}`)}
                    sx={{ cursor: "pointer" }}
                  >
                    <TableCell sx={{ fontWeight: 600 }}>
                      <Link
                        component={RouterLink}
                        to={`/applications/${app.id}`}
                        underline="none"
                        color="inherit"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {app.posting?.title ?? "Untitled role"}
                      </Link>
                    </TableCell>
                    <TableCell>{app.posting?.company?.name ?? "—"}</TableCell>
                    <TableCell>
                      <StatusChip status={app.status} />
                    </TableCell>
                    <TableCell>{app.applied_on ?? "—"}</TableCell>
                    <TableCell>
                      {app.next_action ? (
                        <Stack direction="row" spacing={1} alignItems="center">
                          <span>{app.next_action}</span>
                          {app.next_action_on && (
                            <Chip size="small" variant="outlined" label={app.next_action_on} />
                          )}
                        </Stack>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <MatchScoreCell score={app.match_score} rating={app.match_rating} />
                    </TableCell>
                    <TableCell align="right">
                      {app.excitement ? "★".repeat(app.excitement) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        </Card>
      </QueryState>
    </Stack>
  );
}
