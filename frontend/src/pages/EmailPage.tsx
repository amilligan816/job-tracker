import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import MarkEmailReadIcon from "@mui/icons-material/MarkEmailRead";
import RefreshIcon from "@mui/icons-material/Refresh";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { MailAccount, SuggestionState } from "../api/types";
import MailSuggestionCard from "../components/MailSuggestionCard";
import QueryState from "../components/QueryState";

const TABS: { value: SuggestionState; label: string }[] = [
  { value: "pending", label: "To review" },
  { value: "accepted", label: "Applied" },
  { value: "dismissed", label: "Dismissed" },
];

function relativeTime(value: string | null): string {
  if (!value) return "never";
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function EmailPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<SuggestionState>("pending");
  // Google's callback redirects here with the outcome in the query string.
  const [params, setParams] = useSearchParams();

  const status = useQuery({ queryKey: ["mail-status"], queryFn: api.mail.status });
  const suggestions = useQuery({
    queryKey: ["mail-suggestions", tab],
    queryFn: () => api.mail.suggestions({ state: tab }),
  });

  const connect = useMutation({
    mutationFn: api.mail.startGoogleAuth,
    onSuccess: ({ authorization_url }) => {
      window.location.href = authorization_url;
    },
  });

  const syncAll = useMutation({
    mutationFn: api.mail.syncAll,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mail-status"] });
      queryClient.invalidateQueries({ queryKey: ["mail-suggestions"] });
    },
  });

  const disconnect = useMutation({
    mutationFn: (id: string) => api.mail.disconnect(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mail-status"] });
      queryClient.invalidateQueries({ queryKey: ["mail-suggestions"] });
    },
  });

  const accounts = status.data?.accounts ?? [];
  const connected = params.get("connected");
  const oauthError = params.get("error");

  return (
    <Stack spacing={3}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ sm: "center" }}
        spacing={2}
      >
        <Box>
          <Typography variant="h4">Email</Typography>
          <Typography color="text.secondary">
            Updates read out of your inbox. Nothing moves until you say so.
          </Typography>
        </Box>
        {accounts.length > 0 && (
          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={() => syncAll.mutate()}
            disabled={syncAll.isPending}
          >
            {syncAll.isPending ? "Syncing…" : "Sync now"}
          </Button>
        )}
      </Stack>

      {connected && (
        <Alert severity="success" onClose={() => setParams({})}>
          Connected <strong>{connected}</strong>. The first sync reaches back over the last few
          weeks, so give it a moment.
        </Alert>
      )}
      {oauthError && (
        <Alert severity="error" onClose={() => setParams({})}>
          {oauthError}
        </Alert>
      )}
      {syncAll.error && <Alert severity="error">{(syncAll.error as Error).message}</Alert>}

      <QueryState isLoading={status.isLoading} error={status.error}>
        {status.data && !status.data.configured ? (
          <Alert severity="info">
            <Typography variant="body2" gutterBottom>
              Gmail is not configured yet. In <code>.env</code>, set{" "}
              <code>GOOGLE_CLIENT_ID</code>, <code>GOOGLE_CLIENT_SECRET</code> and{" "}
              <code>MAIL_TOKEN_KEY</code>, then restart the backend.
            </Typography>
            <Typography variant="body2">
              The README has the Google Cloud steps — it takes about five minutes and the app only
              ever asks for read access.
            </Typography>
          </Alert>
        ) : (
          <Stack spacing={2}>
            {accounts.map((account) => (
              <AccountCard
                key={account.id}
                account={account}
                onDisconnect={() => disconnect.mutate(account.id)}
                disconnecting={disconnect.isPending}
              />
            ))}

            <Card>
              <CardContent>
                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  justifyContent="space-between"
                  alignItems={{ sm: "center" }}
                  spacing={2}
                >
                  <Box>
                    <Typography variant="subtitle1">
                      {accounts.length ? "Connect another mailbox" : "Connect your mailbox"}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Read-only access to Gmail. Only mail that matches something you are tracking
                      is stored.
                    </Typography>
                  </Box>
                  <Button
                    variant="contained"
                    onClick={() => connect.mutate()}
                    disabled={connect.isPending}
                  >
                    Connect Gmail
                  </Button>
                </Stack>
                {connect.error && (
                  <Alert severity="error" sx={{ mt: 2 }}>
                    {(connect.error as Error).message}
                  </Alert>
                )}
              </CardContent>
            </Card>
          </Stack>
        )}
      </QueryState>

      {accounts.length > 0 && (
        <Box>
          <Tabs
            value={tab}
            onChange={(_, value) => setTab(value as SuggestionState)}
            sx={{ mb: 2, borderBottom: "1px solid rgba(0,0,0,0.08)" }}
          >
            {TABS.map(({ value, label }) => (
              <Tab
                key={value}
                value={value}
                label={
                  value === "pending" && status.data?.pending_suggestions ? (
                    <Stack direction="row" spacing={1} alignItems="center">
                      <span>{label}</span>
                      <Chip size="small" label={status.data.pending_suggestions} color="primary" />
                    </Stack>
                  ) : (
                    label
                  )
                }
              />
            ))}
          </Tabs>

          <QueryState
            isLoading={suggestions.isLoading}
            error={suggestions.error}
            isEmpty={suggestions.data?.length === 0}
            emptyMessage={
              tab === "pending"
                ? "Nothing to review. New mail about a tracked application shows up here."
                : "Nothing here yet."
            }
          >
            <Stack spacing={2}>
              {suggestions.data?.map((suggestion) => (
                <MailSuggestionCard
                  key={suggestion.id}
                  suggestion={suggestion}
                  showMailbox={accounts.length > 1}
                />
              ))}
            </Stack>
          </QueryState>
        </Box>
      )}
    </Stack>
  );
}

function AccountCard({
  account,
  onDisconnect,
  disconnecting,
}: {
  account: MailAccount;
  onDisconnect: () => void;
  disconnecting: boolean;
}) {
  const queryClient = useQueryClient();
  const sync = useMutation({
    mutationFn: () => api.mail.sync(account.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mail-status"] });
      queryClient.invalidateQueries({ queryKey: ["mail-suggestions"] });
    },
  });

  const stats = account.last_sync_stats;

  return (
    <Card>
      <CardContent>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ sm: "center" }}
          spacing={2}
        >
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
            <MarkEmailReadIcon color={account.status === "active" ? "primary" : "disabled"} />
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" noWrap>
                {account.email_address}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Last synced {relativeTime(account.last_synced_at)}
                {stats && ` · ${stats.scanned} scanned, ${stats.suggested} to review`}
              </Typography>
            </Box>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center">
            <Button size="small" onClick={() => sync.mutate()} disabled={sync.isPending}>
              {sync.isPending ? "Syncing…" : "Sync"}
            </Button>
            <Button
              size="small"
              color="inherit"
              startIcon={<DeleteOutlineIcon />}
              onClick={onDisconnect}
              disabled={disconnecting}
            >
              Disconnect
            </Button>
          </Stack>
        </Stack>

        {account.status === "needs_reauth" && (
          <Alert severity="warning" sx={{ mt: 2 }}>
            {account.last_sync_error ?? "This mailbox needs to be reconnected."} Connect it again
            below.
          </Alert>
        )}
        {account.status === "error" && account.last_sync_error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {account.last_sync_error}
          </Alert>
        )}
        {stats?.truncated && (
          <Alert severity="info" sx={{ mt: 2 }}>
            That run hit its ceiling and stopped early. Sync again to continue.
          </Alert>
        )}
        {sync.error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {(sync.error as Error).message}
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
