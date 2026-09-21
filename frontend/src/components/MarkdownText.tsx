import { Box, Typography } from "@mui/material";
import { Fragment } from "react";

/**
 * Renders the same light markup subset the exporters understand (headings,
 * bullets, numbered items, **bold**, *italic*), so what is on screen matches
 * the Word and PDF versions instead of showing raw asterisks.
 */
type Block =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] };

const HEADING = /^(#{1,4})\s+(.*)$/;
const BOLD_ONLY_LINE = /^\*\*(.+?)\*\*:?$/;
const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const INLINE = /\*\*(.+?)\*\*|\*(.+?)\*/g;

function parse(text: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];

  const flush = () => {
    if (paragraph.length) {
      blocks.push({ kind: "paragraph", text: paragraph.join(" ").trim() });
      paragraph = [];
    }
  };

  const pushItem = (item: string, ordered: boolean) => {
    const last = blocks[blocks.length - 1];
    if (last?.kind === "list" && last.ordered === ordered) last.items.push(item);
    else blocks.push({ kind: "list", ordered, items: [item] });
  };

  for (const raw of (text ?? "").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }

    const heading = line.match(HEADING);
    const boldOnly = line.trim().match(BOLD_ONLY_LINE);
    const bullet = line.match(BULLET);
    const numbered = line.match(NUMBERED);

    if (heading) {
      flush();
      blocks.push({ kind: "heading", text: heading[2].trim() });
    } else if (boldOnly) {
      flush();
      blocks.push({ kind: "heading", text: boldOnly[1].trim() });
    } else if (bullet) {
      flush();
      pushItem(bullet[1].trim(), false);
    } else if (numbered) {
      flush();
      pushItem(numbered[1].trim(), true);
    } else {
      paragraph.push(line.trim());
    }
  }
  flush();
  return blocks;
}

function Inline({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  INLINE.lastIndex = 0;
  while ((match = INLINE.exec(text)) !== null) {
    if (match.index > cursor) parts.push(text.slice(cursor, match.index));
    if (match[1] !== undefined) parts.push(<strong key={match.index}>{match[1]}</strong>);
    else parts.push(<em key={match.index}>{match[2]}</em>);
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));

  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>{part}</Fragment>
      ))}
    </>
  );
}

export default function MarkdownText({ text }: { text: string }) {
  return (
    <Box>
      {parse(text).map((block, i) => {
        if (block.kind === "heading") {
          return (
            <Typography key={i} variant="subtitle2" sx={{ mt: i === 0 ? 0 : 1.5, mb: 0.5 }}>
              <Inline text={block.text} />
            </Typography>
          );
        }
        if (block.kind === "list") {
          return (
            <Box
              key={i}
              component={block.ordered ? "ol" : "ul"}
              sx={{ m: 0, mb: 1, pl: 2.5 }}
            >
              {block.items.map((item, j) => (
                <Typography component="li" variant="body2" key={j}>
                  <Inline text={item} />
                </Typography>
              ))}
            </Box>
          );
        }
        return (
          <Typography key={i} variant="body2" sx={{ mb: 1 }}>
            <Inline text={block.text} />
          </Typography>
        );
      })}
    </Box>
  );
}
