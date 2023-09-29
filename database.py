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

mydb: mysql.connector.connection = None


async def connect():
    global mydb

    if mydb is None or not mydb.is_connected():
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

    # connect to database in case of timeout on previous connection
    await connect()

    return mydb.cursor(buffered=True)


async def commit():
    global mydb

    # connect to database in case of timeout on previous connection
    await connect()

    mydb.commit()
