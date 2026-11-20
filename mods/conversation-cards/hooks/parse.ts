// Pure parsers: the shapes of Claude's own messages (questions, reports, commit blocks, findings, QA,
// the cockpit block).

import { cleanMarkdown, truncate } from './shared/format'
import { commitBlocks } from './shared/commits'
import type { Severities } from './shared/workflows'

export { type CommitBlock, commitBlocks } from './shared/commits'

export function emptySeverities(): Severities {
  return { blocking: 0, major: 0, minor: 0 }
}

export function severityOf(label: string): keyof Severities | null {
  const upper = label.toUpperCase()
  if (/BLOQUANT|BLOCKING|BLOCKER/.test(upper)) return 'blocking'
  if (/MAJEUR|MAJOR/.test(upper)) return 'major'
  if (/MINEUR|MINOR/.test(upper)) return 'minor'
  return null
}

export type QuestionOption = { letter: string; label: string; detail: string; isRecommended: boolean }

export type Question = { id: string; title: string; context: string; options: QuestionOption[]; rationale: string | null }

const QUESTION_HEADING = /^#{2,4}\s*\**\s*((?:Q|D|T)\d+|Question\s+\d+)\s*\**\s*[·.:—–-]\s*(.+?)\s*\**\s*$/

const OPTION_LINE = /^\s{0,1}(?:[-*]\s+|\/\/\s*)?\**([A-E])\**\s*[·.:—–)-]\s+(.+)$/

const RECOMMENDED = /\s*\((?:recommandé|recommended|reco)\)\s*|\s*\*\*recommandé\*\*\s*/i

const RATIONALE = /^\s*(?:→\s*)?\**\s*(?:recommandation|je recommande|je penche|ma reco|reco\s*:)/i

function splitOption(body: string): { label: string; detail: string } {
  const clean = body.replace(RECOMMENDED, ' ').trim()
  const separator = /\s+[—–]\s+|\s*:\s+/.exec(clean)
  if (separator === null || separator.index < 3) return { label: cleanMarkdown(clean), detail: '' }
  return { label: cleanMarkdown(clean.slice(0, separator.index)), detail: clean.slice(separator.index + separator[0].length).trim() }
}

/** Questions written as `### Q1 · Title`, options `- A · label — explanation`, a recommendation line. Nothing is cut. */
export function parseQuestions(text: string): Question[] {
  const questions: Question[] = []
  let current: Question | undefined
  let contextLines: string[] = []
  let rationaleLines: string[] = []
  let lastOption: QuestionOption | undefined
  const close = () => {
    if (current === undefined) return
    current.context = contextLines.join('\n').trim()
    current.rationale = rationaleLines.length > 0 ? cleanMarkdown(rationaleLines.join(' ')) : null
    const pick = /(?:recommande|penche pour|reco(?:mmandation)?\s*:?)\s*\**\s*(?:l'option\s+|option\s+)?\**([A-E])\b/i.exec(rationaleLines.join(' ') || current.context)
    if (pick !== null && !current.options.some(option => option.isRecommended)) {
      for (const option of current.options) option.isRecommended = option.letter === pick[1]
    }
    for (const option of current.options) option.detail = option.detail.trim()
    questions.push(current)
  }
  for (const line of text.split('\n')) {
    const heading = QUESTION_HEADING.exec(line)
    if (heading !== null) {
      close()
      const raw = heading[1] ?? ''
      const id = /^Question/i.test(raw) ? `Q${raw.replace(/\D/g, '')}` : raw.toUpperCase()
      current = { id, title: cleanMarkdown(heading[2] ?? ''), context: '', options: [], rationale: null }
      contextLines = []
      rationaleLines = []
      lastOption = undefined
      continue
    }
    if (current === undefined) continue
    if (/^#{1,4}\s/.test(line)) {
      close()
      current = undefined
      continue
    }
    const option = OPTION_LINE.exec(line)
    if (option !== null) {
      const body = option[2] ?? ''
      const { label, detail } = splitOption(body)
      lastOption = { letter: option[1] ?? '', label, detail, isRecommended: RECOMMENDED.test(body) }
      current.options.push(lastOption)
    } else if (RATIONALE.test(line)) {
      rationaleLines.push(line)
      lastOption = undefined
    } else if (lastOption !== undefined && /^\s{2,}\S/.test(line)) {
      lastOption.detail += `\n${line.replace(/^\s{2,}/, '')}`
    } else if (line.trim() === '') {
      lastOption = undefined
      contextLines.push(line)
    } else if (current.options.length === 0) {
      contextLines.push(line)
    } else {
      rationaleLines.push(line)
    }
  }
  close()
  return questions
}

/** Removes the question sections from a message, for the engine to draw the rest. */
export function withoutQuestions(text: string): string {
  const out: string[] = []
  let isSkipping = false
  for (const line of text.split('\n')) {
    if (QUESTION_HEADING.test(line)) {
      isSkipping = true
      continue
    }
    if (isSkipping && /^#{1,4}\s/.test(line)) isSkipping = false
    if (!isSkipping) out.push(line)
  }
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

export type ReportSection = { kind: string; title: string; body: string }

export type Report = { title: string; intro: string; sections: ReportSection[]; ask: string | null; qa: string[] }

/** Titles of what Claude settled alone and the user may contest: « Décisions », « Mes lectures des tâches (conteste si tu veux) »… */
export const CONFIRM_TITLE = /^décisions|mes lectures|lectures des tâches|^mes choix|^hypothèses|à confirmer|à valider|conteste/i

/** Titles of what the user is asked to do: « Ce que j'attends de toi », « Ce qui reste à toi », « Pour toi »… */
export const ASK_TITLE = /ce que j['’]attends de toi|ce qui reste à toi|^à toi\b|^ton tour|^pour toi\b|ce que je te demande|^tes actions/i

const SECTION_KINDS: [string, RegExp][] = [
  ['done', /^fait\b|ce qui a été fait/i],
  ['decisions', CONFIRM_TITLE],
  ['fixed', /^trouvé/i],
  ['reserves', /^réserves|^risques/i],
  ['tests', /^tests\b|^chiffres|^vérification/i],
  ['ask', ASK_TITLE],
  ['qa', /^qa\b|ce que tu dois voir|qa visuelle/i],
]

function headingTitle(line: string): string | null {
  const match = /^#{1,3}\s+(?:\d+\.\s*)?(.+?)\s*$/.exec(line)
  return match === null ? null : cleanMarkdown(match[1] ?? '')
}

/** A report: at least three of the fixed sections (Fait, Trouvé et corrigé, Réserves, Tests, Ce que j'attends de toi…). */
export function parseReport(text: string): Report | null {
  const lines = text.split('\n')
  const sections: ReportSection[] = []
  let title = ''
  let intro = ''
  let current: ReportSection | undefined
  for (const line of lines) {
    // A question opens its own block: it never belongs to the section above it.
    if (QUESTION_HEADING.test(line)) {
      current = undefined
      continue
    }
    const heading = headingTitle(line)
    if (heading !== null) {
      const kind = SECTION_KINDS.find(([, pattern]) => pattern.test(heading))?.[0]
      if (kind !== undefined) {
        current = { kind, title: heading, body: '' }
        sections.push(current)
        continue
      }
      if (sections.length === 0 && title === '') {
        title = heading
        continue
      }
    }
    if (current !== undefined) current.body += `${line}\n`
    else if (sections.length === 0 && heading === null) intro += `${line}\n`
  }
  const known = new Set(sections.map(section => section.kind))
  if (known.size < 3) return null
  for (const section of sections) section.body = section.body.trim()
  const qaSection = sections.find(section => section.kind === 'qa')
  return {
    title: title || truncate(cleanMarkdown(lines.find(line => line.trim() !== '') ?? 'Rapport'), 80),
    intro: intro.trim(),
    sections,
    ask: sections.find(section => section.kind === 'ask')?.body ?? null,
    qa: qaSection === undefined ? [] : listItems(qaSection.body),
  }
}

export function listItems(markdown: string): string[] {
  return markdown
    .split('\n')
    .map(line => /^\s*(?:[-*]|\d+\.)\s+(?:\[[ xX]\]\s*)?(.+)$/.exec(line)?.[1])
    .filter((item): item is string => item !== undefined && item.trim() !== '')
    .map(item => cleanMarkdown(item))
}

/** A `## QA` (or « Ce que tu dois voir ») checklist anywhere in a message. */
export function qaChecklist(text: string): string[] {
  const lines = text.split('\n')
  const start = lines.findIndex(line => {
    const heading = headingTitle(line)
    return heading !== null && /^qa\b|ce que tu dois voir|qa visuelle/i.test(heading)
  })
  if (start === -1) return []
  const rest = lines.slice(start + 1)
  const end = rest.findIndex(line => /^#{1,3}\s/.test(line))
  return listItems((end === -1 ? rest : rest.slice(0, end)).join('\n'))
}

export type CodeSnippet = { language: string; code: string }

/** A list item: its text (continuation lines kept, one per line), the code blocks written under it, and whether it is numbered. */
export type ListItem = { text: string; code: CodeSnippet[]; isNumbered: boolean }

export type Block =
  | { kind: 'prose'; text: string }
  | { kind: 'code'; snippet: CodeSnippet }
  | { kind: 'list'; items: ListItem[] }
  | { kind: 'table'; headers: string[]; rows: string[][]; markdown: string }
/** A run of blocks under one bold lead line (`**Checklist** : …`), or the blocks before the first one (title null). */
export type BlockGroup = { title: string | null; lead: string; blocks: Block[] }

const LIST_LINE = /^(\s*)([-*]|\d+\.)\s+(?:\[[ xX]\]\s*)?(.*)$/
const FENCE = /^(\s*)```\s*([\w-]*)\s*$/
/** A paragraph opening with a bold label, then a colon, a comma or nothing: `**Checklist** : ouvre DevTools`. */
const GROUP_LEAD = /^\*\*([^*]{2,60}?)\*\*\s*(?:[:,]\s*(.*)|(\([^)]*\))\s*:?|)$/
/** A line in italics alone, an intertitle: `*Partie 1 — sur l'iPhone seul*`. */
const ITALIC_TITLE = /^(?:\*([^*\s][^*]{1,100}[^*\s])\*|_([^_\s][^_]{1,100}[^_\s])_)\s*:?$/

/** A section's markdown as groups of blocks in the order written: prose, code, lists (with what sits under each item). */
export function sectionGroups(markdown: string): BlockGroup[] {
  const groups: BlockGroup[] = [{ title: null, lead: '', blocks: [] }]
  const lines = markdown.split('\n')
  let prose: string[] = []
  let list: ListItem[] | null = null
  const group = () => groups[groups.length - 1] as BlockGroup
  const flushProse = () => {
    const text = prose.join('\n').trim()
    if (text !== '') group().blocks.push({ kind: 'prose', text })
    prose = []
  }
  const flushList = () => {
    if (list !== null && list.length > 0) group().blocks.push({ kind: 'list', items: list })
    list = null
  }
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index] ?? ''
    const fence = FENCE.exec(line)
    if (fence !== null) {
      const body: string[] = []
      index++
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index] ?? '')) body.push(lines[index++] ?? '')
      const indent = (fence[1] ?? '').length
      const snippet = { language: fence[2] ?? '', code: body.map(text => text.slice(Math.min(indent, text.length - text.trimStart().length))).join('\n') }
      const current = list === null ? undefined : (list as ListItem[])[(list as ListItem[]).length - 1]
      if (indent >= 2 && current !== undefined) {
        current.code.push(snippet)
      } else {
        flushProse()
        flushList()
        group().blocks.push({ kind: 'code', snippet })
      }
      continue
    }
    if (line.trim().startsWith('|')) {
      flushProse()
      flushList()
      const tableLines: string[] = []
      while (index < lines.length && (lines[index] ?? '').trim().startsWith('|')) tableLines.push((lines[index++] ?? '').trim())
      index--
      const cells = (row: string) => row.replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim())
      const [head = '', , ...body] = tableLines
      const isSeparated = /^\|?\s*:?-{2,}/.test(tableLines[1] ?? '')
      group().blocks.push({
        kind: 'table',
        headers: cells(head),
        rows: (isSeparated ? body : tableLines.slice(1)).map(cells),
        markdown: tableLines.join('\n'),
      })
      continue
    }
    const item = LIST_LINE.exec(line)
    if (item !== null && (item[1] ?? '').length < 2) {
      flushProse()
      list ??= []
      list.push({ text: item[3] ?? '', code: [], isNumbered: /\d/.test(item[2] ?? '') })
      continue
    }
    if (list !== null && (/^\s{2,}\S/.test(line) || (line.trim() === '' && /^\s{2,}\S/.test(lines[index + 1] ?? '')))) {
      const current = (list as ListItem[])[(list as ListItem[]).length - 1]
      if (current !== undefined && line.trim() !== '') current.text += `\n${line.trim()}`
      continue
    }
    const lead = GROUP_LEAD.exec(line.trim())
    if (lead !== null && !/^\s/.test(line)) {
      flushProse()
      flushList()
      groups.push({ title: cleanMarkdown(lead[1] ?? '').replace(/[.:]$/, '').trim(), lead: (lead[2] ?? lead[3] ?? '').trim(), blocks: [] })
      continue
    }
    const italic = ITALIC_TITLE.exec(line.trim())
    if (italic !== null && !/^\s/.test(line)) {
      flushProse()
      flushList()
      groups.push({ title: (italic[1] ?? italic[2] ?? '').trim(), lead: '', blocks: [] })
      continue
    }
    if (line.trim() === '') {
      flushList()
      prose.push(line)
      continue
    }
    flushList()
    prose.push(line)
  }
  flushProse()
  flushList()
  return groups.filter(candidate => candidate.title !== null || candidate.blocks.length > 0)
}

export type QaCheck = {
  title: string | null
  action: string | null
  expected: string | null
  text: string
  /** The intertitle the check sits under (« Partie 1 — sur l'iPhone seul »), when the QA is split in parts. */
  part?: string
}

export type QaPlan = { preparation: BlockGroup[]; intro: string; checks: QaCheck[] }

const PREPARATION_TITLE = /mise en place|préparation|prépar|setup|avant de tester/i

const CHECKS_TITLE = /checklist|^qa\b|vérifications|à tester|à vérifier|ce que tu dois voir/i

const EXPECTED_MARK = /(?:^|[\s·→—–.;])(?:attendu|résultat attendu|tu dois voir)\s*:\s*/i

/** One check: its bold title, then « Fais : » (what to do) and « Attendu : » (what to see) when it says them. */
export function qaCheck(item: string): QaCheck {
  const head = /^\*\*(.+?)\*\*\s*[—–:.-]?\s*/.exec(item)
  const title = head === null ? null : cleanMarkdown(head[1] ?? '').replace(/[.:]$/, '').trim()
  const rest = head === null ? item : item.slice(head[0].length)
  const flat = cleanMarkdown(rest.replace(/\n/g, ' ')).trim()
  const expectedAt = EXPECTED_MARK.exec(flat)
  if (expectedAt === null) return { title, action: null, expected: null, text: flat }
  const before = flat.slice(0, expectedAt.index).replace(/^(?:fais|action|à faire)\s*:\s*/i, '').replace(/[\s·→—–]+$/, '').trim()
  const expected = flat.slice(expectedAt.index + expectedAt[0].length).trim()
  return { title, action: before === '' ? null : before, expected: expected === '' ? null : expected, text: flat }
}

/** The QA of a message: a `## QA` section, else the « Checklist » and « Mise en place » parts of « Ce que j'attends de toi ». */
export function qaPlan(text: string, report: Report | null): QaPlan {
  const fromGroups = (groups: BlockGroup[], isWholeSectionQa: boolean): QaPlan => {
    const isPreparation = (candidate: BlockGroup) => candidate.title !== null && PREPARATION_TITLE.test(candidate.title)
    const preparation = groups.filter(isPreparation)
    // In a QA section of its own, everything that is not the preparation is checks, intertitles (« Partie 1 ») included.
    const checkGroups = groups.filter(candidate =>
      isWholeSectionQa ? !isPreparation(candidate) : candidate.title !== null && CHECKS_TITLE.test(candidate.title),
    )
    const checks = checkGroups.flatMap(candidate =>
      candidate.blocks.flatMap(block =>
        block.kind === 'list'
          ? block.items.map(item => {
              const check = qaCheck(item.text)
              return candidate.title !== null && !CHECKS_TITLE.test(candidate.title) ? { ...check, part: candidate.title } : check
            })
          : [],
      ),
    )
    const intro = checkGroups
      .map(candidate => [candidate.lead, ...candidate.blocks.filter(block => block.kind === 'prose').map(block => (block.kind === 'prose' ? block.text : ''))].filter(part => part !== '').join('\n'))
      .filter(part => part !== '')
      .join('\n')
    return { preparation, intro, checks }
  }
  const qaSection = report?.sections.find(section => section.kind === 'qa') ?? findSection(text, /^qa\b|ce que tu dois voir|qa visuelle/i) ?? undefined
  if (qaSection !== undefined) return fromGroups(sectionGroups(qaSection.body), true)
  const askSection = report?.sections.find(section => section.kind === 'ask')
  if (askSection !== undefined) {
    const plan = fromGroups(sectionGroups(askSection.body), false)
    if (plan.checks.length > 0) return plan
  }
  return { preparation: [], intro: '', checks: qaChecklist(text).map(qaCheck) }
}

/** A check Claude comes back to after the user's QA answers: « QA 4 (recette importée) : … », and what it says to do now. */
export type QaFollowUp = {
  number: number
  title: string
  /** Claude says the check passes: the user still has to confirm it. */
  isClaimedOk: boolean
  action: string | null
  expected: string | null
  /** The procedure, when the check is redone step by step rather than in « Fais » and « Attendu ». */
  steps: ListItem[]
}

const FOLLOW_UP_LINE = /^\s*(?:[-*]\s+)?(?:#{1,4}\s+)?\*{0,2}\s*(?:la\s+|le\s+)?QA\s+(\d+)\b(.*)$/i

const CLAIMED_OK = /\b(?:est|sont)\s+(?:en fait\s+|donc\s+|bien\s+)*OK\b|c['’]est\s+(?:donc\s+)?OK\b|\bpasse\s+(?:donc\s+)?(?:bien|en fait)\b/i

/** The checks a reply comes back to, each from its « QA N » line to the next; none when the reply has no such line. */
export function qaFollowUps(text: string): QaFollowUp[] {
  const lines = text.split('\n')
  const starts = lines.map((line, index) => ({ index, match: FOLLOW_UP_LINE.exec(line) })).filter(start => start.match !== null)
  return starts.map((start, position) => {
    const match = start.match as RegExpExecArray
    const end = starts[position + 1]?.index ?? lines.length
    const head = (match[2] ?? '').replace(/^\*{1,2}/, '')
    const label = /^\s*\(([^)]{1,40})\)/.exec(head)?.[1]
    const segment = [head, ...lines.slice(start.index + 1, end)].join('\n')
    const items = sectionGroups(segment).flatMap(group => group.blocks.flatMap(block => (block.kind === 'list' ? block.items : [])))
    const marked = (pattern: RegExp) => {
      const item = items.find(candidate => pattern.test(cleanMarkdown(candidate.text)))
      if (item === undefined) return null
      const [first = '', ...rest] = item.text.split('\n')
      const lead = cleanMarkdown(first).replace(pattern, '').trim()
      const more = rest.map(line => cleanMarkdown(line.replace(/^[-*]\s+/, ''))).filter(line => line !== '')
      const parts = [lead, ...more].filter(part => part !== '')
      return parts.map((part, index) => (index < parts.length - 1 ? part.replace(/\s*[;,]$/, '') : part)).join(' ; ') || null
    }
    const action = marked(/^fais\s*:\s*/i)
    const expected = marked(/^attendu\s*:\s*/i)
    return {
      number: Number(match[1]),
      title: `QA ${match[1]}${label !== undefined ? ` · ${label.trim()}` : ''}`,
      isClaimedOk: CLAIMED_OK.test(cleanMarkdown(segment)),
      action,
      expected,
      steps: action === null && expected === null ? items.filter(item => item.isNumbered) : [],
    }
  })
}

/** A choice the user makes, with Claude's recommendation: a row of a table with a « Reco » column, or a `trancher:` line. */
export type Pick = { label: string; reco: string | null; details: string[] }

/** The rows of a table that has a « Reco » column, rows with an empty « # » folded into the row above as its details; null for any other table. */
export function tablePicks(block: Block): Pick[] | null {
  if (block.kind !== 'table') return null
  const recoAt = block.headers.findIndex(header => /reco/i.test(header))
  if (recoAt === -1) return null
  const numberAt = block.headers.findIndex(header => /^#$|^n°$|^no$/i.test(header.trim()))
  const pointAt = block.headers.findIndex((_, index) => index !== recoAt && index !== numberAt)
  const picks: Pick[] = []
  for (const row of block.rows) {
    const point = cleanMarkdown(row[pointAt] ?? '')
    const reco = cleanMarkdown(row[recoAt] ?? '')
    const previous = picks[picks.length - 1]
    if (numberAt !== -1 && (row[numberAt] ?? '').trim() === '' && previous !== undefined) {
      previous.details.push(reco === '' ? point : `${point} → ${reco}`)
      continue
    }
    if (point === '' && reco === '') continue
    picks.push({ label: point, reco: reco === '' ? null : reco, details: [] })
  }
  return picks
}

/** A group of « Ce que j'attends de toi » that says what Claude does itself: « Je fais de mon côté, sans décision de ta part ». */
export const INFO_TITLE = /je fais|de mon côté|sans décision de ta part|je m['’]en charge|côté claude|je m['’]occupe/i

export function isInfoGroup(group: BlockGroup): boolean {
  return group.title !== null && (INFO_TITLE.test(group.title) || INFO_TITLE.test(group.lead))
}

/** One line of a `cockpit` block, with the lines indented under it. */
export type CockpitItem = { kind: 'trancher' | 'confirmer' | 'faire' | 'vérifier' | 'info'; text: string; reco: string | null; details: string[] }

const COCKPIT_FENCE = /```cockpit[^\n]*\n([\s\S]*?)```/i

const COCKPIT_LINE = /^(trancher|confirmer|faire|v[ée]rifier|info)\s*:\s*(.+)$/i

/** The items of the message's `cockpit` block: what Claude lists for the cards, in its own words; null when it wrote none. */
export function cockpitBlock(text: string): CockpitItem[] | null {
  const body = COCKPIT_FENCE.exec(text)?.[1]
  if (body === undefined) return null
  const items: CockpitItem[] = []
  for (const line of body.split('\n')) {
    if (line.trim() === '') continue
    const previous = items[items.length - 1]
    if (/^\s{2,}\S/.test(line) && previous !== undefined) {
      previous.details.push(cleanMarkdown(line.trim().replace(/^[-*]\s+/, '')))
      continue
    }
    const match = COCKPIT_LINE.exec(line.trim())
    if (match === null) continue
    const kind = (match[1] ?? '').toLowerCase().replace('verifier', 'vérifier') as CockpitItem['kind']
    const [point = '', reco] = (match[2] ?? '').split(/\s*(?:→|->)\s*reco\s*:\s*/i)
    items.push({ kind, text: cleanMarkdown(point), reco: reco === undefined ? null : cleanMarkdown(reco), details: [] })
  }
  return items
}

/** The message as the person reads it: the `cockpit` block is for the cards only. */
export function withoutCockpitBlock(text: string): string {
  return text.replace(/\n?```cockpit[^\n]*\n[\s\S]*?```\n?/gi, '\n').trim()
}

function isCommitCode(block: Block): boolean {
  return block.kind === 'code' && commitBlocks(`\`\`\`\n${block.snippet.code}\n\`\`\``).length > 0
}

/**
 * « Ce que j'attends de toi » less what has its own card: the QA's groups, and the commit messages
 * (a group that held nothing else, « Message de commit » and its block, goes with them).
 */
export function askGroups(askBody: string): BlockGroup[] {
  return sectionGroups(askBody)
    .filter(candidate => !(candidate.title !== null && (PREPARATION_TITLE.test(candidate.title) || CHECKS_TITLE.test(candidate.title))))
    .map(candidate => ({
      group: candidate,
      blocks: candidate.blocks.filter(block => !isCommitCode(block) && !(block.kind === 'code' && block.snippet.language === 'cockpit')),
    }))
    .filter(({ group, blocks }) => blocks.length > 0 || blocks.length === group.blocks.length)
    .map(({ group, blocks }) => ({ ...group, blocks }))
}



/** `N BLOQUANT · N MAJEUR · N MINEUR` (or English) counts, summed over a message. */
export function severityCounts(text: string): Severities | null {
  const counts = emptySeverities()
  let isFound = false
  for (const match of text.matchAll(/(\d+)\s*\**\s*(BLOQUANTS?|BLOCKING|BLOCKERS?|MAJEURS?|MAJOR|MINEURS?|MINOR)\b/gi)) {
    const severity = severityOf(match[2] ?? '')
    if (severity === null) continue
    counts[severity] += Number(match[1])
    isFound = true
  }
  return isFound ? counts : null
}

export type Chip = { text: string; tone: 'ok' | 'warning' | 'danger' | 'neutral' }

function number(text: string): number {
  return Number(text.replace(/[\s  ]/g, ''))
}

/** Key figures of a message: tasks, tests, findings, agents. */
export function keyFigures(text: string): Chip[] {
  const chips: Chip[] = []
  const tasks = /(\d+)\s*\/\s*(\d+)\s*tâches/.exec(text)
  if (tasks !== null) chips.push({ text: `${tasks[1]}/${tasks[2]} tâches`, tone: tasks[1] === tasks[2] ? 'ok' : 'neutral' })
  const contract = /Tests?\s*:\s*(\d[\d\s\u202f\u00a0]*?)\s*pass[ée]s?(?:\s*,\s*(\d+)\s*échecs?)?/i.exec(text)
  const maven = /Tests run:\s*(\d+),\s*Failures:\s*(\d+)(?:,\s*Errors:\s*(\d+))?/.exec(text)
  const french = /(\d[\d\s  ]*\d|\d)\s*tests?\b[^\n]{0,40}?(\d+)\s*échecs?/i.exec(text)
  const plain = /(\d[\d\s  ]*\d|\d)\s*tests?\s*(?:passés|passed|verts?|✓)/i.exec(text)
  if (contract !== null) {
    const failed = number(contract[2] ?? '0')
    chips.push({ text: failed === 0 ? `${number(contract[1] ?? '0')} tests ✓` : `${failed} échecs`, tone: failed === 0 ? 'ok' : 'danger' })
  } else if (maven !== null) {
    const failed = number(maven[2] ?? '0') + number(maven[3] ?? '0')
    chips.push({ text: failed === 0 ? `${maven[1]} tests ✓` : `${failed} échecs / ${maven[1]}`, tone: failed === 0 ? 'ok' : 'danger' })
  } else if (french !== null) {
    const failed = number(french[2] ?? '0')
    chips.push({ text: failed === 0 ? `${number(french[1] ?? '0')} tests ✓` : `${failed} échecs`, tone: failed === 0 ? 'ok' : 'danger' })
  } else if (plain !== null) {
    chips.push({ text: `${number(plain[1] ?? '0')} tests ✓`, tone: 'ok' })
  }
  const severities = severityCounts(text)
  if (severities !== null) {
    const parts = [
      severities.blocking > 0 ? `${severities.blocking} bloquant${severities.blocking > 1 ? 's' : ''}` : '',
      severities.major > 0 ? `${severities.major} majeur${severities.major > 1 ? 's' : ''}` : '',
      severities.minor > 0 ? `${severities.minor} mineur${severities.minor > 1 ? 's' : ''}` : '',
    ].filter(part => part !== '')
    chips.push({
      text: parts.length === 0 ? '0 constat' : parts.join(' · '),
      tone: severities.blocking > 0 ? 'danger' : severities.major > 0 ? 'warning' : 'ok',
    })
  }
  const agents = /(\d+)\s*agents?\b/.exec(text)
  if (agents !== null) chips.push({ text: `${agents[1]} agents`, tone: 'neutral' })
  return chips
}

/** The phrase that starts the next session from a handoff file. */
export function handoffPhrase(text: string): string | null {
  return /(?:Lis|Read)\s+`?\.claude\/(?:handoff|passation)\/[^\s`]+`?[^\n`]*/.exec(text)?.[0]?.replace(/`/g, '') ?? null
}

export type Finding = { severity: 'blocking' | 'major' | 'minor'; file: string | null; line: number | null; problem: string; status: 'open' | 'fixed' | 'deferred' }

const FILE_REF = /(?<![\w/@.-])((?:[\w.-]+\/)*[\w-]+\.(?:java|kt|ts|tsx|js|mjs|md|sql|ya?ml|json|sh|css|feature|xml|properties|py|html))(?::(\d+))?(?![\w/])/g

/** `path:line` references, paths with a known extension, in the order met, without duplicates. */
export function fileRefs(text: string, limit = 8): { path: string; line: number | null }[] {
  const seen = new Set<string>()
  const refs: { path: string; line: number | null }[] = []
  for (const match of text.replace(/```[\s\S]*?```/g, '').matchAll(FILE_REF)) {
    const path = match[1] ?? ''
    const line = match[2] !== undefined ? Number(match[2]) : null
    const key = `${path}:${line ?? ''}`
    if (seen.has(key) || !path.includes('/')) continue
    seen.add(key)
    refs.push({ path, line })
    if (refs.length >= limit) break
  }
  return refs
}

/** One finding per list item or table row naming a severity (not the `N BLOQUANT` tallies). */
export function parseFindings(text: string): Finding[] {
  const findings: Finding[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!/^([-*]|\d+\.|\|)/.test(line)) continue
    const label = /(?<!\d\s?)\b(BLOQUANT|BLOCKING|MAJEUR|MAJOR|MINEUR|MINOR)\b/i.exec(line)
    if (label === null || /\d+\s*\**\s*(BLOQUANT|BLOCKING|MAJEUR|MAJOR|MINEUR|MINOR)/i.test(line)) continue
    const severity = severityOf(label[1] ?? '')
    if (severity === null) continue
    const ref = [...line.matchAll(FILE_REF)][0]
    const problem = cleanMarkdown(
      line
        .replace(/^([-*]|\d+\.)\s*/, '')
        .replace(/\|/g, ' ')
        .replace(label[0], '')
        .replace(ref?.[0] ?? '\u0000', '')
        .replace(/^[\s·:—–-]+/, ''),
    )
    findings.push({
      severity,
      file: ref?.[1] ?? null,
      line: ref?.[2] !== undefined ? Number(ref[2]) : null,
      problem: problem.replace(/\s*[·—–-]\s*$/, ''),
      status: /corrigé|fixed|résolu|✓|✅/i.test(line) ? 'fixed' : /reporté|deferred|backlog|déclassé/i.test(line) ? 'deferred' : 'open',
    })
  }
  return findings
}

/** Decisions Claude took alone and wants confirmed: a « Décisions … à valider » section, or the report's Décisions. */
/** The first section of any message whose heading matches, up to the next heading of its level or above. */
export function findSection(text: string, pattern: RegExp): { title: string; body: string } | null {
  const lines = text.split('\n')
  const heading = (line: string) => /^(#{1,4})\s+(?:\d+\.\s*)?(.+?)\s*$/.exec(line)
  const start = lines.findIndex(line => {
    const match = heading(line)
    return match !== null && pattern.test(cleanMarkdown(match[2] ?? ''))
  })
  if (start === -1) return null
  const level = (heading(lines[start] ?? '')?.[1] ?? '#').length
  const rest = lines.slice(start + 1)
  const end = rest.findIndex(line => {
    const match = heading(line)
    return match !== null && (match[1] ?? '').length <= level
  })
  return { title: cleanMarkdown(heading(lines[start] ?? '')?.[2] ?? ''), body: (end === -1 ? rest : rest.slice(0, end)).join('\n').trim() }
}

/** The top-level items of a section, each with its sub-points kept inside it. */
export function sectionItems(body: string): ListItem[] {
  return sectionGroups(body).flatMap(group => group.blocks.flatMap(block => (block.kind === 'list' ? block.items : [])))
}

/** The points to confirm of a message: a « Décisions … », « Mes lectures … », « … à confirmer » section. */
export function decisionsToValidate(text: string): ListItem[] {
  const section = findSection(text, CONFIRM_TITLE)
  return section === null ? [] : sectionItems(section.body)
}

/** The prose of a section without its list items: the context the items need. */
export function sectionProse(markdown: string): string {
  return markdown
    .split('\n')
    .filter(line => !/^\s*(?:[-*]|\d+\.)\s+/.test(line) && !/^\s{2,}\S/.test(line))
    .join('\n')
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

