// Pure parsers of the OpenSpec files and the handoffs: task groups, owner points, handoff decisions.

import type { Decision, TaskGroup } from '../types'
import { cleanMarkdown, truncate } from './logic'

// ---------------------------------------------------------------- OpenSpec



/** Each `## N. Title` section of tasks.md with its checked and total boxes. */
export function taskGroups(tasksMarkdown: string): TaskGroup[] {
  const groups: TaskGroup[] = []
  let current: TaskGroup | undefined
  for (const line of tasksMarkdown.split('\n')) {
    const heading = /^##\s+(\d+[a-z]?)\.\s+(.*)$/.exec(line)
    if (heading !== null) {
      current = {
        number: heading[1] ?? '',
        title: cleanMarkdown((heading[2] ?? '').replace(/\s*\(.*$/, '')),
        done: 0,
        total: 0,
      }
      groups.push(current)
      continue
    }
    if (/^#{1,2}\s/.test(line)) current = undefined
    const box = /^\s*- \[([ xX])\]/.exec(line)
    if (box !== null && current !== undefined) {
      current.total += 1
      if (box[1] !== ' ') current.done += 1
    }
  }
  return groups.filter(group => group.total > 0)
}

/** The rows of verification/owner-points.md: `| # | Point | Decision | Date |`. */
export function ownerDecisions(markdown: string): Decision[] {
  const decisions: Decision[] = []
  for (const line of markdown.split('\n')) {
    const cells = line.split('|').map(cell => cell.trim())
    if (cells.length < 5 || !/^\d+$/.test(cells[1] ?? '')) continue
    const point = cleanMarkdown(cells[2] ?? '')
    const decision = cleanMarkdown(cells[3] ?? '')
    const status: Decision['status'] = /^informed/i.test(decision)
      ? 'informed'
      : /^deferred|to confirm|à confirmer/i.test(decision)
        ? 'open'
        : 'owner'
    decisions.push({
      key: `#${cells[1]}`,
      text: truncate(`${point} → ${decision.split(/ — |\. /)[0] ?? decision}`, 160),
      status,
      source: 'owner-points',
    })
  }
  return decisions
}

function sectionLines(markdown: string, heading: RegExp): string[] {
  const lines = markdown.split('\n')
  const start = lines.findIndex(line => /^##\s/.test(line) && heading.test(line))
  if (start === -1) return []
  const rest = lines.slice(start + 1)
  const end = rest.findIndex(line => /^##\s/.test(line))
  return end === -1 ? rest : rest.slice(0, end)
}

/** Decisions (✅ owner, 🟡 agent) and open questions of a handoff document. */
export function handoffDecisions(markdown: string): Decision[] {
  const decisions: Decision[] = []
  let parent: Decision['status'] | undefined
  sectionLines(markdown, /Décisions|Decisions/i).forEach((line, index) => {
    const item = /^(\s*)[-*]\s+(.*)$/.exec(line)
    if (item === null) return
    const isNested = (item[1] ?? '').length > 0
    const body = item[2] ?? ''
    const status: Decision['status'] | undefined = body.includes('✅') ? 'owner' : body.includes('🟡') ? 'agent' : undefined
    if (!isNested) parent = status
    const effective = status ?? (isNested ? parent : undefined)
    if (effective === undefined) return
    if (!isNested && body.trimEnd().endsWith(':')) return
    decisions.push({
      key: `p${index}`,
      text: truncate(cleanMarkdown(body.replace(/\s*[—–-]\s*(✅|🟡).*$/, '').replace(/[✅🟡]/g, '')), 160),
      status: effective,
      source: 'passation',
    })
  })
  sectionLines(markdown, /Questions ouvertes/i).forEach((line, index) => {
    const item = /^[-*]\s+(.*)$/.exec(line)
    if (item === null) return
    decisions.push({ key: `q${index}`, text: truncate(cleanMarkdown(item[1] ?? ''), 160), status: 'open', source: 'passation' })
  })
  return decisions
}

export type CommitBlock = { subject: string; type: string; scope: string; body: string; hasCoAuthor: boolean; text: string }

/** Fenced blocks that open with a Conventional Commit subject. */
export function commitBlocks(text: string): CommitBlock[] {
  const blocks: CommitBlock[] = []
  for (const match of text.matchAll(/```[a-z]*\n([\s\S]*?)```/g)) {
    const content = (match[1] ?? '').replace(/\s+$/, '')
    const lines = content.split('\n')
    const subject = (lines[0] ?? '').trim()
    const head = /^(feat|fix|chore|docs|refactor|test|perf|build|ci|style)\(([^)]+)\)!?:\s+\S/.exec(subject)
    if (head === null) continue
    const body = lines.slice(1).join('\n').trim()
    blocks.push({
      subject,
      type: head[1] ?? '',
      scope: head[2] ?? '',
      body,
      hasCoAuthor: /co-authored-by/i.test(content),
      text: content,
    })
  }
  return blocks
}

function number(text: string): number {
  return Number(text.replace(/[\s  ]/g, ''))
}

