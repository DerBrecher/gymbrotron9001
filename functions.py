from __future__ import print_function

import os
import json
import telegram
import pandas as pd
import numpy as np
import asyncio
import signal
import openai
from contextlib import contextmanager
import logging
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

def create_file_logger(rootLogger, logFormatter):
    for log in rootLogger.handlers:
        if isinstance(log, logging.FileHandler):
            return None

    fileHandler = logging.FileHandler("log.log")
    fileHandler.setFormatter(logFormatter)
    rootLogger.addHandler(fileHandler)

def create_stdout_logger(rootLogger, logFormatter):
    for log in rootLogger.handlers:
        if isinstance(log, logging.StreamHandler):
            return None
        
    consoleHandler = logging.StreamHandler(sys.stdout)
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)

def create_debug_information(logging_level):
    logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
    rootLogger = logging.getLogger()

    create_stdout_logger(rootLogger, logFormatter)

    create_file_logger(rootLogger, logFormatter)

    rootLogger.setLevel(logging_level)
    logging.debug(f"Python Version: {sys.version}")


def get_secrets():
    with open("secrets/secrets.json") as f:
        return json.load(f)

def check_google_sheet(sheet_id, sample_range):
    """Shows basic usage of the Sheets API.
    Prints values from a sample spreadsheet.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('secrets/google_token.json'):
        creds = Credentials.from_authorized_user_file('secrets/google_token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'secrets/credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('secrets/google_token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('sheets', 'v4', credentials=creds)

        # Call the Sheets API
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=sheet_id, range=sample_range).execute()
        values = result.get('values', [])

        if not values:
            print('No data found.')
            logging.error("Access to google sheets failed")
            return
        else:
            logging.debug("Access to google sheets succeeded")
            return values
    except HttpError as err:
        print(err)

def sheets_to_dataframe(sheet):
    df = pd.DataFrame(sheet)
    df = df.drop(columns=range(3, df.shape[1], 2))
    df.columns = df.iloc[0]
    df = df.drop([0,1]).reset_index(drop=True)
    df["Date"] = pd.to_datetime(df["Date"], format="%d.%m.%Y")
    df.replace('', None, inplace=True)

    logging.debug("Successfully converted google sheet to pandas dataframe")
    return df

def select_last_n_days(df, n_days: int):
    df_n = select_entry_between_dates(df, pd.Timestamp.now() - pd.DateOffset(n_days), pd.Timestamp.now())
    logging.debug(f"Successfully selected last {n_days} days")
    return df_n

def select_entry_between_dates(df, start_date, end_date):
    mask = (df["Date"] > start_date) & (df["Date"] < end_date)
    return df.loc[mask]

def choose_gpt_instruction(counts):
    instruction_win    = """Erstelle eine witzige Nachricht, die Leute motiviert mehr Sport zu machen. Verwende Emojis um die Nachricht lebendiger zu machen, dein name ist {assistant} und du schickst jeden Abend eine Nachricht. Der erste Platz ist {first}, der Zweite {second}, der Dritte {third} und Letzte {last}. Die Anzahl ihrer Sporteinheiten in den letzen 7 Tage ist {first_n}, {second_n}, {third_n}, {last_n}. Ziel ist es 5 Sporteinheiten zu machen. Lobe den ersten Platz und stichle den Letzten zukünftig mehr Sport zu machen."""
    instruction_draw_2 = """Erstelle eine witzige Nachricht, die Leute motiviert mehr Sport zu machen. Verwende Emojis um die Nachricht lebendiger zu machen, dein name ist {assistant} und du schickst jeden Abend eine Nachricht. Den ersten Platz teilen sich {first} und {second}, der Dritte {third} und Letzte {last}. Die Anzahl ihrer Sporteinheiten in den letzen 7 Tage ist {first_n}, {second_n}, {third_n}, {last_n}. Ziel ist es 5 Sporteinheiten zu machen. Lobe den ersten Platz und stichle den Letzten zukünftig mehr Sport zu machen."""
    instruction_draw_3 = """Erstelle eine witzige Nachricht, die Leute motiviert mehr Sport zu machen. Verwende Emojis um die Nachricht lebendiger zu machen, dein name ist {assistant} und du schickst jeden Abend eine Nachricht. Den ersten Platz teilen sich {first}, {second} und {third} und Letzte {last}. Die Anzahl ihrer Sporteinheiten in den letzen 7 Tage ist {first_n}, {second_n}, {third_n}, {last_n}. Ziel ist es 5 Sporteinheiten zu machen. Lobe den ersten Platz und stichle den Letzten zukünftig mehr Sport zu machen."""
    instruction_draw_all = """Erstelle eine witzige Nachricht, die Leute motiviert mehr Sport zu machen. Verwende Emojis um die Nachricht lebendiger zu machen, dein name ist {assistant}. Beachte, dass alle Teilnehmer den ersten Platz belegen, da sie gleich oft Sport gemacht haben. Die Namen der Teilnehmer sind {first}, {second}, {third} und {last}. Die Anzahl ihrer Sporteinheiten in den letzen 7 Tage ist {first_n}. Ziel ist es 5 Sporteinheiten zu machen."""

    if counts[0] == counts[1] and counts[0] == counts[2] and counts[0] == counts[3]:
        instruction = instruction_draw_all
    elif counts[0] == counts[1] and counts[0] == counts[2]:
        instruction = instruction_draw_3
    elif counts[0] == counts[1]:
        instruction = instruction_draw_2
    else:
        instruction = instruction_win

    instruction = instruction.format(first = counts.index[0], second = counts.index[1], third = counts.index[2], last = counts.index[-1], first_n = counts[0], second_n = counts[1], third_n = counts[2], last_n =counts[-1], assistant="Gym-Bro-Tron 9001")
    logging.debug("Successfully created GPT instruction")
    return instruction


class TimeoutException(Exception): pass

@contextmanager
def time_limit(seconds):
    def signal_handler(signum, frame):
        raise TimeoutException("Timed out!")
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)


def get_gpt_message(instruction, timeout=20):
    secrets = get_secrets()

    openai.organization = secrets["open_ai_organization"]
    openai.api_key = secrets["open_ai_token"]

    try:
        with time_limit(timeout):
            resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": instruction}
                ]
            )
        message = resp["choices"][0]["message"]["content"]
        logging.debug("Successfully got GPT message")
        logging.debug(message)
        return message
    except TimeoutException as e:
        logging.error("GPT request timed out")
        logging.error(e)
        return None
    except Exception as e:
        logging.critical("Other Error with GPT")
        logging.critical(e)
        return None

def fallback_message(counts, i=None):
    templates = [f"Yo, Leute! Checkt das mal aus! 🔥 Unser Sport-Guru {counts.index[0]} hat diese Woche die Fitness-Liga dominiert und einfach mal {counts[0]} Mal Sport gemacht! 😲 {counts.index[1]} und {counts.index[2]} sind zwar am Start, aber kämpfen noch um die Fitness-Influencer-Titel in Silber und Bronze. 😏 {counts.index[-1]}, wenn du nächste Woche zum #1 Fit-Zoomer aufsteigen willst, heißt es: Mehr Gas, mehr Schweiß und volle Power, Bro! 💪🚀 Lass uns alle diese Energie spüren! 💥",
                 f"Hey, Sport-Freaks! Schaut mal, wer diese Woche das Fitness-Kingdom regiert! 👑 {counts.index[0]} hat mit {counts[0]} Sporteinheiten die Arena gerockt! 🤘 {counts.index[1]} und {counts.index[2]} sind dabei, aber auf dem Weg zur Fitness-Legende müssen sie noch ein paar Level aufsteigen. 🎮 {counts.index[-1]}, wenn du nächste Woche den Highscore knacken willst, heißt es: Power-Up, mehr Ausdauer und lass die Muskeln spielen! 💥🏋️‍♂️",
                 f"Yo, Leute! Wer braucht Superhelden, wenn wir {counts.index[0]} haben?! 🦸‍♂️ Diese Woche hat er/sie {counts[0]} Mal Sport gemacht und die Liga gesprengt! 💣 {counts.index[1]} und {counts.index[2]} sind zwar auch im Game, aber sie müssen ihre Fitness-Kräfte noch stärker bündeln. 🏃‍♂️ {counts.index[-1]}, wenn du nächste Woche der Sport-Avenger sein willst, heißt es: Mehr Energie, höher, schneller, weiter! 🚴‍♂️💨",
                 f"Hey, Fitness-Fans! Die Siegerpose geht diese Woche an {counts.index[0]} für unglaubliche {counts[0]} Mal Sport! 🥇 {counts.index[1]} und {counts.index[2]} sind zwar im Rennen, aber sie sollten ihre Laufschuhe schon mal schnüren, um zu gewinnen. 👟 {counts.index[-1]}, wenn du nächste Woche die Sport-Challenge meistern willst, heißt es: Mehr Tempo, härter trainieren und den inneren Schweinehund besiegen! 🐶💥",
                 f"Hey, ihr Sport-Enthusiasten! Wer ist der ultimative Fitness-Champion dieser Woche? Natürlich {counts.index[0]} mit {counts[0]} Mal Sport! 🏆 {counts.index[1]} und {counts.index[2]} sind zwar im Rennen, aber der Weg zur Fitness-Glory ist noch weit! 🌟 {counts.index[-1]}, wenn du nächste Woche den Thron besteigen willst, heißt es: Keine Ausreden, mehr Schweiß und gib alles für den Sieg! 🥊🔥",
                 f"Hey, Sportsfreunde! Diese Woche hat {counts.index[0]} das Fitness-Universum erobert und {counts[0]} Mal Sport gemacht! 🌠 {counts.index[1]} und {counts.index[2]} sind zwar auch auf der Fitness-Galaxie unterwegs, aber sie müssen noch durch ein paar Sport-Wurmlöcher reisen. 🌌 {counts.index[-1]}, wenn du nächste Woche zum intergalaktischen Sport-Helden werden willst, heißt es: Mehr Antrieb, höhere Geschwindigkeit und ab in den Fitness-Hyperdrive! 🚀💫",
                 f"Hey, Fitness-Begeisterte! Schaut mal, wer diese Woche das Gym-Königreich regiert! 👑 Mit {counts[0]} Sporteinheiten hat {counts.index[0]} die Konkurrenz in den Schatten gestellt! 🌞 {counts.index[1]} und {counts.index[2]} sind zwar auch dabei, aber um den Fitness-Thron zu erobern, müssen sie noch ein paar mehr Kilometer laufen. 🏃‍♀️ {counts.index[-1]}, wenn du nächste Woche den Champion-Titel erreichen willst, heißt es: Gib alles, steigere dein Training und werde zum wahren Fitness-Helden! 💪🌟",
                 f"Hey, Sportliebhaber! Wer braucht Superstars, wenn wir {counts.index[0]} haben?! 🌟 Diese Woche hat er/sie mit {counts[0]} Sporteinheiten die Spitze erklommen und alle in Erstaunen versetzt! 🔝 {counts.index[1]} und {counts.index[2]} sind zwar auch im Spiel, aber um zu den Sport-Göttern aufzusteigen, müssen sie noch härter arbeiten. 🏋️‍♀️ {counts.index[-1]}, wenn du nächste Woche zur Fitness-Legende werden willst, heißt es: Glaub an dich selbst, kämpfe für deine Ziele und zeige, was in dir steckt! 💥👊",
                 f"Hey, Fitness-Junkies! Die Goldmedaille geht diese Woche an {counts.index[0]}, der/die mit {counts[0]} Sporteinheiten alle in den Schatten gestellt hat! 🏅 {counts.index[1]} und {counts.index[2]} sind zwar auch im Rennen, aber um zu gewinnen, müssen sie noch mehr schwitzen. 💦 {counts.index[-1]}, wenn du nächste Woche den Fitness-Olymp erobern willst, heißt es: Auf geht's, mehr Power, mehr Training und werde zum ultimativen Sport-Champion! 🎖️🔥",
                 f"Hey, Sportfans! Wer hat diese Woche das Fitness-Game gerockt? Natürlich {counts.index[0]} mit {counts[0]} Sporteinheiten! 🤘 {counts.index[1]} und {counts.index[2]} sind zwar auch im Rennen, aber um zu gewinnen, müssen sie noch ein paar Übungen mehr machen. 🏋️‍♀️ {counts.index[-1]}, wenn du nächste Woche zur Fitness-Ikone werden willst, heißt es: Keine Pause, kein Limit und zeig, was du drauf hast! 🚴‍♀️💪"
                 ]
    if i is not None:
        return templates[i]
    else: 
        return templates[np.random.randint(0, len(templates))]

def generate_standing(df):
    counts = df.drop(columns=["Date", "Weekday"]).count()
    counts = counts.sort_values(ascending=False)
    logging.debug("Successfully created current standing")
    logging.debug(counts)
    return counts

def generate_feedback_message(df):
    counts = generate_standing(df)

    instruction = choose_gpt_instruction(counts)

    message = get_gpt_message(instruction, timeout=20)

    if message is None:
        logging.error("Using fallback messages")
        message = fallback_message(counts)
        logging.error("Successfully got fallback messages")

    return message

async def send_telegram_message(bot_token, chat_id, message):
    bot = telegram.Bot(bot_token)
    async with bot:
        await bot.sendMessage(chat_id = chat_id, text=message)
    logging.debug(f"Successfully send telegram message: {message}")

def send_telegram(bot_token, chat_id, message):
    asyncio.run(send_telegram_message(bot_token, chat_id, message))
