# bot.py

import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
from dotenv import load_dotenv
# from src.letterbot.src.letterboxdpy import user as lb_user
from letterboxdpy import user as lb_user
from letterboxdpy import list as lb_list
from letterboxdpy import movie as lb_movie
import datetime as dt
from datetime import datetime, timedelta
import mysql.connector
import functools
import typing
import asyncio

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
global max_recommendations


@client.event
async def on_ready():
    global log_channel
    global mydb
    global max_recommendations

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

    # import saved data
    max_recommendations = 10


# region Logging
async def log(output: discord.Embed):
    global log_channel
    output.set_footer(text=datetime.now())
    await log_channel.send(embed=output)


async def log_slash(author: discord.Member, specific, guild: discord.Guild,
                    parameters: dict = None, message: discord.Message = None):
    desc = "**Server:**\n"
    desc += f"{guild.name} : {guild.id}\n"

    print(f"{specific} from {author}:{author.id} in {guild}:{guild.id} with params: {parameters}")

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

    if await check_guild(message.guild) != is_test:
        return

    # ignore non-text messages and messages from this bot
    if str(message.channel.type) != 'text' \
            or message.author == client.user:
        return

    # basic text command to sync slash command changes
    if message.content.lower() == "sync commands" and message.author.guild_permissions.administrator:
        await sync_commands(message)


async def sync_commands(message: discord.Message):
    print(f'Syncing commands...')
    try:
        if await check_guild(message.guild):
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


@client.tree.command(name="status", description="Prints out a basic status to see if the bot is running")
async def status(interaction: discord.Interaction):
    global mydb
    global is_test

    if await check_guild(interaction.guild) != is_test:
        return

    await log_slash(interaction.user, "status", interaction.guild)

    await interaction.response.send_message(f"Bot is running", ephemeral=True)


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

    await log_slash(interaction.user, "link_account", interaction.guild,
                    {"username": username, "member": member})

    # only allow bots to have linked accounts on test servers
    if member.bot and not is_test:
        await interaction.response.send_message(f'Bots cannot have linked accounts',
                                                ephemeral=True)
        return

    is_admin = interaction.user.guild_permissions.administrator

    cursor = mydb.cursor(buffered=True)

    # only allow someone to change another user's linked account if they're an admin
    if not is_admin:
        if interaction.user != member:
            await interaction.response.send_message(f'Only an admin can link another user\'s account', ephemeral=True)
            cursor.close()
            return

        # don't let user change their account if they already have one linked and aren't an admin
        cursor.execute(f"SELECT * FROM users WHERE member='{member.id}'")
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
            await log_error(e)
            await interaction.response.send_message(f'Unknown error. Ask your admin to check the error log',
                                                    ephemeral=True)
            return

    # make sure Letterboxd account hasn't already been paired to a member in this discord server
    cursor.execute(f"SELECT member, account, guild FROM users WHERE guild='{interaction.guild_id}' "
                   f"AND account='{username}'")
    for item in cursor:
        await interaction.response.send_message(f'This Letterboxd account is '
                                                f'already linked to '
                                                f'{client.get_user(int(item[0])).mention}',
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


@client.tree.command(name="clear_link", description="ADMIN: Removes a discord user from the list of linked accounts")
@app_commands.describe(member="Discord member")
async def clear_link(interaction: discord.Interaction, member: discord.Member):
    global mydb
    global is_test

    if await check_guild(interaction.guild) != is_test:
        return

    await log_slash(interaction.user, "clear_link", interaction.guild,
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

    cursor = mydb.cursor(buffered=True)
    cursor.execute(f"SELECT member FROM users WHERE member='{member.id}' AND guild='{interaction.guild_id}'")
    if cursor.rowcount <= 0:
        await interaction.response.send_message(f'This user does not have a paired Letterboxd account',
                                                ephemeral=True)
        cursor.close()
        return
    cursor.execute(f"DELETE FROM users WHERE member='{member.id}' AND guild='{interaction.guild_id}'")
    mydb.commit()
    await interaction.response.send_message(f'Successfully removed {member.mention} '
                                            f'and their paired Letterboxd account', ephemeral=True)
    cursor.close()
    return


@client.tree.command(name="display_members", description="Prints out a list of discord members "
                                                         "and their paired letterboxd accounts")
async def display_members(interaction: discord.Interaction):
    global mydb
    global is_test

    if await check_guild(interaction.guild) != is_test:
        return

    await log_slash(interaction.user, "display_members", interaction.guild)

    cursor = mydb.cursor(buffered=True)
    cursor.execute(f"SELECT member, account, guild FROM users WHERE guild='{interaction.guild_id}' ORDER BY account")
    if cursor.rowcount <= 0:
        await interaction.response.send_message(f"No linked members in this discord server", ephemeral=True)
        cursor.close()
        return

    desc = ''
    for item in cursor:
        desc += (f'{(await client.fetch_user(int(item[0]))).mention} : '
                 f'[{str(item[1])}](https://letterboxd.com/{str(item[1])}/)\n')

    final = discord.Embed(description=desc, title='**LINKED ACCOUNTS IN THIS SERVER**')
    await interaction.response.send_message(embed=final)
    cursor.close()
    return


@to_thread
@client.tree.command(name="recommend", description="Recommend a movie based on present members' "
                                                   "watch-lists and absent members' watched-lists")
async def recommend(interaction: discord.Interaction):
    global mydb
    global is_test
    global max_recommendations

    if await check_guild(interaction.guild) != is_test:
        return

    await log_slash(interaction.user, "recommend", interaction.guild,
                    {})

    cursor = mydb.cursor(buffered=True)
    cursor.execute(f"SELECT member, account FROM users WHERE guild='{interaction.guild_id}'")

    full_response = "Finding linked Letterboxd accounts..."
    await interaction.response.send_message(embed=discord.Embed(title=f"**Movie Recommendation**",
                                                                description=full_response))
    movies = {}
    users = []
    for item in cursor:
        users.append(lb_user.User(str(item[1])))

    full_response += f"\nCollecting movies in watchlists..."
    await interaction.edit_original_response(embed=discord.Embed(title=f"**Movie Recommendation**",
                                                                 description=full_response))
    for user in users:
        for movie in lb_user.user_films_on_watchlist(user):
            # increment the key of a movie by 2 for each watchlist it is in
            if movie in movies:
                movies[movie] = movies[movie] + 2
            else:
                movies[movie] = 2

    full_response += f"\nChecking which movies have already been seen by people..."
    await interaction.edit_original_response(embed=discord.Embed(title=f"**Movie Recommendation**",
                                                                 description=full_response))
    for user in users:
        for movie in lb_user.user_films_watched(user):
            # decrement the key of a movie by 1 for each person that has seen it
            if movie in movies:
                movies[movie] = movies[movie] - 1

    full_response += f"\nObjectively calculating how good each movie is..."
    await interaction.edit_original_response(embed=discord.Embed(title=f"**Movie Recommendation**",
                                                                 description=full_response))

    sorted_movies = sorted(movies.items(), key=lambda x: (x[1]), reverse=True)

    # find the lowest score of the x number of movies that are going to be recommended
    # to know how many ratings need to be looked up
    lowest_score = sorted_movies[max_recommendations-1][1]

    # convert back to dict to be easier to work with
    sorted_movies = dict(sorted_movies)

    # find the average rating for each recommendation and add it to the movie tuple
    rated_movies = {}
    for movie in sorted_movies:
        # can stop looking up ratings if it doesn't have a chance to be recommended anyway
        if lowest_score > sorted_movies[movie]:
            break
        rating = float(lb_movie.Movie(movie[1]).rating.split()[0])
        rated_movies[(movie[0], movie[1], rating)] = movies[movie]

    # sort again, this time using the rating as a tiebreaker
    sorted_movies = sorted(rated_movies.items(), key=lambda x: (x[1], x[0][2]), reverse=True)

    full_response += f"\nCalculating recommendations..."
    await interaction.edit_original_response(embed=discord.Embed(title=f"**Movie Recommendation**",
                                                                 description=full_response))

    full_response = ''
    poster_link = ''
    i = 0
    score_column = ''
    title_column = ''
    rating_column = ''
    for movie in sorted_movies:
        if i >= max_recommendations:
            break
        if poster_link == '':
            poster_link = lb_movie.movie_poster(movie[0][1])

        score = f"{movie[1]}\n"
        name = f"[{movie[0][0]}](https://www.letterboxd.com/film/{movie[0][1]}/)\n"
        rating = f"{movie[0][2]}\n"
        # field bodies can't go over 1024 characters
        if (len(score) + len(score_column) >= 1024 or
                len(name) + len(title_column) >= 1024 or
                len(rating) + len(rating_column) >= 1024):
            break
        score_column += f"{movie[1]}\n"
        title_column += f"[{movie[0][0]}](https://www.letterboxd.com/film/{movie[0][1]}/)\n"
        rating_column += f"{movie[0][2]}\n"
        i += 1

    final_embed = discord.Embed(title=f"**Movie Recommendation**", description=full_response)
    final_embed.set_image(url=poster_link)
    final_embed.add_field(name="SCORE", value=score_column)
    final_embed.add_field(name="TITLE", value=title_column)
    final_embed.add_field(name="RATING", value=rating_column)
    await interaction.edit_original_response(embed=final_embed)

    cursor.close()
    return


client.run(TOKEN)
