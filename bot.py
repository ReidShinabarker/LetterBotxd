# bot.py

import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
from dotenv import load_dotenv
from src.letterbot.src.letterboxdpy import user as lb_user
from src.letterbot.src.letterboxdpy import movie as lb_movie
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
is_test = os.getenv('TEST') == '1'

client = commands.Bot(command_prefix=PREFIX, intents=discord.Intents.all())

global log_channel
global mydb


@client.event
async def on_ready():
    global log_channel
    global mydb

    await client.login(TOKEN)
    print(f'Bot is online')
    log_channel = client.get_channel(int(LOG_CHANNEL))

    try:
        mydb = mysql.connector.connect(
            host=str(db_address),
            user=str(db_user),
            password=str(db_pass),
            database=str(db_name)
        )
        print(f'Bot is able to connect to the database')
    except Exception as e:
        print(f'ERROR: While trying to connect to the database: {str(e)}')
        await log_error(e)
    if is_test:
        print('Running as a dev environment')
    else:
        print('Running as production')


# region Logging
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
# endregion


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


async def check_guild(guild: discord.Guild) -> bool:
    # adds the guild to the database if it isn't already then returns whether the guild is a test server
    global is_test
    global mydb
    cursor = mydb.cursor()
    cursor.execute(f"SELECT guild, test FROM guilds WHERE guild='{guild.id}'")
    # should only ever be length 1 or 0
    for item in cursor:
        test = item[1] == 1
        cursor.close()
        return test

    # will only get here if guild was not in the database
    # always default test to 0. Manually set a test server in the database
    cursor.execute(f"INSERT INTO guilds (guild, test) VALUES ('{guild.id}', b'0')")
    mydb.commit()
    cursor.close()
    return False


@client.tree.command(name="link_account", description="Link a Letterboxd account to a discord user")
@app_commands.describe(username="Letterboxd account username", member="Discord member")
async def link_account(interaction: discord.Interaction, username: str, member: discord.Member = None):

    global mydb
    global is_test

    if await check_guild(interaction.guild) != is_test:
        return

    # if member left default, set to self
    if member is None:
        member = interaction.user

    await log_slash(interaction.user, "link_account", {"username": username, "member": member})

    is_admin = await check_admin(interaction.user)

    cursor = mydb.cursor()

    # only allow someone to change another user's linked account if they're an admin
    if not is_admin:
        if interaction.user != member:
            await interaction.response.send_message(f'Only an admin can link another user\'s account', ephemeral=True)
            cursor.close()
            return

        # don't let user change their account if they already have one linked and aren't an admin
        cursor.execute(f"SELECT * FROM users WHERE member='{member.id}'")
        for item in cursor:
            # this will only go off if there is at least 1 matching member
            await interaction.response.send_message(f'Letterboxd account already linked.\n'
                                                    f'Ask an admin to change your account if it is incorrect',
                                                    ephemeral=True)
            cursor.close()
            return

    # make sure Letterboxd user exists
    try:
        lb_user.User(username)
    except Exception as e:
        if str(e) == "No user found":
            await interaction.response.send_message(f'Error finding Letterboxd user with that name.'
                                                    f'\nPlease recheck your spelling.', ephemeral=True)
            return
        else:
            await log_error(e)
            await interaction.response.send_message(f'Unknown error. Ask your admin to check the error log',
                                                    ephemeral=True)
            return

    # make sure Letterboxd account hasn't already been paired to a member in this discord server
    cursor.execute(f"SELECT member, account, guild FROM users WHERE guild='{interaction.guild_id}' "
                   f"AND account='{username}'")
    for item in cursor:
        if str(item[0]) == str(member.id):
            await interaction.response.send_message(f'This Letterboxd account is '
                                                    f'already linked to this discord member',
                                                    ephemeral=True)
            cursor.close()
            return
        else:
            await interaction.response.send_message(f'This Letterboxd account is '
                                                    f'already linked to another discord member in this server',
                                                    ephemeral=True)
            cursor.close()
            return

    # otherwise link account
    else:
        cursor.execute(f"REPLACE INTO users (member, account, guild) VALUES "
                       f"('{member.id}','{username}', '{interaction.guild_id}')")
        mydb.commit()
        await interaction.response.send_message(f'{member.display_name} '
                                                f'was linked to the Letterboxd account "{username}"',
                                                ephemeral=True)
        cursor.close()
        return

    cursor.close()
    return

client.run(TOKEN)
