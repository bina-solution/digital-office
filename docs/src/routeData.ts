// Every page names its Markdown twin (blueprint D8): <link rel="alternate" type="text/markdown" href="…/<id>.md">.
// A fallback page (English, while only Hebrew exists) names the twin of the page it shows.
import { defineRouteMiddleware } from '@astrojs/starlight/route-data';

export const onRequest = defineRouteMiddleware((context) => {
	const route = context.locals.starlightRoute;
	if (route.entry.id === '404') return; // Starlight's own 404 is not a page of the docs: it has no twin
	const base = import.meta.env.BASE_URL.replace(/\/*$/, '/');
	route.head.push({
		tag: 'link',
		attrs: { rel: 'alternate', type: 'text/markdown', href: `${base}${route.entry.id}.md` },
	});
});
