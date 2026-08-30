const crypto = require("crypto");

const ACCESS_COOKIE = "warden_vercel_access";
const STATE_COOKIE = "warden_vercel_state";
const PKCE_COOKIE = "warden_vercel_pkce";
const AUTHORIZATION_ENDPOINT = "https://vercel.com/oauth/authorize";
const TOKEN_ENDPOINT = "https://api.vercel.com/login/oauth/token";
const USERINFO_ENDPOINT = "https://api.vercel.com/login/oauth/userinfo";

const text = (value) => String(value || "").trim();

function parseCookies(header) {
  return String(header || "")
    .split(";")
    .map((part) => part.trim().split("="))
    .filter((parts) => parts.length >= 2)
    .reduce((cookies, [name, ...value]) => {
      cookies[name] = decodeURIComponent(value.join("="));
      return cookies;
    }, {});
}

function cookie(name, value, maxAge) {
  return name + "=" + encodeURIComponent(value) + "; Path=/; Max-Age=" + maxAge + "; HttpOnly; Secure; SameSite=Lax";
}

function redirectUri(req) {
  const configured = text(process.env.VERCEL_AUTH_REDIRECT_URI);
  if (configured) return configured;
  const host = text(req.headers["x-forwarded-host"] || req.headers.host).split(",")[0].trim();
  if (!host) throw new Error("VERCEL_AUTH_REDIRECT_URI or request host is required");
  return "https://" + host + "/api/auth/callback";
}

function allowedEmails() {
  return new Set(text(process.env.WARDEN_ALLOWED_VERCEL_EMAILS)
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean));
}

function oauthConfigured() {
  return Boolean(
    text(process.env.VERCEL_CLIENT_ID) &&
    text(process.env.VERCEL_CLIENT_SECRET)
  );
}

function requireOAuthConfiguration() {
  if (!oauthConfigured()) throw new Error("Sign in with Vercel is not configured");
  if (!allowedEmails().size) throw new Error("WARDEN_ALLOWED_VERCEL_EMAILS is not configured");
}

function state() {
  return crypto.randomBytes(32).toString("base64url");
}

function pkceVerifier() {
  return crypto.randomBytes(32).toString("base64url");
}

function pkceChallenge(verifier) {
  const value = text(verifier);
  if (!value) throw new Error("PKCE verifier is required");
  return crypto.createHash("sha256").update(value).digest("base64url");
}

function authorizationUrl(req, csrfState, codeChallenge) {
  requireOAuthConfiguration();
  const challenge = text(codeChallenge);
  if (!challenge) throw new Error("PKCE challenge is required");
  const url = new URL(AUTHORIZATION_ENDPOINT);
  url.searchParams.set("client_id", text(process.env.VERCEL_CLIENT_ID));
  url.searchParams.set("scope", "openid email profile");
  url.searchParams.set("redirect_uri", redirectUri(req));
  url.searchParams.set("response_type", "code");
  url.searchParams.set("state", csrfState);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  return url.toString();
}

async function exchangeCode(req, code, codeVerifier) {
  requireOAuthConfiguration();
  const verifier = text(codeVerifier);
  if (!verifier) throw new Error("PKCE verifier is required");
  const params = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: text(process.env.VERCEL_CLIENT_ID),
    client_secret: text(process.env.VERCEL_CLIENT_SECRET),
    code,
    code_verifier: verifier,
    redirect_uri: redirectUri(req),
  });
  const response = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: params,
  });
  if (!response.ok) throw new Error("Vercel token exchange failed (" + response.status + ")");
  const body = await response.json();
  if (!text(body.access_token)) throw new Error("Vercel token exchange returned no access token");
  return body;
}

async function userFromAccessToken(accessToken) {
  const response = await fetch(USERINFO_ENDPOINT, {
    method: "POST",
    headers: { authorization: "Bearer " + accessToken },
  });
  if (!response.ok) return null;
  const user = await response.json();
  const allowed = allowedEmails();
  const email = text(user.email).toLowerCase();
  if (!email || !allowed.has(email)) return { denied: true, email: email || null };
  return {
    sub: text(user.sub),
    email,
    email_verified: Boolean(user.email_verified),
    name: text(user.name),
    preferred_username: text(user.preferred_username),
    picture: text(user.picture),
  };
}

async function currentUser(req) {
  if (!oauthConfigured()) return null;
  const accessToken = parseCookies(req.headers.cookie)[ACCESS_COOKIE];
  if (!accessToken) return null;
  return userFromAccessToken(accessToken);
}

module.exports = {
  ACCESS_COOKIE,
  STATE_COOKIE,
  PKCE_COOKIE,
  allowedEmails,
  authorizationUrl,
  cookie,
  currentUser,
  exchangeCode,
  oauthConfigured,
  parseCookies,
  pkceChallenge,
  pkceVerifier,
  redirectUri,
  requireOAuthConfiguration,
  state,
};
