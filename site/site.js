const corpusBase = 'https://github.com/alias8818/enoch-ai-research-corpus/blob/main/';
const cards = document.getElementById('cards');
const esc = (value) => String(value ?? '').replace(/[&<>"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
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
        <div class="meta"><span>${esc(item.public_id)}</span><a href="${corpusBase + encodeURI(item.paper_path)}">Read artifact</a></div>
      </article>`).join('');
  })
  .catch(() => {
    cards.innerHTML = '<p class="copy">Could not load highlight data. Open <code>site/highlights.json</code> directly.</p>';
  });
