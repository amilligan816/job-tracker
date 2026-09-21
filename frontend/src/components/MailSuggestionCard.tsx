import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Collapse,
  Divider,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import RuleIcon from "@mui/icons-material/Rule";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";

import { api } from "../api/client";
import type { ApplicationStatus, MailSuggestion } from "../api/types";
import { STATUS_META } from "../theme";
import StatusChip from "./StatusChip";

const ALL_STATUSES = Object.keys(STATUS_META) as ApplicationStatus[];

/** Confidence as words. A bare 0.62 tells a reader less than "fairly sure". */
function confidenceLabel(confidence: number): { text: string; color: "success" | "warning" | "default" } {
  if (confidence >= 0.75) return { text: "Confident", color: "success" };
  if (confidence >= 0.45) return { text: "Fairly sure", color: "warning" };
  return { text: "Unsure", color: "default" };
}

function formatDate(value: string | null): string {
  if (!value) return "";
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * One proposed update, with everything needed to judge it.
 *
 * The status is a dropdown rather than a label because the reviewer is the
 * authority: accepting is where a correction belongs, not a second round trip.
 */
export default function MailSuggestionCard({
  suggestion,
  showMailbox = false,
}: {
  suggestion: MailSuggestion;
  /** Set when several mailboxes are connected and "which inbox" is a real question. */
  showMailbox?: boolean;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState<ApplicationStatus | "">(suggestion.suggested_status ?? "");
  const pending = suggestion.state === "pending";

  // The list endpoint leaves bodies out; fetch this one only once it's opened.
  const detail = useQuery({
    queryKey: ["mail-suggestion", suggestion.id],
    queryFn: () => api.mail.suggestion(suggestion.id),
    enabled: expanded,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["mail-suggestions"] });
    queryClient.invalidateQueries({ queryKey: ["mail-status"] });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
    queryClient.invalidateQueries({ queryKey: ["summary"] });
  };

  const accept = useMutation({
    mutationFn: () => api.mail.accept(suggestion.id, status ? { status } : {}),
    onSuccess: invalidate,
  });
  const dismiss = useMutation({
    mutationFn: () => api.mail.dismiss(suggestion.id),
    onSuccess: invalidate,
  });

  const confidence = confidenceLabel(suggestion.confidence);
  const matchedOn = suggestion.signals?.matched_on ?? [];
  const body = detail.data?.message.body_text;

  return (
    <Card>
      <CardContent>
        <Stack spacing={1.5}>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            justifyContent="space-between"
            alignItems={{ sm: "flex-start" }}
            spacing={1}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }} noWrap>
                {suggestion.message.subject || "(no subject)"}
              </Typography>
              <Typography variant="body2" color="text.secondary" noWrap>
                {suggestion.message.from_name || suggestion.message.from_email || "Unknown sender"}
                {suggestion.message.received_at && ` · ${formatDate(suggestion.message.received_at)}`}
                {showMailbox && suggestion.account_email && ` · to ${suggestion.account_email}`}
              </Typography>
            </Box>
            <Stack direction="row" spacing={0.5} alignItems="center" flexShrink={0}>
              <Chip size="small" label={confidence.text} color={confidence.color} variant="outlined" />
              <Tooltip
                title={
                  suggestion.source === "claude"
                    ? "Claude read this one — the string matching was not sure"
                    : "Matched on sender, company and phrasing; no model call"
                }
              >
                {suggestion.source === "claude" ? (
                  <AutoAwesomeIcon fontSize="small" color="secondary" />
                ) : (
                  <RuleIcon fontSize="small" color="disabled" />
                )}
              </Tooltip>
            </Stack>
          </Stack>

          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            {suggestion.application_id ? (
              <Button
                component={RouterLink}
                to={`/applications/${suggestion.application_id}`}
                size="small"
                sx={{ p: 0, minWidth: 0 }}
              >
                {suggestion.posting_title ?? "this application"}
                {suggestion.company_name && ` · ${suggestion.company_name}`}
              </Button>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Not linked to an application
              </Typography>
            )}
            {suggestion.current_status && <StatusChip status={suggestion.current_status} />}
            {suggestion.suggested_status && (
              <>
                <Typography color="text.secondary">→</Typography>
                <StatusChip status={suggestion.suggested_status} />
              </>
            )}
          </Stack>

          {suggestion.reasoning && (
            <Typography variant="body2" color="text.secondary">
              {suggestion.reasoning}
            </Typography>
          )}

          {matchedOn.length > 0 && (
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
              {matchedOn.map((signal) => (
                <Chip key={signal} label={signal} size="small" variant="outlined" />
              ))}
            </Stack>
          )}

          {(accept.error || dismiss.error) && (
            <Alert severity="error">{((accept.error ?? dismiss.error) as Error).message}</Alert>
          )}

          <Divider />

          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Button
              size="small"
              onClick={() => setExpanded((open) => !open)}
              endIcon={
                <ExpandMoreIcon
                  fontSize="small"
                  sx={{ transform: expanded ? "rotate(180deg)" : "none", transition: "0.2s" }}
                />
              }
            >
              {expanded ? "Hide email" : "Read email"}
            </Button>
            <Box sx={{ flexGrow: 1 }} />

            {pending ? (
              <>
                <TextField
                  select
                  size="small"
                  label="Set status"
                  value={status}
                  onChange={(event) => setStatus(event.target.value as ApplicationStatus)}
                  sx={{ minWidth: 160 }}
                >
                  <MenuItem value="">
                    <em>No change</em>
                  </MenuItem>
                  {ALL_STATUSES.map((value) => (
                    <MenuItem key={value} value={value}>
                      {STATUS_META[value].label}
                    </MenuItem>
                  ))}
                </TextField>
                <Tooltip title="Dismiss">
                  <span>
                    <IconButton
                      size="small"
                      onClick={() => dismiss.mutate()}
                      disabled={dismiss.isPending}
                    >
                      <CloseIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<CheckIcon />}
                  onClick={() => accept.mutate()}
                  disabled={accept.isPending || !suggestion.application_id}
                >
                  {status ? "Apply" : "File it"}
                </Button>
              </>
            ) : (
              <Chip
                size="small"
                label={suggestion.state === "accepted" ? "Accepted" : "Dismissed"}
                color={suggestion.state === "accepted" ? "success" : "default"}
              />
            )}
          </Stack>

          <Collapse in={expanded} unmountOnExit>
            <Box
              sx={{
                mt: 1,
                p: 1.5,
                bgcolor: "background.default",
                borderRadius: 1,
                maxHeight: 320,
                overflow: "auto",
              }}
            >
              <Typography
                variant="body2"
                component="pre"
                sx={{ whiteSpace: "pre-wrap", fontFamily: "inherit", m: 0 }}
              >
                {detail.isLoading
                  ? "Loading…"
                  : body || suggestion.message.snippet || "No readable text in this message."}
              </Typography>
            </Box>
          </Collapse>
        </Stack>
      </CardContent>
    </Card>
  );
}
