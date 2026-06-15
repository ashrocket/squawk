const TOTAL = 10;
const SESSION_TTL = 7 * 24 * 3600;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/')) return handleApi(url.pathname, request, env, url);
    return env.ASSETS.fetch(request);
  }
};

async function handleApi(path, request, env, url) {
  if (path === '/api/auth/github') {
    if (!env.GITHUB_CLIENT_ID)
      return text('Set secrets: wrangler secret put GITHUB_CLIENT_ID && wrangler secret put GITHUB_CLIENT_SECRET', 503);
    const ghUrl = `https://github.com/login/oauth/authorize?client_id=${encodeURIComponent(env.GITHUB_CLIENT_ID)}&scope=read:user`;
    return Response.redirect(ghUrl, 302);
  }

  if (path === '/api/auth/callback') {
    const code = url.searchParams.get('code');
    if (!code) return text('Missing code', 400);

    const tokenRes = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ client_id: env.GITHUB_CLIENT_ID, client_secret: env.GITHUB_CLIENT_SECRET, code }),
    });
    const { access_token } = await tokenRes.json();
    if (!access_token) return text('Auth failed — try again', 400);

    const userRes = await fetch('https://api.github.com/user', {
      headers: { Authorization: `Bearer ${access_token}`, 'User-Agent': 'squawk-site/1.0' },
    });
    const gh = await userRes.json();

    const token = crypto.randomUUID().replace(/-/g, '');
    await env.KV.put(
      `session:${token}`,
      JSON.stringify({ login: gh.login, avatar: gh.avatar_url, name: gh.name || gh.login }),
      { expirationTtl: SESSION_TTL }
    );

    return new Response(null, {
      status: 302,
      headers: {
        Location: '/',
        'Set-Cookie': `sq=${token}; Path=/; Max-Age=${SESSION_TTL}; SameSite=Lax; Secure; HttpOnly`,
      },
    });
  }

  if (path === '/api/me') {
    const user = await getUser(request, env);
    if (!user) return json({ user: null, vote: null });
    const raw = await env.KV.get(`vote:${user.login}`);
    return json({ user, vote: raw !== null ? +raw : null });
  }

  if (path === '/api/votes') {
    return json({ counts: await tallyCounts(env) });
  }

  if (path === '/api/vote' && request.method === 'POST') {
    const user = await getUser(request, env);
    if (!user) return json({ error: 'auth required' }, 401);

    let body;
    try { body = await request.json(); } catch { return json({ error: 'bad json' }, 400); }
    const slide = +body.slide;
    if (!Number.isInteger(slide) || slide < 0 || slide >= TOTAL) return json({ error: 'invalid slide' }, 400);

    await env.KV.put(`vote:${user.login}`, String(slide));
    const counts = await tallyCounts(env);
    return json({ ok: true, slide, counts });
  }

  if (path === '/api/logout' && request.method === 'POST') {
    const token = getCookie(request, 'sq');
    if (token) await env.KV.delete(`session:${token}`);
    return new Response(null, {
      status: 302,
      headers: { Location: '/', 'Set-Cookie': 'sq=; Path=/; Max-Age=0' },
    });
  }

  return json({ error: 'not found' }, 404);
}

async function tallyCounts(env) {
  const { keys } = await env.KV.list({ prefix: 'vote:' });
  const counts = new Array(TOTAL).fill(0);
  const vals = await Promise.all(keys.map(k => env.KV.get(k.name)));
  vals.forEach(v => { if (v !== null) { const i = +v; if (i >= 0 && i < TOTAL) counts[i]++; } });
  return counts;
}

async function getUser(request, env) {
  const token = getCookie(request, 'sq');
  if (!token) return null;
  const raw = await env.KV.get(`session:${token}`);
  return raw ? JSON.parse(raw) : null;
}

function getCookie(request, name) {
  const h = request.headers.get('Cookie') || '';
  const m = h.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

function text(msg, status = 200) {
  return new Response(msg, { status, headers: { 'Content-Type': 'text/plain' } });
}
