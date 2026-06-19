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
4. Open `/mobile` in ShortGen to download the current APK and copy the token.
5. Enter the mobile API token once in the app's Connection section.

The token is stored in Android app-private preferences and is not committed to
this repository. The server token is the `MOBILE_API_TOKEN` value in
`/var/www/shortgen/.env`.

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
