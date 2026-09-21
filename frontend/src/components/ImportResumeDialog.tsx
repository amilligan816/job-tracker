import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  LinearProgress,
  Stack,
  Typography,
} from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api } from "../api/client";
import type { ImportedExperience } from "../api/types";

/**
 * Reads a resume into the experience record. The file itself is not kept — the
 * record is the artifact now — so this is a review-then-merge step, not an
 * upload.
 */
export default function ImportResumeDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [parsed, setParsed] = useState<ImportedExperience | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const read = useMutation({
    mutationFn: (file: File) => api.experience.importResume(file),
    onSuccess: setParsed,
  });

  const apply = useMutation({
    mutationFn: () => api.experience.applyImport(parsed!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["experience"] });
      queryClient.invalidateQueries({ queryKey: ["experience-text"] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      close();
    },
  });

  const close = () => {
    setParsed(null);
    read.reset();
    apply.reset();
    onClose();
  };

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="md">
      <DialogTitle>Import from a resume</DialogTitle>
      <DialogContent>
        {!parsed && (
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              Reads a PDF, Word (.docx), text or markdown resume into your experience record. The
              file is not stored — you review what it found before anything is saved.
            </Typography>
            <Button
              variant="contained"
              startIcon={<UploadFileIcon />}
              onClick={() => fileInput.current?.click()}
              disabled={read.isPending}
              sx={{ alignSelf: "flex-start" }}
            >
              {read.isPending ? "Reading…" : "Choose a file"}
            </Button>
            <input
              ref={fileInput}
              type="file"
              hidden
              accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) read.mutate(file);
                e.target.value = "";
              }}
            />
            {read.isPending && <LinearProgress />}
            {read.error && <Alert severity="error">{(read.error as Error).message}</Alert>}
          </Stack>
        )}

        {parsed && (
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="info">
              Review before saving. Roles are added to what you already have, and existing profile
              fields are left alone.
            </Alert>

            <div>
              <Typography variant="subtitle2">
                {parsed.full_name ?? "(no name found)"}
                {parsed.headline ? ` — ${parsed.headline}` : ""}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {[parsed.email, parsed.phone, parsed.location].filter(Boolean).join(" · ") || "—"}
              </Typography>
            </div>

            {parsed.skills.length > 0 && (
              <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                {parsed.skills.map((skill) => (
                  <Chip key={skill} size="small" label={skill} />
                ))}
              </Stack>
            )}

            <Divider />

            <Typography variant="subtitle2">
              {parsed.roles.length} role{parsed.roles.length === 1 ? "" : "s"}
            </Typography>
            <Stack spacing={1.5}>
              {parsed.roles.map((role, i) => (
                <div key={i}>
                  <Typography variant="body2" fontWeight={600}>
                    {role.title} — {role.company}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {role.start_date ?? "?"} – {role.end_date ?? "Present"}
                  </Typography>
                  <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                    {role.highlights.map((h, j) => (
                      <Typography component="li" variant="body2" key={j}>
                        {h.text}
                      </Typography>
                    ))}
                  </ul>
                </div>
              ))}
            </Stack>

            {apply.error && <Alert severity="error">{(apply.error as Error).message}</Alert>}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>Cancel</Button>
        {parsed && (
          <Button variant="contained" onClick={() => apply.mutate()} disabled={apply.isPending}>
            {apply.isPending ? "Saving…" : "Add to my record"}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
