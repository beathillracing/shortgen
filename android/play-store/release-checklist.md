# Release checklist

## Developer account

- Complete organization verification.
- Create one app: Beathill Studio.
- Use the exact package ID `beathill.studio`.
- Enroll the app in Play App Signing.

## Store setup

- App category: Video Players & Editors.
- Contact email: `dev@beathillracing.fi`.
- Privacy policy: `https://shortgen.beathillracing.fi/public/privacy`.
- Terms: `https://shortgen.beathillracing.fi/public/terms`.
- Upload the app icon and feature graphic from each listing asset directory.
- Add real phone screenshots before production submission.
- Complete the Data safety form using `data-safety.md`.
- Complete restricted App access using `app-access.md` and working reviewer
  tokens entered only in Play Console.
- Declare that the apps contain no ads.
- Complete the content-rating questionnaire.
- Set target audience to adults unless the product is deliberately changed for
  children.

## Testing and rollout

- Upload the `.aab` to Internal testing first.
- Add tester email addresses and install through Google Play.
- Verify login/token setup, upload continuation, notifications, downloads,
  theme selection, and server processing.
- Verify that no APK update dialog or unknown-app-source prompt appears.
- Promote the tested build to the required closed or production track.

## Every update

- Increase `versionCode`.
- Update `versionName` and release notes.
- Build new signed bundles with `./build-play.sh`.
- Test through an internal track before production.
