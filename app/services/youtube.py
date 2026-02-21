import os
import json
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.config import settings

SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',  # Needed for thumbnails
]
CREDENTIALS_FILE = '/var/www/shortgen/youtube_client_secret.json'
TOKEN_FILE = '/var/www/shortgen/youtube_token.json'


def get_youtube_service():
    """Get authenticated YouTube service."""
    creds = None

    # Load existing token
    if Path(TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds)

    if not creds or not creds.valid:
        return None  # Need to authorize first

    return build('youtube', 'v3', credentials=creds)


def save_credentials(creds):
    """Save credentials to file."""
    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())


def is_authenticated():
    """Check if YouTube is authenticated."""
    if not Path(TOKEN_FILE).exists():
        return False
    try:
        service = get_youtube_service()
        return service is not None
    except:
        return False


def get_auth_url():
    """Get OAuth authorization URL for YouTube."""
    if not Path(CREDENTIALS_FILE).exists():
        return None

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    flow.redirect_uri = f"{settings.base_url}/api/youtube/callback"

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    return auth_url


def handle_oauth_callback(authorization_response: str):
    """Handle OAuth callback and save credentials."""
    if not Path(CREDENTIALS_FILE).exists():
        raise ValueError("YouTube client secret not configured")

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    flow.redirect_uri = f"{settings.base_url}/api/youtube/callback"
    flow.fetch_token(authorization_response=authorization_response)

    creds = flow.credentials
    save_credentials(creds)
    return True


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list = None,
    privacy: str = "private",  # private, unlisted, public
    is_short: bool = True,
    thumbnail_path: str = None
) -> dict:
    """
    Upload a video to YouTube.

    Args:
        video_path: Path to video file
        title: Video title
        description: Video description
        tags: List of tags
        privacy: Privacy status (private, unlisted, public)
        is_short: If True, adds #Shorts to title/description

    Returns:
        dict with video_id and url
    """
    service = get_youtube_service()
    if not service:
        raise ValueError("YouTube not authenticated")

    # Add #Shorts for YouTube Shorts
    if is_short:
        if "#Shorts" not in title:
            title = f"{title} #Shorts"
        if "#Shorts" not in description:
            description = f"{description}\n\n#Shorts"

    body = {
        'snippet': {
            'title': title[:100],  # YouTube max 100 chars
            'description': description[:5000],  # YouTube max 5000 chars
            'tags': tags or [],
            'categoryId': '22'  # People & Blogs
        },
        'status': {
            'privacyStatus': privacy,
            'selfDeclaredMadeForKids': False
        }
    }

    media = MediaFileUpload(
        video_path,
        mimetype='video/mp4',
        resumable=True
    )

    request = service.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )

    response = request.execute()

    video_id = response['id']

    # Upload custom thumbnail if provided
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            thumb_media = MediaFileUpload(thumbnail_path, mimetype='image/jpeg')
            service.thumbnails().set(
                videoId=video_id,
                media_body=thumb_media
            ).execute()
        except Exception as e:
            # Thumbnail upload may fail if channel not verified - continue anyway
            print(f"Thumbnail upload failed (channel may need verification): {e}")

    return {
        'video_id': video_id,
        'url': f'https://youtube.com/shorts/{video_id}' if is_short else f'https://youtube.com/watch?v={video_id}'
    }
