from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import openai
from google.cloud import firestore
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

app = FastAPI()

# Initialize Firestore client (make sure your service account has access)
db = firestore.Client()

# Set your OpenAI API key as env var or directly here
openai.api_key = "YOUR_OPENAI_API_KEY"

class EmailData(BaseModel):
    user_id: str
    message_id: str
    subject: str
    body: str

def classify_email(subject: str, body: str) -> str:
    system_prompt = """
    You are an email assistant. Label each email with exactly one of the following:
    ['Work', 'School', 'Awaiting Reply', 'To-Do', 'Scheduled', 'Spam', 'Other'].
    Use 'Other' only if no label fits.
    """
    user_input = f"Subject: {subject}\nBody: {body}\nLabel:"
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]
    )
    return response.choices[0].message.content.strip()

def get_user_creds(user_id: str) -> Credentials:
    doc = db.collection("users").document(user_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    data = doc.to_dict()
    creds = Credentials(
        token=data["access_token"],
        refresh_token=data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET",
        scopes=["https://www.googleapis.com/auth/gmail.modify"]
    )
    return creds

def get_or_create_label(service, label_name):
    labels = service.users().labels().list(userId='me').execute().get("labels", [])
    for label in labels:
        if label["name"].lower() == label_name.lower():
            return label["id"]
    new_label = {
        "name": label_name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show"
    }
    created = service.users().labels().create(userId='me', body=new_label).execute()
    return created["id"]

def apply_label_to_email(service, message_id, label_id):
    service.users().messages().modify(
        userId='me',
        id=message_id,
        body={"addLabelIds": [label_id]}
    ).execute()

@app.post("/label-email")
async def label_email(data: EmailData):
    try:
        creds = get_user_creds(data.user_id)
        gmail_service = build("gmail", "v1", credentials=creds)

        label = classify_email(data.subject, data.body)
        if label.lower() == "spam":
            label_id = "SPAM"  # Gmail built-in spam label
        else:
            label_id = get_or_create_label(gmail_service, label)

        apply_label_to_email(gmail_service, data.message_id, label_id)
        return {"status": "success", "label": label}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
