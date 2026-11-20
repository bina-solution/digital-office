// office-context — the section is an index of the installed apps, built from the compiler's structured
// twin, and falls back to the whole briefs when the twin cannot be read (EXU-64).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply, purposeOf, renderIndex } from '../lib/index.js'

const BRIEF = '# Operating «עזריה»\n\n<!-- a comment -->\nThe office\'s **AI**: a Hebrew agent harness.\n\n## Traps\n- a long trap the index must not carry\n'

function office({ json = true } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'office-context-'))
  mkdirSync(join(root, '.generated/registry'), { recursive: true })
  mkdirSync(join(root, 'platform-base/drive'), { recursive: true })
  writeFileSync(join(root, 'platform-base/drive/AGENT.md'), 'x')
  writeFileSync(join(root, '.generated/registry/agent-context.md'), `# whole briefs\n${BRIEF}`)
  if (json) {
    writeFileSync(join(root, '.generated/registry/agent-context.json'), JSON.stringify({
      apps: [
        { id: 'bina-ds', title: 'עזריה', file: 'AGENT.md', endpoint: 'http://bina-ds:3081',
          capabilities: [{ interface: 'agent.v1' }, { interface: 'agent.v1' }], brief: BRIEF },
        { id: 'drive', title: 'קבצים', file: 'AGENT.md', capabilities: [], brief: '' },
      ],
    }))
  }
  return root
}

function section(root, config = {}) {
  let registered
  const ctx = { effect: (fn) => fn(), systemPrompt: { section: (s) => { registered = s } } }
  apply(ctx, { path: join(root, '.generated/registry/agent-context.md'), ...config })
  return registered
}

test('the purpose is the first line of prose, without emphasis', () => {
  assert.equal(purposeOf(BRIEF), "The office's AI: a Hebrew agent harness.")
  assert.equal(purposeOf(''), '')
  const long = purposeOf(`${'word '.repeat(60)}`, 50)
  assert.ok(long.endsWith('…') && long.length <= 51, long)
})

test('the section is an index: one line per app, its address, and where its brief is', () => {
  const root = office()
  const s = section(root)
  assert.equal(s.interpolate, false)
  const text = s.text()
  assert.match(text, /2 app\(s\):/)
  assert.match(text, /- \*\*עזריה\*\* `bina-ds` · `http:\/\/bina-ds:3081` \(agent\.v1\) — The office's AI: a Hebrew agent harness\. · brief: `apps\/bina-ds\/AGENT\.md`/)
  assert.match(text, /- \*\*קבצים\*\* `drive` · brief: `platform-base\/drive\/AGENT\.md`/)
  assert.doesNotMatch(text, /a long trap the index must not carry/)
  assert.equal(text, s.text(), 'the same file renders the same bytes (a stable prompt prefix)')
})

test('without the structured twin, the whole briefs are given, as before', () => {
  const text = section(office({ json: false })).text()
  assert.match(text, /^# whole briefs/)
  assert.match(text, /a long trap the index must not carry/)
})

test("mode 'full' keeps the whole briefs on purpose", () => {
  assert.match(section(office(), { mode: 'full' }).text(), /a long trap the index must not carry/)
})

test('the live registry renders: every app has a line', () => {
  const doc = { apps: [{ id: 'a', title: 'א', brief: 'Does A.' }] }
  assert.equal(renderIndex(doc, '/nowhere').split('\n- ').length - 1, 1)
})
