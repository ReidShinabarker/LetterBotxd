# database.py

import os
import mysql.connector
import log
from dotenv import load_dotenv

load_dotenv('.env')
db_address = os.getenv('DATABASE_ADDRESS')
db_name = os.getenv('DATABASE_NAME')
db_user = os.getenv('DATABASE_USER')
db_pass = os.getenv('DATABASE_PASS')

global mydb


async def connect():
    global mydb
    try:
        mydb = mysql.connector.connect(
            host=str(db_address),
            user=str(db_user),
            password=str(db_pass),
            database=str(db_name)
        )
    except Exception as e:
        await log.error(e)


async def get_cursor():
    global mydb
    try:
        cursor = mydb.cursor(buffered=True)
    except:
        # if the cursor failed, it is likely that the database login timed out, so try logging back in
        await connect()
        print(f'\nBot has reconnected to the database')
        try:
            cursor = mydb.cursor(buffered=True)
        except Exception as e:
            await log.error(e)
            return
    return cursor


async def commit():
    global mydb
    mydb.commit()
