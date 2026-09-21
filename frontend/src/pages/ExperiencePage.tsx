import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { ExperienceProfile, ExperienceRole } from "../api/types";
import ExperienceChat from "../components/ExperienceChat";
import ImportResumeDialog from "../components/ImportResumeDialog";
import QueryState from "../components/QueryState";

export default function ExperiencePage() {
  const [tab, setTab] = useState<"record" | "chat" | "text">("record");
  const [importOpen, setImportOpen] = useState(false);

  const profile = useQuery({ queryKey: ["experience"], queryFn: api.experience.get });

  return (
    <Stack spacing={3}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ sm: "center" }}
        spacing={2}
      >
        <Box>
          <Typography variant="h4">Experience</Typography>
          <Typography color="text.secondary">
            Your professional record. Resumes are generated from this, and every cover letter and
            interview answer is grounded in it.
          </Typography>
        </Box>
        <Button variant="contained" onClick={() => setImportOpen(true)}>
          Import from a resume
        </Button>
      </Stack>

      <Tabs value={tab} onChange={(_, v) => setTab(v)}>
        <Tab label="Record" value="record" />
        <Tab label="Deepen it" value="chat" />
        <Tab label="What the model sees" value="text" />
      </Tabs>

      <QueryState isLoading={profile.isLoading} error={profile.error}>
        {profile.data && (
          <>
            {tab === "record" && <RecordTab profile={profile.data} />}
            {tab === "chat" && <ExperienceChat profile={profile.data} />}
            {tab === "text" && <RenderedTextTab />}
          </>
        )}
      </QueryState>

      <ImportResumeDialog open={importOpen} onClose={() => setImportOpen(false)} />
    </Stack>
  );
}

function RecordTab({ profile }: { profile: ExperienceProfile }) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["experience"] });

  const updateProfile = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.experience.update(body),
    onSuccess: invalidate,
  });
  const removeRole = useMutation({
    mutationFn: (id: string) => api.experience.removeRole(id),
    onSuccess: invalidate,
  });
  const removeStory = useMutation({
    mutationFn: (id: string) => api.experience.removeStory(id),
    onSuccess: invalidate,
  });

  const [roleOpen, setRoleOpen] = useState(false);

  return (
    <Stack spacing={2}>
      {profile.is_empty && (
        <Alert severity="info">
          Nothing recorded yet. Import a resume to fill this in, then use <strong>Deepen it</strong>{" "}
          to add the detail a resume has no room for.
        </Alert>
      )}

      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            About you
          </Typography>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                size="small"
                label="Name"
                fullWidth
                key={`name-${profile.full_name}`}
                defaultValue={profile.full_name ?? ""}
                onBlur={(e) => updateProfile.mutate({ full_name: e.target.value || null })}
              />
              <TextField
                size="small"
                label="Headline"
                fullWidth
                key={`headline-${profile.headline}`}
                defaultValue={profile.headline ?? ""}
                onBlur={(e) => updateProfile.mutate({ headline: e.target.value || null })}
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                size="small"
                label="Email"
                fullWidth
                key={`email-${profile.email}`}
                defaultValue={profile.email ?? ""}
                onBlur={(e) => updateProfile.mutate({ email: e.target.value || null })}
              />
              <TextField
                size="small"
                label="Location"
                fullWidth
                key={`location-${profile.location}`}
                defaultValue={profile.location ?? ""}
                onBlur={(e) => updateProfile.mutate({ location: e.target.value || null })}
              />
            </Stack>
            <TextField
              size="small"
              label="Summary"
              multiline
              minRows={2}
              key={`summary-${profile.summary}`}
              defaultValue={profile.summary ?? ""}
              onBlur={(e) => updateProfile.mutate({ summary: e.target.value || null })}
            />
            <TextField
              size="small"
              label="Skills"
              helperText="Comma separated"
              key={`skills-${profile.skills.join(",")}`}
              defaultValue={profile.skills.join(", ")}
              onBlur={(e) =>
                updateProfile.mutate({
                  skills: e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
            />
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="h6">Roles</Typography>
            <Button size="small" startIcon={<AddIcon />} onClick={() => setRoleOpen(true)}>
              Add role
            </Button>
          </Stack>

          {profile.roles.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No roles yet.
            </Typography>
          ) : (
            <Stack spacing={2} divider={<Divider flexItem />}>
              {profile.roles.map((role) => (
                <RoleBlock key={role.id} role={role} onRemove={() => removeRole.mutate(role.id)} />
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h6">Stories</Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            The depth behind the bullets — what a cover letter and an interview answer draw on.
          </Typography>

          {profile.stories.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
              None yet. The <strong>Deepen it</strong> tab is the fastest way to add them.
            </Typography>
          ) : (
            <Stack spacing={2} sx={{ mt: 1 }} divider={<Divider flexItem />}>
              {profile.stories.map((story) => (
                <Box key={story.id}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                    <Box>
                      <Typography variant="subtitle2">{story.title}</Typography>
                      <Stack direction="row" spacing={0.5} sx={{ my: 0.5 }} flexWrap="wrap" useFlexGap>
                        <Chip size="small" variant="outlined" label={story.source} />
                        {story.skills.map((skill) => (
                          <Chip key={skill} size="small" label={skill} />
                        ))}
                      </Stack>
                    </Box>
                    <IconButton
                      size="small"
                      color="error"
                      onClick={() => removeStory.mutate(story.id)}
                    >
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    {story.body}
                  </Typography>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      <AddRoleDialog open={roleOpen} onClose={() => setRoleOpen(false)} />
    </Stack>
  );
}

function RoleBlock({ role, onRemove }: { role: ExperienceRole; onRemove: () => void }) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["experience"] });
  const [newHighlight, setNewHighlight] = useState("");

  const addHighlight = useMutation({
    mutationFn: () => api.experience.addHighlight(role.id, newHighlight, role.highlights.length),
    onSuccess: () => {
      setNewHighlight("");
      invalidate();
    },
  });
  const removeHighlight = useMutation({
    mutationFn: (id: string) => api.experience.removeHighlight(id),
    onSuccess: invalidate,
  });

  const period = `${role.start_date ?? "?"} – ${role.end_date ?? "Present"}`;

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
        <Box>
          <Typography variant="subtitle1" fontWeight={600}>
            {role.title} — {role.company}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {period}
            {role.location ? ` · ${role.location}` : ""}
          </Typography>
        </Box>
        <Tooltip title="Remove role and its highlights" arrow>
          <IconButton size="small" color="error" onClick={onRemove}>
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      {role.summary && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {role.summary}
        </Typography>
      )}

      <Stack spacing={0.5} sx={{ mt: 1 }}>
        {role.highlights.map((highlight) => (
          <Stack key={highlight.id} direction="row" spacing={1} alignItems="flex-start">
            <Typography variant="body2" sx={{ flex: 1 }}>
              • {highlight.text}
            </Typography>
            <IconButton size="small" onClick={() => removeHighlight.mutate(highlight.id)}>
              <DeleteOutlineIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Stack>
        ))}
      </Stack>

      <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
        <TextField
          size="small"
          placeholder="Add a highlight…"
          fullWidth
          value={newHighlight}
          onChange={(e) => setNewHighlight(e.target.value)}
        />
        <Button
          size="small"
          disabled={!newHighlight.trim() || addHighlight.isPending}
          onClick={() => addHighlight.mutate()}
        >
          Add
        </Button>
      </Stack>
    </Box>
  );
}

function AddRoleDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    company: "",
    title: "",
    location: "",
    start_date: "",
    end_date: "",
    summary: "",
  });

  const create = useMutation({
    mutationFn: () =>
      api.experience.createRole({
        company: form.company,
        title: form.title,
        location: form.location || null,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
        summary: form.summary || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["experience"] });
      setForm({ company: "", title: "", location: "", start_date: "", end_date: "", summary: "" });
      onClose();
    },
  });

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Add role</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Title"
            required
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
          <TextField
            label="Company"
            required
            value={form.company}
            onChange={(e) => setForm({ ...form, company: e.target.value })}
          />
          <TextField
            label="Location"
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
          />
          <Stack direction="row" spacing={2}>
            <TextField
              label="Started"
              type="date"
              InputLabelProps={{ shrink: true }}
              fullWidth
              value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
            />
            <TextField
              label="Ended"
              type="date"
              InputLabelProps={{ shrink: true }}
              fullWidth
              helperText="Leave blank if current"
              value={form.end_date}
              onChange={(e) => setForm({ ...form, end_date: e.target.value })}
            />
          </Stack>
          <TextField
            label="Summary"
            multiline
            minRows={2}
            value={form.summary}
            onChange={(e) => setForm({ ...form, summary: e.target.value })}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!form.title.trim() || !form.company.trim() || create.isPending}
          onClick={() => create.mutate()}
        >
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function RenderedTextTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["experience-text"],
    queryFn: api.experience.text,
  });

  return (
    <Card>
      <CardContent>
        <Typography variant="h6">What the model sees</Typography>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          Exactly the text used to score match ratings and ground every generated document. If
          something reads wrong here, it will read wrong there.
        </Typography>
        <QueryState isLoading={isLoading} error={error}>
          <Box
            component="pre"
            sx={{
              mt: 1,
              p: 2,
              bgcolor: "background.default",
              borderRadius: 1,
              fontSize: 13,
              whiteSpace: "pre-wrap",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}
          >
            {data?.text || "(empty)"}
          </Box>
        </QueryState>
      </CardContent>
    </Card>
  );
}
