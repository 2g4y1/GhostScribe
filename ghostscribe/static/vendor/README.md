# Third-party libraries

Unmodified release builds, served from here so that the web interface works offline and loads nothing from a CDN.

| File | Library | Version | License |
|---|---|---|---|
| `marked.umd.js` | [marked](https://github.com/markedjs/marked) (`lib/marked.umd.js` of the npm package) | 18.0.14 | MIT, see `LICENSE-marked.txt` |
| `purify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) (`dist/purify.min.js` of the npm package) | 3.4.16 | Apache-2.0 (chosen of Apache-2.0 or MPL-2.0), see `LICENSE-dompurify.txt` |

To update, download the new npm package (`npm pack marked@<version> dompurify@<version>`), copy the files named above
and the license files, update the versions in this table and check that the SHA-256 checksums of the copies match the
files in the packages.
