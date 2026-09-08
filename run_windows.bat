@echo off
set /p BOT_TOKEN=Telegram Bot Token: 
set /p OPENAI_API_KEY=OpenAI API Key: 
set /p ADMIN_ID=Your Telegram numeric ID: 
set OPENAI_MODEL=gpt-5.6-luna
python -m pip install -r requirements.txt
python bot.py
pause
