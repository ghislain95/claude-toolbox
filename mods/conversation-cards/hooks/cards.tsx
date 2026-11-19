// Claude's messages drawn as cards: questions with their options and the
// recommendation, end-of-task reports section by section, findings, commits,
// QA, decisions to confirm. One « Envoyer mes réponses » gathers every answer
// of a card into one prompt. The message itself is never changed.

import type { EngineInterface, RenderChildren, RenderElement, RenderInput } from 'claude-code'

import { addToPrompt, copyText, insertAnswers, markQa, notePrompt, openFile, summarize, toggleReportSection } from './actions'
import { cleanMarkdown, truncate } from './logic'
import {
  type Block,
  type BlockGroup,
  type Chip,
  type CommitBlock,
  type Finding,
  type CockpitItem,
  type ListItem,
  type Pick,
  type QaCheck,
  type QaFollowUp,
  type QaPlan,
  type Question,
  type Report,
  ASK_TITLE,
  CONFIRM_TITLE,
  askGroups,
  cockpitBlock,
  commitBlocks,
  decisionsToValidate,
  fileRefs,
  findSection,
  handoffPhrase,
  isInfoGroup,
  keyFigures,
  listItems,
  parseFindings,
  parseQuestions,
  parseReport,
  qaFollowUps,
  qaPlan,
  sectionItems,
  sectionProse,
  tablePicks,
  withoutCockpitBlock,
} from './parse'
import { type IconName, GALET, type Mode, NATIVE, type Tone, chip, disc, dot, familyOf, icon, pills, surface, tileFill } from './shared/sienne'

export type MessageShape = {
  questions: Question[]
  report: Report | null
  commits: CommitBlock[]
  /** The QA's checks by title, for the answers; `qaPlan` holds how to prepare and each check whole. */
  qa: string[]
  qaPlan: QaPlan
  /** The checks a reply comes back to after the user's QA answers, when it holds no QA of its own. */
  followUps: QaFollowUp[]
  asks: string[]
  /** « Ce que j'attends de toi » in the order written, less the QA and the commit message (drawn in their own cards). */
  askGroups: BlockGroup[]
  /** The points to confirm, each on one line for the answers; their sub-points in `decisionDetails`. */
  decisions: string[]
  decisionDetails: (string | null)[]
  /** « Décisions que j’ai prises seul » for a « Décisions » section, « À confirmer » for « Mes lectures », « Hypothèses »… */
  decisionsTitle: string
  /** Choices the user makes, each with Claude's recommendation: a « Reco » table, or the `trancher:` lines of the cockpit block. */
  picks: Pick[]
  /** What Claude says it does next without the user's decision (the cockpit block's `info:` lines). */
  infos: CockpitItem[]
  /** True when the message carries a cockpit block: the cards come from it, nothing is guessed. */
  hasCockpitBlock: boolean
  findings: Finding[]
  files: { path: string; line: number | null }[]
  phrase: string | null
  chips: Chip[]
  isLong: boolean
}

const LONG_MESSAGE = 1800

/** A list item's first line, plain: what a reply row shows and the answers quote. */
function itemLine(item: ListItem): string {
  return cleanMarkdown(item.text.split('\n')[0] ?? '')
}

/** What a list item says under its first line (its sub-points), as markdown; null when nothing. */
function itemDetail(item: ListItem): string | null {
  const rest = item.text.split('\n').slice(1).join('\n').trim()
  return rest === '' ? null : rest
}

/** What a message holds that deserves a card; null when it is short plain prose. */
export function messageShape(fullText: string): MessageShape | null {
  const cockpit = cockpitBlock(fullText)
  const text = cockpit === null ? fullText : withoutCockpitBlock(fullText)
  const questions = parseQuestions(text).filter(question => question.options.length >= 2)
  const report = parseReport(text)
  const commits = commitBlocks(text)
  const parsedPlan = qaPlan(text, report)
  // The block's « vérifier: » lines name the checks; a report keeps its own QA, drawn whole in place of the text.
  const verifyItems = cockpit?.filter(item => item.kind === 'vérifier') ?? []
  const plan =
    verifyItems.length > 0 && (report === null || parsedPlan.checks.length === 0)
      ? { preparation: [], intro: '', checks: verifyItems.map(item => ({ title: item.text, action: null, expected: null, text: item.text })) }
      : parsedPlan
  const followUps = plan.checks.length === 0 ? qaFollowUps(text) : []
  const qa = plan.checks.length > 0 ? plan.checks.map(check => check.title ?? check.text) : followUps.map(followUp => followUp.title)
  const askBody = report?.ask ?? findSection(text, ASK_TITLE)?.body ?? null
  const sectionGroupsOfAsk = askBody !== null && askBody !== '' ? askGroups(askBody) : []
  const reportDecisions = report?.sections.find(section => section.kind === 'decisions')
  const confirmSection = reportDecisions ?? findSection(text, CONFIRM_TITLE)
  let asking: BlockGroup[]
  let asks: string[]
  let picks: Pick[]
  let decisions: string[]
  let decisionDetails: (string | null)[]
  let decisionsTitle: string
  if (cockpit !== null) {
    // The block says what needs the user: the cards follow it, the section keeps only its prose and commands.
    const doItems = cockpit.filter(item => item.kind === 'faire')
    asks = doItems.map(item => item.text)
    asking = [
      ...(doItems.length > 0 ? [{ title: null, lead: '', blocks: [{ kind: 'list' as const, items: doItems.map(item => ({ text: [item.text, ...item.details.map(detail => `- ${detail}`)].join('\n'), code: [], isNumbered: false })) }] }] : []),
      ...sectionGroupsOfAsk
        .filter(group => !isInfoGroup(group))
        .map(group => ({ ...group, blocks: group.blocks.filter(block => block.kind === 'prose' || block.kind === 'code') }))
        .filter(group => group.blocks.length > 0 || group.lead !== ''),
    ]
    picks = cockpit.filter(item => item.kind === 'trancher').map(item => ({ label: item.text, reco: item.reco, details: item.details }))
    const confirmed = cockpit.filter(item => item.kind === 'confirmer')
    decisions = confirmed.map(item => item.text)
    decisionDetails = confirmed.map(item => (item.details.length > 0 ? item.details.map(detail => `- ${detail}`).join('\n') : null))
    decisionsTitle = 'Décisions que j’ai prises seul'
  } else {
    asking = sectionGroupsOfAsk
    asks = asking.filter(group => !isInfoGroup(group)).flatMap(group => group.blocks.flatMap(block => (block.kind === 'list' ? block.items.map(itemLine) : [])))
    picks = asking.flatMap(group => group.blocks.flatMap(block => tablePicks(block) ?? []))
    const decisionItems = reportDecisions !== undefined ? sectionItems(reportDecisions.body) : decisionsToValidate(text)
    decisions = decisionItems.map(itemLine)
    decisionDetails = decisionItems.map(itemDetail)
    decisionsTitle = confirmSection === undefined || confirmSection === null || /^décisions/i.test(confirmSection.title) ? 'Décisions que j’ai prises seul' : 'À confirmer'
  }
  const infos = cockpit?.filter(item => item.kind === 'info') ?? []
  const allFindings = parseFindings(text)
  const findings = allFindings.some(finding => finding.file !== null) || allFindings.length >= 2 ? allFindings : []
  const files = fileRefs(text)
  const phrase = handoffPhrase(text)
  const isLong = text.length > LONG_MESSAGE
  const hasStructure =
    questions.length > 0 ||
    report !== null ||
    commits.length > 0 ||
    qa.length > 0 ||
    findings.length > 0 ||
    phrase !== null ||
    decisions.length > 0 ||
    asks.length > 0 ||
    picks.length > 0 ||
    infos.length > 0
  if (!hasStructure && !isLong) return null
  return {
    questions,
    report,
    commits,
    qa,
    qaPlan: plan,
    followUps,
    asks,
    askGroups: asking,
    decisions,
    decisionDetails,
    decisionsTitle,
    picks,
    infos,
    hasCockpitBlock: cockpit !== null,
    findings,
    files,
    phrase,
    chips: report !== null ? keyFigures(text) : [],
    isLong,
  }
}

export type CardContext = {
  messageId: string
  root: string
  home: string
  changeNames: string[]
  recentCommits: { hash: string; subject: string }[]
  isOpen: boolean
  marks: Record<string, string>
  sectionsOpen: Record<string, boolean>
  brief: string | null
  onToggle: () => void
  /**
   * The message is drawn whole above the cards: they hold the actions only (titles and buttons), never its content again.
   * False under a report, whose card replaces the text.
   */
  isCompact?: boolean
  /** The person has sent something since this reply: its cards stop moving (only the latest reply moves). */
  isSettled?: boolean
  /** True on a surface that draws Svg (desktop, VS Code): the Galet cards; the terminal keeps its framed text cards. */
  isRich?: boolean
  /** The app's light or dark mode: tiles and chips are white on light, a veil on dark. */
  mode?: Mode
}

type Elements = ReturnType<EngineInterface['ui']['resolve']>
type Event = RenderInput<'AssistantMessage'>

/**
 * A card's head: a tag (Q1) or an icon, the title, a meta on the right. `waiting` marks a question that waits for
 * an answer in the latest reply (a dot that breathes); `pending`, one that waits in an earlier reply (a still dot).
 */
type Header = { icon: IconName | { badge: string }; title: string; meta?: string; tone?: Tone; waiting?: boolean; pending?: boolean; done?: boolean }

const BORDER: Record<Tone, string> = {
  accent: NATIVE.accentBorder,
  running: NATIVE.accentBorder,
  muted: NATIVE.accentBorder,
  ok: NATIVE.ok,
  warning: 'warning',
  danger: NATIVE.danger,
}

type SvgElement = (props: Record<string, unknown>) => RenderElement

/** The Svg element where the surface draws one (desktop, VS Code) and the context asks for Galet cards. */
function richSvg(els: Elements, context: CardContext): SvgElement | null {
  const { Svg } = els as { Svg?: SvgElement }
  return context.isRich === true && Svg !== undefined ? Svg : null
}

/**
 * A card: on a surface that draws Svg, a Galet pebble (a pastel of the card's tone, round corners, no rim) that
 * opens on its tag or icon, its title and a meta; on the terminal, the framed text card it always was.
 */
function framed(els: Elements, key: string, context: CardContext, header: Header, textHeader: RenderChildren, body: RenderChildren, gap: 'xs' | 'sm' = 'xs'): RenderChildren {
  const { Box, Text } = els
  const Svg = richSvg(els, context)
  if (Svg === null) {
    return (
      <Box key={key} flexDirection="column" gap={gap} borderStyle="round" borderColor={BORDER[header.tone ?? 'accent']} paddingX="md" paddingY="sm">
        {textHeader}
        {body}
      </Box>
    )
  }
  const tone = header.tone ?? 'accent'
  const family = familyOf(tone)
  const lead =
    typeof header.icon === 'string' ? (
      <Svg key={`${key}-icon`} alt={header.title} source={icon(header.icon, { tone, size: 15 })} width={15} height={15} />
    ) : (
      <Box key={`${key}-tag`} flexDirection="row" alignItems="center" gap="xs" flexShrink={0} {...chip(GALET.deep[family])}>
        <Svg key={`${key}-tag-icon`} alt={header.icon.badge} source={icon('question', { tone, size: 12 })} width={12} height={12} />
        <Text size="caption" weight="semibold" color={GALET.text[family]}>
          {header.icon.badge}
        </Text>
      </Box>
    )
  return (
    <Box key={key} flexDirection="column" gap="sm" {...surface(family)} paddingX="md" paddingY="md">
      <Box flexDirection="row" gap="sm" alignItems="center">
        {lead}
        <Box flexGrow={1} flexShrink={1} minWidth={0}>
          <Text weight="semibold" wrap="wrap">
            {header.title}
          </Text>
        </Box>
        {header.meta !== undefined && header.meta !== '' && (
          <Box flexShrink={0} flexDirection="row" gap="xs" alignItems="center">
            {(header.waiting === true || header.pending === true) && (
              <Svg key={`${key}-waiting`} alt="en attente" source={dot(tone, { pulse: header.waiting === true, size: 10 })} width={10} height={10} isInteractive={header.waiting === true} />
            )}
            <Text size="caption" dimColor>
              {header.meta}
            </Text>
          </Box>
        )}
        {header.done === true && <Svg key={`${key}-done`} alt="fait" source={icon('check', { tone: 'ok', size: 15 })} width={15} height={15} />}
      </Box>
      <Box flexDirection="column" gap={gap}>
        {body}
      </Box>
    </Box>
  )
}

/**
 * A mark (OK, KO, Corriger, Ton avis, Note): on the desktop a soft chip, white on light and a veil on dark,
 * that takes the pastel of its tone once chosen; on the terminal a quiet text button.
 */
function markButton(els: Elements, context: CardContext, key: string, label: string, isOn: boolean, tone: Tone, onPress: () => void): RenderChildren {
  const { Box, Button } = els
  const button = <Button key={key} plain dimColor={!isOn} label={label} onPress={onPress} />
  if (richSvg(els, context) === null) return button
  return (
    <Box key={`${key}-chip`} flexShrink={0} {...chip(isOn ? GALET.deep[familyOf(tone)] : tileFill(context.mode ?? 'auto'), { pressable: true })}>
      {button}
    </Box>
  )
}

const TONE_OF_COLOR: Record<string, Tone> = { success: 'ok', error: 'danger', warning: 'warning' }

// ---------------------------------------------------------------- the answer sent back

const SPECIAL_ANSWERS: Record<string, string> = { avis: 'ton avis ?', simple: 'explique plus simplement, avec un exemple' }

/** Every answer of a card as the lines of the framed block added to the prompt. Notes live in the prompt itself. */
export function answersBlock(shape: MessageShape, marks: Record<string, string>): string {
  const lines: string[] = []
  for (const question of shape.questions) {
    const mark = marks[`q:${question.id}`]
    if (mark === undefined) continue
    const option = question.options.find(candidate => candidate.letter === mark)
    lines.push(`${question.id} : ${option !== undefined ? `${option.letter} · ${option.label}` : SPECIAL_ANSWERS[mark] ?? mark}`)
  }
  const picked = shape.picks.map((pick, index) => ({ pick, index, mark: marks[`pick:${index}`] })).filter(entry => entry.mark !== undefined)
  if (picked.length > 0) {
    lines.push('À trancher :')
    for (const entry of picked) lines.push(`- ${entry.mark === 'ok' ? '✓ reco' : '✎ autre choix'} ${entry.index + 1}. ${truncate(entry.pick.label, 100)}`)
  }
  const asksDone = shape.asks.map((_, index) => index).filter(index => marks[`ask:${index}`] === 'ok')
  if (asksDone.length > 0) lines.push(`Demandes : ${asksDone.map(index => `${index + 1} OK`).join(' · ')}`)
  const decided = shape.decisions
    .map((item, index) => ({ item, index, mark: marks[`dec:${index}`] }))
    .filter(entry => entry.mark !== undefined)
  if (decided.length > 0) {
    lines.push('Décisions :')
    for (const entry of decided) lines.push(`- ${entry.mark === 'ok' ? '✓' : '✎ à corriger'} ${entry.index + 1}. ${truncate(entry.item, 110)}`)
  }
  if (shape.qa.some((_, index) => marks[`qa:${index}`] !== undefined)) lines.push(qaSummary(shape.qa, marks))
  return lines.join('\n')
}

/** The QA result: the count, then every line that is not OK. */
export function qaSummary(items: string[], marks: Record<string, string>): string {
  const mark = (index: number) => marks[`qa:${index}`]
  const ok = items.filter((_, index) => mark(index) === 'ok').length
  const ko = items.filter((_, index) => mark(index) === 'ko').length
  const untested = items.length - ok - ko
  const head = [`QA : ${ok}/${items.length} OK`, ko > 0 ? `${ko} KO` : '', untested > 0 ? `${untested} non testé${untested > 1 ? 's' : ''}` : '']
    .filter(part => part !== '')
    .join(', ')
  const others = items
    .map((item, index) => ({ item, index, mark: mark(index) }))
    .filter(entry => entry.mark !== 'ok')
    .map(entry => `- ${entry.mark === 'ko' ? '✗' : '○'} ${/^QA \d+/.test(entry.item) ? '' : `${entry.index + 1}. `}${truncate(entry.item, 110)}`)
  return others.length === 0 ? head : `${head}\n${others.join('\n')}`
}

function answeredCount(marks: Record<string, string>): number {
  return Object.keys(marks).length
}

// ---------------------------------------------------------------- shared pieces

function noteButton($: EngineInterface, els: Elements, key: string, label: string, context: CardContext): RenderChildren {
  return markButton(els, context, `note-button-${context.messageId}-${key}`, 'Note', false, 'muted', () => void notePrompt($, label))
}

/**
 * A row's number; on the desktop, once marked, a check (OK) or a cross (KO, à corriger) in the mark's tone takes
 * its place and the text keeps its own colour, so a card full of answers stays calm.
 */
function rowIndex(els: Elements, context: CardContext, index: number, chosen: MarkOption | undefined): RenderChildren {
  const { Text } = els
  if (chosen === undefined || richSvg(els, context) === null) {
    return (
      <Text size="caption" dimColor tabular>
        {index + 1}.
      </Text>
    )
  }
  if (chosen.value !== 'ok') {
    return (
      <Text size="caption" dimColor tabular>
        {index + 1}.
      </Text>
    )
  }
  return (
    <Text size="caption" weight="semibold" color={GALET.text.sage} tabular>
      ✓
    </Text>
  )
}

/** The colour of a marked row's text: the mark's on the terminal; on the desktop a row marked OK goes quiet. */
function rowColor(els: Elements, context: CardContext, chosen: MarkOption | undefined): string | undefined {
  if (richSvg(els, context) === null) return chosen?.color
  return chosen?.value === 'ok' ? 'subtle' : undefined
}

type MarkOption = { value: string; label: string; color: string }
const QA_MARKS: MarkOption[] = [
  { value: 'ok', label: 'OK', color: 'success' },
  { value: 'ko', label: 'KO', color: 'error' },
]
const ASK_MARKS: MarkOption[] = [{ value: 'ok', label: 'OK', color: 'success' }]
const DECISION_MARKS: MarkOption[] = [
  { value: 'ok', label: 'OK', color: 'success' },
  { value: 'ko', label: 'Corriger', color: 'warning' },
]

const PREFIX_LABEL: Record<string, string> = { qa: 'QA', ask: 'Demande', dec: 'Décision' }

/** Rows of items, each with its mark buttons and a « Note » that opens a labelled line in the prompt. */
function replyRows(
  $: EngineInterface,
  els: Elements,
  prefix: string,
  items: string[],
  options: MarkOption[],
  context: CardContext,
  offset = 0,
  details: (string | null)[] = [],
): RenderChildren {
  const { Box, Text, Markdown } = els
  return items.map((item, position) => {
    const index = offset + position
    const key = `${prefix}:${index}`
    const mark = context.marks[key]
    const chosen = options.find(option => option.value === mark)
    const label = `${PREFIX_LABEL[prefix] ?? prefix} ${index + 1} · ${truncate(item, 60)}`
    const detail = details[position] ?? null
    return (
      <Box key={`row-${context.messageId}-${key}`} flexDirection="column" gap="xs">
      <Box flexDirection="row" gap="sm" alignItems="center">
        {rowIndex(els, context, index, chosen)}
        <Box flexGrow={1} flexShrink={1} minWidth={0}>
          <Text wrap="wrap" color={rowColor(els, context, chosen)}>
            {item}
          </Text>
        </Box>
        {options.map(option =>
          markButton(els, context, `mark-${context.messageId}-${key}-${option.value}`, option.label, mark === option.value, TONE_OF_COLOR[option.color] ?? 'accent', () => {
            void markQa($, context.messageId, key, option.value)
            if (prefix === 'dec' && option.value === 'ko' && mark !== 'ko') void notePrompt($, `${label} — à corriger`)
          }),
        )}
        {noteButton($, els, key, label, context)}
      </Box>
      {detail !== null && (
        <Box paddingLeft={3}>
          <Markdown key={`row-detail-${context.messageId}-${key}`} text={detail} />
        </Box>
      )}
      </Box>
    )
  })
}

function sendButton($: EngineInterface, els: Elements, shape: MessageShape, context: CardContext): RenderChildren {
  const { Box, Text, Button } = els
  const count = answeredCount(context.marks)
  if (count === 0) return null
  const block = answersBlock(shape, context.marks)
  return (
    <Box key={`send-${context.messageId}`} flexDirection="column" gap="xs">
      <Box flexDirection="row" gap="sm" alignItems="center">
        <Button key={`send-button-${context.messageId}`} variant="primary" label={`Ajouter mes réponses au prompt (${count})`} onPress={() => void insertAnswers($, block)} />
      </Box>
      <Text size="caption" dimColor>
        Ajoutées à la fin du prompt dans un bloc encadré : ton texte est conservé, tu relis puis tu envoies.
      </Text>
    </Box>
  )
}

function chipsRow($: EngineInterface, e: Event, chips: Chip[]): RenderChildren {
  if (chips.length === 0) return null
  if (e.surface === 'desktop' || e.surface === 'vscode') {
    const { Svg } = $.ui.resolve(e)
    const width = Math.max(240, Math.min(640, Math.floor((e.viewport?.columns ?? 80) * 6)))
    const drawn = pills(
      chips.map(chip => ({ label: chip.text, tone: chip.tone === 'neutral' ? ('muted' as const) : chip.tone, hint: chip.text })),
      { maxWidth: width },
    )
    return <Svg key="figures" alt={chips.map(chip => chip.text).join(', ')} source={drawn.source} width={drawn.width} height={drawn.height} />
  }
  const { Text } = $.ui.resolve(e)
  return <Text dimColor>{chips.map(chip => chip.text).join(' · ')}</Text>
}

function basename(path: string): string {
  return path.split('/').pop() ?? path
}

function filesRow($: EngineInterface, els: Elements, files: { path: string; line: number | null }[], context: CardContext): RenderChildren {
  const { Box, Text, Button } = els
  if (files.length === 0) return null
  return (
    <Box key={`files-${context.messageId}`} flexDirection="row" gap="sm" alignItems="center" flexWrap="wrap">
      <Text size="caption" dimColor>
        Fichiers cités
      </Text>
      {files.map(file => {
        const fileKey = `file-${context.messageId}-${file.path}-${file.line ?? ''}`
        const button = (
          <Button
            key={fileKey}
            plain
            dimColor
            label={`${basename(file.path)}${file.line !== null ? `:${file.line}` : ''}`}
            onPress={() => void openFile($, context.root, context.home, file.path, file.line, context.changeNames)}
          />
        )
        const Svg = richSvg(els, context)
        if (Svg === null) return button
        return (
          <Box key={`${fileKey}-row`} flexDirection="row" alignItems="center" flexShrink={0}>
            <Svg key={`${fileKey}-icon`} alt="fichier" source={icon('file', { tone: 'muted', size: 12 })} width={12} height={12} />
            {button}
          </Box>
        )
      })}
    </Box>
  )
}

// ---------------------------------------------------------------- blocks

const SEVERITY_LABEL = { blocking: 'BLOQUANT', major: 'MAJEUR', minor: 'MINEUR' } as const
const SEVERITY_COLOR = { blocking: 'error', major: 'warning', minor: 'inactive' } as const
/** A severity as the desktop names it: in a soft chip of its tone, in sentence case. */
const SEVERITY_NAME = { blocking: 'Bloquant', major: 'Majeur', minor: 'Mineur' } as const
const SEVERITY_TONE: Record<Finding['severity'], Tone> = { blocking: 'danger', major: 'warning', minor: 'muted' }

function findingsTable($: EngineInterface, els: Elements, findings: Finding[], context: CardContext): RenderChildren {
  const { Box, Text, Button } = els
  if (findings.length === 0) return null
  const open = findings.filter(finding => finding.status === 'open')
  const counts = (['blocking', 'major', 'minor'] as const)
    .map(severity => {
      const n = findings.filter(finding => finding.severity === severity).length
      return n > 0 ? `${n} ${SEVERITY_LABEL[severity].toLowerCase()}${n > 1 ? 's' : ''}` : ''
    })
    .filter(part => part !== '')
    .join(' · ')
  return framed(
    els,
    `findings-${context.messageId}`,
    context,
    {
      icon: 'warning',
      title: `Constats · ${counts}`,
      meta: open.length < findings.length ? `${findings.length - open.length} traités` : undefined,
      tone: open.length > 0 ? 'danger' : 'muted',
    },
    (
      <Text size="caption" weight="semibold" dimColor>
        Constats · {counts}
        {open.length < findings.length ? ` · ${findings.length - open.length} traités` : ''}
      </Text>
    ),
    <Box flexDirection="column" gap="xs">
      {findings.map((finding, index) => (
        <Box key={`finding-${context.messageId}-${index}`} flexDirection="row" gap="sm" alignItems="center">
          {richSvg(els, context) !== null ? (
            finding.status === 'open' ? (
              <Box key={`finding-sev-${context.messageId}-${index}`} flexShrink={0} {...chip(GALET.deep[familyOf(SEVERITY_TONE[finding.severity])])}>
                <Text size="caption" weight="medium" color={GALET.text[familyOf(SEVERITY_TONE[finding.severity])]}>
                  {SEVERITY_NAME[finding.severity]}
                </Text>
              </Box>
            ) : (
              <Text size="caption" dimColor>
                {SEVERITY_NAME[finding.severity]}
              </Text>
            )
          ) : (
            <Text size="caption" weight="semibold" color={finding.status === 'open' ? SEVERITY_COLOR[finding.severity] : 'inactive'}>
              {SEVERITY_LABEL[finding.severity]}
            </Text>
          )}
          {finding.file !== null && (
            <Button
              key={`finding-file-${context.messageId}-${index}`}
              plain
              dimColor
              label={`${basename(finding.file)}${finding.line !== null ? `:${finding.line}` : ''}`}
              onPress={() => void openFile($, context.root, context.home, finding.file ?? '', finding.line, context.changeNames)}
            />
          )}
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text wrap="wrap" dimColor={finding.status !== 'open'} strikethrough={finding.status === 'fixed'}>
              {finding.problem}
            </Text>
          </Box>
          {finding.status === 'open' ? (
            <Button
              key={`finding-fix-${context.messageId}-${index}`}
              plain
              dimColor
              label="Corriger"
              onPress={() =>
                void addToPrompt(
                  $,
                  `Corrige ${SEVERITY_LABEL[finding.severity]} ${finding.file !== null ? `${finding.file}${finding.line !== null ? `:${finding.line}` : ''} ` : ''}— ${truncate(finding.problem, 120)}`,
                )
              }
            />
          ) : (
            <Text size="caption" color={finding.status === 'fixed' ? 'success' : 'inactive'}>
              {finding.status === 'fixed' ? 'corrigé' : 'reporté'}
            </Text>
          )}
        </Box>
      ))}
    </Box>,
    'xs',
  )
}

function commitCard($: EngineInterface, els: Elements, commit: CommitBlock, index: number, context: CardContext): RenderChildren {
  const { Box, Text, Button } = els
  const committed = context.recentCommits.find(entry => entry.subject === commit.subject)
  // Outside an OpenSpec project there is no change-id to scope a commit to: any scope is fine.
  const hasChanges = context.changeNames.length > 0
  const isScoped = !hasChanges || context.changeNames.includes(commit.scope)
  const hasBody = commit.body !== ''
  const isClean = isScoped && hasBody && !commit.hasCoAuthor
  const checks = [
    hasChanges ? `scope ${commit.scope} ${isScoped ? '✓' : '✗ (pas un change-id)'}` : `scope ${commit.scope}`,
    `corps ${hasBody ? '✓' : '✗'}`,
    commit.hasCoAuthor ? 'Co-Authored-By ✗' : 'sans trailer ✓',
  ].join(' · ')
  return framed(
    els,
    `commit-${context.messageId}-${index}`,
    context,
    {
      icon: 'commit',
      title: committed !== undefined ? `Commité · ${committed.hash}` : 'Commit prêt',
      meta: committed !== undefined ? undefined : `${commit.body.split('\n').length + 1} lignes`,
      tone: committed !== undefined || isClean ? 'ok' : 'warning',
      done: committed !== undefined,
    },
    (
      <Text size="caption" weight="semibold" color={committed !== undefined ? 'success' : undefined} dimColor={committed === undefined}>
        {committed !== undefined ? `Commité ✓ · ${committed.hash}` : `Commit prêt · ${commit.body.split('\n').length + 1} lignes`}
      </Text>
    ),
    <Box flexDirection="column" gap="xs">
      <Text mono weight="medium" wrap="truncate-end">
        {commit.subject}
      </Text>
      {committed === undefined && (
        <Text size="caption" color={isClean ? 'success' : 'warning'}>
          {checks}
        </Text>
      )}
      {committed === undefined && (
        <Box flexDirection="row" gap="sm">
          <Button key={`commit-copy-${context.messageId}-${index}`} variant="secondary" label="Copier le message" onPress={() => void copyText($, commit.text, 'Message de commit')} />
        </Box>
      )}
    </Box>,
    'xs',
  )
}

/** A question's options on the terminal: a letter button, the label, « ★ recommandé », the detail under it. */
function textOptions($: EngineInterface, els: Elements, question: Question, context: CardContext, selected: string | undefined): RenderChildren {
  const { Box, Text, Button, Markdown } = els
  const key = `q:${question.id}`
  return question.options.map(option => {
    const isSelected = selected === option.letter
    const frame = isSelected ? { borderStyle: 'round', borderColor: 'claude' } : option.isRecommended ? { borderStyle: 'round', borderColor: 'success' } : {}
    return (
      <Box key={`q-${context.messageId}-${question.id}-${option.letter}-row`} flexDirection="row" gap="sm" alignItems="flex-start" paddingX={1} {...frame}>
        <Button
          key={`q-${context.messageId}-${question.id}-${option.letter}`}
          variant={isSelected ? 'primary' : 'secondary'}
          label={option.letter}
          onPress={() => void markQa($, context.messageId, key, option.letter)}
        />
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0} gap="xs">
          <Box flexDirection="row" gap="sm" alignItems="center" flexWrap="wrap">
            <Text weight="semibold" wrap="wrap">
              {option.label}
            </Text>
            {option.isRecommended && (
              <Text size="caption" weight="semibold" color="success">
                ★ recommandé
              </Text>
            )}
          </Box>
          {option.detail !== '' && <Markdown key={`q-${context.messageId}-${question.id}-${option.letter}-detail`} text={option.detail} />}
        </Box>
      </Box>
    )
  })
}

/** An option's letter: a round button, grey, sage when recommended, ochre once chosen. */
const DISC = { plain: 'rgba(128,128,128,.20)', recommended: 'rgba(93,138,90,.55)', chosen: 'rgba(191,111,58,.55)' } as const

/**
 * A question's options on the desktop: each a tile (white on light, a veil on dark; sage when recommended, ochre
 * once chosen) with the letter in a round button, the label over its explanation. The letter and the label are the presses
 * that answer (a button holds one line, so the explanation cannot be one): under the pointer the whole tile
 * deepens and the label turns ochre, to say so.
 */
function pebbleOptions($: EngineInterface, els: Elements, Svg: SvgElement, question: Question, context: CardContext, selected: string | undefined): RenderChildren {
  const { Box, Text, Button } = els
  const key = `q:${question.id}`
  const mode = context.mode ?? 'auto'
  return question.options.map(option => {
    const isSelected = selected === option.letter
    const id = `q-${context.messageId}-${question.id}-${option.letter}`
    const fill = isSelected ? GALET.deep.ochre : option.isRecommended ? GALET.deep.sage : tileFill(mode)
    const hover = isSelected ? GALET.hover.ochre : option.isRecommended ? GALET.hover.sage : GALET.deep.ochre
    return (
      <Box
        key={`${id}-row`}
        flexDirection="row"
        gap="sm"
        alignItems="flex-start"
        borderStyle="round"
        borderColor={isSelected ? NATIVE.accentBorder : 'rgba(0,0,0,0)'}
        backgroundColor={fill}
        paddingX="md"
        paddingY="sm"
        hover={{ backgroundColor: hover }}
      >
        <Box flexShrink={0} {...chip(isSelected ? DISC.chosen : option.isRecommended ? DISC.recommended : DISC.plain, { pressable: true })}>
          <Button key={`${id}-letter`} plain label={option.letter} onPress={() => void markQa($, context.messageId, key, option.letter)} />
        </Box>
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
          <Box flexDirection="row" alignItems="center" gap="xs" flexWrap="wrap">
            <Button key={id} plain label={option.label} hover={{ color: NATIVE.accent }} onPress={() => void markQa($, context.messageId, key, option.letter)} />
            {option.isRecommended && (
              <Text size="caption" weight="medium" color={GALET.text.sage}>
                recommandé
              </Text>
            )}
          </Box>
          {option.detail !== '' && (
            <Box paddingLeft="xs">
              <Text size="footnote" dimColor wrap="wrap">
                {cleanMarkdown(option.detail)}
              </Text>
            </Box>
          )}
        </Box>
      </Box>
    )
  })
}

function questionCard($: EngineInterface, els: Elements, question: Question, context: CardContext): RenderChildren {
  const { Box, Text, Button, Markdown } = els
  const Svg = richSvg(els, context)
  const key = `q:${question.id}`
  const selected = context.marks[key]
  const recommended = question.options.find(option => option.isRecommended)
  const isRich = Svg !== null
  return framed(
    els,
    `q-${context.messageId}-${question.id}`,
    context,
    {
      icon: { badge: question.id },
      title: question.title,
      meta: selected !== undefined ? `→ ${SPECIAL_ANSWERS[selected] ?? selected}` : 'en attente',
      waiting: selected === undefined && context.isSettled !== true,
      pending: selected === undefined && context.isSettled === true,
    },
    (
      <Box flexDirection="row" gap="sm" alignItems="center">
        <Text weight="semibold" color="claude">
          {question.id}
        </Text>
        <Box flexGrow={1} flexShrink={1} minWidth={0}>
          <Text weight="semibold" wrap="wrap">
            {question.title}
          </Text>
        </Box>
        {selected !== undefined && (
          <Text size="caption" color="claude">
            → {SPECIAL_ANSWERS[selected] ?? selected}
          </Text>
        )}
      </Box>
    ),
    <Box flexDirection="column" gap="sm">
      {question.context !== '' && <Markdown key={`q-${context.messageId}-${question.id}-context`} text={question.context} />}
      {Svg !== null ? pebbleOptions($, els, Svg, question, context, selected) : textOptions($, els, question, context, selected)}
      {question.rationale !== null &&
        (isRich ? (
          <Text size="footnote" wrap="wrap" dimColor>
            <Text size="footnote" weight="medium" dimColor={false}>
              Recommandation ·{' '}
            </Text>
            {question.rationale.replace(/^\s*recommandation\s*[:·]\s*/i, '')}
          </Text>
        ) : (
          <Box borderStyle="quote" borderColor="success" paddingLeft={1}>
            <Text size="footnote" wrap="wrap">
              <Text size="footnote" weight="semibold" color="success">
                {recommended !== undefined ? `Pourquoi ${recommended.letter} · ` : 'Recommandation · '}
              </Text>
              {question.rationale}
            </Text>
          </Box>
        ))}
      <Box flexDirection="row" gap="sm" alignItems="center">
        {isRich ? (
          [
            markButton(els, context, `q-${context.messageId}-${question.id}-opinion`, 'Ton avis', selected === 'avis', 'accent', () => void markQa($, context.messageId, key, 'avis')),
            markButton(els, context, `q-${context.messageId}-${question.id}-simpler`, 'Plus simple', selected === 'simple', 'accent', () => void markQa($, context.messageId, key, 'simple')),
          ]
        ) : (
          [
            <Button key={`q-${context.messageId}-${question.id}-opinion`} plain dimColor={selected !== 'avis'} label="ton avis ?" onPress={() => void markQa($, context.messageId, key, 'avis')} />,
            <Button
              key={`q-${context.messageId}-${question.id}-simpler`}
              plain
              dimColor={selected !== 'simple'}
              label="plus simple, avec un exemple"
              onPress={() => void markQa($, context.messageId, key, 'simple')}
            />,
          ]
        )}
        {noteButton($, els, key, `${question.id} · ${question.title}`, context)}
      </Box>
    </Box>,
    'sm',
  )
}

/** Each kind of card by the icon that leads its title on the desktop, found from its key. */
const BLOCK_ICONS: [string, IconName][] = [
  ['qa-', 'qa'],
  ['decisions-', 'check'],
  ['picks-', 'flag'],
  ['infos-', 'next'],
  ['ask-', 'hand'],
  ['reserves-', 'warning'],
  ['brief-', 'report'],
]

/** A titled block with a one-line help under its title, so each part of a card says what it is for. */
function block(els: Elements, key: string, title: string, help: string | null, color: string, body: RenderChildren, context: CardContext, cardIcon?: IconName): RenderChildren {
  const { Text } = els
  const tone: Tone = color === 'warning' ? 'warning' : color === 'error' ? 'danger' : color === 'success' ? 'ok' : color === 'subtle' ? 'muted' : 'accent'
  const helpText =
    help !== null ? (
      <Text key={`${key}-help`} size="caption" dimColor wrap="wrap">
        {help}
      </Text>
    ) : null
  return framed(
    els,
    key,
    context,
    { icon: cardIcon ?? BLOCK_ICONS.find(([prefix]) => key.startsWith(prefix))?.[1] ?? (tone === 'warning' ? 'warning' : 'info'), title, tone },
    <Text size="caption" weight="semibold" color={color === 'subtle' ? undefined : color} dimColor={color === 'subtle'}>
      {title}
    </Text>,
    [helpText, body],
  )
}

/** A command or a snippet, with a button that copies it. */
function codeBlock($: EngineInterface, els: Elements, key: string, snippet: { language: string; code: string }): RenderChildren {
  const { Box, Code, Button } = els
  return (
    <Box key={key} flexDirection="column" gap="xs">
      <Code key={`${key}-code`} source={snippet.code} language={snippet.language === '' ? undefined : snippet.language} />
      <Box flexDirection="row">
        <Button key={`${key}-copy`} plain dimColor label="Copier" onPress={() => void copyText($, snippet.code, 'Commande')} />
      </Box>
    </Box>
  )
}

/**
 * Groups of blocks in the order they were written: a group's bold title and its lead, prose, code with its copy button.
 * Lists are drawn by `drawList`, which numbers its items from the offset it is given.
 */
function drawGroups(
  $: EngineInterface,
  els: Elements,
  key: string,
  groups: BlockGroup[],
  drawList: (items: ListItem[], offset: number, key: string) => RenderChildren,
  drawPicks?: (picks: Pick[], offset: number, key: string) => RenderChildren,
): RenderChildren {
  const { Box, Text, Markdown } = els
  let offset = 0
  let pickOffset = 0
  return groups.map((group, groupIndex) => {
    const groupKey = `${key}-g${groupIndex}`
    return (
      <Box key={groupKey} flexDirection="column" gap="xs">
        {group.title !== null && (
          <Text key={`${groupKey}-title`} weight="semibold" wrap="wrap">
            {group.title}
          </Text>
        )}
        {group.lead !== '' && <Markdown key={`${groupKey}-lead`} text={group.lead} />}
        {group.blocks.map((item: Block, blockIndex) => {
          const blockKey = `${groupKey}-b${blockIndex}`
          if (item.kind === 'prose') return <Markdown key={blockKey} text={item.text} />
          if (item.kind === 'code') return codeBlock($, els, blockKey, item.snippet)
          if (item.kind === 'table') {
            const picks = drawPicks !== undefined ? tablePicks(item) : null
            if (picks === null || drawPicks === undefined) return <Markdown key={blockKey} text={item.markdown} />
            const drawn = drawPicks(picks, pickOffset, blockKey)
            pickOffset += picks.length
            return drawn
          }
          // What Claude does itself is information: no button on it.
          if (isInfoGroup(group)) return <Markdown key={blockKey} text={item.items.map(listed => `- ${listed.text}`).join('\n')} />
          const drawn = drawList(item.items, offset, blockKey)
          offset += item.items.length
          return drawn
        })}
      </Box>
    )
  })
}

/** A numbered step: its text, then each command under it with its copy button. */
function stepRows($: EngineInterface, els: Elements, items: ListItem[], offset: number, key: string): RenderChildren {
  const { Box, Text, Markdown } = els
  return items.map((item, index) => (
    <Box key={`${key}-s${index}`} flexDirection="row" gap="sm">
      <Text size="caption" dimColor tabular>
        {offset + index + 1}.
      </Text>
      <Box flexDirection="column" gap="xs" flexGrow={1} flexShrink={1} minWidth={0}>
        <Markdown key={`${key}-s${index}-text`} text={item.text} />
        {item.code.map((snippet, codeIndex) => codeBlock($, els, `${key}-s${index}-c${codeIndex}`, snippet))}
      </Box>
    </Box>
  ))
}

/** One check: its title with OK / KO / note, then what to do and what to see. */
function checkRows($: EngineInterface, els: Elements, checks: QaCheck[], context: CardContext): RenderChildren {
  const { Box, Text, Button } = els
  return checks.map((check, index) => {
    const key = `qa:${index}`
    const mark = context.marks[key]
    const chosen = QA_MARKS.find(option => option.value === mark)
    const name = check.title ?? check.text
    const label = `QA ${index + 1} · ${truncate(name, 60)}`
    return (
      <Box key={`check-${context.messageId}-${index}`} flexDirection="column" gap="xs">
        <Box flexDirection="row" gap="sm" alignItems="center">
          {rowIndex(els, context, index, chosen)}
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text wrap="wrap" weight={check.title !== null ? 'semibold' : 'regular'} color={rowColor(els, context, chosen)}>
              {name}
            </Text>
          </Box>
          {QA_MARKS.map(option =>
            markButton(els, context, `mark-${context.messageId}-${key}-${option.value}`, option.label, mark === option.value, TONE_OF_COLOR[option.color] ?? 'accent', () => void markQa($, context.messageId, key, option.value)),
          )}
          {noteButton($, els, key, label, context)}
        </Box>
        {check.title !== null && check.action === null && check.text !== '' && (
          <Box paddingLeft={3}>
            <Text wrap="wrap" dimColor>
              {check.text}
            </Text>
          </Box>
        )}
        {check.action !== null && (
          <Box paddingLeft={3}>
            <Text wrap="wrap">
              <Text weight="semibold">Fais : </Text>
              {check.action}
            </Text>
          </Box>
        )}
        {check.expected !== null && (
          <Box paddingLeft={3}>
            <Text wrap="wrap">
              <Text weight="semibold" color="success">
                Attendu :{' '}
              </Text>
              {check.expected}
            </Text>
          </Box>
        )}
      </Box>
    )
  })
}

/** A check to redo: its number and name with OK / KO / note, Claude's own verdict to confirm, then what to do. */
function followUpRows($: EngineInterface, els: Elements, followUps: QaFollowUp[], context: CardContext): RenderChildren {
  const { Box, Text, Button } = els
  return followUps.map((followUp, index) => {
    const key = `qa:${index}`
    const mark = context.marks[key]
    const chosen = QA_MARKS.find(option => option.value === mark)
    return (
      <Box key={`follow-${context.messageId}-${index}`} flexDirection="column" gap="xs">
        <Box flexDirection="row" gap="sm" alignItems="center">
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text wrap="wrap" weight="semibold" color={rowColor(els, context, chosen)}>
              {followUp.title}
            </Text>
          </Box>
          {QA_MARKS.map(option =>
            markButton(els, context, `mark-${context.messageId}-${key}-${option.value}`, option.label, mark === option.value, TONE_OF_COLOR[option.color] ?? 'accent', () => void markQa($, context.messageId, key, option.value)),
          )}
          {noteButton($, els, key, followUp.title, context)}
        </Box>
        {followUp.isClaimedOk && mark === undefined && (
          <Box paddingLeft={3}>
            <Text size="caption" color="warning" wrap="wrap">
              Claude la juge OK : à toi de confirmer (OK) ou non (KO).
            </Text>
          </Box>
        )}
        {context.isCompact !== true && followUp.action !== null && (
          <Box paddingLeft={3}>
            <Text wrap="wrap">
              <Text weight="semibold">Fais : </Text>
              {followUp.action}
            </Text>
          </Box>
        )}
        {context.isCompact !== true && followUp.expected !== null && (
          <Box paddingLeft={3}>
            <Text wrap="wrap">
              <Text weight="semibold" color="success">
                Attendu :{' '}
              </Text>
              {followUp.expected}
            </Text>
          </Box>
        )}
        {context.isCompact !== true && followUp.steps.length > 0 && <Box paddingLeft={3} flexDirection="column" gap="xs">{stepRows($, els, followUp.steps, 0, `follow-${context.messageId}-${index}-steps`)}</Box>}
      </Box>
    )
  })
}

/** A check's short name: its bold title, else its first words. */
function checkName(check: QaCheck): string {
  if (check.title !== null) return check.title
  const words = check.text.split(/\s+/)
  return words.length > 10 ? `${words.slice(0, 10).join(' ')}…` : check.text
}

/** The checks as names only, under their intertitles, with OK / KO / note: the message above holds how to do each. */
function compactCheckRows($: EngineInterface, els: Elements, checks: QaCheck[], context: CardContext): RenderChildren {
  const { Box, Text, Button } = els
  return checks.map((check, index) => {
    const key = `qa:${index}`
    const mark = context.marks[key]
    const chosen = QA_MARKS.find(option => option.value === mark)
    const name = checkName(check)
    const isNewPart = check.part !== undefined && check.part !== checks[index - 1]?.part
    return (
      <Box key={`check-${context.messageId}-${index}`} flexDirection="column" gap="xs">
        {isNewPart && (
          <Text size="caption" weight="semibold" dimColor wrap="wrap">
            {check.part}
          </Text>
        )}
        <Box flexDirection="row" gap="sm" alignItems="center">
          {rowIndex(els, context, index, chosen)}
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text wrap="truncate-end" color={rowColor(els, context, chosen)}>
              {name}
            </Text>
          </Box>
          {QA_MARKS.map(option =>
            markButton(els, context, `mark-${context.messageId}-${key}-${option.value}`, option.label, mark === option.value, TONE_OF_COLOR[option.color] ?? 'accent', () => void markQa($, context.messageId, key, option.value)),
          )}
          {noteButton($, els, key, `QA ${index + 1} · ${truncate(name, 60)}`, context)}
        </Box>
      </Box>
    )
  })
}

function qaBlock($: EngineInterface, els: Elements, shape: MessageShape, context: CardContext): RenderChildren {
  const { Markdown, Text } = els
  const plan = shape.qaPlan
  if (context.isCompact === true && plan.checks.length > 0) {
    const ok = plan.checks.filter((_, index) => context.marks[`qa:${index}`] === 'ok').length
    const ko = plan.checks.filter((_, index) => context.marks[`qa:${index}`] === 'ko').length
    return block(
      els,
      `qa-${context.messageId}`,
      `À tester de ton côté · ${ok}/${plan.checks.length} OK${ko > 0 ? ` · ${ko} KO` : ''}`,
      'Le détail de chaque vérification est dans le message ci-dessus : marque ici ce que tu vois.',
      ko > 0 ? 'error' : 'success',
      compactCheckRows($, els, plan.checks, context),
      context,
    )
  }
  if (plan.checks.length === 0 && shape.followUps.length > 0) {
    const ok = shape.followUps.filter((_, index) => context.marks[`qa:${index}`] === 'ok').length
    const ko = shape.followUps.filter((_, index) => context.marks[`qa:${index}`] === 'ko').length
    return block(
      els,
      `qa-${context.messageId}`,
      `QA à refaire · ${ok}/${shape.followUps.length} OK${ko > 0 ? ` · ${ko} KO` : ''}`,
      'Les vérifications que Claude reprend après tes retours. Son message est au-dessus, tel quel ; marque ici chacune selon ce que tu vois.',
      ko > 0 ? 'error' : 'success',
      followUpRows($, els, shape.followUps, context),
      context,
    )
  }
  if (plan.checks.length === 0) return null
  const ok = plan.checks.filter((_, index) => context.marks[`qa:${index}`] === 'ok').length
  const ko = plan.checks.filter((_, index) => context.marks[`qa:${index}`] === 'ko').length
  return block(
    els,
    `qa-${context.messageId}`,
    `À tester de ton côté · ${ok}/${plan.checks.length} OK${ko > 0 ? ` · ${ko} KO` : ''}`,
    'Prépare, puis fais chaque vérification : OK si tu vois ce qui est attendu, KO sinon ; « Note » ouvre une ligne dans le prompt pour décrire ce que tu vois.',
    ko > 0 ? 'error' : 'success',
    [
      plan.preparation.length > 0 ? (
        <Text key={`qa-prep-title-${context.messageId}`} size="caption" weight="semibold" dimColor>
          Préparation
        </Text>
      ) : null,
      drawGroups($, els, `qa-prep-${context.messageId}`, plan.preparation.map(group => ({ ...group, title: null })), (items, offset, key) => stepRows($, els, items, offset, key)),
      plan.intro !== '' ? <Markdown key={`qa-intro-${context.messageId}`} text={plan.intro} /> : null,
      <Text key={`qa-checks-title-${context.messageId}`} size="caption" weight="semibold" dimColor>
        Vérifications
      </Text>,
      checkRows($, els, plan.checks, context),
    ],
    context,
  )
}

function decisionsBlock($: EngineInterface, els: Elements, shape: MessageShape, prose: string, context: CardContext): RenderChildren {
  const { Markdown } = els
  if (shape.decisions.length === 0) return null
  return block(
    els,
    `decisions-${context.messageId}`,
    shape.decisionsTitle,
    'Valide chacune, ou « Corriger » pour dire quoi changer.',
    'warning',
    [
      prose !== '' && context.isCompact !== true ? <Markdown key={`decisions-prose-${context.messageId}`} text={prose} /> : null,
      replyRows($, els, 'dec', shape.decisions, DECISION_MARKS, context, 0, context.isCompact === true ? [] : shape.decisionDetails),
    ],
    context,
  )
}

const PICK_MARKS: MarkOption[] = [
  { value: 'ok', label: 'Reco OK', color: 'success' },
  { value: 'ko', label: 'Autre choix', color: 'warning' },
]

/** A choice: the point, Claude's recommendation under it, the details folded into it; « Reco OK », or « Autre choix » that opens a line in the prompt. */
function pickRows($: EngineInterface, els: Elements, picks: Pick[], offset: number, context: CardContext): RenderChildren {
  const { Box, Text, Button } = els
  return picks.map((pick, position) => {
    const index = offset + position
    const key = `pick:${index}`
    const mark = context.marks[key]
    const chosen = PICK_MARKS.find(option => option.value === mark)
    const label = `À trancher ${index + 1} · ${truncate(pick.label, 60)}`
    return (
      <Box key={`pick-${context.messageId}-${index}`} flexDirection="column" gap="xs">
        <Box flexDirection="row" gap="sm" alignItems="center">
          {rowIndex(els, context, index, chosen)}
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text wrap="wrap" weight="semibold" color={rowColor(els, context, chosen)}>
              {pick.label}
            </Text>
          </Box>
          {PICK_MARKS.map(option =>
            markButton(els, context, `mark-${context.messageId}-${key}-${option.value}`, option.label, mark === option.value, TONE_OF_COLOR[option.color] ?? 'accent', () => {
              void markQa($, context.messageId, key, option.value)
              if (option.value === 'ko' && mark !== 'ko') void notePrompt($, `${label} — autre choix`)
            }),
          )}
          {noteButton($, els, key, label, context)}
        </Box>
        {pick.reco !== null && (
          <Box paddingLeft={3}>
            {richSvg(els, context) !== null ? (
              <Text size="footnote" wrap="wrap" dimColor>
                <Text size="footnote" weight="medium" color={GALET.text.sage}>
                  Reco :{' '}
                </Text>
                {pick.reco}
              </Text>
            ) : (
              <Text wrap="wrap">
                <Text weight="semibold" color="success">
                  Reco :{' '}
                </Text>
                {pick.reco}
              </Text>
            )}
          </Box>
        )}
        {(context.isCompact === true ? [] : pick.details).map((detail, detailIndex) => (
          <Box key={`pick-${context.messageId}-${index}-d${detailIndex}`} paddingLeft={3}>
            <Text wrap="wrap" dimColor>
              · {detail}
            </Text>
          </Box>
        ))}
      </Box>
    )
  })
}

/** The choices of a cockpit block, in their own card (a « Reco » table is drawn where it stands, in « Ce que j'attends de toi »). */
function picksBlock($: EngineInterface, els: Elements, shape: MessageShape, context: CardContext): RenderChildren {
  if (!shape.hasCockpitBlock || shape.picks.length === 0) return null
  return block(
    els,
    `picks-${context.messageId}`,
    'À trancher',
    '« Reco OK » pour suivre la recommandation, « Autre choix » pour dire ce que tu préfères.',
    'warning',
    pickRows($, els, shape.picks, 0, context),
    context,
  )
}

/** What Claude does next without the user's decision: information, no button. */
function infosBlock(els: Elements, shape: MessageShape, context: CardContext): RenderChildren {
  const { Box, Text } = els
  if (shape.infos.length === 0) return null
  return block(
    els,
    `infos-${context.messageId}`,
    'Ce que je fais ensuite',
    'Sans décision de ta part : pour information.',
    'subtle',
    shape.infos.map((info, index) => (
      <Box key={`info-${context.messageId}-${index}`} flexDirection="column">
        <Text wrap="wrap">· {info.text}</Text>
        {info.details.map((detail, detailIndex) => (
          <Box key={`info-${context.messageId}-${index}-d${detailIndex}`} paddingLeft={3}>
            <Text wrap="wrap" dimColor>
              · {detail}
            </Text>
          </Box>
        ))}
      </Box>
    )),
    context,
  )
}

/** « Ce que j'attends de toi » (or « Ce qui reste à toi »…) in the order written: OK and note on each ask, its sub-points under it. */
function askBlock($: EngineInterface, els: Elements, shape: MessageShape, context: CardContext): RenderChildren {
  if (shape.askGroups.length === 0) return null
  if (context.isCompact === true) {
    // The text is above: only what to mark, the asks and the choices of a « Reco » table.
    const asks = shape.askGroups.filter(group => !isInfoGroup(group)).flatMap(group => group.blocks.flatMap(item => (item.kind === 'list' ? item.items : [])))
    const tablePicked = shape.hasCockpitBlock ? [] : shape.askGroups.flatMap(group => group.blocks.flatMap(item => tablePicks(item) ?? []))
    if (asks.length === 0 && tablePicked.length === 0) return null
    return block(els, `ask-${context.messageId}`, "Ce que j'attends de toi", 'Le détail est dans le message ci-dessus : marque ici ce qui est fait.', 'claude', [
      tablePicked.length > 0 ? pickRows($, els, tablePicked, 0, context) : null,
      replyRows($, els, 'ask', asks.map(itemLine), ASK_MARKS, context),
    ], context)
  }
  return block(
    els,
    `ask-${context.messageId}`,
    "Ce que j'attends de toi",
    shape.asks.length > 0 || (!shape.hasCockpitBlock && shape.picks.length > 0)
      ? 'Marque OK ce qui est fait, « Reco OK » si tu suis une recommandation ; « Note » pour répondre en détail dans le prompt.'
      : null,
    'claude',
    drawGroups(
      $,
      els,
      `ask-${context.messageId}`,
      shape.askGroups,
      (items, offset) => replyRows($, els, 'ask', items.map(itemLine), ASK_MARKS, context, offset, items.map(itemDetail)),
      shape.hasCockpitBlock ? undefined : (picks, offset) => pickRows($, els, picks, offset, context),
    ),
    context,
  )
}

function handoffBlock($: EngineInterface, els: Elements, shape: MessageShape, context: CardContext): RenderChildren {
  const { Box, Text, Button } = els
  if (shape.phrase === null) return null
  const phrase = shape.phrase
  return (
    <Box key={`handoff-${context.messageId}`} flexDirection="row" gap="sm" alignItems="center" {...(richSvg(els, context) !== null ? surface('stone') : { borderStyle: 'round', borderColor: 'subtle' })} paddingX="md" paddingY="sm">
      <Box flexGrow={1} flexShrink={1} minWidth={0}>
        <Text size="footnote" dimColor wrap="truncate-end">
          {phrase}
        </Text>
      </Box>
      <Button key={`handoff-copy-${context.messageId}`} label="Copier la reprise" onPress={() => void copyText($, phrase, 'Phrase de reprise')} />
    </Box>
  )
}

// ---------------------------------------------------------------- the four renderings

/** Questions: the rest of the text as the engine draws it, then one card per question. */
export function renderQuestions($: EngineInterface, e: Event, shape: MessageShape, cardContext: CardContext, rest: RenderChildren) {
  const context = { ...cardContext, isCompact: true }
  const els = $.ui.resolve(e)
  const { Box, Text } = els
  return (
    <Box flexDirection="column" gap="sm">
      {rest}
      {shape.questions.map(question => questionCard($, els, question, context))}
      {picksBlock($, els, shape, context)}
      {decisionsBlock($, els, shape, '', context)}
      {findingsTable($, els, shape.findings, context)}
      {qaBlock($, els, shape, context)}
      {shape.commits.map((commit, index) => commitCard($, els, commit, index, context))}
      {askBlock($, els, shape, context)}
      {infosBlock(els, shape, context)}
      {filesRow($, els, shape.files, context)}
      {handoffBlock($, els, shape, context)}
      {sendButton($, els, shape, context)}
      {shape.questions.length > 1 && answeredCount(context.marks) === 0 && (
        <Text size="caption" dimColor>
          Choisis une option par question (ou « ton avis ? »), puis ajoute tes réponses au prompt d’un coup.
        </Text>
      )}
    </Box>
  )
}

/** A report in reading order: what it is about, what was done (folded), what may go wrong, what to decide, what to test, what to hand over, what Claude needs. */
export function renderReport($: EngineInterface, e: Event, shape: MessageShape, context: CardContext, full: RenderChildren) {
  const els = $.ui.resolve(e)
  const { Box, Text, Button, Markdown } = els
  const report = shape.report
  if (report === null) return <Box>{full}</Box>
  const section = (kind: string) => report.sections.find(candidate => candidate.kind === kind)
  const reserves = section('reserves')
  const decisions = section('decisions')
  const done = ['done', 'fixed', 'tests'].map(kind => section(kind)).filter((candidate): candidate is NonNullable<typeof candidate> => candidate !== undefined)
  const preview = (body: string) => {
    const items = listItems(body)
    const first = items[0] ?? sectionProse(body).split('\n')[0] ?? ''
    return `${items.length > 1 ? `${items.length} points · ` : ''}${truncate(first, 70)}`
  }
  return (
    <Box flexDirection="column" gap="sm" {...(richSvg(els, context) !== null ? surface('stone') : { borderStyle: 'round', borderColor: 'subtle' })} paddingX="md" paddingY={richSvg(els, context) !== null ? 'md' : 'sm'}>
      <Box flexDirection="row" gap="sm" alignItems="center">
        {(() => {
          const Svg = richSvg(els, context)
          return Svg === null ? null : <Svg key={`report-icon-${context.messageId}`} alt="Rapport" source={icon('report', { tone: 'muted', size: 15 })} width={15} height={15} />
        })()}
        <Box flexGrow={1} flexShrink={1} minWidth={0}>
          <Text weight="semibold" wrap="wrap">
            {report.title}
          </Text>
        </Box>
        <Text size="caption" dimColor>
          Rapport
        </Text>
      </Box>
      {report.intro !== '' && <Markdown key={`intro-${context.messageId}`} text={report.intro} />}
      {chipsRow($, e, shape.chips)}

      {done.length > 0 && (
        <Box key={`done-${context.messageId}`} flexDirection="column" gap="xs">
          {richSvg(els, context) === null && (
            <Text size="caption" weight="semibold" dimColor>
              Ce qui a été fait
            </Text>
          )}
          {done.map(part => {
            const isOpen = context.sectionsOpen[part.kind] === true
            return (
              <Box key={`section-${context.messageId}-${part.kind}`} flexDirection="column" gap="xs">
                <Button key={`section-toggle-${context.messageId}-${part.kind}`} plain dimColor onPress={() => void toggleReportSection($, context.messageId, part.kind)}>
                  <Text size="footnote" weight="semibold">
                    {isOpen ? '▾' : '▸'} {part.title}
                  </Text>
                  {!isOpen && (
                    <Text size="footnote" dimColor>
                      {'  '}
                      {preview(part.body)}
                    </Text>
                  )}
                </Button>
                {isOpen && <Markdown key={`section-text-${context.messageId}-${part.kind}`} text={part.body} />}
                {part.kind === 'fixed' && findingsTable($, els, shape.findings, context)}
              </Box>
            )
          })}
        </Box>
      )}
      {done.every(part => part.kind !== 'fixed') && findingsTable($, els, shape.findings, context)}

      {reserves !== undefined &&
        block(els, `reserves-${context.messageId}`, reserves.title, 'Ce qui peut encore coincer : à garder en tête.', 'warning', <Markdown key={`reserves-text-${context.messageId}`} text={reserves.body} />, context)}

      {decisionsBlock($, els, shape, decisions !== undefined ? sectionProse(decisions.body) : '', context)}
      {shape.questions.map(question => questionCard($, els, question, context))}
      {qaBlock($, els, shape, context)}
      {shape.commits.map((commit, index) => commitCard($, els, commit, index, context))}
      {handoffBlock($, els, shape, context)}

      {picksBlock($, els, shape, context)}
      {askBlock($, els, shape, context)}
      {infosBlock(els, shape, context)}

      {filesRow($, els, shape.files, context)}
      {sendButton($, els, shape, context)}
      <Button key={`report-toggle-${context.messageId}`} plain dimColor onPress={() => context.onToggle()}>
        <Text size="caption" dimColor>
          {context.isOpen ? '▾ Masquer le texte complet' : '▸ Texte complet, tel que Claude l’a écrit'}
        </Text>
      </Button>
      {context.isOpen && full}
    </Box>
  )
}

/** Prose with deliverables (findings, commit, QA, decisions, handoff): the text, then the cards. */
export function renderDeliverables($: EngineInterface, e: Event, shape: MessageShape, cardContext: CardContext, full: RenderChildren) {
  const context = { ...cardContext, isCompact: true }
  const els = $.ui.resolve(e)
  const { Box } = els
  return (
    <Box flexDirection="column" gap="sm">
      {full}
      {picksBlock($, els, shape, context)}
      {decisionsBlock($, els, shape, '', context)}
      {findingsTable($, els, shape.findings, context)}
      {qaBlock($, els, shape, context)}
      {shape.commits.map((commit, index) => commitCard($, els, commit, index, context))}
      {askBlock($, els, shape, context)}
      {infosBlock(els, shape, context)}
      {filesRow($, els, shape.files, context)}
      {handoffBlock($, els, shape, context)}
      {sendButton($, els, shape, context)}
    </Box>
  )
}

/** A long plain message: the text, and a three-bullet summary on demand. */
export function renderLong($: EngineInterface, e: Event, context: CardContext, text: string, full: RenderChildren) {
  const els = $.ui.resolve(e)
  const { Box, Text, Button, Markdown } = els
  return (
    <Box flexDirection="column" gap="sm">
      {context.brief !== null &&
        block(
          els,
          `brief-${context.messageId}`,
          'En bref',
          null,
          'claude',
          context.brief === '…' ? <Text dimColor>Résumé en cours…</Text> : <Markdown key={`brief-text-${context.messageId}`} text={context.brief} />,
          context,
        )}
      {full}
      {filesRow($, els, fileRefs(text), context)}
      {context.brief === null && (
        <Box flexDirection="row" justifyContent="flex-end">
          <Button key={`brief-${context.messageId}-button`} plain dimColor label="En bref" onPress={() => void summarize($, context.messageId, text)} />
        </Box>
      )}
    </Box>
  )
}
