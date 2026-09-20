import {
  Box,
  Button,
  Card,
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
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DownloadIcon from "@mui/icons-material/Download";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api } from "../api/client";
import type { DocumentKind } from "../api/types";
import QueryState from "../components/QueryState";

const KINDS: DocumentKind[] = ["resume", "cover_letter", "portfolio", "offer_letter", "other"];

const label = (kind: DocumentKind) => kind.replace("_", " ");

export default function DocumentsPage() {
  const [kind, setKind] = useState<DocumentKind>("resume");
  const fileInput = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["documents"],
    queryFn: () => api.documents.list(),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.documents.upload(file, kind),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.documents.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  const download = async (id: string) => {
    const { url } = await api.documents.downloadUrl(id);
    window.open(url, "_blank", "noopener");
  };

  return (
    <Stack spacing={3}>
      <div>
        <Typography variant="h4">Documents</Typography>
        <Typography color="text.secondary">
          Resumes, cover letters and anything else worth keeping. Stored in MinIO; PDFs and text
          files are also read so the assistant can use them.
        </Typography>
      </div>

      <Card>
        <Box sx={{ p: 2 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
            <TextField
              select
              size="small"
              label="Kind"
              value={kind}
              onChange={(e) => setKind(e.target.value as DocumentKind)}
              sx={{ minWidth: 180, textTransform: "capitalize" }}
            >
              {KINDS.map((k) => (
                <MenuItem key={k} value={k} sx={{ textTransform: "capitalize" }}>
                  {label(k)}
                </MenuItem>
              ))}
            </TextField>
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
        </Box>
      </Card>

      <QueryState
        isLoading={isLoading}
        error={error}
        isEmpty={!data?.length}
        emptyMessage="No documents uploaded yet."
      >
        <Card>
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>File</TableCell>
                  <TableCell>Kind</TableCell>
                  <TableCell align="right">Size</TableCell>
                  <TableCell>Uploaded</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data?.map((doc) => (
                  <TableRow key={doc.id} hover>
                    <TableCell sx={{ fontWeight: 600 }}>{doc.filename}</TableCell>
                    <TableCell>
                      <Chip size="small" label={label(doc.kind)} sx={{ textTransform: "capitalize" }} />
                    </TableCell>
                    <TableCell align="right">{(doc.size_bytes / 1024).toFixed(1)} KB</TableCell>
                    <TableCell>{new Date(doc.created_at).toLocaleDateString()}</TableCell>
                    <TableCell align="right">
                      <IconButton size="small" onClick={() => download(doc.id)} title="Download">
                        <DownloadIcon fontSize="small" />
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={() => remove.mutate(doc.id)}
                        title="Delete"
                        color="error"
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
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
