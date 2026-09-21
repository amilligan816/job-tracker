import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControlLabel,
  LinearProgress,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import ArticleIcon from "@mui/icons-material/Article";
import DescriptionIcon from "@mui/icons-material/Description";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";

import { api } from "../api/client";
import type { ExportFormat, ResumeBuildResult } from "../api/types";

/** Builds a resume for this application from the experience record. */
export default function ResumeBuilder({ applicationId }: { applicationId: string }) {
  const [tailor, setTailor] = useState(true);
  const [templateId, setTemplateId] = useState("");
  const [result, setResult] = useState<ResumeBuildResult | null>(null);
  const queryClient = useQueryClient();

  const profile = useQuery({ queryKey: ["experience"], queryFn: api.experience.get });
  const templates = useQuery({ queryKey: ["resume-templates"], queryFn: api.resumes.templates });
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: api.assistant.status });

  const assistantOff = status.data && !status.data.enabled;
  // Tailoring needs Claude; without it, fall back to a straight render rather
  // than sending a request that can only 503.
  const willTailor = tailor && !assistantOff;

  const build = useMutation({
    mutationFn: (format?: ExportFormat) =>
      api.resumes.build({
        application_id: applicationId,
        template_id: templateId || undefined,
        tailor: willTailor,
        export_format: format,
      }),
    onSuccess: async (data) => {
      setResult(data);
      if (data.document) {
        queryClient.invalidateQueries({ queryKey: ["application"] });
        const { url } = await api.documents.downloadUrl(data.document.id);
        window.open(url, "_blank", "noopener");
      }
    },
  });

  const recordEmpty = profile.data?.is_empty ?? false;

  return (
    <Card>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
          <ArticleIcon fontSize="small" color="action" />
          <Typography variant="h6">Resume</Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          Built from your experience record — there is no stored resume to keep in sync.
        </Typography>

        {recordEmpty ? (
          <Alert severity="info" sx={{ mt: 1 }}>
            Your{" "}
            <Box component={RouterLink} to="/experience" sx={{ color: "inherit" }}>
              experience record
            </Box>{" "}
            is empty. Import a resume or add a role first.
          </Alert>
        ) : (
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
              <TextField
                select
                size="small"
                label="Template"
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
                sx={{ minWidth: 180 }}
              >
                <MenuItem value="">Default</MenuItem>
                {(templates.data ?? []).map((template) => (
                  <MenuItem key={template.id} value={template.id}>
                    {template.name}
                  </MenuItem>
                ))}
              </TextField>

              <Tooltip
                title={
                  assistantOff
                    ? "Needs ANTHROPIC_API_KEY. Without it you still get a straight render of your record."
                    : "Claude picks and sharpens the highlights for this posting. Companies, titles and dates always come from your record."
                }
                arrow
              >
                <FormControlLabel
                  control={
                    <Switch
                      checked={willTailor}
                      disabled={assistantOff}
                      onChange={(e) => setTailor(e.target.checked)}
                    />
                  }
                  label="Tailor to this posting"
                />
              </Tooltip>
            </Stack>

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button
                size="small"
                variant="contained"
                disabled={build.isPending}
                onClick={() => build.mutate(undefined)}
              >
                Preview
              </Button>
              <Button
                size="small"
                variant="outlined"
                startIcon={<DescriptionIcon fontSize="small" />}
                disabled={build.isPending}
                onClick={() => build.mutate("docx")}
              >
                Word
              </Button>
              <Button
                size="small"
                variant="outlined"
                startIcon={<PictureAsPdfIcon fontSize="small" />}
                disabled={build.isPending}
                onClick={() => build.mutate("pdf")}
              >
                PDF
              </Button>
            </Stack>

            {build.isPending && <LinearProgress />}
            {build.error && <Alert severity="error">{(build.error as Error).message}</Alert>}

            {result && (
              <Box>
                <Stack direction="row" spacing={1} sx={{ mb: 1 }} alignItems="center">
                  <Chip
                    size="small"
                    label={result.tailored ? "Tailored" : "Straight from your record"}
                    color={result.tailored ? "primary" : "default"}
                  />
                  {result.document && (
                    <Typography variant="caption" color="text.secondary">
                      Saved as {result.document.filename}
                    </Typography>
                  )}
                </Stack>
                <Box
                  component="pre"
                  sx={{
                    p: 2,
                    m: 0,
                    bgcolor: "background.default",
                    borderRadius: 1,
                    fontSize: 12.5,
                    maxHeight: 360,
                    overflow: "auto",
                    whiteSpace: "pre-wrap",
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                  }}
                >
                  {result.preview}
                </Box>
              </Box>
            )}
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
