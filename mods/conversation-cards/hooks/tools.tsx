// A tool call as one compact row: what it acts on, how it went; a press opens Claude Code's own row under it.

import { atom, memberOf, read, update } from 'claude-code'
import type { EngineInterface, RenderElement, RenderInput } from 'claude-code'

import { toolCard, toolTail, truncate } from './logic'

const toolTimes = atom({ plugin: 'conversation-cards', key: 'toolTimes' } as const, null)
const isToolOpen = atom({ plugin: 'conversation-cards', key: 'isToolOpen' } as const, false)

export async function renderToolUse(
  $: EngineInterface,
  e: RenderInput<'ToolUse'>,
  next: (e: RenderInput<'ToolUse'>) => Promise<RenderElement>,
  root: string,
): Promise<RenderElement> {
  const card = toolCard(e.props.tool, (e.props.input ?? {}) as Record<string, unknown>, root)
  if (card === null) return next(e)
  const [timing, isOpen] = await Promise.all([read($, memberOf(toolTimes, e)), read($, memberOf(isToolOpen, e))])
  const tail = toolTail({
    isRunning: e.props.isRunning,
    isErrored: e.props.isErrored || timing?.isError === true,
    isInterrupted: e.props.isInterrupted,
    durationMs: timing?.durationMs,
  })
  const { Box, Text, Button } = $.ui.resolve(e)
  const id = e.requestId
  const isRich = e.surface !== 'terminal'
  const accent = card.tone === 'agent' ? 'claude' : card.tone === 'web' ? 'suggestion' : 'subtle'
  const tailColor = tail.tone === 'running' ? 'claude' : tail.tone === 'error' ? 'error' : tail.tone === 'ok' ? 'success' : 'inactive'
  const barColor = tail.tone === 'error' ? 'error' : tail.tone === 'running' ? 'claude' : 'subtle'
  const header = (
    <Box key={`tool-${id}`} flexDirection="row" gap={1} alignItems="center" paddingLeft={isRich ? 1 : 0} {...(isRich ? { borderStyle: 'quote', borderColor: barColor } : {})}>
      <Text color={accent} weight="semibold">
        {card.icon}
      </Text>
      <Box flexGrow={1} flexShrink={1} minWidth={0} flexDirection="row" gap={1} overflow="hidden">
        <Box flexShrink={card.detail !== '' ? 0 : 1} minWidth={0}>
          <Text weight="medium" wrap="truncate-end">
            {truncate(card.title, 60)}
          </Text>
        </Box>
        {card.detail !== '' && (
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text dimColor mono size="footnote" wrap="truncate-end">
              {card.detail}
            </Text>
          </Box>
        )}
      </Box>
      <Box flexShrink={0} flexDirection="row" gap={1} alignItems="center">
        <Text color={tailColor} size="footnote" tabular>
          {tail.text}
        </Text>
        <Button key={`open-${id}`} plain dimColor label={isOpen ? '▴' : '▾'} onPress={() => update($, memberOf(isToolOpen, { requestId: id }), value => !value)} />
      </Box>
    </Box>
  )
  if (!isOpen) return header
  return (
    <Box flexDirection="column">
      {header}
      {await next(e)}
    </Box>
  )
}
