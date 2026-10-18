# USB integration fixtures

`usb/` contains synthetic, redistributable exports in the real DeviceSQL PDB and
SQLCipher-encrypted OneLibrary formats. The tables/columns used in the encrypted
fixture follow the actual export schema; this is not an unencrypted generic
SQLite stand-in. Its schema includes only the tables/columns consumed by the
reader. It was generated independently of the production reader. The generator is
covered by the project's strict mypy gate.

`build_exports.py` independently encodes PDB headers/pages/rows/strings, emits
real encrypted SQLite, and generates a one-second stereo PCM WAV and a tiny PNG.
Its values are intentionally distinctive: Unicode/spaces, long/far strings,
nested/empty playlists, repeated entries, absent tracks and unsupported audio.
All of these synthetic assets are original project fixtures under Apache-2.0.
Rebuild from the repository root with:

```sh
uv run --locked python tests/fixtures/build_exports.py
```

SQLCipher uses random salts, so rebuilding preserves semantic contents rather
than identical encrypted bytes. Tests assert values and source integrity.

`upstream/one-song-export.pdb` is the genuine 2024-02-29 rekordbox export included
by `fragmede/rekordbox-pdb` at commit
`ee3bac2f22ca11a5ce61eea35f8cb951c246eaef`, under its MIT license reproduced in
`upstream/LICENSE`. It contains metadata only; its referenced commercial audio
and artwork are not included. Independently verified expectations in upstream's
`tests/test_pdb.py` are checked by our integration test.

Source: https://github.com/fragmede/rekordbox-pdb/tree/ee3bac2f22ca11a5ce61eea35f8cb951c246eaef/tests

The user's USB is never copied into these fixtures.
