const ROOT = require('path').resolve(__dirname, '../..');
const V = require(ROOT + '/probatio/site_assets/verify.js');
const fs = require('fs'), path = require('path');
const probs = {};
for (const f of fs.readdirSync(ROOT + '/problems')) for (const p of JSON.parse(fs.readFileSync(ROOT + '/problems/'+f))) probs[p.id]=p;
(async () => {
  let ok = 0, bad = 0;
  const dir = ROOT + '/results/certs';
  for (const f of fs.readdirSync(dir)) {
    const raw = fs.readFileSync(path.join(dir, f), 'utf8');
    const cert = JSON.parse(raw);
    const r = V.check(probs[cert.problem_id], cert.candidate);
    const keys = cert.verdict.score.marks !== undefined ? ['marks','length'] : ['n','k','d','d_lower'];
    const same = r.valid && keys.every(k => r.score[k] === cert.verdict.score[k]);
    same ? ok++ : (bad++, console.log('MISMATCH', f, r.reason, JSON.stringify(r.score), JSON.stringify(cert.verdict.score)));
  }
  // SHA-256 fallback vs node crypto
  const c = require('crypto');
  for (const s of ['', 'abc', 'x'.repeat(1000), 'Ωmega ✓']) {
    if (V.sha256Fallback(new TextEncoder().encode(s)) !== c.createHash('sha256').update(s).digest('hex')) { bad++; console.log('SHA MISMATCH', s); }
  }
  console.log(`js-verifier: ${ok} certificates agree, ${bad} mismatches`);
  process.exit(bad ? 1 : 0);
})();
