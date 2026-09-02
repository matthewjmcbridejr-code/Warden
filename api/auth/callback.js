const {
  ACCESS_COOKIE,
  PKCE_COOKIE,
  STATE_COOKIE,
  cookie,
  currentUser,
  exchangeCode,
  parseCookies,
  redirectUri,
} = require("../_vercel-auth");

module.exports = async function handler(req, res) {
  const query = req.query || {};
  const code = String(query.code || "");
  const returnedState = String(query.state || "");
  const cookies = parseCookies(req.headers.cookie);
  const verifier = String(cookies[PKCE_COOKIE] || "");
  let invalidReason = "";
  if (!code) invalidReason = "missing_code";
  else if (!returnedState) invalidReason = "missing_query_state";
  else if (!cookies[STATE_COOKIE]) invalidReason = "missing_state_cookie";
  else if (!verifier) invalidReason = "missing_pkce_cookie";
  else if (!cryptoSafeEqual(returnedState, cookies[STATE_COOKIE])) invalidReason = "state_mismatch";
  if (invalidReason) {
    console.error("oauth callback rejected", {
      reason: invalidReason,
      query_code_present: Boolean(code),
      query_state_present: Boolean(returnedState),
      stored_state_present: Boolean(cookies[STATE_COOKIE]),
      pkce_verifier_present: Boolean(verifier),
      redirect_uri: safeRedirectUri(req),
    });
    return res.status(400).json({ ok: false, error: "Invalid Vercel OAuth callback" });
  }
  try {
    const tokens = await exchangeCode(req, code, verifier);
    const user = await currentUser({ headers: { cookie: cookie(ACCESS_COOKIE, tokens.access_token, 3600) } });
    if (!user || user.denied) return res.status(403).json({ ok: false, error: "Vercel account is not allowed" });
    res.setHeader("Set-Cookie", [
      cookie(ACCESS_COOKIE, tokens.access_token, Math.min(Number(tokens.expires_in) || 3600, 3600)),
      cookie(STATE_COOKIE, "", 0),
      cookie(PKCE_COOKIE, "", 0),
    ]);
    res.writeHead(302, { Location: "/" });
    return res.end();
  } catch (error) {
    console.error("oauth callback failed", {
      reason: "token_exchange_or_identity_failure",
      message: error instanceof Error ? error.message : "unknown_error",
      query_code_present: Boolean(code),
      query_state_present: Boolean(returnedState),
      stored_state_present: Boolean(cookies[STATE_COOKIE]),
      pkce_verifier_present: Boolean(verifier),
      redirect_uri: safeRedirectUri(req),
    });
    return res.status(503).json({ ok: false, error: "Vercel sign-in unavailable" });
  }
};

function safeRedirectUri(req) {
  try {
    return redirectUri(req);
  } catch (_) {
    return "unavailable";
  }
}

function cryptoSafeEqual(left, right) {
  const a = Buffer.from(String(left));
  const b = Buffer.from(String(right));
  return a.length === b.length && require("crypto").timingSafeEqual(a, b);
}
