import os
import sys
import tempfile
import pathlib
import json
import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, AudioMessage
from dotenv import load_dotenv
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

load_dotenv()

app = Flask(__name__)

# Get environment variables
channel_secret = os.getenv('CHANNEL_SECRET')
channel_access_token = os.getenv('CHANNEL_ACCESS_TOKEN')
gemini_api_key = os.getenv('GEMINI_API_KEY')
firebase_credentials_path = os.getenv('FIREBASE_CREDENTIALS_PATH')

if channel_secret is None or channel_access_token is None or gemini_api_key is None:
    print('Specify CHANNEL_SECRET, CHANNEL_ACCESS_TOKEN and GEMINI_API_KEY as environment variables.')
    sys.exit(1)

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# Configure Gemini
genai.configure(api_key=gemini_api_key)
model = genai.GenerativeModel('gemini-2.0-flash')

# Initialize Firebase
if not firebase_admin._apps:
    firebase_credentials_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
    
    if firebase_credentials_json:
        # Load from environment variable (Deployment)
        cred_dict = json.loads(firebase_credentials_json)
        cred = credentials.Certificate(cred_dict)
    else:
        # Load from file (Local Development)
        cred = credentials.Certificate(firebase_credentials_path)
        
    firebase_admin.initialize_app(cred)
db = firestore.client()

def get_monthly_status(user_id, target_month_str=None):
    """
    Returns (spent, limit, percentage) for the month.
    target_month_str: 'YYYY-MM'
    """
    now = datetime.datetime.now()
    if not target_month_str:
        target_month_str = now.strftime("%Y-%m")
    
    # Get Limit
    limit_ref = db.collection('users').document(user_id).collection('settings').document('monthly_limits')
    limit_doc = limit_ref.get()
    limit_data = limit_doc.to_dict() if limit_doc.exists else {}
    limit = limit_data.get(target_month_str, 0)
    
    # Get Spend
    start_date = datetime.datetime.strptime(target_month_str, "%Y-%m")
    # End date is start of next month
    if start_date.month == 12:
        end_date = datetime.datetime(start_date.year + 1, 1, 1)
    else:
        end_date = datetime.datetime(start_date.year, start_date.month + 1, 1)
        
    transactions = db.collection('users').document(user_id).collection('transactions')\
        .where(filter=firestore.FieldFilter('date', '>=', start_date))\
        .where(filter=firestore.FieldFilter('date', '<', end_date))\
        .stream()
        
    spent = sum(t.to_dict().get('price', 0) for t in transactions)
    
    return spent, limit

def get_project_status(user_id, project_name):
    """
    Returns (spent, limit, percentage) for the project.
    """
    # Get Limit
    limit_ref = db.collection('users').document(user_id).collection('settings').document('project_limits')
    limit_doc = limit_ref.get()
    limit_data = limit_doc.to_dict() if limit_doc.exists else {}
    limit = limit_data.get(project_name, 0)
    
    # Get Spend
    transactions = db.collection('users').document(user_id).collection('transactions')\
        .where(filter=firestore.FieldFilter('project', '==', project_name))\
        .stream()
        
    spent = sum(t.to_dict().get('price', 0) for t in transactions)
    
    return spent, limit

def process_text_input(text, user_id, reply_token):
    try:
        # Help / Static Responses
        if text.lower() in ["help", "input guide", "how to record?"]:
            help_msg = """📝 How to Record:
• Standard: "Lunch $100"
• Project: "TripTokyo Flight $500"

⚙️ Settings:
• "Set monthly limit 2025-01 50000"
• "Set project limit TripTokyo 20000"

📊 Reports:
• Use the Rich Menu for instant reports!"""
            line_bot_api.reply_message(reply_token, TextSendMessage(text=help_msg))
            return

        if text == "How to set monthly limit?":
             line_bot_api.reply_message(reply_token, TextSendMessage(text="To set a monthly limit, type:\nSet monthly limit YYYY-MM AMOUNT\n\nExample:\nSet monthly limit 2025-01 50000"))
             return

        if text == "How to set project limit?":
             line_bot_api.reply_message(reply_token, TextSendMessage(text="To set a project limit, type:\nSet project limit PROJECT_NAME AMOUNT\n\nExample:\nSet project limit Renovation 100000"))
             return

        # NLP Prompt
        prompt = f"""
        You are a smart accounting assistant. Analyze the user input.
        
        Current Date: {datetime.datetime.now().strftime("%Y-%m-%d")}
        
        Intents:
        1. record: User is spending money. Extract item, price, category, and optionally 'project'.
        2. query: User wants a report.
        3. set_limit_month: User wants to set a budget for a specific month.
        4. set_limit_project: User wants to set a budget for a specific project.
        
        Output JSON format:
        
        For 'record':
        {{
            "intent": "record",
            "item": "string",
            "price": int,
            "category": "string",
            "project": "string|null"  (extract if user mentions a specific event/project context like 'Trip', 'Renovation')
        }}
        
        For 'set_limit_month':
        {{
            "intent": "set_limit_month",
            "month": "YYYY-MM", (default to current month if not specified)
            "amount": int
        }}
        
        For 'set_limit_project':
        {{
            "intent": "set_limit_project",
            "project": "string",
            "amount": int
        }}

        For 'query':
        {{
            "intent": "query",
            "type": "monthly_status" | "monthly_rate" | "project_status" | "project_rate",
            "target": "string|null" (e.g., project name if applicable)
        }}
        
        Special Keywords Mapping:
        - "Report Monthly Status" -> query, type=monthly_status
        - "Report Monthly Rate" -> query, type=monthly_rate
        - "Report Project Status" -> query, type=project_status
        - "Report Project Rate" -> query, type=project_rate
        
        User Input: {text}
        """
        
        response = model.generate_content(prompt)
        cleaned_text = response.text.replace('```json', '').replace('```', '').strip()
        
        try:
            data = json.loads(cleaned_text)
        except json.JSONDecodeError:
            data = {"intent": "unknown"}
        
        # --- Handle Intents ---
        
        if data.get('intent') == 'record':
            # Add timestamp and save to Firestore
            doc_data = {
                'item': data['item'],
                'price': data['price'],
                'category': data['category'],
                'date': datetime.datetime.now(),
                'project': data.get('project') # Can be None
            }
            db.collection('users').document(user_id).collection('transactions').add(doc_data)
            
            reply_msg = f"✅ Recorded: {data['item']} - ${data['price']} ({data['category']})"
            if data.get('project'):
                reply_msg += f"\n📂 Project: {data['project']}"
                
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_msg))
            
        elif data.get('intent') == 'set_limit_month':
            month = data.get('month')
            amount = data.get('amount')
            
            db.collection('users').document(user_id).collection('settings').document('monthly_limits').set(
                {month: amount}, merge=True
            )
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"✅ Limit set for {month}: ${amount}"))
            
        elif data.get('intent') == 'set_limit_project':
            project = data.get('project')
            amount = data.get('amount')
            
            db.collection('users').document(user_id).collection('settings').document('project_limits').set(
                {project: amount}, merge=True
            )
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"✅ Limit set for project '{project}': ${amount}"))
            
        elif data.get('intent') == 'query':
            q_type = data.get('type')
            
            if q_type in ['monthly_status', 'monthly_rate']:
                current_month = datetime.datetime.now().strftime("%Y-%m")
                spent, limit = get_monthly_status(user_id, current_month)
                
                if limit > 0:
                    rate = (spent / limit) * 100
                    status_emoji = "🟢" if rate < 80 else "🟡" if rate < 100 else "🔴"
                    msg = f"📅 Month ({current_month})\n"
                    msg += f"💸 Spent: ${spent}\n"
                    msg += f"🛑 Limit: ${limit}\n"
                    msg += f"📊 Rate: {rate:.1f}% {status_emoji}"
                    if spent > limit:
                        msg += f"\n⚠️ Over budget by ${spent - limit}!"
                else:
                     msg = f"📅 Month ({current_month})\n💸 Spent: ${spent}\n(No limit set)"
                
                line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))

            elif q_type in ['project_status', 'project_rate']:
                # For project summary, we might need a specific project name or list all?
                # For simplicity, if no specific project mentioned, list top active ones or ask for name.
                # Here we'll list all projects that have limits set or transactions.
                # Actually, listing all might be too long. Let's fetch projects with limits for now.
                
                settings_ref = db.collection('users').document(user_id).collection('settings').document('project_limits').get()
                projects_limits = settings_ref.to_dict() if settings_ref.exists else {}
                
                if not projects_limits:
                     line_bot_api.reply_message(reply_token, TextSendMessage(text="No project limits found. Set one via 'Set project limit NAME AMOUNT'"))
                     return

                report = "📂 Projects Status:\n"
                for proj_name, limit in projects_limits.items():
                    spent, _ = get_project_status(user_id, proj_name)
                    rate = (spent / limit) * 100 if limit > 0 else 0
                    emoji = "🟢" if rate < 100 else "🔴"
                    report += f"\n▪️ {proj_name}\n   ${spent} / ${limit} ({rate:.1f}%) {emoji}"
                
                line_bot_api.reply_message(reply_token, TextSendMessage(text=report))

        else:
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text="I didn't understand that. You can say 'Help' for instructions.")
            )

    except Exception as e:
        print(f"Error processing text: {e}")
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="Sorry, an error occurred while processing your request.")
        )

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    process_text_input(event.message.text, event.source.user_id, event.reply_token)

@handler.add(MessageEvent, message=AudioMessage)
def handle_audio_message(event):
    # Get audio content
    message_content = line_bot_api.get_message_content(event.message.id)
    
    # Save to temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.m4a') as tf:
        for chunk in message_content.iter_content():
            tf.write(chunk)
        temp_path = tf.name

    try:
        # Transcribe with Gemini
        audio_file = genai.upload_file(path=pathlib.Path(temp_path), mime_type='audio/m4a')
        response = model.generate_content(["Please transcribe this audio exactly as spoken.", audio_file])
        transcribed_text = response.text
        
        # Process the transcribed text
        process_text_input(transcribed_text, event.source.user_id, event.reply_token)
        
    except Exception as e:
        print(f"Error processing audio: {e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="Sorry, I couldn't process the audio.")
        )
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host='0.0.0.0', port=port)
