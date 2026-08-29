/* Authenticated Vercel -> private Cloud Run bridge.
 *
 * Required Vercel runtime variables:
 *   GCP_CLOUD_RUN_URL
 *   GCP_WORKLOAD_IDENTITY_PROVIDER
 *   GCP_SERVICE_ACCOUNT
 *   VERCEL_OIDC_TOKEN (provided by Vercel when OIDC is enabled)
 *
 * No service-account key is accepted here. The function exchanges the
 * short-lived Vercel OIDC subject token for a short-lived Google access token,
 * then mints a Cloud Run audience-bound ID token.
 */

const text = (value) => String(value || "").trim();

async function vercelSubjectToken() {
  // Vercel's helper handles runtime token retrieval in deployments where the
  // system variable is not directly materialized in process.env.
  try {
    const { getVercelOidcToken } = await import("@vercel/oidc");
    return text(await getVercelOidcToken());
  } catch (_) {
    return text(process.env.VERCEL_OIDC_TOKEN);
  }
}

async function googleAccessToken() {
  const subjectToken = await vercelSubjectToken();
  const provider = text(process.env.GCP_WORKLOAD_IDENTITY_PROVIDER);
  const serviceAccount = text(process.env.GCP_SERVICE_ACCOUNT);
  if (!subjectToken || !provider || !serviceAccount) {
    throw new Error("Vercel OIDC/WIF is not configured");
  }

  const sts = await fetch("https://sts.googleapis.com/v1/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:token-exchange",
      audience: provider.startsWith("//") ? provider : `//iam.googleapis.com/${provider}`,
      scope: "https://www.googleapis.com/auth/cloud-platform",
      requested_token_type: "urn:ietf:params:oauth:token-type:access_token",
      subject_token_type: "urn:ietf:params:oauth:token-type:jwt",
      subject_token: subjectToken,
    }),
  });
  if (!sts.ok) {
    const detail = await sts.text();
    console.error(`Google STS rejected Vercel OIDC (${sts.status}): ${detail.slice(0, 500)}`);
    throw new Error(`Google STS rejected Vercel OIDC (${sts.status})`);
  }
  const stsBody = await sts.json();
  if (!stsBody.access_token) throw new Error("Google STS returned no access token");

  const iam = await fetch(
    `https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${encodeURIComponent(serviceAccount)}:generateIdToken`,
    {
      method: "POST",
      headers: {
        authorization: `Bearer ${stsBody.access_token}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        audience: text(process.env.GCP_CLOUD_RUN_URL),
        includeEmail: true,
      }),
    },
  );
  if (!iam.ok) throw new Error(`Google IAM Credentials rejected WIF (${iam.status})`);
  const iamBody = await iam.json();
  if (!iamBody.token) throw new Error("Google IAM Credentials returned no ID token");
  return iamBody.token;
}

module.exports = async function handler(req, res) {
  const consoleToken = text(process.env.WARDEN_CONSOLE_TOKEN);
  const presentedToken = text(req.headers["x-warden-console-token"]);
  if (!consoleToken || presentedToken !== consoleToken) {
    return res.status(401).json({ ok: false, error: "Warden console authentication required" });
  }
  const cloudRunUrl = text(process.env.GCP_CLOUD_RUN_URL).replace(/\/$/, "");
  if (!cloudRunUrl) return res.status(503).json({ ok: false, error: "GCP_CLOUD_RUN_URL is not configured" });

  const rawPath = req.query.path ?? req.query["...path"];
  const pathValues = Array.isArray(rawPath) ? rawPath : [rawPath];
  const segments = pathValues.flatMap((value) => text(value).split("/").filter(Boolean));
  const target = `${cloudRunUrl}/api/mcharness/${segments.map(encodeURIComponent).join("/")}`;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(req.query)) {
    if (key === "path" || key === "...path") continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, String(item));
  }

  try {
    const idToken = await googleAccessToken();
    const upstream = await fetch(`${target}${query.toString() ? `?${query}` : ""}`, {
      method: req.method,
      headers: {
        authorization: `Bearer ${idToken}`,
        "content-type": req.headers["content-type"] || "application/json",
        accept: req.headers.accept || "application/json",
      },
      body: ["GET", "HEAD"].includes(req.method) ? undefined : JSON.stringify(req.body || {}),
    });
    res.status(upstream.status);
    const contentType = upstream.headers.get("content-type");
    if (contentType) res.setHeader("content-type", contentType);
    const body = Buffer.from(await upstream.arrayBuffer());
    return res.send(body);
  } catch (error) {
    return res.status(503).json({ ok: false, error: "Authenticated GCP bridge unavailable", detail: String(error.message || error) });
  }
}
