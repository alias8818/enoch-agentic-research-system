# Enoch launch site

This is a static, no-build launch site. It can be served locally or published through GitHub Pages / any static host.

Local preview:

```bash
cd site
python3 -m http.server 8080
```

Open `http://127.0.0.1:8080`.

The site intentionally links to the code and corpus repositories but does not embed private runtime state, credentials, or generated local config.
