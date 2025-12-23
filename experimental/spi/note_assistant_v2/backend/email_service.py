from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, EmailStr
import os
import sys
import base64
import html
import csv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import smtplib

# Load environment variables from .env file (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SCOPES = ['https://www.googleapis.com/auth/gmail.send']
CREDENTIALS_FILE = 'client_secret.json'  # Place this in your backend dir
TOKEN_FILE = 'token.json'
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PROVIDER = os.getenv('EMAIL_PROVIDER', 'gmail')
SMTP_HOST = os.getenv('SMTP_HOST', 'localhost')
SMTP_PORT = os.getenv('SMTP_PORT')
if SMTP_PORT is not None:
    SMTP_PORT = int(SMTP_PORT)
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SMTP_TLS = os.getenv('SMTP_TLS', 'false').lower() == 'true'

router = APIRouter()

class EmailNotesRequest(BaseModel):
    email: EmailStr
    notes: list
    subject: str = "Dailies Shot Notes"  # Optional custom subject with default

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
    message = create_gmail_message(EMAIL_SENDER, to, subject, html_content)
    sent = service.users().messages().send(userId="me", body=message).execute()
    return sent

def send_smtp_email(to, subject, html_content, cc=None, bcc=None):
    recipients = [to]
    if cc:
        recipients += cc
    if bcc:
        recipients += bcc
    msg = MIMEMultipart('')
    msg['Subject'] = subject
    msg['From'] = EMAIL_SENDER
    msg['To'] = ','.join([to])
    if cc:
        msg['Cc'] = ','.join(cc)
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    try:
        smtp_msg = smtplib.SMTP()
        if SMTP_PORT is not None:
            smtp_msg.connect(SMTP_HOST, SMTP_PORT)
        else:
            smtp_msg.connect(SMTP_HOST)
        if SMTP_TLS:
            smtp_msg.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            smtp_msg.login(SMTP_USER, SMTP_PASSWORD)
        smtp_msg.sendmail(EMAIL_SENDER, recipients, msg.as_string())
        smtp_msg.close()
    except Exception as e:
        raise RuntimeError(f"SMTP email send failed: {e}")

def send_email(to, subject, html_content):
    if EMAIL_PROVIDER == 'smtp':
        send_smtp_email(to, subject, html_content)
    else:
        send_gmail_email(to, subject, html_content)

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
    
    # Use the custom subject from the request
    subject = data.subject
    try:
        send_email(data.email, subject, html)
        return {"status": "success", "message": f"Notes sent to {data.email}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Email service error: {str(e)}"}

def main():
    """
    Send email with CSV data including version number, LLM summary, SG notes, and first 500 characters from conversation.
    Usage: python email_service.py <recipient_email> <csv_file_path>
    """
    
    if len(sys.argv) < 3:
        print("Usage: python email_service.py <recipient_email> <csv_file_path>")
        return
    
    TO_EMAIL = sys.argv[1]
    CSV_FILE = sys.argv[2]
    
    # Check if CSV file exists
    if not os.path.exists(CSV_FILE):
        print(f"CSV file not found: {CSV_FILE}")
        return
    
    FROM_EMAIL = EMAIL_SENDER
    SUBJECT = 'Dailies Review Data - Version Notes and Summaries'
    
    # Read CSV data
    rows = []
    try:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip rows without version_id
                if row.get('version_id') and row['version_id'].strip():
                    rows.append(row)
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return
    
    if not rows:
        print("No valid data found in CSV file")
        return
    
    # Generate HTML content
    html_content = '''
    <h2>Dailies Review Data</h2>
    <p>Review notes and summaries from the dailies session.</p>
    <table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:12px;'>
      <thead>
        <tr style='background:#f1f5f9;font-weight:bold;'>
          <th style='min-width:80px;'>Version ID</th>
          <th style='min-width:200px;'>LLM Summary</th>
          <th style='min-width:150px;'>SG Notes</th>
          <th style='min-width:250px;'>Conversation (First 500 chars)</th>
        </tr>
      </thead>
      <tbody>
    '''
    
    for row in rows:
        version_id = html.escape(row.get('version_id', ''))
        llm_summary = html.escape(row.get('llm_summary', ''))
        sg_summary = html.escape(row.get('sg_summary', ''))
        conversation = row.get('conversation', '')
        
        # Get first 500 characters of conversation
        conversation_preview = conversation[:500]
        if len(conversation) > 500:
            conversation_preview += "..."
        conversation_preview = html.escape(conversation_preview)
        
        # Replace newlines with <br> tags for proper HTML display
        llm_summary = llm_summary.replace('\n', '<br>')
        sg_summary = sg_summary.replace('\n', '<br>')
        conversation_preview = conversation_preview.replace('\n', '<br>')
        
        html_content += f'''
        <tr style='vertical-align:top;'>
          <td style='font-weight:bold;'>{version_id}</td>
          <td>{llm_summary}</td>
          <td>{sg_summary}</td>
          <td style='font-family:monospace;font-size:11px;'>{conversation_preview}</td>
        </tr>
        '''
    
    html_content += '''
      </tbody>
    </table>
    <p style='margin-top:20px;font-size:11px;color:#666;'>
      Generated from combined_review_data_with_summaries.csv
    </p>
    '''
    
    # Send email based on provider
    if EMAIL_PROVIDER == 'smtp':
        print("Sending email using SMTP...")
        try:
            send_smtp_email(TO_EMAIL, SUBJECT, html_content)
            print(f"Email sent successfully to {TO_EMAIL} with {len(rows)} records.")
        except Exception as e:
            print(f"SMTP email failed: {e}")
    else:
        print("Sending email using Gmail API...")
        try:
            # Handle Gmail OAuth if needed
            creds = None
            if not os.path.exists(TOKEN_FILE):
                print("token.json not found. Running OAuth flow to create it...")
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
                print("token.json created.")
            
            service = get_gmail_service()
            message = create_gmail_message(FROM_EMAIL, TO_EMAIL, SUBJECT, html_content)
            sent = service.users().messages().send(userId="me", body=message).execute()
            print(f"Gmail API email sent successfully to {TO_EMAIL}! Message ID: {sent['id']}")
            print(f"Sent {len(rows)} records from CSV file.")
        except Exception as e:
            print(f"Gmail API email failed: {e}")

if __name__ == '__main__':
    main()
