const { ACCESS_COOKIE, cookie } = require("../_vercel-auth");

module.exports = function handler(_req, res) {
  res.setHeader("Set-Cookie", cookie(ACCESS_COOKIE, "", 0));
  res.writeHead(302, { Location: "/" });
  return res.end();
};
