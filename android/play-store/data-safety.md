# Data safety working sheet

Use this as the basis for the Play Console Data safety form. Confirm the final
answers against the production server configuration before submission.

## Shared answers

- Data is encrypted in transit: Yes, HTTPS.
- Users can request deletion: Yes, through `info@beathillracing.fi`.
- Data is sold: No.
- Advertising data use: No.
- Ads in the app: No.
- Account creation inside the app: No. Access is configured with a server-issued
  mobile API token.

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

- The mobile API token identifies the configured ShortGen access role.
- Connected social-platform identifiers are processed by the server for the
  Full edition when publishing is configured.
- Purpose: Authentication, account management, and app functionality.

### App activity and diagnostics

- Job state, upload progress, publishing state, and technical errors may be
  recorded by the server.
- Purpose: App functionality, security, and troubleshooting.

## Third parties

Depending on enabled features and explicit user actions, necessary content or
metadata may be processed by Anthropic, Google/YouTube, Meta, TikTok, Groq, or
other providers configured on the ShortGen server.

Free accounts do not expose direct social publishing. Pro accounts may use
configured publishing providers after purchase verification.
