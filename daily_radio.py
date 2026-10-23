
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import os

IST = ZoneInfo("Asia/Kolkata")


def ask_date(prompt):
    while True:
        value = input(prompt).strip()
        try:
            return date.fromisoformat(value)
        except ValueError:
            print("Invalid date. Use YYYY-MM-DD, e.g. 2025-10-01.")


def main():
    print("=" * 60)
    print("            SLACK DAILY RADIO EXPORTER")
    print("=" * 60)

    # All inputs are visible as requested.
    token = input("\nSlack OAuth Token (xoxp-... or xoxb-...): ").strip()
    channel_id = input("Daily Radio Channel ID: ").strip()

    start_date = ask_date("Start date (YYYY-MM-DD): ")
    end_date = ask_date("End date   (YYYY-MM-DD): ")

    output_file = input(
        "Output filename [Daily_Radio.txt]: "
    ).strip() or "Daily_Radio.txt"

    if not output_file.lower().endswith(".txt"):
        output_file += ".txt"

    if not token or not channel_id:
        print("\nERROR: Token and channel ID are required.")
        return

    if end_date < start_date:
        print("\nERROR: End date cannot be before start date.")
        return

    client = WebClient(token=token)

    # Validate authentication first.
    try:
        auth = client.auth_test()
        print(f"\nAuthenticated successfully: {auth.get('user', 'Slack user')}")
        print(f"Workspace: {auth.get('team', 'Unknown')}")

    except SlackApiError as error:
        print("\nAUTHENTICATION FAILED:", error.response.get("error"))
        print("Check that the token is current and has not been revoked.")
        return

    # Convert date range to Unix timestamps in IST.
    oldest = datetime.combine(
        start_date, time.min, tzinfo=IST
    ).timestamp()

    latest = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=IST
    ).timestamp()

    messages = []
    cursor = None

    print(f"\nDownloading messages: {start_date} to {end_date}")

    try:
        while True:
            response = client.conversations_history(
                channel=channel_id,
                oldest=str(oldest),
                latest=str(latest),
                inclusive=True,
                limit=200,
                cursor=cursor
            )

            messages.extend(response.get("messages", []))
            print(f"Retrieved {len(messages)} messages...")

            cursor = response.get(
                "response_metadata", {}
            ).get("next_cursor")

            if not cursor:
                break

        # Oldest to newest.
        messages.sort(key=lambda m: float(m["ts"]))

        output_path = os.path.abspath(output_file)

        with open(output_path, "w", encoding="utf-8") as file:
            file.write("SLACK DAILY RADIO EXPORT\n")
            file.write("=" * 60 + "\n")
            file.write(f"Workspace: {auth.get('team', 'Unknown')}\n")
            file.write(f"Channel ID: {channel_id}\n")
            file.write(f"Start date: {start_date}\n")
            file.write(f"End date: {end_date}\n")
            file.write(f"Total messages: {len(messages)}\n\n")

            for msg in messages:
                timestamp = datetime.fromtimestamp(
                    float(msg["ts"]), IST
                ).strftime("%d %B %Y, %I:%M:%S %p")

                sender = (
                    msg.get("user")
                    or msg.get("username")
                    or msg.get("bot_id")
                    or "Unknown"
                )

                file.write("-" * 70 + "\n")
                file.write(f"Date/Time: {timestamp} IST\n")
                file.write(f"Sender ID: {sender}\n")
                file.write(f"Message:\n{msg.get('text', '')}\n\n")

        print("\n" + "=" * 60)
        print("EXPORT COMPLETE")
        print("=" * 60)
        print(f"Messages exported: {len(messages)}")
        print(f"Saved file: {output_path}")

    except SlackApiError as error:
        print("\nSLACK API ERROR:", error.response.get("error"))

        if error.response.get("error") == "missing_scope":
            print("Add the required history scope to the token.")
        elif error.response.get("error") == "not_in_channel":
            print("The bot must join the channel, or use an authorized user token.")
        elif error.response.get("error") == "channel_not_found":
            print("Check the channel ID and your access to the channel.")

    except Exception as error:
        print("\nERROR:", error)


if __name__ == "__main__":
    main()
