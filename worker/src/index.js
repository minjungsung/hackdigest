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
 *   1. cd worker
 *   2. npm install wrangler
 *   3. npx wrangler login
 *   4. npx wrangler deploy
 *   5. npx wrangler secret put GITHUB_TOKEN
 */

const GITHUB_OWNER = 'minjungsung';
const GITHUB_REPO = 'hackdigest';

// [FIX #2] CORS: 프로덕션 origin만 허용 — 'null', localhost, 127.0.0.1 제거
const ALLOWED_ORIGINS = [
  'https://minjungsung.github.io',
];

// [FIX #1] 필드 화이트리스트
const ALLOWED_LANGUAGES = ['ko', 'en'];
const ALLOWED_TOPICS = ['tech', 'stocks', 'realestate'];

// [FIX #4] Request body 크기 제한
const MAX_BODY_SIZE = 1024; // 1KB

// [FIX #5] Email 길이 제한
const MAX_EMAIL_LENGTH = 254;

// ─── Rate Limiting (in-memory, per-worker instance) ──────────
// IP별 요청 제한: 1분에 5건, 1시간에 20건
const RATE_LIMIT_WINDOW_MIN = 60;       // 1 minute in seconds
const RATE_LIMIT_MAX_PER_MIN = 5;
const RATE_LIMIT_WINDOW_HOUR = 3600;    // 1 hour in seconds
const RATE_LIMIT_MAX_PER_HOUR = 20;

const requestLog = new Map();  // IP -> [{timestamp}, ...]

function cleanOldEntries(entries, windowSeconds) {
  const cutoff = Date.now() - windowSeconds * 1000;
  return entries.filter(t => t > cutoff);
}

function isRateLimited(ip) {
  let entries = requestLog.get(ip) || [];

  // Clean entries older than 1 hour
  entries = cleanOldEntries(entries, RATE_LIMIT_WINDOW_HOUR);

  // Remove IP from map if no entries left
  if (entries.length === 0) {
    requestLog.delete(ip);
    entries = [];
  } else {
    requestLog.set(ip, entries);
  }

  // Periodic cleanup: every 50 requests, purge stale IPs
  if (requestLog.size > 100) {
    const cutoff = Date.now() - RATE_LIMIT_WINDOW_HOUR * 1000;
    for (const [key, vals] of requestLog) {
      const valid = vals.filter(t => t > cutoff);
      if (valid.length === 0) requestLog.delete(key);
      else requestLog.set(key, valid);
    }
  }

  // Check per-minute limit
  const recentMinute = entries.filter(t => t > Date.now() - RATE_LIMIT_WINDOW_MIN * 1000);
  if (recentMinute.length >= RATE_LIMIT_MAX_PER_MIN) {
    return { limited: true, reason: 'Too many requests. Please wait a minute.' };
  }

  // Check per-hour limit
  if (entries.length >= RATE_LIMIT_MAX_PER_HOUR) {
    return { limited: true, reason: 'Hourly limit reached. Please try again later.' };
  }

  // Record this request
  entries.push(Date.now());
  requestLog.set(ip, entries);

  return { limited: false };
}

// Cleanup happens inside isRateLimited() on each call — no setInterval needed in Workers.

// ─── CORS ────────────────────────────────────────────────────
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

// ─── Main Handler ────────────────────────────────────────────
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

    // [FIX #3] POST 요청 시 Origin 헤더 검증 — 허용된 origin이 아니면 403
    if (!ALLOWED_ORIGINS.includes(origin)) {
      return jsonResponse({ error: 'Forbidden' }, 403, origin);
    }

    // Rate limit check
    const clientIP = request.headers.get('CF-Connecting-IP') || 'unknown';
    const rateCheck = isRateLimited(clientIP);
    if (rateCheck.limited) {
      return jsonResponse({ error: rateCheck.reason }, 429, origin);
    }

    // [FIX #4] Request body 크기 제한 (1KB)
    const contentLength = parseInt(request.headers.get('Content-Length') || '0', 10);
    if (contentLength > MAX_BODY_SIZE) {
      return jsonResponse({ error: 'Request body too large' }, 413, origin);
    }

    // Parse request body
    let body;
    try {
      const rawBody = await request.text();
      if (rawBody.length > MAX_BODY_SIZE) {
        return jsonResponse({ error: 'Request body too large' }, 413, origin);
      }
      body = JSON.parse(rawBody);
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

    // [FIX #5] Email 길이 제한 (254자)
    if (email.length > MAX_EMAIL_LENGTH) {
      return jsonResponse({ error: 'Email too long' }, 400, origin);
    }

    // Validate email format
    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    if (!emailRegex.test(email)) {
      return jsonResponse({ error: 'Invalid email format' }, 400, origin);
    }

    // [FIX #1] language 검증 — 화이트리스트 외 'ko'로 fallback
    const sanitizedLanguage = ALLOWED_LANGUAGES.includes(language) ? language : 'ko';

    // [FIX #1] topics 검증 — 화이트리스트로 필터링, 유효한 것만 통과
    let sanitizedTopics = 'tech'; // default
    if (topics) {
      if (Array.isArray(topics)) {
        const validTopics = topics.filter(t => ALLOWED_TOPICS.includes(t));
        sanitizedTopics = validTopics.length > 0 ? validTopics : ['tech'];
      } else if (typeof topics === 'string') {
        sanitizedTopics = ALLOWED_TOPICS.includes(topics) ? topics : 'tech';
      }
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
              language: sanitizedLanguage,
              topics: sanitizedTopics,
            },
          }),
        }
      );

      if (githubResp.status === 204) {
        return jsonResponse({ success: true, message: 'Request submitted' }, 200, origin);
      } else {
        // [FIX #6] GitHub API 에러 상세를 로그에 노출하지 않음
        console.error(`GitHub API error: ${githubResp.status}`);
        return jsonResponse({ error: 'Failed to process request' }, 502, origin);
      }
    } catch (err) {
      // [FIX #6] 에러 메시지만 로그, 전체 에러 객체 제거
      console.error('GitHub API call failed');
      return jsonResponse({ error: 'Service unavailable' }, 503, origin);
    }
  },
};
