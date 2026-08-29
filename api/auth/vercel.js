const { authorizationUrl, cookie, state, STATE_COOKIE } = require("../_vercel-auth");

module.exports = function handler(req, res) {
  try {
    const csrfState = state();
    res.setHeader("Set-Cookie", cookie(STATE_COOKIE, csrfState, 600));
    res.writeHead(302, { Location: authorizationUrl(req, csrfState) });
    return res.end();
  } catch (error) {
    return res.status(503).json({ ok: false, error: error.message });
  }
};
