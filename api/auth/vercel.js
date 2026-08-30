const {
  authorizationUrl,
  cookie,
  pkceChallenge,
  pkceVerifier,
  state,
  PKCE_COOKIE,
  STATE_COOKIE,
} = require("../_vercel-auth");

module.exports = function handler(req, res) {
  try {
    const csrfState = state();
    const verifier = pkceVerifier();
    const challenge = pkceChallenge(verifier);
    res.setHeader("Set-Cookie", [
      cookie(STATE_COOKIE, csrfState, 600),
      cookie(PKCE_COOKIE, verifier, 600),
    ]);
    res.writeHead(302, { Location: authorizationUrl(req, csrfState, challenge) });
    return res.end();
  } catch (error) {
    return res.status(503).json({ ok: false, error: error.message });
  }
};
