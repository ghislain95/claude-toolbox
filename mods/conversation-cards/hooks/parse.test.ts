import { describe, expect, test } from 'claude-code/testing'

import { mergeAnswers } from './actions'
import {
  decisionsToValidate,
  fileRefs,
  parseFindings,
  handoffPhrase,
  keyFigures,
  parseQuestions,
  parseReport,
  qaChecklist,
  ASK_TITLE,
  askGroups,
  cockpitBlock,
  findSection,
  isInfoGroup,
  tablePicks,
  withoutCockpitBlock,
  parseReport as parseReportForQa,
  qaCheck,
  qaFollowUps,
  qaPlan,
  sectionGroups,
  severityCounts,
  withoutQuestions,
} from './parse'
import { commitBlocks } from './shared/commits'
import { MINUTE, formatDuration } from './shared/format'
import { CONTRACT_QA, PLAN_21_22, QA_FOLLOW_UP, PLANNER_GUIDE, REPORT_21_22, S5_REPORT, WITH_COCKPIT_BLOCK } from './fixtures'

describe('sections in the order written', () => {
  test('« Ce que j’attends de toi » of the S5 report reads as its asks, then the QA set-up, the checklist and the commit, each with what sits under it', () => {
    const ask = parseReportForQa(S5_REPORT)?.ask ?? ''
    const groups = sectionGroups(ask)
    expect(groups.map(group => group.title)).toEqual([null, 'Mise en place de la QA', 'Checklist', 'Message de commit'])
    expect(groups.map(group => group.blocks.map(block => block.kind))).toEqual([['list'], ['code', 'code', 'code'], ['list'], ['code']])
    expect(groups[1]?.lead).toBe('`fake-store` et le catalogue dev sont déjà là, et le port 8080 est libre.')
    expect(groups[2]?.lead).toBe('ouvre DevTools, onglet Network, avec le filtre `recipes|catalog`.')
    // The asks are the three asks only: the QA has its own card, the commit message its own.
    expect(askGroups(ask).map(group => group.title)).toEqual([null])
  })

  test('the S5 QA is found inside the asks: its set-up commands, the DevTools hint and its three checks', () => {
    const plan = qaPlan(S5_REPORT, parseReportForQa(S5_REPORT))
    expect(plan.preparation.flatMap(group => group.blocks.map(block => (block.kind === 'code' ? block.snippet.code : '')))).toEqual([
      'cd backend && npm start -- --profile=local',
      'echo "VITE_RECIPE_SOURCE=catalog" > frontend/.env.development.local',
      'cd frontend && npm run dev',
    ])
    expect(plan.intro).toBe('ouvre DevTools, onglet Network, avec le filtre `recipes|catalog`.')
    expect(plan.checks.map(check => check.title)).toEqual(['Ouverture sur la semaine', 'Recherche « risotto »', 'Indisponible'])
    expect(plan.checks[0]?.text).toBe('Le planning est rempli. On voit manifest.v1.json puis les fichiers du catalogue, et aucun /api/v1/recipes/*.')
  })

  test('a QA written to the contract: numbered steps with their command, then « Fais » and « Attendu » apart', () => {
    const plan = qaPlan(CONTRACT_QA, parseReportForQa(CONTRACT_QA))
    const steps = plan.preparation.flatMap(group => group.blocks.flatMap(block => (block.kind === 'list' ? block.items : [])))
    expect(steps.map(step => [step.text, step.code.map(snippet => snippet.code)])).toEqual([
      ['Terminal 1, lance le backend :', ['cd backend && npm start -- --profile=local']],
      ['Ouvre http://localhost:5173, puis DevTools, onglet **Network**, filtre `recipes|catalog`.', []],
    ])
    expect(plan.checks).toEqual([
      { title: 'Ouverture sur la semaine', action: 'recharge la page, puis change de semaine.', expected: 'le planning est rempli, aucune ligne /api/v1/recipes.', text: 'Fais : recharge la page, puis change de semaine. · Attendu : le planning est rempli, aucune ligne /api/v1/recipes.' },
      { title: 'Catalogue indisponible', action: 'bloque l’URL larder-catalog-dev et recharge.', expected: 'le message « Les recettes de cette semaine n’ont pas pu être chargées… ».', text: 'Fais : bloque l’URL larder-catalog-dev et recharge. · Attendu : le message « Les recettes de cette semaine n’ont pas pu être chargées… ».' },
    ])
  })

  test('a check reads « Attendu » on its own line too, and stays whole when it says neither', () => {
    expect(qaCheck('**Thème** — Fais : bascule en sombre.\nAttendu : les couleurs restent.')).toMatchObject({ action: 'bascule en sombre.', expected: 'les couleurs restent.' })
    expect(qaCheck('Les textes affichés sont ceux validés.')).toEqual({ title: null, action: null, expected: null, text: 'Les textes affichés sont ceux validés.' })
  })
})

describe('points to confirm and asks in any message', () => {
  test('the 21-22 framing: « Mes lectures des tâches » are two points to confirm, sub-points inside; « Ce qui reste à toi » four asks', () => {
    const confirm = decisionsToValidate(PLAN_21_22)
    expect(confirm.map(item => item.text.split('\n')[0]?.slice(0, 6))).toEqual(['**22.2', '**22.3'])
    expect(confirm[1]?.text).toContain('- les docs du groupe 21 ;')
    const asks = askGroups(findSection(PLAN_21_22, ASK_TITLE)?.body ?? '')
    const starts = ['**Pendant le run**', '**IntelliJ est ouvert', '**À la fin de 22.3**', '**Je propose de garder']
    const items = asks.flatMap(group => group.blocks.flatMap(block => (block.kind === 'list' ? block.items : [])))
    expect(items.map((item, index) => item.text.startsWith(starts[index] ?? '?'))).toEqual([true, true, true, true])
  })

  test('the title variants: what Claude settled alone, what the user has to do', () => {
    expect(['Mes lectures des tâches (conteste si tu veux)', 'Hypothèses', 'Choix à confirmer', 'Décisions'].map(title => decisionsToValidate(`## ${title}\n- un point`).length)).toEqual([1, 1, 1, 1])
    expect(['Ce qui reste à toi', 'Pour toi', 'Ce que je te demande', "Ce que j’attends de toi"].map(title => findSection(`## ${title}\n- un point`, ASK_TITLE)?.body)).toEqual(['- un point', '- un point', '- un point', '- un point'])
    expect(findSection('## Objectif\n- rien à toi ici', ASK_TITLE)).toBe(null)
  })
})

describe('choices, information and the cockpit block', () => {
  test('the 21-22 « Reco » table reads as five choices, « Nommage » keeping its three lines; « Je fais de mon côté » is information', () => {
    const groups = askGroups(parseReportForQa(REPORT_21_22)?.ask ?? '')
    const picks = groups.flatMap(group => group.blocks.flatMap(block => tablePicks(block) ?? []))
    expect(picks.map(pick => pick.reco)).toEqual([
      'Corriger cette ligne pour qu’elle reprenne le glossaire'.replace('’', "'"),
      'Les aligner maintenant',
      'Garder ce qui est proposé',
      'Ne pas y toucher maintenant, ajouter une ligne backlog',
      'Garder, et trancher au prochain cadrage',
    ])
    expect(picks[2]?.details).toEqual([
      "« D15 » existe aussi comme numéro d'écran dans Parcours → Garder « ADR D15 » et toujours le qualifier ainsi",
      '« planifieur » contre « planificateur » → « planificateur » partout',
      "« retrait d'un catalogue » et « empreinte nutritionnelle » → Toujours écrits en entier",
    ])
    expect(groups.map(group => [group.title, isInfoGroup(group)])).toEqual([
      [null, false],
      ['Je fais de mon côté', true],
      ['Hébergeur', false],
    ])
  })

  test('the cockpit block: choices with their reco, details indented under them, and the message read without it', () => {
    expect(cockpitBlock(WITH_COCKPIT_BLOCK)).toEqual([
      { kind: 'trancher', text: 'Parcours, annexe B contredit le glossaire sur « Recette couverte »', reco: 'corriger la ligne pour reprendre le glossaire', details: [] },
      { kind: 'trancher', text: 'Nommage', reco: 'garder ce qui est proposé', details: ['« planificateur » partout'] },
      { kind: 'confirmer', text: 'la passe 1 porte sur tout le change depuis la base — presque tout est déjà commité', reco: null, details: [] },
      { kind: 'faire', text: 'poser VITE_CATALOG_BASE_URL et VITE_RECIPE_SOURCE dans la préversion de l’hébergeur avant le push', reco: null, details: [] },
      { kind: 'info', text: 'j’aligne la Data Strategy sur l’ADR', reco: null, details: [] },
    ])
    expect(withoutCockpitBlock(WITH_COCKPIT_BLOCK).includes('```cockpit')).toBe(false)
    expect(withoutCockpitBlock(WITH_COCKPIT_BLOCK).endsWith('| 1 | Parcours, annexe B | Corriger la ligne |')).toBe(true)
    expect(cockpitBlock('Pas de bloc ici.')).toBe(null)
  })
})

describe('a QA outside any report', () => {
  test('the iPhone walkthrough: four preparation steps apart, thirteen checks by their bold title, under their three parts', () => {
    const plan = qaPlan(PLANNER_GUIDE, null)
    expect(plan.preparation.flatMap(group => group.blocks.flatMap(block => (block.kind === 'list' ? block.items : []))).length).toBe(4)
    expect(plan.checks.map(check => check.title)).toEqual([
      'Page fraîche',
      "(c) Temps d'affichage",
      '(e) Thème',
      '(f) Filtre à 10 ingrédients',
      '(a) Défilement fluide',
      '(d) Glisser-déposer',
      'Relevé 1',
      "Ouvrir l'inspecteur",
      "Lancer l'enregistrement",
      '(b) Deux sessions',
      'Pic de mémoire',
      'Relevé 2',
      'Mémoire du produit',
    ])
    expect([...new Set(plan.checks.map(check => check.part))]).toEqual([
      "Partie 1 — sur l'iPhone seul, l'inspecteur fermé",
      'Partie 2 — la session (b), avec la mémoire enregistrée sur le Mac',
      "Partie 3 — la référence de l'app publiée sur larder.example",
    ])
  })
})

describe('a reply to the QA answers', () => {
  test('the S5 follow-up comes back to QA 1, 4 and 5: Claude’s own OK flagged, « Fais » and « Attendu » read, the numbered procedure kept', () => {
    const followUps = qaFollowUps(QA_FOLLOW_UP)
    expect(followUps.map(followUp => [followUp.number, followUp.title, followUp.isClaimedOk])).toEqual([
      [1, 'QA 1', true],
      [4, 'QA 4 · recette importée', true],
      [5, 'QA 5 · indisponible', false],
    ])
    expect(followUps[1]?.action).toBe('depuis la semaine en cours, fais défiler le planning à la main vers la semaine suivante, puis la fin du plan.')
    expect(followUps[1]?.expected).toBe(
      "côté catalogue, les fiches s'affichent jusqu'au bout du plan ; tant qu'une recette du catalogue est dans la vue, aucune notice ; quand la vue ne contient que des recettes importées, la notice apparaît.",
    )
    // QA 1 explains what the user saw (bullets, no procedure); QA 5 is redone in five numbered steps.
    expect(followUps[0]?.steps).toEqual([])
    expect(followUps[2]?.steps.length).toBe(5)
    expect(followUps[2]?.steps[1]?.text.startsWith('`Cmd+Shift+P`')).toBe(true)
  })

  test('a reply with no « QA N » line has no follow-up', () => {
    expect(qaFollowUps('Je relance la review.\n- un point\n- un autre')).toEqual([])
  })
})

describe('message shapes', () => {
  const QUESTIONS = [
    'Deux points à trancher.',
    '',
    '### Q1 · Découpage de S4',
    'Tout 13→20 en une session, ou découper ?',
    '- A · une session — 36 tâches d’un coup, un seul workflow long',
    '- B · 13-16 puis 17-20 (recommandé) — deux workflows plus courts',
    '  le rendu (17) reste isolé, plus simple à relire',
    'Recommandation : B, parce que 17 touche rendering/ et mérite sa propre review.',
    '',
    '### Q2 · Port 8080',
    "k9s prend 8080. Je penche pour **B**.",
    '- A · libérer 8080',
    '- B · API sur 8081',
    '',
    '## Ensuite',
    'Je lance sur ton GO.',
  ].join('\n')

  test('questions keep each option whole, its explanation, and the reason of the recommendation', () => {
    const questions = parseQuestions(QUESTIONS)
    expect(questions.map(question => question.id)).toEqual(['Q1', 'Q2'])
    expect(questions[0]?.options).toEqual([
      { letter: 'A', label: 'une session', detail: '36 tâches d’un coup, un seul workflow long', isRecommended: false },
      { letter: 'B', label: '13-16 puis 17-20', detail: 'deux workflows plus courts\nle rendu (17) reste isolé, plus simple à relire', isRecommended: true },
    ])
    expect(questions[0]?.rationale).toBe('Recommandation : B, parce que 17 touche rendering/ et mérite sa propre review.')
    expect(questions[0]?.context).toBe('Tout 13→20 en une session, ou découper ?')
    expect(questions[1]?.options.find(option => option.isRecommended)?.letter).toBe('B')
  })

  test('the text without its questions keeps what surrounds them', () => {
    expect(withoutQuestions(QUESTIONS)).toBe('Deux points à trancher.\n\n## Ensuite\nJe lance sur ton GO.')
  })

  test('a report needs three known sections, and pins its ask and QA', () => {
    const report = [
      '# Groupes 8 et 9 — bilan',
      '## Fait',
      '- 96/164 tâches',
      '## Trouvé et corrigé',
      '- 2 BLOQUANT · 3 MAJEUR · 9 MINEUR',
      '## Tests',
      'Tests : 2484 passés, 0 échecs',
      '## QA',
      '- [ ] la notice de saison s’affiche',
      "## Ce que j'attends de toi",
      '1. Valider l’option A',
    ].join('\n')
    const parsed = parseReport(report)
    expect(parsed?.title).toBe('Groupes 8 et 9 — bilan')
    expect(parsed?.sections.map(section => section.kind)).toEqual(['done', 'fixed', 'tests', 'qa', 'ask'])
    expect(parsed?.ask).toBe('1. Valider l’option A')
    expect(parsed?.qa).toEqual(['la notice de saison s’affiche'])
    expect(parseReport('## Fait\nx\n## Tests\ny')).toBe(null)
    expect(keyFigures(report).map(chip => chip.text)).toEqual(['96/164 tâches', '2484 tests ✓', '2 bloquants · 3 majeurs · 9 mineurs'])
  })

  test('commit blocks read the subject, scope, body and a forbidden trailer', () => {
    const text = 'Prêt :\n```text\nfeat(offline-catalog): add the catalog client\n\nBody line.\n```\n```\nchore(x): y\n\nCo-Authored-By: Claude\n```\n```ts\nconst a = 1\n```'
    const blocks = commitBlocks(text)
    expect(blocks.map(block => [block.scope, block.body !== '', block.hasCoAuthor])).toEqual([
      ['offline-catalog', true, false],
      ['x', true, true],
    ])
  })

  test('severities, QA lists and handoff phrases are found in prose', () => {
    expect(severityCounts('Review : 2 BLOQUANT, 3 MAJEURS et 1 minor')).toEqual({ blocking: 2, major: 3, minor: 1 })
    expect(severityCounts('rien')).toBe(null)
    expect(qaChecklist('Avant.\n## QA visuelle\n- ouvrir /sources\n- [ ] voir la date\n## Suite\n- pas QA')).toEqual(['ouvrir /sources', 'voir la date'])
    expect(handoffPhrase('Colle : `Lis .claude/passation/2026-10-17-x.md et reprends.`')).toBe('Lis .claude/passation/2026-10-17-x.md et reprends.')
    expect(handoffPhrase('Paste: `Read .claude/handoff/2026-11-20-0930-x.md and pick up exactly where we left off.`')).toBe(
      'Read .claude/handoff/2026-11-20-0930-x.md and pick up exactly where we left off.',
    )
  })
})

describe('findings, files and decisions to validate', () => {
  test('findings are read one per line, with their file, line and status; tallies are not findings', () => {
    const text = [
      'Review : 1 BLOQUANT · 1 MAJEUR · 1 MINEUR',
      '- BLOQUANT · backend/src/main/java/Catalog.java:42 · lock never released → release in finally',
      '- MAJEUR · frontend/src/a.ts:12 · stale state → reset, corrigé',
      '| MINEUR | docs/x.md | wording | reporté |',
    ].join('\n')
    expect(parseFindings(text).map(finding => [finding.severity, finding.file, finding.line, finding.status])).toEqual([
      ['blocking', 'backend/src/main/java/Catalog.java', 42, 'open'],
      ['major', 'frontend/src/a.ts', 12, 'fixed'],
      ['minor', 'docs/x.md', null, 'deferred'],
    ])
    expect(parseFindings(text)[0]?.problem).toBe('lock never released → release in finally')
  })

  test('file references need a folder and a known extension, outside code blocks, once each', () => {
    const text = 'Voir `frontend/src/a.ts:12`, frontend/src/a.ts:12 et README.md.\n```\nignored/b.ts:3\n```\nbackend/x/Y.java'
    expect(fileRefs(text)).toEqual([
      { path: 'frontend/src/a.ts', line: 12 },
      { path: 'backend/x/Y.java', line: null },
    ])
  })

  test('decisions to validate come from a « Décisions … à valider » section', () => {
    expect(decisionsToValidate('## Décisions prises en rédigeant (à valider)\n- garder 1.50.2\n- un seul bean\n## Suite\n- non').map(item => item.text)).toEqual(['garder 1.50.2', 'un seul bean'])
  })
})

describe('report reading order', () => {
  test('the intro is kept, and a question heading closes the section above it', () => {
    const report = parseReport('# Bilan\nContexte en une phrase.\n## Fait\n- a\n## Décisions\n- garder X\n### Q1 · Envoi\n- A · préremplir\n- B · direct\n## Tests\nTests : 1 passés, 0 échecs')
    expect(report?.intro).toBe('Contexte en une phrase.')
    expect(report?.sections.find(section => section.kind === 'decisions')?.body).toBe('- garder X')
  })

  test('the answers block goes at the end of the prompt, or in place of the previous one', () => {
    expect(mergeAnswers('', 'Q1 : A')).toBe('── Réponses aux cartes ──\nQ1 : A\n── fin des réponses ──')
    const once = mergeAnswers('mon texte  \n', 'Q1 : A')
    expect(once).toBe('mon texte\n\n── Réponses aux cartes ──\nQ1 : A\n── fin des réponses ──')
    expect(mergeAnswers(`${once}\nPS : merci`, 'Q1 : B')).toBe('mon texte\n\n── Réponses aux cartes ──\nQ1 : B\n── fin des réponses ──\nPS : merci')
  })
})

describe('formatting', () => {
  test('durations', () => {
    expect(formatDuration(42 * 1000)).toBe('42 s')
    expect(formatDuration(59 * MINUTE)).toBe('59 min')
    expect(formatDuration(65 * MINUTE)).toBe('1 h 05')
    expect(formatDuration(119.7 * MINUTE)).toBe('2 h')
    expect(formatDuration(3 * 24 * 60 * MINUTE)).toBe('3 j')
  })
})
