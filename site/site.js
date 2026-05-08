const corpusBase = 'https://github.com/alias8818/enoch-ai-research-corpus/blob/main/';
const cards = document.getElementById('cards');
const esc = (value) => String(value ?? '').replace(/[&<>"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));

function renderManifest(manifest) {
  const artifactCount = document.getElementById('artifactCount');
  const gatePassCount = document.getElementById('gatePassCount');
  const manifestNote = document.getElementById('manifestNote');
  const strictAuditCount = document.getElementById('strictAuditCount');
  if (!manifest || !Number.isFinite(Number(manifest.artifact_count)) || !Number.isFinite(Number(manifest.packaging_provenance_pass_count)) || !Number.isFinite(Number(manifest.strict_claim_evidence_pass_count))) {
    throw new Error('manifest missing required counts');
  }
  const total = Number(manifest.artifact_count);
  const strictPass = Number(manifest.strict_claim_evidence_pass_count);
  const strictTotal = Number(manifest.strict_claim_evidence_total_count || manifest.artifact_count);
  const strictBlocked = Math.max(strictTotal - strictPass, 0);
  artifactCount.textContent = total.toLocaleString();
  gatePassCount.textContent = `${Number(manifest.packaging_provenance_pass_count).toLocaleString()}/${total.toLocaleString()}`;
  strictAuditCount.textContent = `${strictPass.toLocaleString()}/${strictTotal.toLocaleString()}`;
  manifestNote.innerHTML = `Strict audit passes ${strictPass.toLocaleString()}/${strictTotal.toLocaleString()}; ${strictBlocked.toLocaleString()} failed claims stay visible because the gate is the product. <a href="#strict-pass-examples">See the ${strictPass.toLocaleString()} that pass →</a>`;
}

fetch('ecosystem.json', {cache: 'no-cache'})
  .then((response) => {
    if (!response.ok) throw new Error(`manifest HTTP ${response.status}`);
    return response.json();
  })
  .then(renderManifest)
  .catch(() => {
    const manifestNote = document.getElementById('manifestNote');
    if (manifestNote) manifestNote.textContent = 'Manifest unavailable; open site/ecosystem.json or the corpus index before relying on counts.';
  });

fetch('highlights.json')
  .then((response) => response.json())
  .then((data) => {
    cards.innerHTML = data.featured.map((item) => `
      <article class="card">
        <div class="card-main">
          <div class="card-kicker"><span class="tag">${esc(item.category)}</span><span>${esc(item.public_id)}</span></div>
          <h3>${esc(item.title)}</h3>
          <p>${esc(item.why_it_matters)}</p>
        </div>
        <div class="card-proof">
          <p class="result"><strong>Reported result:</strong> ${esc(item.result)}</p>
          <p><strong>Bounded by:</strong> ${esc(item.bounds)}</p>
          <p><strong>Gate:</strong> ${esc(item.gate_scope || 'packaging/provenance')} lint; strict claim/evidence audit is separate.</p>
          ${item.falsification_prompt ? `<p><strong>Falsify:</strong> ${esc(item.falsification_prompt)}</p>` : ''}
          <a class="artifact-link" href="${corpusBase + encodeURI(item.paper_path)}">Read artifact →</a>
        </div>
      </article>`).join('');
  })
  .catch(() => {
    cards.innerHTML = '<p class="copy">Could not load highlight data. Open <code>site/highlights.json</code> directly.</p>';
  });
