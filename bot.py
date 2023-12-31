# bot.py

import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
from dotenv import load_dotenv
from letterboxdpy import user as lb_user
from letterboxdpy import list as lb_list
from letterboxdpy import movie as lb_movie
from datetime import datetime
import mysql.connector
import functools
import typing
import asyncio
import database
import log
from recommend import Recommendation

load_dotenv('.env')
TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = os.getenv('PREFIX')
is_test = os.getenv('TEST') == '1'

client = commands.Bot(command_prefix=PREFIX, intents=discord.Intents.all())

global max_recommendations


@client.event
async def on_ready():
    global log_channel
    global max_recommendations

    await client.login(TOKEN)
    print(f'Bot is online')

    await log.initiate(client)

    await database.connect()
    print(f'Bot has connected to the database')

    if is_test:
        print('Running as a dev environment')
    else:
        print('Running as production')

    # import saved data
    max_recommendations = 10


# sends long functions to a separate thread so the bot doesn't hang while the function is working
def to_thread(func: typing.Callable) -> typing.Coroutine:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)
    return wrapper


@client.event
async def on_message(message):

    # if message is a DM
    if isinstance(message.channel, discord.DMChannel):
        pass
        return

    # ignore non-text messages and messages from this bot
    if str(message.channel.type) != 'text' \
            or message.author == client.user:
        return

    # basic text command to sync slash command changes
    if message.content.lower() == "sync commands" and message.author.guild_permissions.administrator:
        await sync_commands(message)


async def sync_commands(message: discord.Message):
    test_guild = await check_guild(message.guild)
    if test_guild != is_test:
        return
    print(f'\nSyncing commands...')
    try:
        if test_guild:
            client.tree.copy_global_to(guild=message.guild)
            synced = await client.tree.sync(guild=message.guild)
            print(f'Syncing to test guild only')
        else:
            synced = await client.tree.sync()
        print(f'Synced {len(synced)} command(s)\n')
        await message.reply(content=f'Synced {len(synced)} command(s)\n')
    except Exception as e:
        print(e)
        await message.reply(e.__str__())


async def check_guild(guild: discord.Guild) -> bool:
    # adds the guild to the database if it isn't already then returns whether the guild is a test server
    # returns whether this is a test guild
    global is_test
    cursor = await database.get_cursor()
    cursor.execute(f"SELECT guild, test FROM guilds WHERE guild='{guild.id}'")
    # should only ever be length 1 or 0
    for item in cursor:
        test = item[1] == 1
        cursor.close()
        return test

    # will only get here if guild was not in the database
    # always default test to 0. Manually set a test server in the database
    cursor.execute(f"INSERT INTO guilds (guild, test) VALUES ('{guild.id}', b'0')")
    await database.commit()

    # check the guild for existing paired members and add new membership pairs if any
    member_ids = ''
    for member in guild.members:
        member_ids += f"'{member.id}' , "
    member_ids = member_ids.strip(" ,")
    cursor.execute(f"SELECT member FROM users WHERE member IN ({member_ids})")
    if cursor.rowcount >= 1:
        rows = ''
        for row in cursor.fetchall():
            rows += f"('{guild.id}', {row[0]}), "
        rows = rows.strip(", ")
        cursor.execute(f"REPLACE INTO memberships (guild, member) VALUES {rows}")
        await database.commit()

    return False


@client.tree.command(name="help", description="Gives a more in-depth description of available commands")
async def help(interaction: discord.Interaction):
    global is_test

    if await check_guild(interaction.guild) != is_test:
        return

    await log.slash(interaction.user, "help", interaction.guild)

    total_help = f'# **SLASH COMMANDS**\n'
    total_help += await slash_describer("recommend",
                                        "Recommend a list of movies that would be good "
                                        "for the users of the discord with paired Letterboxd accounts",
                                        parameters={'show_ratings': ('Whether to show the Letterboxd average rating '
                                                                      'for each movie in a third column. '
                                                                      'Leaving out the rating check drastically '
                                                                      'increases the overall speed of the command')})

    total_help += await slash_describer("solo_recommend",
                                        "Recommend a list of movies that would be good to watch alone, "
                                        "taking into account which movies want to be watched and / or have been seen "
                                        "by your Letterboxd mutuals",
                                        parameters={})
    total_help += await slash_describer("display_members",
                                        "Display all Discord users that have paired Letterboxd accounts "
                                        "with links to the Letterboxd accounts")
    total_help += await slash_describer("link_account",
                                        "Links a Letterboxd account to a discord user in this server\n "
                                        "Only Admins can link an account to another user or overwrite a linked account",
                                        parameters={'username': 'The Letterboxd account username',
                                                    'member': 'The Discord user'})
    total_help += await slash_describer("clear_link",
                                        "ADMIN ONLY. Clears the link between a Discord user"
                                        " and their paired Letterboxd account",
                                        parameters={'member': 'The Discord user'})

    await interaction.response.send_message(total_help, ephemeral=True)


# creates a text block describing a slash command
async def slash_describer(name: str, description: str, parameters: dict = None):
    final = f'## **/{name}**\n'
    final += f'**Description**\n {description}\n'
    if parameters is not None:
        final += f'**Parameters**\n'
        for item in parameters:
            final += f' {item} : {parameters[item]}\n'
    final += "\n"
    return final


@client.tree.command(name="link_account", description="Link a Letterboxd account to a discord user")
@app_commands.describe(username="Letterboxd account username", member="Discord member")
async def link_account(interaction: discord.Interaction, username: str, member: discord.Member = None):

    global is_test

    if await check_guild(interaction.guild) != is_test:
        return

    # if member left default, set to self
    if member is None:
        member = interaction.user

    await log.slash(interaction.user, "link_account", interaction.guild,
                    {"username": username, "member": member})

    # only allow bots to have linked accounts on test servers
    if member.bot and not is_test:
        await interaction.response.send_message(f'Bots cannot have linked accounts',
                                                ephemeral=True)
        return

    is_admin = interaction.user.guild_permissions.administrator

    cursor = await database.get_cursor()

    # only allow someone to change another user's linked account if they're an admin
    if not is_admin:
        if interaction.user != member:
            await interaction.response.send_message(f'Only an admin can link another user\'s account', ephemeral=True)
            cursor.close()
            return

        # don't let user change their account if they already have one linked and aren't an admin
        cursor.execute(f"SELECT member FROM users WHERE member='{member.id}'")
        if cursor.rowcount >= 1:
            await interaction.response.send_message(f'Letterboxd account already linked.\n'
                                                    f'Ask an admin to change your account if it is incorrect',
                                                    ephemeral=True)
            cursor.close()
            return

    # make sure Letterboxd user exists
    try:
        user = lb_user.User(username)
        # set username to the capitalization of the official online account
        username = user.username
    except Exception as e:
        if str(e) == "No user found":
            await interaction.response.send_message(f'Error finding Letterboxd user with that name.'
                                                    f'\nPlease recheck your spelling.', ephemeral=True)
            return
        else:
            await log.error(e)
            await interaction.response.send_message(f'Unknown error. Ask your admin to check the error log',
                                                    ephemeral=True)
            return

    # make sure Letterboxd account hasn't already been paired to a member
    cursor.execute(f"SELECT account FROM users WHERE account='{username}'")
    for item in cursor:
        await interaction.response.send_message(f'This Letterboxd account is '
                                                f'already linked to another Discord user', ephemeral=True)
        cursor.close()
        return

    # otherwise link account
    else:
        cursor.execute(f"REPLACE INTO users (member, account) VALUES "
                       f"('{member.id}','{username}')")
        await database.commit()

        # reconnect to db so the child table sees the newly added and required parent table entry
        cursor.close()
        await database.connect()
        cursor = await database.get_cursor()

        # create a membership for the member for all registered guilds
        cursor.execute(f"SELECT guild FROM guilds")
        rows = ''
        for row in cursor:
            if client.get_guild(int(row[0])).get_member(member.id) is not None:
                rows += f"({row[0]},'{member.id}'), "
        rows = rows.strip(", ")

        cursor.execute(f"\nREPLACE INTO memberships (guild, member) VALUES "
                       f"{rows}")
        await database.commit()

        await interaction.response.send_message(f'{member.display_name} '
                                                f'was linked to the Letterboxd account "{username}"',
                                                ephemeral=True)
        cursor.close()
        return

    cursor.close()
    return


@client.tree.command(name="clear_link", description="ADMIN: Removes a discord user from the list of linked accounts")
@app_commands.describe(member="Discord member")
async def clear_link(interaction: discord.Interaction, member: discord.Member):
    global is_test

    if await check_guild(interaction.guild) != is_test:
        return

    await log.slash(interaction.user, "clear_link", interaction.guild,
                    {"member": member})

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(f'This is an Admin-only command',
                                                ephemeral=True)
        return

    # bots can have linked accounts on test servers, so allow them to be removed there as well
    if member.bot and not is_test:
        await interaction.response.send_message(f'Bots cannot have linked accounts, so there is nothing to clear',
                                                ephemeral=True)
        return

    cursor = await database.get_cursor()
    cursor.execute(f"SELECT member FROM users WHERE member='{member.id}'")
    if cursor.rowcount <= 0:
        await interaction.response.send_message(f'This user does not have a paired Letterboxd account',
                                                ephemeral=True)
        cursor.close()
        return
    cursor.execute(f"DELETE FROM users WHERE member='{member.id}'")
    await database.commit()
    await interaction.response.send_message(f'Successfully removed {member.mention} '
                                            f'and their paired Letterboxd account', ephemeral=True)
    cursor.close()
    return


@client.tree.command(name="display_members", description="Prints out a list of discord members "
                                                         "and their paired letterboxd accounts")
async def display_members(interaction: discord.Interaction):
    global is_test

    if await check_guild(interaction.guild) != is_test:
        return

    await log.slash(interaction.user, "display_members", interaction.guild)

    cursor = await database.get_cursor()
    cursor.execute(f"SELECT users.member, users.account FROM users, memberships "
                   f"WHERE memberships.guild='{interaction.guild_id}' AND users.member=memberships.member "
                   f"ORDER BY account")
    if cursor.rowcount <= 0:
        await interaction.response.send_message(f"No linked members in this discord server", ephemeral=True)
        cursor.close()
        return

    members = ''
    accounts = ''
    for item in cursor:
        members += f'{(await client.fetch_user(int(item[0]))).mention}\n'
        accounts += f'[{str(item[1])}](https://letterboxd.com/{str(item[1])}/)\n'

    final = discord.Embed(title='**LINKED ACCOUNTS IN THIS SERVER**')
    final.add_field(name='Discord Member', value=members)
    final.add_field(name='Letterboxd Account', value=accounts)
    await interaction.response.send_message(embed=final)
    cursor.close()
    return


@to_thread
@client.tree.command(name="recommend", description="Recommend a movie based on present members' "
                                                   "watch-lists and absent members' watched-lists")
@app_commands.describe(channel_for_attendance="The Voice Channel used to automatically take attendance. "
                                              "If left empty, attendance is done manually.")
async def recommend(interaction: discord.Interaction,
                    channel_for_attendance: discord.VoiceChannel = None):
    global is_test
    global max_recommendations

    if await check_guild(interaction.guild) != is_test:
        return

    await log.slash(interaction.user, "recommend", interaction.guild,
                    {'channel_for_attendance': channel_for_attendance})

    recommendation = Recommendation(channel_for_attendance)
    await recommendation.initiate(interaction)

    return


# @to_thread
# @client.tree.command(name="solo_recommend", description="Recommend a list of movies to watch alone, "
#                                                         "treating all Letterboxd mutuals as absent")
# async def solo_recommend(interaction: discord.Interaction):
#     global is_test
#     global max_recommendations
#
#     if await check_guild(interaction.guild) != is_test:
#         return
#
#     await log_slash(interaction.user, "recommend", interaction.guild,
#                     {})
#
#     cursor = await database.get_cursor()
#     cursor.execute(f"SELECT member, account FROM users WHERE guild='{interaction.guild_id}'")


client.run(TOKEN)
