import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DescriptionIcon from "@mui/icons-material/Description";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import MarkdownText from "./MarkdownText";
import {
  DOCUMENT_KIND_LABELS,
  type AssistantRun,
  type ExportFormat,
  type MatchAnalysis,
  type StoredDocument,
} from "../api/types";

type Kind = "match_analysis" | "cover_letter" | "interview_prep";

export default function AssistantPanel({
  applicationId,
  documents,
}: {
  applicationId: string;
  documents: StoredDocument[];
}) {
  const [resumeId, setResumeId] = useState("");
  const [tone, setTone] = useState("professional and direct");
  const [roundType, setRoundType] = useState("recruiter screen");
  const queryClient = useQueryClient();

  const status = useQuery({ queryKey: ["assistant-status"], queryFn: api.assistant.status });
  const runs = useQuery({
    queryKey: ["assistant-runs", applicationId],
    queryFn: () => api.assistant.runs(applicationId),
  });

  // Tailored first: that is what would actually be sent for this application.
  const resumes = documents
    .filter((d) => d.kind === "tailored_resume" || d.kind === "base_resume")
    .sort((a, b) => Number(b.kind === "tailored_resume") - Number(a.kind === "tailored_resume"));

  const run = useMutation({
    mutationFn: (kind: Kind) => {
      const base = { application_id: applicationId, resume_document_id: resumeId || undefined };
      if (kind === "match_analysis") return api.assistant.matchAnalysis(base);
      if (kind === "cover_letter") return api.assistant.coverLetter({ ...base, tone });
      return api.assistant.interviewPrep({ ...base, round_type: roundType });
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["assistant-runs", applicationId] }),
  });

  // When the assistant is off, the generate controls go away but anything
  // already generated stays readable and exportable.
  const enabled = status.data?.enabled ?? true;

  if (!enabled) {
    return (
      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Assistant
          </Typography>
          <Alert severity="info" sx={{ mb: runs.data?.length ? 2 : 0 }}>
            Set <code>ANTHROPIC_API_KEY</code> in <code>.env</code> and restart the backend to
            enable match analysis, cover letters and interview prep.
          </Alert>
          <Stack spacing={2}>
            {runs.data?.map((item) => (
              <RunResult key={item.id} run={item} />
            ))}
          </Stack>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
          <AutoAwesomeIcon color="primary" fontSize="small" />
          <Typography variant="h6">Assistant</Typography>
          {status.data && <Chip size="small" variant="outlined" label={status.data.model} />}
        </Stack>

        <Stack spacing={2}>
          <TextField
            select
            size="small"
            label="Resume"
            value={resumeId}
            onChange={(e) => setResumeId(e.target.value)}
            helperText={
              resumes.length
                ? "Which resume to compare against."
                : "None attached — the tailored resume, else your base resume, is used."
            }
          >
            <MenuItem value="">Tailored, else base resume</MenuItem>
            {resumes.map((doc) => (
              <MenuItem key={doc.id} value={doc.id}>
                {doc.filename} — {DOCUMENT_KIND_LABELS[doc.kind]}
              </MenuItem>
            ))}
          </TextField>

          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <TextField
              size="small"
              label="Cover letter tone"
              value={tone}
              onChange={(e) => setTone(e.target.value)}
              fullWidth
            />
            <TextField
              size="small"
              label="Interview round"
              value={roundType}
              onChange={(e) => setRoundType(e.target.value)}
              fullWidth
            />
          </Stack>

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button variant="contained" size="small" onClick={() => run.mutate("match_analysis")}>
              Match analysis
            </Button>
            <Button variant="outlined" size="small" onClick={() => run.mutate("cover_letter")}>
              Cover letter
            </Button>
            <Button variant="outlined" size="small" onClick={() => run.mutate("interview_prep")}>
              Interview prep
            </Button>
          </Stack>

          {run.isPending && (
            <Box>
              <LinearProgress />
              <Typography variant="caption" color="text.secondary">
                Working… this can take a minute.
              </Typography>
            </Box>
          )}
          {run.error && <Alert severity="error">{(run.error as Error).message}</Alert>}

          {runs.data?.map((item) => (
            <RunResult key={item.id} run={item} />
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}

function RunResult({ run }: { run: AssistantRun }) {
  const queryClient = useQueryClient();
  const [exported, setExported] = useState<string | null>(null);

  const exportRun = useMutation({
    mutationFn: (format: ExportFormat) => api.assistant.exportRun(run.id, format),
    onSuccess: async (document) => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["application"] });
      setExported(document.filename);
      // Hand the file straight over rather than making them hunt for it.
      const { url } = await api.documents.downloadUrl(document.id);
      window.open(url, "_blank", "noopener");
    },
  });

  const title =
    run.kind === "match_analysis"
      ? "Match analysis"
      : run.kind === "cover_letter"
        ? "Cover letter"
        : "Interview prep";

  return (
    <Card variant="outlined" sx={{ bgcolor: "background.default" }}>
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="subtitle2">{title}</Typography>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="caption" color="text.secondary">
              {new Date(run.created_at).toLocaleString()}
            </Typography>
            {run.output_text && (
              <Button
                size="small"
                startIcon={<ContentCopyIcon fontSize="small" />}
                onClick={() => navigator.clipboard.writeText(run.output_text ?? "")}
              >
                Copy
              </Button>
            )}
            <Button
              size="small"
              startIcon={<DescriptionIcon fontSize="small" />}
              disabled={exportRun.isPending}
              onClick={() => exportRun.mutate("docx")}
            >
              Word
            </Button>
            <Button
              size="small"
              startIcon={<PictureAsPdfIcon fontSize="small" />}
              disabled={exportRun.isPending}
              onClick={() => exportRun.mutate("pdf")}
            >
              PDF
            </Button>
          </Stack>
        </Stack>

        {exportRun.error && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {(exportRun.error as Error).message}
          </Alert>
        )}
        {exported && (
          <Alert severity="success" sx={{ mb: 1 }} onClose={() => setExported(null)}>
            Saved <strong>{exported}</strong> to Documents.
          </Alert>
        )}

        {run.output_json ? (
          <MatchAnalysisView analysis={run.output_json} />
        ) : (
          <MarkdownText text={run.output_text ?? ""} />
        )}
      </CardContent>
    </Card>
  );
}

function MatchAnalysisView({ analysis }: { analysis: MatchAnalysis }) {
  // Fit is a single ratio against a limit, so it reads as a meter, not a chart.
  const fit = analysis.overall_fit;
  return (
    <Stack spacing={2}>
      <Box>
        <Stack direction="row" justifyContent="space-between" alignItems="baseline">
          <Typography variant="body2" color="text.secondary">
            Overall fit
          </Typography>
          <Typography sx={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
            {fit}
            <Typography component="span" variant="caption" color="text.secondary">
              /100
            </Typography>
          </Typography>
        </Stack>
        <LinearProgress
          variant="determinate"
          value={fit}
          sx={{ height: 10, borderRadius: 1, mt: 0.5 }}
        />
      </Box>

      <Typography variant="body2">{analysis.summary}</Typography>

      <Section title="Strengths" items={analysis.strengths} />

      {analysis.gaps.length > 0 && (
        <Box>
          <Typography variant="subtitle2" gutterBottom>
            Gaps
          </Typography>
          <Stack spacing={1}>
            {analysis.gaps.map((gap, i) => (
              <Box key={i}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip
                    size="small"
                    label={gap.severity}
                    color={
                      gap.severity === "blocking"
                        ? "error"
                        : gap.severity === "significant"
                          ? "warning"
                          : "default"
                    }
                  />
                  <Typography variant="body2" fontWeight={600}>
                    {gap.requirement}
                  </Typography>
                </Stack>
                {gap.evidence && (
                  <Typography variant="body2" color="text.secondary" sx={{ pl: 1 }}>
                    {gap.evidence}
                  </Typography>
                )}
              </Box>
            ))}
          </Stack>
        </Box>
      )}

      <Section title="Resume suggestions" items={analysis.resume_suggestions} />
      <Section title="Talking points" items={analysis.talking_points} />
    </Stack>
  );
}

function Section({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        {title}
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
        {items.map((item, i) => (
          <Typography component="li" variant="body2" key={i}>
            {item}
          </Typography>
        ))}
      </Box>
    </Box>
  );
}
