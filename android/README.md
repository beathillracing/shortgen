# ShortGen Android

Native Android uploader for `https://shortgen.beathillracing.fi`.

## Behavior

- Uploads continue through WorkManager with a foreground notification.
- Files are transferred in resumable 8 MB chunks.
- Network failures retry automatically and continue from the server offset.
- Closing the app does not cancel the upload.
- Job progress, thumbnail selection, review, metadata edits, video preview and
  social publishing are available in the native app.
- Final video processing and social publishing run on the ShortGen server.
- The web interface remains available as a backup/admin client.

## Build

1. Open this `android` directory in Android Studio.
2. Let Android Studio install Android SDK 35 when prompted.
3. Build and install the required direct release variant on the phone:
   `fullDirectRelease` or `creatorDirectRelease`.
4. Play builds create a private installation account automatically.
5. Link Google in Settings for account recovery across reinstalls and devices.

Session and remembered-account tokens are encrypted with Android Keystore.
Manual support or administrator access codes remain available in Settings.

The release signing keystore and passwords are stored only on this server in
`shortgen-release.jks` and `local.properties`. Keep both files backed up;
future APK updates must use the same signing key.

## Distribution variants

The app has two independent flavor dimensions:

- Edition: `full` or `creator`
- Distribution: `direct` or `play`

Direct builds retain the self-hosted APK updater:

```bash
./gradlew :app:assembleFullDirectRelease :app:assembleCreatorDirectRelease
```

The Play build removes `REQUEST_INSTALL_PACKAGES` and all self-update prompts.
Google Play manages updates:

```bash
./gradlew :app:bundleFullPlayRelease
```

The Play app is **Beathill Studio**, package `beathill.studio`. It is a separate
installation from the existing direct ShortGen APKs.

Before a Play upload, run:

```bash
./release-preflight.sh
```
