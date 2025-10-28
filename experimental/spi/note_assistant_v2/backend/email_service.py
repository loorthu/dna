from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, EmailStr
import os
import sys
import base64
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# Load environment variables from .env file (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SCOPES = ['https://www.googleapis.com/auth/gmail.send']
CREDENTIALS_FILE = 'client_secret.json'  # Place this in your backend dir
TOKEN_FILE = 'token.json'
GMAIL_SENDER = os.getenv('GMAIL_SENDER')

router = APIRouter()

class EmailNotesRequest(BaseModel):
    email: EmailStr
    notes: list

def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            raise RuntimeError(f"Google credentials file is missing or invalid: {e}")
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError("Google credentials are missing or invalid. Please contact your administrator.")
    return build('gmail', 'v1', credentials=creds)

def create_gmail_message(sender, to, subject, html_content):
    message = MIMEText(html_content, 'html')
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw}

def send_gmail_email(to, subject, html_content):
    service = get_gmail_service()
    message = create_gmail_message(GMAIL_SENDER, to, subject, html_content)
    sent = service.users().messages().send(userId="me", body=message).execute()
    return sent

@router.post("/email-notes")
async def email_notes(data: EmailNotesRequest):
    """
    Send the notes as an HTML table to the given email address using Gmail API.
    """
    html = """
    <h2>Dailies Shot Notes</h2>
    <table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-family:sans-serif;'>
      <thead>
        <tr style='background:#f1f5f9;'>
          <th>Shot/Version</th>
          <th>Notes</th>
          <th>Transcription</th>
          <th>Summary</th>
        </tr>
      </thead>
      <tbody>
    """
    for row in data.notes:
        html += f"<tr>"
        html += f"<td>{row.get('shot','')}</td>"
        html += f"<td>{row.get('notes','').replace(chr(10),'<br>')}</td>"
        html += f"<td>{row.get('transcription','').replace(chr(10),'<br>')}</td>"
        html += f"<td>{row.get('summary','').replace(chr(10),'<br>')}</td>"
        html += "</tr>"
    html += "</tbody></table>"
    subject = "Dailies Shot Notes"
    try:
        send_gmail_email(data.email, subject, html)
        return {"status": "success", "message": f"Notes sent to {data.email}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Email service error: {str(e)}"}

def main():
    """
    Standalone test for sending a Gmail message using the Gmail API.
    If token.json does not exist, run OAuth flow to create it.
    """
    TO_EMAIL = sys.argv[1] if len(sys.argv) > 1 else GMAIL_SENDER
    FROM_EMAIL = GMAIL_SENDER
    SUBJECT = 'Gmail API Test Email'
    HTML_CONTENT = '''
    <h2>Hello from Gmail API!</h2>
    <p>This is a test email sent using the Gmail API and Python.</p>
    '''
    creds = None
    if not os.path.exists(TOKEN_FILE):
        print("token.json not found. Running OAuth flow to create it...")
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        print("token.json created.")
    service = get_gmail_service()
    message = create_gmail_message(FROM_EMAIL, TO_EMAIL, SUBJECT, HTML_CONTENT)
    sent = service.users().messages().send(userId="me", body=message).execute()
    print(f"Email sent! Message ID: {sent['id']}")

if __name__ == '__main__':
    main()
