# log.py

import os
import discord
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('.env')
LOG_CHANNEL = os.getenv('LOG_CHANNEL')

global log_channel
global client


async def initiate(bot_client: discord.Client):
    global log_channel
    global client

    client = bot_client
    log_channel = client.get_channel(int(LOG_CHANNEL))


async def log(output: discord.Embed):
    global log_channel
    output.set_footer(text=datetime.now())
    await log_channel.send(embed=output)


async def slash(author: discord.Member, specific, guild: discord.Guild,
                parameters: dict = None, message: discord.Message = None):
    desc = "**Server:**\n"
    desc += f"{guild.name} : {guild.id}\n"

    print(f"\n{specific} from {author}:{author.id} in {guild}:{guild.id} with params: {parameters}")

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


async def error(error):
    embed = discord.Embed(title=f'ERROR', description=str(error), colour=15548997)
    print(f"\nERROR: {error}")
    await log(embed)
