// Vercel's static router does not consistently dispatch nested catch-all
// paths in a framework-less project. The rewrite in vercel.json normalizes
// them to this stable function endpoint.
module.exports = require("./mcharness/[...path].js");
