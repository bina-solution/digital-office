// The Markdown twin of every page (blueprint D8): `/he/start.md` beside `/he/start/`, for agents and for «copy as
// Markdown». The office's own agents read these; `sites` serves them as text/markdown; charset=utf-8 (DGO-1793).
import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection } from 'astro:content';

export const getStaticPaths: GetStaticPaths = async () =>
	(await getCollection('docs')).map((entry) => ({ params: { slug: entry.id }, props: { entry } }));

export const GET: APIRoute = ({ props }) => {
	const { data, body } = props.entry;
	const text = `# ${data.title}\n\n${data.description ? `${data.description}\n\n` : ''}${body ?? ''}`;
	return new Response(text, { headers: { 'Content-Type': 'text/markdown; charset=utf-8' } });
};
