export const meta = {
  name: 'dgo-content-library',
  description: 'Write DGO content-library pieces in Hebrew with Sonnet writers, edit each job adversarially, and import it into digital assets as drafts',
  whenToUse: 'Filling apps/digital-assets/content from assignments: args {jobs:[{id,pieces}]} or {pieces:[…], categories:[…]}',
  phases: [
    { title: 'Write', detail: 'one Sonnet writer per job: research first, then the Hebrew pieces', model: 'sonnet' },
    { title: 'Edit', detail: 'one Sonnet editor per job: facts, voice, checks, then import into digital assets', model: 'sonnet' },
  ],
}

// The checkout this run writes into. Default: the MacBook office's checkout, whose directory name ends
// with a space. Another machine — for example a Claude cloud VM — passes args.repo = its clone's absolute
// path. args.import = false skips the import step where digital assets is not running; the files are the
// source, and `./bbox digital-assets content` imports them later on the office that runs the app.
const REPO = (args && args.repo) || '/Users/shlomobolotin/הלשכה הדיגיטלית שלי '
const IMPORT = !(args && args.import === false)
const C = REPO + '/apps/digital-assets/content'
const WORDS = { article: '1,800–2,400', project: '450–650', tutorial: '1,000–2,200', comparison: '1,200–1,800', directory: '1,500–3,000', news: '400–800', report: '1,000–2,500', glossary: '40–90 per entry, 50 entries' }
const SOURCES = { article: 8, comparison: 8, directory: 8, tutorial: 4, news: 4, report: 4, project: 3, glossary: 4 }

function buildJobs(a) {
  if (a && a.jobs) return a.jobs
  const jobs = []
  const pieces = (a && a.pieces) || []
  pieces.filter(p => p.type !== 'comparison').forEach(p => jobs.push({ id: `${p.type}/${p.slug}`, pieces: [p] }))
  const alts = pieces.filter(p => p.type === 'comparison')
  for (let i = 0; i < alts.length; i += 2) jobs.push({ id: `comparison/alternatives-${i / 2 + 1}`, pieces: alts.slice(i, i + 2) })
  for (const c of (a && a.categories) || []) {
    for (let i = 0; i < c.slugs.length; i += 6) {
      jobs.push({ id: `project/${c.category}-${i / 6 + 1}`, pieces: c.slugs.slice(i, i + 6).map(s => ({ type: 'project', slug: s, plane: c.plane, category: c.category, category_he: c.he })) })
    }
  }
  return jobs
}

const file = (p) => `${C}/${p.type}/${p.slug}.he.md`
const line = (p) => {
  const bits = [`type: ${p.type}`, `slug: ${p.slug}`, `plane: ${p.plane}`, `body length: ${WORDS[p.type]} words`, `minimum sources: ${SOURCES[p.type]}`]
  if (p.status) bits.push(`DGO status per FACTS.md: ${p.status}`)
  if (p.category_he) bits.push(`category: ${p.category_he} (${p.category})`)
  return `- FILE "${file(p)}"\n  ${bits.join(' · ')}\n  working title: ${p.title || '(choose the best Hebrew title for the search)'}${p.angle ? `\n  angle to cover: ${p.angle}` : ''}`
}

const projectNote = `For project profiles: each is short but researched (at least 3 sources each). Decide each project's DGO status honestly from FACTS.md: Archify runs in DGO today (live); Lima is the engine DGO itself uses on a Mac (say exactly that); Umbrel, CasaOS, YunoHost, Cloudron and Coolify are other platforms in DGO's own field — describe them fairly; a server project not in FACTS.md is not-packaged; a desktop program is desktop.`

const WRITER = (job) => `You are a senior Hebrew writer-researcher and an Israeli practitioner, writing for the DGO content library of Bina Solutions (בינה סולושנס).

Read completely before anything else, and follow exactly (quote every path — the repo directory name ends with a space):
- "${C}/BRIEF.md" — the reader, the Israeli author's voice, research minimums, types and lengths, media/link placeholders, front matter, the checklist
- "${C}/FACTS.md" — the ONLY claims you may make about DGO, Bina Solutions or the office
- the house style, finished and reviewed: "${C}/tutorial/install-dgo-with-claude.he.md" (and, if they exist, "${C}/article/n8n.he.md" and "${C}/project/freecad.he.md"). Match its density, honesty and sourcing — not its subject.

YOUR JOB: ${job.id} — ${job.pieces.length} piece(s):
${job.pieces.map(line).join('\n')}
${job.pieces.some(p => p.type === 'project') ? '\n' + projectNote + '\n' : ''}
For each piece, in order:
1. If its FILE already exists, read it: if it already passes the brief's checklist, leave it and report "skipped"; otherwise improve it in place.
2. Research first with WebSearch and WebFetch: primary sources first (the official site, docs and pricing; the repository's README, LICENSE and latest releases with dates; the law or the official announcement itself), then credible 2025–2026 reviews and community threads, and Israeli sources where they matter. Verify every number you will print; date every price and version; convert prices to ₪ with a dated rate when it helps the reader.
3. Write the whole piece in natural, dense Hebrew, in the brief's voice: the answer first, no filler, honest trade-offs, fair to competitors, an «לשכה» (never «משרד») for an installation, media placeholders with alt text, the :::dgo box where the brief requires it, FAQ in front matter, at least 3 internal dgo:// links, and every source in front matter and inline.
4. Save it to its FILE (create the folder if needed). Run every check of the brief's checklist — the banned-phrase/emoji/exclamation grep, the word count, the ruby front-matter parse — fix until all pass, then fill words and reading_minutes.

Rules: write only your job's files; do not commit; do not run bbox, docker or anything that changes the machine; never invent a person, a quote, a statistic, a price or a source — a fact about DGO you need and FACTS.md lacks becomes [[fact: …]].

Return the structured result for every piece.`

const EDITOR = (job, w) => `You are the adversarial editor of the DGO content library: a Hebrew editor with a fact-checker's suspicion. A writer just finished job ${job.id}. Make every piece true, human and dense — then import it into digital assets.

Read first (quote paths — the repo directory name ends with a space): "${C}/BRIEF.md" and "${C}/FACTS.md".

The writer reported: ${JSON.stringify((w && w.pieces) || [])}

The job's files:
${job.pieces.map(p => `- "${file(p)}" (${p.type}, ${WORDS[p.type]} words${p.status ? `, DGO status ${p.status}` : ''})`).join('\n')}

For each file:
1. It must exist and its front matter must parse: ruby -ryaml -e 'puts YAML.load(File.read(ARGV[0]).split(/^---\\s*$/)[1]).keys.size' FILE. If a file is missing, write it yourself to the brief (research included).
2. DGO truth: every sentence about DGO, Bina Solutions, the office or its apps must be supported by FACTS.md, including the DGO status. Fix or delete anything that is not.
3. World truth: pick the 5 claims that matter most (prices, licences, versions, dates, legal facts) and check each against a primary source with WebFetch. Correct what is wrong, delete what cannot be verified, and make sure every URL in sources: is real.
4. Voice: rewrite any sentence that reads machine-written, generic or salesy; cut filler; keep the Israeli practitioner's directness and density; «לשכה» never «משרד» for an installation; עזריה is masculine; no banned phrase, no exclamation mark, no emoji.
5. Shape: the body word count is in range (awk '/^---$/{n++; next} n>=2' FILE | wc -w); media placeholders with alt text are present; at least 3 dgo:// links; enough sources; words and reading_minutes in the front matter are right.
${IMPORT ? `6. Import the job into digital assets as drafts — run exactly:
   cd "${REPO}" && ./bbox digital-assets content ${job.pieces.map(p => `${p.type}/${p.slug}`).join(' ')}
   and report its summary line. If it fails, report the error; retry once at most.` : `6. Do not import: this run only writes files. Set import to "skipped".`}

Do not commit. Return the structured result.`

const WRITE_SCHEMA = { type: 'object', properties: { pieces: { type: 'array', items: { type: 'object', properties: {
  file: { type: 'string' }, status: { type: 'string', enum: ['written', 'improved', 'skipped', 'failed'] }, words: { type: 'number' },
  sources: { type: 'number' }, placeholders: { type: 'number' }, fact_placeholders: { type: 'array', items: { type: 'string' } },
  unverified: { type: 'array', items: { type: 'string' } }, note: { type: 'string' } }, required: ['file', 'status'] } } }, required: ['pieces'] }
const EDIT_SCHEMA = { type: 'object', properties: { pieces: { type: 'array', items: { type: 'object', properties: {
  file: { type: 'string' }, verdict: { type: 'string', enum: ['pass', 'fixed', 'failed'] }, words: { type: 'number' },
  fixes: { type: 'array', items: { type: 'string' } }, removed_claims: { type: 'array', items: { type: 'string' } } }, required: ['file', 'verdict'] } },
  import: { type: 'string' } }, required: ['pieces', 'import'] }

const jobs = buildJobs(args)
log(`${jobs.length} jobs, ${jobs.reduce((n, j) => n + j.pieces.length, 0)} pieces`)
const results = await pipeline(jobs,
  (job) => agent(WRITER(job), { label: `write ${job.id}`, phase: 'Write', schema: WRITE_SCHEMA, model: 'sonnet', agentType: 'general-purpose' }),
  (w, job) => agent(EDITOR(job, w), { label: `edit ${job.id}`, phase: 'Edit', schema: EDIT_SCHEMA, model: 'sonnet', agentType: 'general-purpose' })
    .then(e => ({ id: job.id, write: w, edit: e })),
)
const done = results.filter(Boolean)
log(`${done.length}/${jobs.length} jobs finished`)
return done.map(r => ({
  id: r.id,
  written: ((r.write && r.write.pieces) || []).map(p => `${p.status}:${p.words || 0}w:${p.sources || 0}src`),
  edited: ((r.edit && r.edit.pieces) || []).map(p => p.verdict),
  import: r.edit && r.edit.import,
}))
