import os
import sys
from linebot import LineBotApi
from linebot.models import RichMenu, RichMenuSize, RichMenuArea, RichMenuBounds, MessageAction
from dotenv import load_dotenv

load_dotenv()

# Config
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
if not CHANNEL_ACCESS_TOKEN:
    print("Error: CHANNEL_ACCESS_TOKEN not found in .env")
    sys.exit(1)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

# 1. Define the Rich Menu
rich_menu_to_create = RichMenu(
    size=RichMenuSize(width=2500, height=1686),
    selected=True,
    name="BabyFinance 6-Grid",
    chat_bar_text="Open Menu",
    areas=[
        # Row 1, Col 1: Input Guide
        RichMenuArea(
            bounds=RichMenuBounds(x=0, y=0, width=833, height=843),
            action=MessageAction(label="Input Guide", text="How to record?")
        ),
        # Row 1, Col 2: Today
        RichMenuArea(
            bounds=RichMenuBounds(x=833, y=0, width=834, height=843),
            action=MessageAction(label="Today", text="Report Today")
        ),
        # Row 1, Col 3: This Month
        RichMenuArea(
            bounds=RichMenuBounds(x=1667, y=0, width=833, height=843),
            action=MessageAction(label="This Month", text="Report This Month")
        ),
        # Row 2, Col 1: Total
        RichMenuArea(
            bounds=RichMenuBounds(x=0, y=843, width=833, height=843),
            action=MessageAction(label="Total", text="Report Total")
        ),
        # Row 2, Col 2: Last Record
        RichMenuArea(
            bounds=RichMenuBounds(x=833, y=843, width=834, height=843),
            action=MessageAction(label="Last Record", text="Check last")
        ),
        # Row 2, Col 1: Help
        RichMenuArea(
            bounds=RichMenuBounds(x=1667, y=843, width=833, height=843),
            action=MessageAction(label="Help", text="Help")
        )
    ]
)

# 2. Create the Rich Menu ID
rich_menu_id = line_bot_api.create_rich_menu(rich_menu=rich_menu_to_create)
print(f"Created Rich Menu ID: {rich_menu_id}")

# 3. Upload the Image
# Assumes the image is named 'rich_menu_6grid.png' in the current directory
image_path = 'rich_menu_6grid.png' 
if not os.path.exists(image_path):
    print(f"Error: {image_path} not found. Please ensure the image is generated and saved.")
    sys.exit(1)

with open(image_path, 'rb') as f:
    line_bot_api.set_rich_menu_image(rich_menu_id, "image/png", f)
print("Image uploaded.")

# 4. Set as Default
line_bot_api.set_default_rich_menu(rich_menu_id)
print(f"Successfully set {rich_menu_id} as the default rich menu!")
