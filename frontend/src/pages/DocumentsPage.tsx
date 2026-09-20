import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  IconButton,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DownloadIcon from "@mui/icons-material/Download";
import StarIcon from "@mui/icons-material/Star";
import StarBorderIcon from "@mui/icons-material/StarBorder";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link as RouterLink } from "react-router-dom";

import { api } from "../api/client";
import {
  DOCUMENT_KIND_LABELS,
  type Application,
  type DocumentKind,
  type StoredDocument,
} from "../api/types";
import QueryState from "../components/QueryState";

const UPLOAD_KINDS: DocumentKind[] = [
  "base_resume",
  "tailored_resume",
  "cover_letter",
  "portfolio",
  "offer_letter",
  "other",
];

export default function DocumentsPage() {
  const [kind, setKind] = useState<DocumentKind>("base_resume");
  const [applicationId, setApplicationId] = useState("");
  const [derivedFromId, setDerivedFromId] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const documents = useQuery({ queryKey: ["documents"], queryFn: () => api.documents.list() });
  const applications = useQuery({
    queryKey: ["applications", ""],
    queryFn: () => api.applications.list(),
  });

  const all = documents.data ?? [];
  const baseResumes = all.filter((d) => d.kind === "base_resume");
  const tailored = all.filter((d) => d.kind === "tailored_resume");
  const others = all.filter((d) => !d.kind.endsWith("resume"));
  const base = baseResumes.find((d) => d.is_base);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["documents"] });
    queryClient.invalidateQueries({ queryKey: ["application"] });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
  };

  const upload = useMutation({
    mutationFn: (file: File) =>
      api.documents.upload(file, kind, {
        applicationId: applicationId || undefined,
        derivedFromId: kind === "tailored_resume" ? derivedFromId || undefined : undefined,
      }),
    onSuccess: invalidate,
  });

  const setBase = useMutation({
    mutationFn: (id: string) => api.documents.setBase(id),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.documents.remove(id),
    onSuccess: invalidate,
  });

  const isTailored = kind === "tailored_resume";

  return (
    <Stack spacing={3}>
      <div>
        <Typography variant="h4">Documents</Typography>
        <Typography color="text.secondary">
          Keep one base resume as your master. Tailor it per application, and the match rating
          scores each application against its tailored resume when one exists.
        </Typography>
      </div>

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                select
                size="small"
                label="Kind"
                value={kind}
                onChange={(e) => setKind(e.target.value as DocumentKind)}
                sx={{ minWidth: 190 }}
              >
                {UPLOAD_KINDS.map((k) => (
                  <MenuItem key={k} value={k}>
                    {DOCUMENT_KIND_LABELS[k]}
                  </MenuItem>
                ))}
              </TextField>

              <TextField
                select
                size="small"
                label="Application"
                value={applicationId}
                onChange={(e) => setApplicationId(e.target.value)}
                sx={{ minWidth: 220 }}
                helperText={isTailored ? "Which application this is tailored for" : "Optional"}
              >
                <MenuItem value="">Not attached</MenuItem>
                {(applications.data ?? []).map((app: Application) => (
                  <MenuItem key={app.id} value={app.id}>
                    {app.posting?.title ?? "Untitled"} — {app.posting?.company?.name ?? "—"}
                  </MenuItem>
                ))}
              </TextField>

              {isTailored && (
                <TextField
                  select
                  size="small"
                  label="Tailored from"
                  value={derivedFromId}
                  onChange={(e) => setDerivedFromId(e.target.value)}
                  sx={{ minWidth: 200 }}
                  helperText="Which base resume it started from"
                >
                  <MenuItem value="">Not recorded</MenuItem>
                  {baseResumes.map((doc) => (
                    <MenuItem key={doc.id} value={doc.id}>
                      {doc.filename}
                      {doc.is_base ? " (base)" : ""}
                    </MenuItem>
                  ))}
                </TextField>
              )}
            </Stack>

            <Stack direction="row" spacing={2} alignItems="center">
              <Button
                variant="contained"
                startIcon={<UploadFileIcon />}
                onClick={() => fileInput.current?.click()}
                disabled={upload.isPending}
              >
                {upload.isPending ? "Uploading…" : "Upload"}
              </Button>
              <input
                ref={fileInput}
                type="file"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) upload.mutate(file);
                  e.target.value = "";
                }}
              />
              {upload.error && (
                <Typography color="error" variant="body2">
                  {(upload.error as Error).message}
                </Typography>
              )}
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <QueryState isLoading={documents.isLoading} error={documents.error}>
        <Stack spacing={3}>
          {baseResumes.length > 0 && !base && (
            <Alert severity="warning">
              No base resume is set. Pick one with the star so tailored resumes and match ratings
              have a master to work from.
            </Alert>
          )}

          <Section
            title="Base resumes"
            caption="Your master resumes. The starred one is what tailored resumes are written from."
            documents={baseResumes}
            empty="No base resume yet. Upload one to start rating matches."
            onSetBase={(id) => setBase.mutate(id)}
            onRemove={(id) => remove.mutate(id)}
          />

          <Section
            title="Tailored resumes"
            caption="Per-application versions. These take precedence when rating that application."
            documents={tailored}
            empty="No tailored resumes yet."
            applications={applications.data ?? []}
            baseResumes={baseResumes}
            onRemove={(id) => remove.mutate(id)}
          />

          <Section
            title="Other documents"
            caption="Cover letters, portfolios and anything else worth keeping."
            documents={others}
            empty="Nothing else stored."
            onRemove={(id) => remove.mutate(id)}
          />
        </Stack>
      </QueryState>
    </Stack>
  );
}

function Section({
  title,
  caption,
  documents,
  empty,
  applications = [],
  baseResumes = [],
  onSetBase,
  onRemove,
}: {
  title: string;
  caption: string;
  documents: StoredDocument[];
  empty: string;
  applications?: Application[];
  baseResumes?: StoredDocument[];
  onSetBase?: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const download = async (id: string) => {
    const { url } = await api.documents.downloadUrl(id);
    window.open(url, "_blank", "noopener");
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="h6">{title}</Typography>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          {caption}
        </Typography>

        {documents.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
            {empty}
          </Typography>
        ) : (
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {onSetBase && <TableCell padding="checkbox" />}
                  <TableCell>File</TableCell>
                  {applications.length > 0 && <TableCell>For</TableCell>}
                  {baseResumes.length > 0 && <TableCell>From</TableCell>}
                  <TableCell align="right">Size</TableCell>
                  <TableCell>Uploaded</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {documents.map((doc) => {
                  const app = applications.find((a) => a.id === doc.application_id);
                  const from = baseResumes.find((b) => b.id === doc.derived_from_id);
                  return (
                    <TableRow key={doc.id} hover>
                      {onSetBase && (
                        <TableCell padding="checkbox">
                          <Tooltip
                            title={doc.is_base ? "This is the base resume" : "Set as base resume"}
                            arrow
                          >
                            {/* Span so the tooltip still works on the disabled button. */}
                            <span>
                              <IconButton
                                size="small"
                                disabled={doc.is_base}
                                onClick={() => onSetBase(doc.id)}
                              >
                                {doc.is_base ? (
                                  <StarIcon fontSize="small" color="primary" />
                                ) : (
                                  <StarBorderIcon fontSize="small" />
                                )}
                              </IconButton>
                            </span>
                          </Tooltip>
                        </TableCell>
                      )}

                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography variant="body2" fontWeight={600}>
                            {doc.filename}
                          </Typography>
                          {doc.is_base && <Chip size="small" color="primary" label="Base" />}
                          {!doc.has_text && (
                            <Tooltip
                              title="No readable text — this file can't be used for match ratings or the assistant."
                              arrow
                            >
                              <Chip size="small" variant="outlined" label="No text" />
                            </Tooltip>
                          )}
                        </Stack>
                      </TableCell>

                      {applications.length > 0 && (
                        <TableCell>
                          {app ? (
                            <Typography
                              variant="body2"
                              component={RouterLink}
                              to={`/applications/${app.id}`}
                              sx={{ color: "primary.main", textDecoration: "none" }}
                            >
                              {app.posting?.title ?? "Untitled"}
                            </Typography>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                      )}

                      {baseResumes.length > 0 && (
                        <TableCell>
                          <Typography variant="body2" color="text.secondary">
                            {from?.filename ?? "—"}
                          </Typography>
                        </TableCell>
                      )}

                      <TableCell align="right">{(doc.size_bytes / 1024).toFixed(1)} KB</TableCell>
                      <TableCell>{new Date(doc.created_at).toLocaleDateString()}</TableCell>
                      <TableCell align="right">
                        <IconButton size="small" onClick={() => download(doc.id)} title="Download">
                          <DownloadIcon fontSize="small" />
                        </IconButton>
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => onRemove(doc.id)}
                          title="Delete"
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
