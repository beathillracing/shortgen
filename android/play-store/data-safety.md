# Data safety working sheet

Use this as the basis for the Play Console Data safety form. Confirm the final
answers against the production server configuration before submission.

## Shared answers

- Data is encrypted in transit: Yes, HTTPS.
- Users can request deletion: Yes, directly in Settings and through
  `info@beathillracing.fi`.
- Data is sold: No.
- Advertising data use: No.
- Ads in the app: No.
- Account creation inside the app: Yes. A private installation account is
  created automatically and can be linked to Google.

## Data handled

### Photos and videos

- Video files selected by the user are uploaded to the ShortGen server.
- Purpose: App functionality.
- Processing is required when the user requests video creation.
- Data may be retained on the server until the operator or user deletes it.

### User-generated content

- Titles, descriptions, thumbnail text, captions, and publishing selections.
- Purpose: App functionality.
- Data is sent to the ShortGen server and may be sent to configured processing
  or publishing providers when the user requests those operations.

### User identifiers

- Installation/account IDs and an app session token identify the account.
- When Google is linked, email address, display name and Google subject ID are
  stored for authentication and account recovery.
- Connected social-platform identifiers are processed by the server for the
  Pro publishing features.
- Purpose: Authentication, account management, and app functionality.

### Purchases

- Google Play purchase tokens, subscription product, status and expiry are
  processed to verify Beathill Studio Pro.
- Purpose: App functionality, fraud prevention and account management.

### App activity and diagnostics

- Job state, upload progress, publishing state, and technical errors may be
  recorded by the server.
- Purpose: App functionality, security, and troubleshooting.

## Third parties

Depending on enabled features and explicit user actions, necessary content,
audio or metadata may be processed by Anthropic, Google/YouTube, Meta,
Instagram, TikTok, Groq, or other configured providers.

Free accounts do not expose direct social publishing. Pro accounts may use
configured publishing providers after purchase verification.
