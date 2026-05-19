import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    raise ValueError('DISCORD_TOKEN 未設定，請在 .env 填入 Token')

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'目前登入身分：{bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.content == 'hello':
        await message.channel.send('你好！我收到訊息了！')

bot.run(TOKEN)
