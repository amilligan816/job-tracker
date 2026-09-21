import {
  Alert,
  Button,
  Card,
  CardContent,
  Checkbox,
  FormControlLabel,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { JobPosting } from "../api/types";

export default function CapturePage() {
  const [tab, setTab] = useState<"url" | "text">("url");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [parse, setParse] = useState(true);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const capture = useMutation({
    mutationFn: () => api.postings.capture(tab === "url" ? { url, parse } : { text, parse }),
    onSuccess: async (posting: JobPosting) => {
      // Capturing a posting is only step one -- start tracking it immediately.
      const app = await api.applications.create({ posting_id: posting.id, status: "saved" });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["summary"] });
      navigate(`/applications/${app.id}`);
    },
  });

  const canSubmit = tab === "url" ? url.trim().length > 0 : text.trim().length > 50;

  return (
    <Stack spacing={3}>
      <div>
        <Typography variant="h4">Capture a posting</Typography>
        <Typography color="text.secondary">
          Paste a link or the description itself. The raw text is always stored, so you can
          re-parse it later.
        </Typography>
      </div>

      <Card>
        <CardContent>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
            <Tab label="From URL" value="url" />
            <Tab label="Paste description" value="text" />
          </Tabs>

          <Stack spacing={2}>
            {tab === "url" ? (
              <TextField
                label="Job posting URL"
                placeholder="https://..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                fullWidth
                helperText="Boards that render postings in the browser return no text — paste instead."
              />
            ) : (
              <TextField
                label="Job description"
                value={text}
                onChange={(e) => setText(e.target.value)}
                fullWidth
                multiline
                minRows={10}
                helperText="Paste the whole posting, including requirements."
              />
            )}

            <FormControlLabel
              control={<Checkbox checked={parse} onChange={(e) => setParse(e.target.checked)} />}
              label="Extract title, company, location and requirements with Claude"
            />

            {capture.error && <Alert severity="error">{(capture.error as Error).message}</Alert>}

            <Button
              variant="contained"
              size="large"
              disabled={!canSubmit || capture.isPending}
              onClick={() => capture.mutate()}
              sx={{ alignSelf: "flex-start" }}
            >
              {capture.isPending ? "Capturing…" : "Capture and track"}
            </Button>
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  );
}
