import {
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid2 as Grid,
  Link,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import QueryState from "../components/QueryState";

export default function CompaniesPage() {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", website: "", industry: "", notes: "" });
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["companies"],
    queryFn: () => api.companies.list(),
  });

  const create = useMutation({
    mutationFn: () =>
      api.companies.create({
        name: form.name,
        website: form.website || null,
        industry: form.industry || null,
        notes: form.notes || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      setOpen(false);
      setForm({ name: "", website: "", industry: "", notes: "" });
    },
  });

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h4">Companies</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setOpen(true)}>
          Add company
        </Button>
      </Stack>

      <QueryState
        isLoading={isLoading}
        error={error}
        isEmpty={!data?.length}
        emptyMessage="No companies yet. Capturing a posting creates one automatically."
      >
        <Grid container spacing={2}>
          {data?.map((company) => (
            <Grid size={{ xs: 12, sm: 6, md: 4 }} key={company.id}>
              <Card sx={{ height: "100%" }}>
                <CardContent>
                  <Typography variant="h6">{company.name}</Typography>
                  {company.industry && (
                    <Typography variant="body2" color="text.secondary">
                      {company.industry}
                    </Typography>
                  )}
                  {company.website && (
                    <Link
                      href={company.website}
                      target="_blank"
                      rel="noreferrer"
                      variant="body2"
                      sx={{ display: "block", mt: 1, wordBreak: "break-all" }}
                    >
                      {company.website}
                    </Link>
                  )}
                  {company.notes && (
                    <Typography variant="body2" sx={{ mt: 1 }}>
                      {company.notes}
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </QueryState>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add company</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              error={!!create.error}
              helperText={create.error ? (create.error as Error).message : " "}
            />
            <TextField
              label="Website"
              value={form.website}
              onChange={(e) => setForm({ ...form, website: e.target.value })}
            />
            <TextField
              label="Industry"
              value={form.industry}
              onChange={(e) => setForm({ ...form, industry: e.target.value })}
            />
            <TextField
              label="Notes"
              multiline
              minRows={3}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!form.name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
