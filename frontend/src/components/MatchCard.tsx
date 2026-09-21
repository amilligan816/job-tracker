import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import InsightsIcon from "@mui/icons-material/Insights";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { MatchSkill } from "../api/types";
import { MatchMeter } from "./MatchScore";
import QueryState from "./QueryState";

export default function MatchCard({ applicationId }: { applicationId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["match", applicationId],
    queryFn: () => api.applications.match(applicationId),
  });

  return (
    <Card>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
          <InsightsIcon fontSize="small" color="action" />
          <Typography variant="h6">Match rating</Typography>
          <Tooltip
            title="Computed from the posting and your resume by matching skills — no AI, so it is instant and always the same."
            arrow
          >
            <Chip size="small" variant="outlined" label="computed" />
          </Tooltip>
        </Stack>

        <QueryState isLoading={isLoading} error={error}>
          {data && (
            <Stack spacing={2}>
              {data.score === null ? (
                <Alert severity="info">{data.explanation}</Alert>
              ) : (
                <>
                  <MatchMeter score={data.score} rating={data.rating} />

                  <Typography variant="body2" color="text.secondary">
                    {data.explanation}
                    {data.confidence === "medium" && " The posting is short, so treat this loosely."}
                  </Typography>

                  {data.required_years !== null && (
                    <Typography variant="caption" color="text.secondary">
                      Asks for {data.required_years} years
                      {data.resume_years !== null
                        ? ` · your resume shows about ${data.resume_years} (${data.years_basis})`
                        : " · no experience length found on your resume, so it was not counted"}
                    </Typography>
                  )}

                  <SkillRow title="Covered" skills={data.matched} tone="covered" />
                  <SkillRow title="Not evidenced" skills={data.missing} tone="missing" />

                  {data.extra.length > 0 && (
                    <Box>
                      <Typography variant="subtitle2" gutterBottom>
                        Also on your resume
                      </Typography>
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                        {data.extra.map((skill) => (
                          <Chip key={skill} size="small" variant="outlined" label={skill} />
                        ))}
                      </Stack>
                    </Box>
                  )}
                </>
              )}
            </Stack>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function SkillRow({
  title,
  skills,
  tone,
}: {
  title: string;
  skills: MatchSkill[];
  tone: "covered" | "missing";
}) {
  if (skills.length === 0) return null;

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        {title}
      </Typography>
      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
        {skills.map((hit) => (
          <Tooltip key={hit.skill} title={`${hit.source} in the posting`} arrow>
            <Chip
              size="small"
              label={hit.skill}
              // Weight shows through as emphasis: a hard requirement reads louder.
              variant={tone === "covered" ? "filled" : "outlined"}
              color={tone === "covered" ? "primary" : "default"}
              sx={hit.weight >= 3 ? { fontWeight: 700 } : undefined}
            />
          </Tooltip>
        ))}
      </Stack>
    </Box>
  );
}
