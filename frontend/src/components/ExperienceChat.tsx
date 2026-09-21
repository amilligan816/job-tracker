import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { ExperienceProfile, ProposedStory } from "../api/types";
import QueryState from "./QueryState";

/**
 * An interview that draws out detail a resume has no room for. Stories it
 * proposes are never saved silently — they land here for the user to accept.
 */
export default function ExperienceChat({ profile }: { profile: ExperienceProfile }) {
  const [draft, setDraft] = useState("");
  const [proposed, setProposed] = useState<ProposedStory[]>([]);
  const bottom = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const status = useQuery({ queryKey: ["assistant-status"], queryFn: api.assistant.status });
  const messages = useQuery({ queryKey: ["experience-chat"], queryFn: api.experience.chat });

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data?.length, proposed.length]);

  const send = useMutation({
    mutationFn: (text: string) => api.experience.sendChat(text),
    onSuccess: (turn) => {
      setProposed((current) => [...current, ...turn.proposed_stories]);
      queryClient.invalidateQueries({ queryKey: ["experience-chat"] });
    },
  });

  const accept = useMutation({
    mutationFn: (story: ProposedStory) =>
      api.experience.createStory({ ...story, source: "chat" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["experience"] });
      queryClient.invalidateQueries({ queryKey: ["experience-text"] });
    },
  });

  const clear = useMutation({
    mutationFn: () => api.experience.clearChat(),
    onSuccess: () => {
      setProposed([]);
      queryClient.invalidateQueries({ queryKey: ["experience-chat"] });
    },
  });

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    send.mutate(text);
  };

  if (status.data && !status.data.enabled) {
    return (
      <Alert severity="info">
        The interview needs Claude. Set <code>ANTHROPIC_API_KEY</code> in <code>.env</code> and
        restart the backend. You can still edit your record by hand on the Record tab.
      </Alert>
    );
  }

  return (
    <Stack spacing={2}>
      <Card>
        <CardContent>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <div>
              <Typography variant="h6">Deepen your experience</Typography>
              <Typography variant="body2" color="text.secondary">
                Talk through what you actually did. Anything worth keeping gets proposed as a
                story, and nothing is saved until you accept it.
              </Typography>
            </div>
            {(messages.data?.length ?? 0) > 0 && (
              <Button size="small" onClick={() => clear.mutate()}>
                Start over
              </Button>
            )}
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <QueryState isLoading={messages.isLoading} error={messages.error}>
            <Stack spacing={1.5} sx={{ maxHeight: 420, overflowY: "auto", pr: 1 }}>
              {(messages.data?.length ?? 0) === 0 && (
                <Typography variant="body2" color="text.secondary">
                  {profile.is_empty
                    ? "Import a resume first, or just start talking about a project you are proud of."
                    : "Ask me about a role and I'll dig into it — or tell me what you want to talk through."}
                </Typography>
              )}

              {messages.data?.map((message) => (
                <Box
                  key={message.id}
                  sx={{
                    alignSelf: message.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: "85%",
                    bgcolor: message.role === "user" ? "primary.main" : "background.default",
                    color: message.role === "user" ? "primary.contrastText" : "text.primary",
                    px: 1.5,
                    py: 1,
                    borderRadius: 2,
                  }}
                >
                  <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                    {message.content}
                  </Typography>
                </Box>
              ))}
              <div ref={bottom} />
            </Stack>
          </QueryState>

          {send.isPending && <LinearProgress sx={{ mt: 1 }} />}
          {send.error && (
            <Alert severity="error" sx={{ mt: 1 }}>
              {(send.error as Error).message}
            </Alert>
          )}

          <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
            <TextField
              fullWidth
              size="small"
              multiline
              maxRows={4}
              placeholder="Tell me about something you built…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // Enter sends; Shift+Enter is a newline.
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <Button variant="contained" disabled={!draft.trim() || send.isPending} onClick={submit}>
              Send
            </Button>
          </Stack>
        </CardContent>
      </Card>

      {proposed.length > 0 && (
        <Card>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Stories to keep
            </Typography>
            <Stack spacing={2}>
              {proposed.map((story, i) => (
                <Box key={i} sx={{ p: 2, bgcolor: "background.default", borderRadius: 1 }}>
                  <Typography variant="subtitle2">{story.title}</Typography>
                  <Stack direction="row" spacing={0.5} sx={{ my: 0.5 }} flexWrap="wrap" useFlexGap>
                    {story.skills.map((skill) => (
                      <Chip key={skill} size="small" label={skill} />
                    ))}
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    {story.body}
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                    <Button
                      size="small"
                      variant="contained"
                      startIcon={<AddIcon />}
                      disabled={accept.isPending}
                      onClick={() => {
                        accept.mutate(story);
                        setProposed((current) => current.filter((_, j) => j !== i));
                      }}
                    >
                      Keep it
                    </Button>
                    <Button
                      size="small"
                      onClick={() => setProposed((current) => current.filter((_, j) => j !== i))}
                    >
                      Discard
                    </Button>
                  </Stack>
                </Box>
              ))}
            </Stack>
          </CardContent>
        </Card>
      )}
    </Stack>
  );
}
