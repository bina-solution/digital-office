/**
 * command-next — the office's `/next`.
 *
 * WHAT IT IS. One slash command whose whole job is to ask the agent the question the owner asks
 * every time he comes back: "what is open, and what should we do now?". The command starts one
 * ordinary model turn carrying a fixed brief; the ANALYSIS lives in the `next-work` skill beside the
 * preset (skills/next-work/SKILL.md) and in the offline overview that ships with it, so this file
 * never grows a second copy of "where the work lives".
 *
 * WHY IT IS A PLUGIN AND NOT A PROMPT. The harness parses a line that starts with `/` as a command
 * and REJECTS an unknown name instead of sending it to the model: before this package existed,
 * typing `/next` produced nothing at all — not even a prompt the agent could answer. A command
 * handler may start model work through `invocation.agent.followup(...)`, which is exactly what
 * `@deepseek-ai/dsh-command-goal` does with a goal's attachments, and what this does with one user
 * message.
 *
 * NO STATIC IMPORT OF A HARNESS PACKAGE, on purpose. This plugin is installed into the profile as a
 * `file:` dependency (harness/profile/package.json), so at runtime it lives at
 * `/opt/bina/plugins/command-next`, OUTSIDE the profile's node_modules tree: a bare
 * `import { createUserMessage } from '@deepseek-ai/dsh-llm'` resolves only if Node happens to walk up
 * into a directory that holds the harness, which is an accident of layout rather than a contract.
 * Instead the helper is looked up at mount time — first by package name (which works under any
 * layout that hoists the harness under the profile, and under `pnpm`'s own linking), then by the
 * image's path — and if neither is found the handler still runs, with a plain message object, which
 * is what `followup` expects after `createUserMessage` has normalized it.
 */

const name = 'command-next'

/** The registry this plugin talks to. Same injection shape as the shipped command plugins. */
const inject = ['commands']

/** What `/next <focus>` hands the model when the owner narrows the question. */
const FOCUS_LINE = 'מיקוד שהבעלים ביקש לסבב הזה'

const BRIEF = `בקשה מהבעלים: /next — סבב עבודה חדש.

טען את המיומנות \`next-work\` ובצע אותה עכשיו, במלואה, בלי לשאול שאלות ביניים: סרוק את כל מקורות
העבודה הפתוחה (שני קובצי התוכנית של DGO, issues/*.yaml הפתוחים, מצב הלשכות והקישורים, והמשימות שלי
ב-Plane כשהאפליקציה נגישה), ואז החזר דוח קצר בעברית: מה דחוף, מה חוסם ומי חוסם, מה מחכה להחלטה של
הבעלים, ומה אני ממליץ לעשות בסבב הזה — עם הנימוק ומה הראיה שתוכיח שזה נעשה.

אם משהו שסרקת נכשל (למשל Plane לא נגיש), אמור זאת במפורש ואל תמציא תוצאה ממנו.`

function prompt(rawInput) {
  const focus = (rawInput || '').trim()
  return focus ? `${BRIEF}\n\n${FOCUS_LINE}: ${focus}` : BRIEF
}

/** Find `createUserMessage` without a static bare import (see the header). */
async function loadCreateUserMessage() {
  const candidates = [
    '@deepseek-ai/dsh-llm',
    '/opt/bina/harness/profile/node_modules/@deepseek-ai/dsh-llm/lib/index.js',
    `${process.env.DSH_PROFILE_DIR || ''}/node_modules/@deepseek-ai/dsh-llm/lib/index.js`,
  ]
  for (const spec of candidates) {
    if (!spec || spec.startsWith('/node_modules')) continue
    try {
      const mod = await import(spec)
      if (typeof mod.createUserMessage === 'function') return mod.createUserMessage
    } catch {
      /* the next candidate; a missing helper is not a reason to lose the command */
    }
  }
  return null
}

async function apply(ctx) {
  const createUserMessage = await loadCreateUserMessage()
  ctx.commands.register({
    name: 'next',
    description: 'הצג את כל העבודה הפתוחה והצע מה לעשות בסבב הזה',
    input: { hint: '[מיקוד] — ריק = כל העבודה הפתוחה' },
    handler: (invocation) => {
      const text = prompt(invocation.rawInput)
      const content = [{ type: 'text', text }]
      invocation.agent.followup(
        createUserMessage
          ? createUserMessage({ content, source: { kind: 'user' } })
          : { role: 'user', content, source: { kind: 'user' } },
      )
      return {
        kind: 'success',
        text: '‏/next — קורא את העבודה הפתוחה ומכין את הדוח.',
      }
    },
  })
}

export { apply, inject, name }
