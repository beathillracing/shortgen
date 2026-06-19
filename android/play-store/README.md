# ShortGen Play Store release

Prepared Play Store application:

| App | Package ID | Version |
| --- | --- | --- |
| Beathill Studio | `beathill.studio` | `0.10.0` (`10`) |

Build the signed Android App Bundle:

```bash
./build-play.sh
```

The resulting bundles and checksums are written to `play-store/builds/`.
These binary artifacts are intentionally ignored by Git.

## Important signing choice

The Play app uses a new package and is intentionally separate from existing
ShortGen sideload installations. Google Play manages distribution signing.

The public upload certificate and fingerprints are in `signing/`. The private
key and passwords are not included. When Play Console provides its PEPK
encryption key, use its exact export command against `shortgen-release.jks`;
never upload or email the raw keystore.

## Play-specific behavior

- Self-hosted APK update checks are disabled.
- `REQUEST_INSTALL_PACKAGES` is absent.
- Google Play manages updates.
- API level 35 is targeted.
- One Play listing provides free creation/export features and a Pro
  subscription for direct publishing.

See `release-checklist.md` before uploading.
