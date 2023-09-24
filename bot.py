# bot.py

import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
from dotenv import load_dotenv

# region Dotenv setup and imports
load_dotenv('.env')

TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = os.getenv('PREFIX')

client = commands.Bot(command_prefix=PREFIX, intents=discord.Intents.all())


@client.event
async def on_ready():
    await client.login(TOKEN)
    print(f'Bot is online')


@client.event
async def on_message(message):

    # if message is a DM
    if isinstance(message.channel, discord.DMChannel):
        pass

    # ignore non-text messages and messages from this bot
    if str(message.channel.type) != 'text' \
            or message.author == client.user:
        return

    if message.content.lower() == "sync commands" and await check_admin(message.author):
        await sync_commands(message)


async def sync_commands(message: discord.Message):
    print(f'Syncing commands...')
    try:
        synced = await client.tree.sync()
        print(f'Synced {len(synced)} command(s)\n')
        await message.reply(content=f'Synced {len(synced)} command(s)\n')
    except Exception as e:
        print(e)
        await message.reply(e.__str__())


async def check_admin(member: discord.Member):
    if member.guild_permissions.administrator:
        return True
    return False



client.run(TOKEN)
