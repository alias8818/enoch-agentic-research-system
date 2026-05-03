const corpusBase = 'https://github.com/alias8818/enoch-ai-research-corpus/blob/main/';
const cards = document.getElementById('cards');
const esc = (value) => String(value ?? '').replace(/[&<>"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));

function renderManifest(manifest) {
  const artifactCount = document.getElementById('artifactCount');
  const gatePassCount = document.getElementById('gatePassCount');
  const manifestNote = document.getElementById('manifestNote');
  if (!manifest || !Number.isFinite(Number(manifest.artifact_count)) || !Number.isFinite(Number(manifest.packaging_provenance_pass_count))) {
    throw new Error('manifest missing required counts');
  }
  artifactCount.textContent = Number(manifest.artifact_count).toLocaleString();
  gatePassCount.textContent = `${Number(manifest.packaging_provenance_pass_count).toLocaleString()}/${Number(manifest.artifact_count).toLocaleString()}`;
  manifestNote.textContent = `Gate: ${manifest.gate_name || 'packaging_provenance_gate'} ${manifest.gate_version || ''}. Not validated: scientific correctness, peer review, or independent replication.`;
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
        <span class="tag">${esc(item.category)}</span>
        <h3>${esc(item.title)}</h3>
        <p>${esc(item.why_it_matters)}</p>
        <p class="result"><strong>Reported result:</strong> ${esc(item.result)}</p>
        <p><strong>Bounded by:</strong> ${esc(item.bounds)}</p>
        <p><strong>Gate scope:</strong> ${esc(item.gate_scope || 'packaging/provenance')} checks; not peer-reviewed or independently replicated unless the artifact says so.</p>
        ${item.falsification_prompt ? `<p><strong>Falsification prompt:</strong> ${esc(item.falsification_prompt)}</p>` : ''}
        <div class="meta"><span>${esc(item.public_id)}</span><a href="${corpusBase + encodeURI(item.paper_path)}">Read artifact</a></div>
      </article>`).join('');
  })
  .catch(() => {
    cards.innerHTML = '<p class="copy">Could not load highlight data. Open <code>site/highlights.json</code> directly.</p>';
  });
