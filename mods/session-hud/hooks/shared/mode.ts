// Copied from shared/mode.ts by scripts/sync-shared.sh: edit the original, not this copy.
// Shared by the mods of this repository: the app's light or dark mode, for the few native colours that differ
// between the two (a tile is white on light, a veil on dark).
// Copied into each mod's hooks/shared/ by scripts/sync-shared.sh: edit it here, then run the script.
//
// The session's `theme` setting does not follow the desktop app's appearance, so the mode is read where the app
// keeps it: `userThemeMode` in its config.json (`light`, `dark`, or `system`, then macOS's own appearance). Only
// that one key is read. Elsewhere (another OS, another surface, a file that moved) the `theme` setting answers.

import type { EngineInterface } from 'claude-code'

import { type Mode, modeOf } from './sienne'

const APP_CONFIG = 'Library/Application Support/Claude/config.json'

/** The appearance the desktop app shows, from its own settings; null when they cannot be read. */
async function appMode($: EngineInterface): Promise<Mode | null> {
  try {
    const home = await $.env.get('HOME')
    if (home === undefined || home === '') return null
    const settings = JSON.parse(await $.fs.read(`${home}/${APP_CONFIG}`)) as { userThemeMode?: unknown }
    const chosen = settings.userThemeMode
    if (chosen === 'light' || chosen === 'dark') return chosen
    if (chosen !== 'system' && chosen !== undefined) return null
    // Following the system: macOS names its dark appearance, and names nothing when light.
    const result = await $.process.run(['/usr/bin/defaults', 'read', '-g', 'AppleInterfaceStyle'], { timeoutMs: 2000 })
    return result.exitCode === 0 && /dark/i.test(String(result.stdout)) ? 'dark' : 'light'
  } catch {
    return null
  }
}

/** The mode now; `auto` when neither the app's settings nor the session's `theme` setting say. */
export async function readMode($: EngineInterface): Promise<Mode> {
  const fromApp = await appMode($)
  if (fromApp !== null) return fromApp
  try {
    const rows = await $.config.list()
    return modeOf(rows.find(row => row.key === 'theme')?.value)
  } catch {
    return 'auto'
  }
}
