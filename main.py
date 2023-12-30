import functions
import logging
import traceback

def main():
    secrets = functions.get_secrets()

    sheet = functions.check_google_sheet(secrets["google_sheet_id"], secrets["range_name"])

    df = functions.sheets_to_dataframe(sheet)

    df_7 = functions.select_last_n_days(df, 7)

    message = functions.generate_feedback_message(df_7)

    print(message)

    functions.send_telegram(secrets["telegram_token"], secrets["telegram_chat_id"], message)

def handle_exception():
    secrets = functions.get_secrets()
    trace = traceback.format_exc()

    logging.error(trace)
    functions.send_telegram(secrets["telegram_token"], secrets["telegram_monitor_chat_id"], "!!!Gym-Bro-Tron is dead!!!")
    functions.send_telegram(secrets["telegram_token"], secrets["telegram_monitor_chat_id"], trace)

if __name__ == "__main__":
    functions.create_debug_information(logging.DEBUG)

    try:
        main()
    except Exception as e:
        handle_exception()