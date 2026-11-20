// docs.digital-office.co.il (DGO-1788) — Starlight, Hebrew first, English the second locale, llms.txt for agents.
// The decisions are reports/DGO docs blueprint 2026.md (D1 the tool, D2 the languages, D8 docs for machines).
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLlmsTxt from 'starlight-llms-txt';

// DOCS_BASE: "/" for docs.digital-office.co.il; "/a/sites/public/dgo-docs" for the preview the office shows behind its
// sign-in (the console's mount of the `sites` app). Starlight's own links follow the base; the pages link each other
// as "/he/…", so `withBase` puts the base in front of those too — one source, both builds.
const base = (process.env.DOCS_BASE || '/').replace(/\/*$/, '/');

function withBase() {
	const visit = (node) => {
		// a link's href and a picture's src (the diagrams in public/diagrams/) both name the site's root
		const key = node.type === 'element' ? { a: 'href', img: 'src' }[node.tagName] : undefined;
		const url = key ? node.properties?.[key] : undefined;
		if (typeof url === 'string' && url.startsWith('/') && !url.startsWith('//') && !url.startsWith(base)) {
			node.properties[key] = base + url.slice(1);
		}
		for (const child of node.children || []) visit(child);
	};
	return (tree) => (base === '/' ? undefined : visit(tree));
}

// The writers mark a picture still to be made as `![what it shows](TODO-shot: what to capture or draw)`. With a space
// in the address that is not a Markdown image, so it would print as raw text: here each becomes a marked box saying
// what will stand there. The public build must carry the real picture instead (a TODO-shot left is a draft).
function shotPlaceholders() {
	const one = /!\[([^\]]*)\]\(TODO-shot:\s*([^)]*)\)/;
	const all = new RegExp(one.source, 'g');
	const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
	// the box speaks the page's language: a page under content/docs/en/ is English, every other page Hebrew
	const label = (what, en) =>
		en
			? `${/diagram|תרשים/i.test(what) ? 'Diagram' : 'Screenshot'} to come:`
			: `${/תרשים/.test(what) ? 'תרשים' : 'צילום מסך'} שעוד יבוא:`;
	const box = (alt, what, en) =>
		`<span class="shot-todo" role="img" aria-label="${esc(alt)}"><b>${label(what, en)}</b> ${esc(alt)}` +
		`<small>${esc(what)}</small></span>`;
	let en = false;
	const visit = (node) => {
		if (!Array.isArray(node.children)) return;
		const out = [];
		for (const child of node.children) {
			if (child.type !== 'text' || !one.test(child.value)) {
				visit(child);
				out.push(child);
				continue;
			}
			let last = 0;
			for (const m of child.value.matchAll(all)) {
				if (m.index > last) out.push({ type: 'text', value: child.value.slice(last, m.index) });
				out.push({ type: 'html', value: box(m[1], m[2], en) });
				last = m.index + m[0].length;
			}
			if (last < child.value.length) out.push({ type: 'text', value: child.value.slice(last) });
		}
		node.children = out;
	};
	return (tree, file) => {
		en = /[\\/]content[\\/]docs[\\/]en[\\/]/.test(file?.path || '');
		visit(tree);
	};
}

export default defineConfig({
	site: 'https://docs.digital-office.co.il',
	base,
	markdown: { remarkPlugins: [shotPlaceholders], rehypePlugins: [withBase] },
	integrations: [
		starlight({
			// DGO-1802 (the owner, 2026-11-10): the Hebrew name always with its mark — a government service has the same name.
			// The English pages carry the English name, as the public README does.
			title: { he: 'הלשכה הדיגיטלית DGO', en: 'DGO — the digital office' },
			defaultLocale: 'he',
			locales: {
				he: { label: 'עברית', lang: 'he', dir: 'rtl' },
				en: { label: 'English', lang: 'en' },
			},
			// the blueprint's map (§2) in its order, for the pages written so far (the home page is the title's link)
			sidebar: [
				{ slug: 'what-is-dgo' },
				{ slug: 'idea' },
				{
					label: 'התחלה',
					translations: { en: 'Start' },
					items: [
						{ slug: 'start' },
						{ slug: 'start/requirements' },
						{ slug: 'start/install/linux' },
						{ slug: 'start/install/macos' },
						{ slug: 'start/install/windows' },
						{ slug: 'start/agent-prompt' },
						{ slug: 'start/after-install' },
						{ slug: 'start/first-hour' },
						{ slug: 'start/uninstall' },
					],
				},
				{
					label: 'המושגים',
					translations: { en: 'Concepts' },
					items: [{ slug: 'concepts' }, { slug: 'concepts/office' }, { slug: 'concepts/app' }, { slug: 'concepts/declaration' }, { slug: 'concepts/connection' }, { slug: 'concepts/agent' }, { slug: 'concepts/herd' }, { slug: 'concepts/link' }, { slug: 'glossary' }],
				},
				{
					label: 'שימוש בלשכה',
					translations: { en: 'Using the office' },
					items: [
						{ slug: 'use/console' },
						{ slug: 'use/sign-in' },
						{ slug: 'use/add-app' },
						{ slug: 'use/files' },
						{ slug: 'use/mail' },
						{ slug: 'use/ask-bina' },
					],
				},
				{
					label: 'האפליקציות',
					translations: { en: 'Apps' },
					// the base first (what every office runs, as apps/index lists it), then the apps a business adds
					items: [
						{ slug: 'apps' },
						{ slug: 'apps/console' },
						{ slug: 'apps/app-management' },
						{ slug: 'apps/connections' },
						{ slug: 'apps/traefik' },
						{ slug: 'apps/https-redirect' },
						{ slug: 'apps/forward-auth' },
						{ slug: 'apps/authentik' },
						{ slug: 'apps/notifications' },
						{ slug: 'apps/machine' },
						{ slug: 'apps/data-management' },
						{ slug: 'apps/autoheal' },
						{ slug: 'apps/containers' },
						{ slug: 'apps/postgres' },
						{ slug: 'apps/redis' },
						{ slug: 'apps/supabase' },
						{ slug: 'apps/bina-ui' },
						{ slug: 'apps/security' },
						{ slug: 'apps/glitchtip' },
						{ slug: 'apps/drive' },
						{ slug: 'apps/mail' },
						{ slug: 'apps/indox' },
						{ slug: 'apps/apitools' },
						{ slug: 'apps/my-docs' },
						{ slug: 'apps/esign' },
						{ slug: 'apps/bina-ds' },
						{ slug: 'apps/n8n' },
						{ slug: 'apps/raphael' },
						{ slug: 'apps/any-concurrency' },
						{ slug: 'apps/project-pln' },
						{ slug: 'apps/chat' },
						{ slug: 'apps/telegram' },
						{ slug: 'apps/meet' },
						{ slug: 'apps/sites' },
						{ slug: 'apps/domains' },
						{ slug: 'apps/digital-assets' },
						{ slug: 'apps/entities' },
						{ slug: 'apps/social-list' },
						{ slug: 'apps/browser42' },
						{ slug: 'apps/computers' },
						{ slug: 'apps/dgo-extend' },
					],
				},
				{
					label: 'גיבוי ושחזור',
					translations: { en: 'Backup and restore' },
					items: [{ slug: 'backup' }, { slug: 'backup/restore' }],
				},
				{
					label: 'ניהול',
					translations: { en: 'Administration' },
					items: [{ slug: 'admin/health' }, { slug: 'admin/updates' }, { slug: 'admin/never-do' }],
				},
				{
					label: 'עיון',
					translations: { en: 'Reference' },
					items: [{ slug: 'reference/cli' }],
				},
				{ slug: 'architecture' },
				{ slug: 'for-agents' },
			],
			customCss: ['./src/styles/olive.css'],
			routeMiddleware: './src/routeData.ts',
			plugins: [starlightLlmsTxt()],
		}),
	],
});
