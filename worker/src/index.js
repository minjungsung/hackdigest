/**
 * HackDigest Subscription Proxy — Cloudflare Worker
 *
 * Proxies subscription requests to GitHub Actions repository_dispatch API.
 * Keeps the GitHub PAT token server-side (in Worker secrets).
 *
 * Environment variables (set via Cloudflare dashboard or wrangler):
 *   GITHUB_TOKEN  — Fine-grained PAT with Contents:write for the hackdigest repo
 *
 * Deploy:
 *   1. npm create cloudflare@latest hackdigest-proxy
 *   2. Replace src/index.js with this file
 *   3. wrangler secret put GITHUB_TOKEN
 *   4. wrangler deploy
 */

const GITHUB_OWNER = 'minjungsung';
const GITHUB_REPO = 'hackdigest';
const ALLOWED_ORIGINS = [
  'https://minjungsung.github.io',
  'http://localhost:3000',
  'http://127.0.0.1:3000',
];

function corsHeaders(origin) {
  const allowedOrigin = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin': allowedOrigin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function jsonResponse(data, status, origin) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(origin),
    },
  });
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    // Only accept POST
    if (request.method !== 'POST') {
      return jsonResponse({ error: 'Method not allowed' }, 405, origin);
    }

    // Parse request body
    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResponse({ error: 'Invalid JSON' }, 400, origin);
    }

    // Validate required fields
    const { action, email, language, topics } = body;

    if (!action || !email) {
      return jsonResponse({ error: 'Missing required fields: action, email' }, 400, origin);
    }

    if (!['add', 'remove', 'update'].includes(action)) {
      return jsonResponse({ error: 'Invalid action. Must be: add, remove, update' }, 400, origin);
    }

    // Validate email format
    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    if (!emailRegex.test(email)) {
      return jsonResponse({ error: 'Invalid email format' }, 400, origin);
    }

    // Call GitHub repository_dispatch API
    const githubToken = env.GITHUB_TOKEN;
    if (!githubToken) {
      return jsonResponse({ error: 'Server configuration error' }, 500, origin);
    }

    try {
      const githubResp = await fetch(
        `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/dispatches`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${githubToken}`,
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json',
            'User-Agent': 'hackdigest-proxy',
          },
          body: JSON.stringify({
            event_type: 'manage_subscriber',
            client_payload: {
              action: action,
              email: email,
              language: language || 'ko',
              topics: topics || 'tech',
            },
          }),
        }
      );

      if (githubResp.status === 204) {
        return jsonResponse({ success: true, message: 'Request submitted' }, 200, origin);
      } else {
        const errorText = await githubResp.text();
        console.error(`GitHub API error: ${githubResp.status} ${errorText}`);
        return jsonResponse({ error: 'Failed to process request' }, 502, origin);
      }
    } catch (err) {
      console.error('GitHub API call failed:', err);
      return jsonResponse({ error: 'Service unavailable' }, 503, origin);
    }
  },
};
