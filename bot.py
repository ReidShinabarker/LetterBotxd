# bot.py

import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
from dotenv import load_dotenv
from letterboxdpy import user
import datetime as dt
from datetime import datetime, timedelta
import mysql.connector

# region Dotenv setup and imports
load_dotenv('.env')

TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = os.getenv('PREFIX')
LOG_CHANNEL = os.getenv('LOG_CHANNEL')
db_address = os.getenv('DATABASE_ADDRESS')
db_name = os.getenv('DATABASE_NAME')
db_user = os.getenv('DATABASE_USER')
db_pass = os.getenv('DATABASE_PASS')

client = commands.Bot(command_prefix=PREFIX, intents=discord.Intents.all())

global log_channel
global mydb
global cursor


@client.event
async def on_ready():
    global log_channel
    global mydb
    global cursor

    await client.login(TOKEN)
    print(f'Bot is online')
    log_channel = client.get_channel(int(LOG_CHANNEL))
    mydb = mysql.connector.connect(
        host=str(db_address),
        user=str(db_user),
        password=str(db_pass),
        database=str(db_name)
    )
    print(f'Bot is connected to the MariaDB database')

    cursor = mydb.cursor()


async def log(output: discord.Embed):
    global log_channel
    output.set_footer(text=datetime.now())
    await log_channel.send(embed=output)


async def log_slash(author: discord.Member, specific, parameters: dict = None, message: discord.Message = None):
    desc = ""
    if parameters is not None:
        desc += "**Parameters:**\n"
        for item in parameters:
            desc += f'{item}: {parameters[item]}\n'

    if message is not None:
        desc += f'\n\n[link to message]({message.jump_url})'

    embed = discord.Embed(title=f'/{specific}', description=desc)
    embed.set_author(name=author,
                     icon_url=author.default_avatar.url if author.display_avatar is None else author.display_avatar.url)

    await log(embed)


async def log_error(error):
    embed = discord.Embed(title=f'ERROR', description=str(error), colour=15548997)
    await log(embed)


@client.event
async def on_message(message):

    # if message is a DM
    if isinstance(message.channel, discord.DMChannel):
        pass

    # ignore non-text messages and messages from this bot
    if str(message.channel.type) != 'text' \
            or message.author == client.user:
        return

    # basic text command to sync slash command changes
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


@client.tree.command(name="link_account", description="Link a Letterboxd account to a discord user")
@app_commands.describe(username="Letterboxd account username", member="Discord member")
async def link_account(interaction: discord.Interaction, username: str, member: discord.Member = None):

    # make sure Letterboxd user exists
    try:
        user.User(username)
    except Exception as e:
        if str(e) == "No user found":
            await interaction.response.send_message(f'Error finding Letterboxd user with that name.'
                                                    f'\nPlease recheck your spelling.', ephemeral=True)
        else:
            await log_error(e)
            await interaction.response.send_message(f'Unknown error. Ask your admin to check the error log',
                                                    ephemeral=True)

    # make sure Letterboxd account hasn't already been paired to a member in this discord server
    # if username already in use
    #     await interaction.response.send_message(f'Letterboxd account already paired to a discord user in this server',
    #                                             ephemeral=True)

    # if member left default, assume self
    if member is None:
        member = interaction.user

    # only allow someone to change another user's linked account if they're an admin
    if not await check_admin(interaction.user) and interaction.user != member:
        await interaction.response.send_message(f'Only an admin can link another user\'s account', ephemeral=True)

    # don't let user change their account if they already have one linked
    # Else If member already has a letterboxd account paired and is not an admin
    #     await interaction.response.send_message(f'Letterboxd account already linked.\n'
    #                                             f'Ask an admin to change your account if it is incorrect',
    #                                             ephemeral=True)

    # otherwise link account
    else:
        # link account to user
        await interaction.response.send_message(f'{member.display_name} '
                                                f'was linked to the Letterboxd account "{username}"',
                                                ephemeral=True)

    await log_slash(interaction.user, "link_account", {"username": username, "member": member})

client.run(TOKEN)
