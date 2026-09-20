import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid2 as Grid,
  Link,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";

import { api } from "../api/client";
import { APPLICATION_STATUSES, type ApplicationStatus } from "../api/types";
import AssistantPanel from "../components/AssistantPanel";
import QueryState from "../components/QueryState";
import StatusChip from "../components/StatusChip";
import { STATUS_META } from "../theme";

export default function ApplicationDetailPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["application", id],
    queryFn: () => api.applications.get(id),
    enabled: !!id,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["application", id] });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
    queryClient.invalidateQueries({ queryKey: ["summary"] });
  };

  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.applications.update(id, body),
    onSuccess: invalidate,
  });

  const updatePosting = useMutation({
    mutationFn: ({ postingId, body }: { postingId: string; body: Record<string, unknown> }) =>
      api.postings.update(postingId, body),
    onSuccess: invalidate,
  });

  const addNote = useMutation({
    mutationFn: () => api.applications.addEvent(id, { kind: "note", summary: note }),
    onSuccess: () => {
      setNote("");
      invalidate();
    },
  });

  return (
    <Stack spacing={3}>
      <Button
        component={RouterLink}
        to="/applications"
        startIcon={<ArrowBackIcon />}
        sx={{ alignSelf: "flex-start" }}
      >
        All applications
      </Button>

      <QueryState isLoading={isLoading} error={error}>
        {data && (
          <Stack spacing={3}>
            <Box>
              <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography variant="h4">{data.posting?.title ?? "Untitled role"}</Typography>
                <StatusChip status={data.status} size="medium" />
              </Stack>
              <Typography color="text.secondary">
                {data.posting?.company?.name ?? "Unknown company"}
                {data.posting?.location ? ` · ${data.posting.location}` : ""}
                {data.posting?.remote_type && data.posting.remote_type !== "unknown"
                  ? ` · ${data.posting.remote_type}`
                  : ""}
              </Typography>
              {data.posting?.source_url && (
                <Link
                  href={data.posting.source_url}
                  target="_blank"
                  rel="noreferrer"
                  variant="body2"
                  sx={{ display: "inline-flex", alignItems: "center", gap: 0.5, mt: 0.5 }}
                >
                  Original posting <OpenInNewIcon sx={{ fontSize: 14 }} />
                </Link>
              )}
            </Box>

            <Grid container spacing={2}>
              <Grid size={{ xs: 12, md: 7 }}>
                <Stack spacing={2}>
                  <Card>
                    <CardContent>
                      <Typography variant="h6" gutterBottom>
                        Role
                      </Typography>
                      <Stack spacing={2}>
                        <TextField
                          size="small"
                          label="Title"
                          key={`title-${data.posting?.id}`}
                          defaultValue={data.posting?.title ?? ""}
                          onBlur={(e) => {
                            const value = e.target.value.trim();
                            if (data.posting && value && value !== data.posting.title) {
                              updatePosting.mutate({
                                postingId: data.posting.id,
                                body: { title: value },
                              });
                            }
                          }}
                        />
                        <TextField
                          size="small"
                          label="Location"
                          key={`location-${data.posting?.id}`}
                          defaultValue={data.posting?.location ?? ""}
                          onBlur={(e) => {
                            if (data.posting) {
                              updatePosting.mutate({
                                postingId: data.posting.id,
                                body: { location: e.target.value || null },
                              });
                            }
                          }}
                        />
                      </Stack>
                    </CardContent>
                  </Card>

                  <Card>
                    <CardContent>
                      <Typography variant="h6" gutterBottom>
                        Tracking
                      </Typography>
                      <Stack spacing={2}>
                        <TextField
                          select
                          size="small"
                          label="Stage"
                          value={data.status}
                          onChange={(e) =>
                            update.mutate({ status: e.target.value as ApplicationStatus })
                          }
                        >
                          {APPLICATION_STATUSES.map((s) => (
                            <MenuItem key={s} value={s}>
                              {STATUS_META[s].label}
                            </MenuItem>
                          ))}
                        </TextField>

                        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                          <TextField
                            size="small"
                            label="Next action"
                            defaultValue={data.next_action ?? ""}
                            onBlur={(e) => update.mutate({ next_action: e.target.value || null })}
                            fullWidth
                          />
                          <TextField
                            size="small"
                            type="date"
                            label="Due"
                            InputLabelProps={{ shrink: true }}
                            defaultValue={data.next_action_on ?? ""}
                            onBlur={(e) =>
                              update.mutate({ next_action_on: e.target.value || null })
                            }
                          />
                        </Stack>

                        <TextField
                          size="small"
                          label="Notes"
                          multiline
                          minRows={3}
                          defaultValue={data.notes ?? ""}
                          onBlur={(e) => update.mutate({ notes: e.target.value || null })}
                        />
                      </Stack>
                    </CardContent>
                  </Card>

                  {data.posting?.extracted && <PostingFacts extracted={data.posting.extracted} />}

                  <AssistantPanel applicationId={id} documents={data.documents} />
                </Stack>
              </Grid>

              <Grid size={{ xs: 12, md: 5 }}>
                <Stack spacing={2}>
                  <Card>
                    <CardContent>
                      <Typography variant="h6" gutterBottom>
                        Timeline
                      </Typography>
                      <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
                        <TextField
                          size="small"
                          placeholder="Add a note…"
                          value={note}
                          onChange={(e) => setNote(e.target.value)}
                          fullWidth
                        />
                        <Button
                          variant="contained"
                          disabled={!note.trim() || addNote.isPending}
                          onClick={() => addNote.mutate()}
                        >
                          Add
                        </Button>
                      </Stack>
                      <Stack spacing={1.5}>
                        {data.events.map((event) => (
                          <Box key={event.id}>
                            <Stack direction="row" spacing={1} alignItems="center">
                              <Chip size="small" variant="outlined" label={event.kind.replace("_", " ")} />
                              <Typography variant="caption" color="text.secondary">
                                {new Date(event.occurred_at).toLocaleString()}
                              </Typography>
                            </Stack>
                            <Typography variant="body2" sx={{ mt: 0.5 }}>
                              {event.summary}
                            </Typography>
                            {event.detail && (
                              <Typography variant="body2" color="text.secondary">
                                {event.detail}
                              </Typography>
                            )}
                          </Box>
                        ))}
                      </Stack>
                    </CardContent>
                  </Card>

                  <Card>
                    <CardContent>
                      <Typography variant="h6" gutterBottom>
                        Documents
                      </Typography>
                      {data.documents.length === 0 ? (
                        <Typography variant="body2" color="text.secondary">
                          None attached. Upload one from the Documents page.
                        </Typography>
                      ) : (
                        <Stack spacing={1}>
                          {data.documents.map((doc) => (
                            <Stack
                              key={doc.id}
                              direction="row"
                              justifyContent="space-between"
                              alignItems="center"
                            >
                              <Typography variant="body2">{doc.filename}</Typography>
                              <Button
                                size="small"
                                onClick={async () => {
                                  const { url } = await api.documents.downloadUrl(doc.id);
                                  window.open(url, "_blank", "noopener");
                                }}
                              >
                                Download
                              </Button>
                            </Stack>
                          ))}
                        </Stack>
                      )}
                    </CardContent>
                  </Card>
                </Stack>
              </Grid>
            </Grid>
          </Stack>
        )}
      </QueryState>
    </Stack>
  );
}

function PostingFacts({ extracted }: { extracted: Record<string, unknown> }) {
  const sections: [string, string][] = [
    ["requirements", "Requirements"],
    ["responsibilities", "Responsibilities"],
    ["nice_to_have", "Nice to have"],
    ["tech_stack", "Tech stack"],
    ["benefits", "Benefits"],
  ];

  const present = sections.filter(([key]) => (extracted[key] as string[] | undefined)?.length);
  if (!present.length) return null;

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          What the posting asks for
        </Typography>
        <Stack spacing={2} divider={<Divider flexItem />}>
          {present.map(([key, title]) => (
            <Box key={key}>
              <Typography variant="subtitle2" gutterBottom>
                {title}
              </Typography>
              {key === "tech_stack" ? (
                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                  {(extracted[key] as string[]).map((item) => (
                    <Chip key={item} size="small" label={item} />
                  ))}
                </Stack>
              ) : (
                <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                  {(extracted[key] as string[]).map((item, i) => (
                    <Typography component="li" variant="body2" key={i}>
                      {item}
                    </Typography>
                  ))}
                </Box>
              )}
            </Box>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}
