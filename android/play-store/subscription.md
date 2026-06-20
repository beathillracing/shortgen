# Beathill Studio Pro

Create this subscription in Play Console after the first AAB has been uploaded.

- Product ID: `beathill_studio_pro`
- Display name: `Beathill Studio Pro`
- Base plan ID: `monthly`
- Billing type: Auto-renewing monthly subscription
- Grace period: 7 days
- Account hold: Enabled
- Resubscribe: Enabled
- Price: choose and confirm in Play Console before activating the base plan

## Free features

- Upload and combine clips
- Caption and process videos
- Generate titles, descriptions, and thumbnail text
- Review and edit metadata
- Download videos, thumbnails, and copyable text

## Pro features

- Direct publishing from the app
- YouTube, Instagram, Facebook, and TikTok publishing where configured
- Multi-platform publish selection
- Future scheduling and publishing automation

The Android client submits the purchase token to the ShortGen server. The
server verifies it through the Google Play Developer API for package
`beathill.studio` and grants publishing only while the subscription is active.

`./release-preflight.sh` verifies that this product exists and is reachable
through the configured Play service account. The release must not be promoted
while that check reports `Subscription not found`.
