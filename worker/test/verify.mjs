// Usage: node verify.mjs <goodToken> <badToken> <secret>  -> prints claims JSON, then "null" for the bad one.
import { verifyToken } from "../src/index.js";
const [good, bad, secret] = process.argv.slice(2);
console.log(JSON.stringify(await verifyToken(good, secret)));
console.log(JSON.stringify(await verifyToken(bad, secret)));
