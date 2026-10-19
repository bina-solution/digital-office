# Notices

DGO — the digital office — Copyright (C) 2026 Bina Solutions.

DGO is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public
License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
version. The full text is in [LICENSE](LICENSE). Section 13 applies: if you run a modified version as a network
service, you must offer its users the corresponding source.

## Third-party components

These parts are not Bina Solutions' work. Each keeps its own license, and its notice stays with it.

| Component | Where | License | Copyright |
|---|---|---|---|
| qr-scanner | `apps/dgo-extend/static/vendor/qr-scanner/` | MIT (its `LICENSE` is kept beside it) | © 2017 Nimiq, danimoh |
| qrcode | `apps/dgo-extend/static/vendor/qrcode/` | MIT (see the note kept beside it) | © its authors |
| RevoGrid | `apps/my-docs/static/vendor/revo-grid/` | MIT (text below) | © Revolist OU |
| any-concurrency | `apps/any-concurrency/` | MIT (its `LICENSE` is kept beside it) | © 2024 any-concurrency contributors |
| Agent presets derived from `@deepseek-ai/dsh-agent-presets` | `apps/bina-ds/harness/profile/agent-presets/` | MIT (text below) | © 2026 DeepSeek |
| Heebo font | `apps/apitools/src/doc_gen/fonts/Heebo.ttf` | SIL Open Font License 1.1 ([LICENSES/OFL-1.1-Heebo.txt](LICENSES/OFL-1.1-Heebo.txt)) | © 2014 The Heebo Project Authors |
| Rubik font | `apps/apitools/src/doc_gen/fonts/Rubik.ttf` | SIL Open Font License 1.1 ([LICENSES/OFL-1.1-Rubik.txt](LICENSES/OFL-1.1-Rubik.txt)) | © 2015 The Rubik Project Authors |
| Tesseract trained data (`eng`, `heb`) | `apps/apitools/src/ocr_core/tessdata/` | Apache License 2.0 ([LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt)) | © Google and the tesseract-ocr contributors |

The packages under `apps/bina-ds/plugins/` are Bina Solutions' own work. Their `package.json` files declare the MIT
license, and that grant stands for those packages.

Container images that the stack pulls at run time (n8n, authentik, traefik, postgres, redis, Plane and others) are not
part of this repository. Each is used under its own license.

## The MIT License (for RevoGrid and the DeepSeek agent presets)

Copyright (c) Revolist OU
Copyright (c) 2026 DeepSeek

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## What this release leaves out

This public tree is a snapshot of the private development branch `dgo-stable`. It leaves out the following:

- client and personal data: document scans, chat exports, data sets, operational captures, screenshots of live systems;
- internal agent memory and the retired archive;
- one proprietary font, which is not redistributable.

Credentials found in example and test files are replaced by placeholders (`CHANGE_ME`, `REDACTED-…`). Personal email
addresses and phone numbers in fixtures are replaced by synthetic ones (`personN@example.com`, `050-000-NNNN`).
