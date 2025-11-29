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
    cred = credentials.Certificate(firebase_credentials_path)
    firebase_admin.initialize_app(cred)
db = firestore.client()

def process_text_input(text, user_id, reply_token):
    try:
        # NLP Prompt
        prompt = f"""
        You are a professional accounting assistant. Analyze the user's input and determine if they are recording a transaction or asking for a spending report.

        If recording a transaction:
        Return JSON: {{"intent": "record", "item": "string", "price": int, "category": "string"}}
        
        If asking for a report/query (e.g., "how much spent", "report", "check spending"):
        Return JSON: {{"intent": "query", "period": "string"}}
        (period can be "this_month", "last_month", "today", or "all")

        If neither/unclear:
        Return JSON: {{"intent": "unknown"}}
        
        User Input: {text}
        """
        
        response = model.generate_content(prompt)
        cleaned_text = response.text.replace('```json', '').replace('```', '').strip()
        
        try:
            data = json.loads(cleaned_text)
        except json.JSONDecodeError:
            data = {"intent": "unknown"}
        
        if data.get('intent') == 'record':
            # Add timestamp and save to Firestore
            data['date'] = datetime.datetime.now()
            
            # Path: users/{user_id}/transactions/{auto_id}
            db.collection('users').document(user_id).collection('transactions').add({
                'item': data['item'],
                'price': data['price'],
                'category': data['category'],
                'date': data['date']
            })
            
            reply_msg = f"✅ Recorded: {data['item']} - ${data['price']} ({data['category']})"
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=reply_msg)
            )
            
        elif data.get('intent') == 'query':
            # Handle Query
            now = datetime.datetime.now()
            query_ref = db.collection('users').document(user_id).collection('transactions')
            
            start_date = None
            period_str = "Total"
            
            if data['period'] == 'this_month':
                start_date = datetime.datetime(now.year, now.month, 1)
                period_str = "This Month"
            elif data['period'] == 'today':
                start_date = datetime.datetime(now.year, now.month, now.day)
                period_str = "Today"
            # Add more periods as needed
            
            if start_date:
                query_ref = query_ref.where(field_path='date', op_string='>=', value=start_date)
            
            docs = query_ref.stream()
            
            total_amount = 0
            category_totals = {}
            
            for doc in docs:
                t = doc.to_dict()
                price = t.get('price', 0)
                category = t.get('category', 'Uncategorized')
                
                total_amount += price
                category_totals[category] = category_totals.get(category, 0) + price
            
            # Format Report
            report = f"📊 Spending Report ({period_str})\n"
            report += f"💰 Total: ${total_amount}\n"
            report += "----------------\n"
            for cat, amount in category_totals.items():
                report += f"• {cat}: ${amount}\n"
                
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=report)
            )

        else:
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text="I didn't understand that. You can say 'Coffee $50' to record, or 'Check spending' to see report.")
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
