import {
  Button,
  Card,
  CardContent,
  Chip,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DownloadIcon from "@mui/icons-material/Download";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api } from "../api/client";
import { DOCUMENT_KIND_LABELS, type DocumentKind, type StoredDocument } from "../api/types";

const KINDS: DocumentKind[] = [
  "resume",
  "cover_letter",
  "interview_prep",
  "offer_letter",
  "portfolio",
  "other",
];

/** Files belonging to one application — generated exports and anything attached. */
export default function ApplicationFiles({
  applicationId,
  documents,
}: {
  applicationId: string;
  documents: StoredDocument[];
}) {
  const [kind, setKind] = useState<DocumentKind>("other");
  const fileInput = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["application"] });

  const upload = useMutation({
    mutationFn: (file: File) => api.documents.upload(file, kind, applicationId),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.documents.remove(id),
    onSuccess: invalidate,
  });

  const download = async (id: string) => {
    const { url } = await api.documents.downloadUrl(id);
    window.open(url, "_blank", "noopener");
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Files
        </Typography>

        {documents.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Nothing yet. Exports from the assistant land here automatically.
          </Typography>
        ) : (
          <Stack spacing={1}>
            {documents.map((doc) => (
              <Stack key={doc.id} direction="row" spacing={1} alignItems="center">
                <Chip size="small" label={DOCUMENT_KIND_LABELS[doc.kind]} variant="outlined" />
                <Typography variant="body2" sx={{ flex: 1, wordBreak: "break-word" }}>
                  {doc.filename}
                </Typography>
                <IconButton size="small" onClick={() => download(doc.id)} title="Download">
                  <DownloadIcon fontSize="small" />
                </IconButton>
                <IconButton
                  size="small"
                  color="error"
                  onClick={() => remove.mutate(doc.id)}
                  title="Delete"
                >
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
            ))}
          </Stack>
        )}

        <Stack direction="row" spacing={1} sx={{ mt: 2 }} alignItems="center">
          <TextField
            select
            size="small"
            label="Kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as DocumentKind)}
            sx={{ minWidth: 150 }}
          >
            {KINDS.map((k) => (
              <MenuItem key={k} value={k}>
                {DOCUMENT_KIND_LABELS[k]}
              </MenuItem>
            ))}
          </TextField>
          <Button
            size="small"
            startIcon={<UploadFileIcon />}
            onClick={() => fileInput.current?.click()}
            disabled={upload.isPending}
          >
            {upload.isPending ? "Uploading…" : "Attach"}
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
        </Stack>
      </CardContent>
    </Card>
  );
}
