import { Box, Stack, Tooltip, Typography } from "@mui/material";

/**
 * Score steps from the same validated ordinal blue ramp as the pipeline chart:
 * one hue, darker as the score rises. The rating word always travels with the
 * colour, so the meaning never rests on colour alone.
 */
function stepFor(score: number): string {
  if (score >= 80) return "#104281";
  if (score >= 60) return "#2a78d6";
  if (score >= 40) return "#5598e7";
  return "#86b6ef";
}

/** Compact form for a table cell: a number, a short meter, and the rating word. */
export function MatchScoreCell({
  score,
  rating,
}: {
  score: number | null;
  rating: string | null;
}) {
  if (score === null) {
    return (
      <Tooltip title={rating ?? "Not rated"} placement="top" arrow>
        <Typography variant="body2" color="text.disabled">
          —
        </Typography>
      </Tooltip>
    );
  }

  return (
    <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end">
      <Typography
        variant="body2"
        sx={{ fontWeight: 600, fontVariantNumeric: "tabular-nums", minWidth: 24 }}
      >
        {score}
      </Typography>
      <Box
        sx={{
          width: 48,
          height: 8,
          borderRadius: 1,
          bgcolor: "action.hover",
          overflow: "hidden",
          flexShrink: 0,
        }}
      >
        <Box sx={{ width: `${score}%`, height: "100%", bgcolor: stepFor(score) }} />
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 52 }}>
        {rating}
      </Typography>
    </Stack>
  );
}

/** Full-width meter for the detail card. */
export function MatchMeter({ score, rating }: { score: number; rating: string }) {
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="baseline">
        <Typography variant="body2" color="text.secondary">
          Skill match
        </Typography>
        <Stack direction="row" spacing={1} alignItems="baseline">
          <Typography sx={{ fontWeight: 700, fontSize: 28, fontVariantNumeric: "tabular-nums" }}>
            {score}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            /100 · {rating}
          </Typography>
        </Stack>
      </Stack>
      <Box sx={{ height: 10, borderRadius: 1, bgcolor: "action.hover", overflow: "hidden", mt: 0.5 }}>
        <Box
          sx={{
            width: `${score}%`,
            height: "100%",
            bgcolor: stepFor(score),
            transition: "width 240ms ease",
          }}
        />
      </Box>
    </Box>
  );
}
