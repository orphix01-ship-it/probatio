const ROOT = require('path').resolve(__dirname, '../..');
const V = require(ROOT + '/probatio/site_assets/verify.js');
const fs = require('fs'), path = require('path');
const probs = {};
for (const f of fs.readdirSync(ROOT + '/problems')) for (const p of JSON.parse(fs.readFileSync(ROOT + '/problems/'+f))) probs[p.id]=p;
(async () => {
  let ok = 0, bad = 0;
  const dirs = [ROOT + '/results/certs', ROOT + '/results/study-v1/certs', ROOT + '/results/study-v2/certs', process.env.EXTRA_CERTS].filter(d => d && fs.existsSync(d));
  const dir = dirs[0];
  const allCerts = dirs.flatMap(d => fs.readdirSync(d).map(f => path.join(d, f)));
  for (const f of allCerts) {
    const raw = fs.readFileSync(f, 'utf8');
    const cert = JSON.parse(raw);
    const r = V.check(probs[cert.problem_id], cert.candidate);
    const sc = cert.verdict.score;
    const keys = sc.marks !== undefined ? ['marks','length'] : sc.size !== undefined ? ['n','size'] : sc.min_dist_sq !== undefined ? ['n','min_dist_sq'] : sc.A_d !== undefined ? ['n','k','d','A_d'] : ['n','k','d','d_lower'];
    const same = r.valid && keys.every(k => r.score[k] === cert.verdict.score[k]);
    same ? ok++ : (bad++, console.log('MISMATCH', f, r.reason, JSON.stringify(r.score), JSON.stringify(cert.verdict.score)));
  }
  // live-proof traces must end at the same distance / length as the checker
  for (const f of allCerts) {
    const cert = JSON.parse(fs.readFileSync(f, 'utf8'));
    if (cert.candidate.generators) {
      let last; for (const ev of V.traceCode(cert.candidate.generators)) last = ev;
      if (last.type !== 'found' || last.w !== cert.verdict.score.d) { bad++; console.log('TRACE MISMATCH', f, last); }
    } else if (cert.candidate.marks) {
      let last; for (const ev of V.traceGolomb(cert.candidate.marks)) last = ev;
      if (last.type !== 'done') { bad++; console.log('GOLOMB TRACE MISMATCH', f); }
    }
  }
  // GF(2) rank trace must give rank = n - k for every code certificate
  for (const f of allCerts) {
    const cert = JSON.parse(fs.readFileSync(f, 'utf8'));
    if (!cert.candidate.generators) continue;
    let last; for (const ev of V.traceRank(cert.candidate.generators)) last = ev;
    const sc = cert.verdict.score;
    if (last.rank !== sc.n - sc.k) { bad++; console.log('RANK MISMATCH', f, last.rank, sc.n - sc.k); }
    if (V.commutationMatrix(cert.candidate.generators).flat().some(x => x)) { bad++; console.log('COMMUTATION MISMATCH', f); }
  }
  // a broken ruler must end in a clash
  { let last; for (const ev of V.traceGolomb([0, 1, 3, 4])) last = ev; if (last.type !== 'fail') { bad++; console.log('trace missed clash'); } }
  // SHA-256 fallback vs node crypto
  const c = require('crypto');
  for (const s of ['', 'abc', 'x'.repeat(1000), 'Ωmega ✓']) {
    if (V.sha256Fallback(new TextEncoder().encode(s)) !== c.createHash('sha256').update(s).digest('hex')) { bad++; console.log('SHA MISMATCH', s); }
  }
  console.log(`js-verifier: ${ok} certificates agree, ${bad} mismatches`);
  process.exit(bad ? 1 : 0);
})();
