# Vendored browser dependency

`vis-network.min.js` is the standalone UMD build of
[vis-network](https://visjs.github.io/vis-network/) 10.1.5, fetched from
<https://unpkg.com/vis-network/standalone/umd/vis-network.min.js>.

It is vendored so the local viewer works offline and the page can run under a
strict `script-src 'self'` Content-Security-Policy. vis-network is dual
licensed under Apache-2.0 and MIT; the license header is retained in the
minified file. See the repository `NOTICE` for attribution.
