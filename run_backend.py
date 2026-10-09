import getpass
import os
import threading
import webbrowser

import uvicorn


def main() -> None:
    print("Set an admin password to start the GreenLife website.")
    print("For security, password keystrokes are hidden while you type.")
    while True:
        password = getpass.getpass("Create or re-enter admin password (minimum 10 characters): ")
        if len(password) < 10:
            print("Password must contain at least 10 characters.")
            continue
        confirmation = getpass.getpass("Confirm admin password: ")
        if password != confirmation:
            print("Passwords do not match. Try again.")
            continue
        break

    os.environ["GREENLIFE_ADMIN_PASSWORD"] = password
    print("Admin password is held in memory only. Admin session 8 hours baad expire hoga.")
    print("Starting website at http://127.0.0.1:8000/ ...", flush=True)
    threading.Timer(1.5, webbrowser.open, args=("http://127.0.0.1:8000/",)).start()
    uvicorn.run("main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
