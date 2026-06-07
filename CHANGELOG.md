# Changelog

## [0.9.0](https://github.com/tjboudreaux/hermes-wiki/compare/v0.8.0...v0.9.0) (2026-06-07)


### Features

* video modality — scene keyframes + transcript composition (design PR4) ([681628e](https://github.com/tjboudreaux/hermes-wiki/commit/681628ef98e41191e6ad7665cd62ed388c172970))
* **video:** scene keyframes + audio-track transcription composition ([4dca86b](https://github.com/tjboudreaux/hermes-wiki/commit/4dca86b3cd25dbc408821ced24c1e6cf83bfd9fa))

## [0.8.0](https://github.com/tjboudreaux/hermes-wiki/compare/v0.7.0...v0.8.0) (2026-06-07)


### Features

* audio modality — faster-whisper transcription with hh:mm:ss anchors (design PR3) ([66e4277](https://github.com/tjboudreaux/hermes-wiki/commit/66e427761419aba2c0bdfd6f12f6823b5346d18a))
* **audio:** faster-whisper transcription with timestamped anchors ([02905e3](https://github.com/tjboudreaux/hermes-wiki/commit/02905e337117c40109d1778f267781bb0a1b0bab))

## [0.7.0](https://github.com/tjboudreaux/hermes-wiki/compare/v0.6.0...v0.7.0) (2026-06-07)


### Features

* image modality — Pillow metadata + OCR, captioning protocol (design PR2) ([d9853ee](https://github.com/tjboudreaux/hermes-wiki/commit/d9853ee50740be17677b5ad89934eba7106b3ed8))
* **image:** Pillow metadata extraction, best-effort OCR, embed pages ([a45dfd5](https://github.com/tjboudreaux/hermes-wiki/commit/a45dfd56279512c64f6b8b83c0f6514fe1ef3523))

## [0.6.0](https://github.com/tjboudreaux/hermes-wiki/compare/v0.5.0...v0.6.0) (2026-06-07)


### Features

* **evals:** PDF extraction gates, golden, live pdf skill reference ([5fa9dc8](https://github.com/tjboudreaux/hermes-wiki/commit/5fa9dc81d4cb67e738fc3e2dc165bf44cbcad093))
* PDF modality — pdfplumber extraction with page anchors (design PR1) ([46b7855](https://github.com/tjboudreaux/hermes-wiki/commit/46b7855b3dfb97eff3c0dbb9c0b58e1d4b747c95))
* **pdf:** pdfplumber extraction processor and DerivedArtifact protocol ([cac40c5](https://github.com/tjboudreaux/hermes-wiki/commit/cac40c5120ae93eafb822f5d5a53f650d27d788a))

## [0.5.0](https://github.com/tjboudreaux/hermes-wiki/compare/v0.4.1...v0.5.0) (2026-06-07)


### Features

* **classifiers:** built-in image/audio/video detection ([f9e6fb3](https://github.com/tjboudreaux/hermes-wiki/commit/f9e6fb35fc1b304ca407d35dea360916cd4e82d7))
* **evals:** media micro-corpus, plumbing lane, and eval_media skeleton ([aaee4ca](https://github.com/tjboudreaux/hermes-wiki/commit/aaee4ca45fef16d6aad4c0ac1b57496ebc297187))
* media ingestion foundations (design PR0) ([9f1457f](https://github.com/tjboudreaux/hermes-wiki/commit/9f1457fc1e5cfd11fd806b4dc26fb08dd271989a))
* **media:** foundations module — manifests, storage tiers, preflights ([5bef9aa](https://github.com/tjboudreaux/hermes-wiki/commit/5bef9aa315c73268ec16a787ceb8f828d7925db5))
* **pipeline:** two-tier media ingest, stub processor, provenance manifests ([cffda32](https://github.com/tjboudreaux/hermes-wiki/commit/cffda3219d67d512b944ea963c51a86ecc51c022))
* **skills:** media skill kind and wiki-media-ingestion scaffold ([0139055](https://github.com/tjboudreaux/hermes-wiki/commit/013905554c79c763a2fe9fa074f115ee1c67714e))

## [0.4.1](https://github.com/tjboudreaux/hermes-wiki/compare/v0.4.0...v0.4.1) (2026-06-07)


### Documentation

* media ingestion design — decision record and build plan ([b9469df](https://github.com/tjboudreaux/hermes-wiki/commit/b9469df04c8234f41b5b6d4bc309bb5a158cbfd7))
* media ingestion design — decision record and build plan (D1–D11) ([b137f9b](https://github.com/tjboudreaux/hermes-wiki/commit/b137f9bc78e52584f3951662b30a6d6a675d7439))

## [0.4.0](https://github.com/tjboudreaux/hermes-wiki/compare/v0.3.0...v0.4.0) (2026-06-07)


### Features

* **prompt:** instruct agents to load assigned wiki skills before writing ([60d17b9](https://github.com/tjboudreaux/hermes-wiki/commit/60d17b9847fece9c830ceb653ae0ef673d9b010b))
* **prompt:** load assigned wiki skills before writing (F9) ([641a273](https://github.com/tjboudreaux/hermes-wiki/commit/641a273398517964fae3ee208da4f4b72852045a))

## [0.3.0](https://github.com/tjboudreaux/hermes-wiki/compare/v0.2.0...v0.3.0) (2026-06-07)


### Features

* **api:** expose per-wiki skill assignment endpoints ([54bd536](https://github.com/tjboudreaux/hermes-wiki/commit/54bd536f6ab500ed447da769d674de595eea71b2))
* **cli:** add wiki skills show/set commands ([848267e](https://github.com/tjboudreaux/hermes-wiki/commit/848267e8334f118c0e0b555ad4d9a899f9d72b83))
* **dashboard:** add per-wiki skills settings card ([8758fbf](https://github.com/tjboudreaux/hermes-wiki/commit/8758fbf053b64d821c3a228ea17cedffd962c993))
* **evals:** add skill-behavior eval cases and corpus sources ([cba0adb](https://github.com/tjboudreaux/hermes-wiki/commit/cba0adbc37f6fd7c6e57d1689f5f46c912ecce9c))
* **evals:** pytest eval harness, BM25 baseline gate, and graph metrics ([3c25c6d](https://github.com/tjboudreaux/hermes-wiki/commit/3c25c6d26e89b2de4af038c42cf04f2f3df6df45))
* **lint:** add unresolved_citation check; ci: coverage floor + golden snapshots ([b47d56d](https://github.com/tjboudreaux/hermes-wiki/commit/b47d56d54545921ed7efcad8a7ea46e6cb6989e4))
* **skills:** package wiki skills and register them with Hermes ([9614040](https://github.com/tjboudreaux/hermes-wiki/commit/9614040e6d0f931df0678aec43edb669067a70a1))
* **skills:** per-wiki skill assignments stored in SCHEMA.md ([a31bbf7](https://github.com/tjboudreaux/hermes-wiki/commit/a31bbf731fe41421adc24b21db0b9f6faaa323ec))
* **skills:** port upstream synthesis/dedup/contradiction protocols ([1d5abbb](https://github.com/tjboudreaux/hermes-wiki/commit/1d5abbb82103019a2e6031f92f035a21cb31ec5f))
* wiki skills, per-wiki skill assignments, and hooks architecture ([0f2d1d4](https://github.com/tjboudreaux/hermes-wiki/commit/0f2d1d4fc2d47da3141a584f2b041f580cb5bb10))


### Bug Fixes

* **dashboard:** unlink multipart upload temp file after ingest ([13b5167](https://github.com/tjboudreaux/hermes-wiki/commit/13b516704714576c5ec4f8d33f549404fcaaa220))
* **lint:** keep confirmed kanban findings on mid-scan unavailability ([4961025](https://github.com/tjboudreaux/hermes-wiki/commit/4961025c3d1b83e30935531b11aafa645b8f2b27))
* **pipeline:** correct keyword-only param handling in processor dispatch ([100b3b4](https://github.com/tjboudreaux/hermes-wiki/commit/100b3b4153167c2228798213e9b607ef6628410f))
* **pipeline:** size-check the new content in write_inbox_file ([93e6cfd](https://github.com/tjboudreaux/hermes-wiki/commit/93e6cfd58b93dc982dbd8b9fd073fffbf12dae90))
* **trust:** quote the author scalar in SCHEMA.md trust blocks ([dc6168e](https://github.com/tjboudreaux/hermes-wiki/commit/dc6168ee69a67a9b8456783dbeda8e05b490b4d2))


### Performance Improvements

* **db:** only rebuild the FTS index when pages_fts is first created ([a796c00](https://github.com/tjboudreaux/hermes-wiki/commit/a796c0063cd73b51b082ec1603118c99253fd64e))


### Documentation

* add quality audit and improvement roadmap ([b64c0e9](https://github.com/tjboudreaux/hermes-wiki/commit/b64c0e975a8f9e1fb7585374cafa8eb757b7823e))
* **audit:** record verified skill-precedence findings, add F9 ([a1b779c](https://github.com/tjboudreaux/hermes-wiki/commit/a1b779c73e5c1875ecafae4f101bf8450ac73137))
* per-wiki hooks architecture and skills CLI reference ([ee19074](https://github.com/tjboudreaux/hermes-wiki/commit/ee190740f4b72572026de60e7c092a9d9803cc26))
* split bundled llm-wiki skill decision by layer in CONTEXT.md ([081515e](https://github.com/tjboudreaux/hermes-wiki/commit/081515ea3148e4f51a12461039c13f48ff4265e2))

## [0.2.0](https://github.com/tjboudreaux/hermes-wiki/compare/v0.1.0...v0.2.0) (2026-06-06)


### Features

* **api:** expose inbox file GET/PUT/DELETE endpoints ([b4cfa25](https://github.com/tjboudreaux/hermes-wiki/commit/b4cfa257dc65d36304611066609c7b2dbf2377b6))
* **dashboard:** add inbox file editor route with save and delete ([ef4a36d](https://github.com/tjboudreaux/hermes-wiki/commit/ef4a36d3d62d2d9ac7b7a4f961e944a2266f9c6f))
* inbox file editing and automated semantic versioning ([c235abc](https://github.com/tjboudreaux/hermes-wiki/commit/c235abc478d3265bb717773b35aa1546b9e6c24d))
* **inbox:** add read, edit, and delete pipeline functions for inbox files ([d087b9e](https://github.com/tjboudreaux/hermes-wiki/commit/d087b9eecfb63437b09f6e4bb58c9c1f773c66b4))


### Documentation

* document Conventional Commits and automated releases ([12c06e9](https://github.com/tjboudreaux/hermes-wiki/commit/12c06e9de0d8b825911863d7fa9b67b2941305d4))
