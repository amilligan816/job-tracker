import { Alert, Box, CircularProgress, Typography } from "@mui/material";
import type { ReactNode } from "react";

/** Uniform loading / error / empty handling so pages don't each reinvent it. */
export default function QueryState({
  isLoading,
  error,
  isEmpty,
  emptyMessage = "Nothing here yet.",
  children,
}: {
  isLoading: boolean;
  error: unknown;
  isEmpty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
}) {
  if (isLoading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }
  if (error) {
    return <Alert severity="error">{(error as Error).message}</Alert>;
  }
  if (isEmpty) {
    return (
      <Typography color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
        {emptyMessage}
      </Typography>
    );
  }
  return <>{children}</>;
}
