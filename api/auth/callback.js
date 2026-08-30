const {
  ACCESS_COOKIE,
  PKCE_COOKIE,
  STATE_COOKIE,
  cookie,
  currentUser,
  exchangeCode,
  parseCookies,
} = require("../_vercel-auth");

module.exports = async function handler(req, res) {
  const query = req.query || {};
  const code = String(query.code || "");
  const returnedState = String(query.state || "");
  const cookies = parseCookies(req.headers.cookie);
  const verifier = String(cookies[PKCE_COOKIE] || "");
  if (
    !code ||
    !returnedState ||
    !cookies[STATE_COOKIE] ||
    !verifier ||
    !cryptoSafeEqual(returnedState, cookies[STATE_COOKIE])
  ) {
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
    return res.status(503).json({ ok: false, error: "Vercel sign-in unavailable" });
  }
};

function cryptoSafeEqual(left, right) {
  const a = Buffer.from(String(left));
  const b = Buffer.from(String(right));
  return a.length === b.length && require("crypto").timingSafeEqual(a, b);
}
