const { currentUser, oauthConfigured } = require("../_vercel-auth");

module.exports = async function handler(req, res) {
  if (!oauthConfigured()) return res.status(503).json({ ok: false, configured: false });
  try {
    const user = await currentUser(req);
    if (!user || user.denied) return res.status(401).json({ ok: false, authenticated: false });
    return res.status(200).json({ ok: true, authenticated: true, user });
  } catch (_) {
    return res.status(503).json({ ok: false, error: "Vercel identity provider unavailable" });
  }
};
